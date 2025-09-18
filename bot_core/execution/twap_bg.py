# bot_core/execution/twap_bg.py
"""
Background TWAP Executor with per-slice retry/backoff

See earlier twap_bg implementation. This one adds:
 - per-slice retry wrapper with exponential backoff
 - configurable attempts/base/max via constructor
"""
from __future__ import annotations

import time
import uuid
import threading
import hashlib
from typing import Any, Callable, Dict, List, Optional


class BackgroundTWAPExecutor:
    def __init__(self, broker,
                 default_order_delay: Optional[float] = None,
                 place_order_fn: Optional[Callable[..., Any]] = None,
                 order_retry_attempts: int = 3,
                 order_retry_base: float = 0.05,
                 order_retry_max: float = 1.0):
        """
        :param broker: broker object; used if place_order_fn not provided.
        :param default_order_delay: default delay between slices (seconds).
        :param place_order_fn: optional callable to place orders (signature: **kwargs).
        :param order_retry_attempts: number of attempts per slice (including first).
        :param order_retry_base: base delay (seconds) for exponential backoff.
        :param order_retry_max: max delay (seconds) between retries.
        """
        self.broker = broker
        self.default_order_delay = default_order_delay
        self.place_order_fn = place_order_fn or getattr(broker, "place_order")
        self._jobs: Dict[str, Dict[str, Any]] = {}
        self._lock = threading.Lock()

        # retry settings
        self.order_retry_attempts = int(order_retry_attempts)
        self.order_retry_base = float(order_retry_base)
        self.order_retry_max = float(order_retry_max)

    def _sanitize_kwargs(self, kwargs: Dict[str, Any]) -> Dict[str, Any]:
        kw = dict(kwargs)
        kw.pop("cid", None)
        kw.pop("event_id", None)
        return kw

    def _retry_call(self, func: Callable, attempts: int, base: float, maxi: float, *args, **kwargs):
        """
        Retry helper with exponential backoff. Retries on any Exception raised by func.
        Returns result of func or raises last exception.
        """
        last_exc = None
        delay = base
        # do not forward tracing keys if present
        if kwargs:
            sanitized_kwargs = dict(kwargs)
            sanitized_kwargs.pop("cid", None)
            sanitized_kwargs.pop("event_id", None)
            kwargs = sanitized_kwargs

        for attempt in range(1, attempts + 1):
            try:
                return func(*args, **kwargs)
            except Exception as e:
                last_exc = e
                if attempt == attempts:
                    raise
                # sleep min(delay, maxi)
                time.sleep(min(delay, maxi))
                delay = min(delay * 2.0, maxi)
        if last_exc:
            raise last_exc

    def start_job(self,
                  symbol: str,
                  side: str,
                  total_amount: float,
                  slices: int = 1,
                  price: Optional[float] = None,
                  duration_seconds: float = 0.0,
                  order_delay_seconds: Optional[float] = None,
                  extra: Optional[Dict[str, Any]] = None) -> str:
        """
        Launch a TWAP job in background and return job_id immediately.
        """
        if slices < 1:
            raise ValueError("slices must be >= 1")
        job_id = uuid.uuid4().hex
        cancel_ev = threading.Event()
        job_meta = {
            "id": job_id,
            "status": "running",
            "results": [],
            "error": None,
            "cancel_event": cancel_ev,
            "thread": None,
        }
        with self._lock:
            self._jobs[job_id] = job_meta

        def _worker():
            try:
                slice_amount = float(total_amount) / float(slices)
                delay = float(duration_seconds) / float(slices) if slices > 0 else 0.0
                effective_delay = order_delay_seconds if order_delay_seconds is not None else (
                    self.default_order_delay if self.default_order_delay is not None else delay
                )

                for i in range(slices):
                    if cancel_ev.is_set():
                        with self._lock:
                            job_meta["status"] = "canceled"
                        return

                    kwargs: Dict[str, Any] = {
                        "symbol": symbol,
                        "side": side,
                        "amount": slice_amount
                    }
                    if price is not None:
                        kwargs["price"] = price
                    if extra:
                        kwargs.update(extra)
                    kwargs = self._sanitize_kwargs(kwargs)

                    # attempt placing with retry/backoff
                    try:
                        res = self._retry_call(
                            self.place_order_fn,
                            attempts=self.order_retry_attempts,
                            base=self.order_retry_base,
                            maxi=self.order_retry_max,
                            **kwargs
                        )
                    except Exception as e:
                        with self._lock:
                            job_meta["status"] = "failed"
                            job_meta["error"] = str(e)
                        return

                    with self._lock:
                        job_meta["results"].append(res)

                    # sleep between slices (cooperative with cancel)
                    if i < slices - 1 and effective_delay and effective_delay > 0:
                        slept = 0.0
                        chunk = min(0.05, effective_delay)
                        while slept < effective_delay:
                            if cancel_ev.is_set():
                                with self._lock:
                                    job_meta["status"] = "canceled"
                                return
                            time.sleep(chunk)
                            slept += chunk
                with self._lock:
                    job_meta["status"] = "completed"
            except Exception as e:
                with self._lock:
                    job_meta["status"] = "failed"
                    job_meta["error"] = str(e)

        t = threading.Thread(target=_worker, daemon=True)
        job_meta["thread"] = t
        t.start()
        return job_id

    def cancel_job(self, job_id: str) -> bool:
        with self._lock:
            job = self._jobs.get(job_id)
            if not job:
                return False
            job["cancel_event"].set()
        return True

    def get_status(self, job_id: str) -> Optional[str]:
        with self._lock:
            job = self._jobs.get(job_id)
            return job["status"] if job else None

    def get_results(self, job_id: str) -> Optional[List[Any]]:
        with self._lock:
            job = self._jobs.get(job_id)
            return list(job["results"]) if job else None

    def list_jobs(self) -> List[Dict[str, Any]]:
        with self._lock:
            return [{ "id": v["id"], "status": v["status"], "n_results": len(v["results"]) } for v in self._jobs.values()]
