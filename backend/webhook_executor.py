# backend/webhook_executor.py
"""
Webhook Executor - idempotent & retrying (dedupe is opt-in)

Features:
 - idempotent processing using a processed-registry (file-backed JSONL) if enabled
 - deterministic event_id (use event-provided id if present, else SHA256(payload))
 - correlation id (cid) support for tracing
 - retry wrapper for broker.place_order (exponential backoff)
 - safe append to optional processed_path in process_file
 - structured logging

Control via env:
 - WEBHOOK_ENABLE_DEDUP (default: false) -> when true, use persistent processed-registry
 - WEBHOOK_PROCESSED_PATH (default if dedup enabled: ./webhook_processed.jsonl)
 - WEBHOOK_ORDER_RETRIES (default: 3)
 - WEBHOOK_ORDER_RETRY_BASE (seconds, default: 0.5)
 - WEBHOOK_ORDER_RETRY_MAX  (seconds, default: 5.0)
"""

import os
import json
import time
import uuid
import hashlib
import logging
import threading
from typing import Dict, Any, List, Optional, Callable

# Notifications (Telegram/Slack wrapper)
from bot_core.notifications.async_notify import AsyncNotifier

# Build an async notifier from environment (dry_run if no creds)
_notifier = AsyncNotifier.from_env(dry_run_if_no_creds=True)

# Logging setup (module-level logger)
logger = logging.getLogger("webhook_executor")
if not logger.handlers:
    ch = logging.StreamHandler()
    # Keep the formatter simple and JSON-ish for downstream log collectors.
    ch.setFormatter(logging.Formatter(
        '{"ts":"%(asctime)s","level":"%(levelname)s","cid":"%(cid)s","event_id":"%(event_id)s","msg":%(message)s}'
    ))
    logger.addHandler(ch)
logger.setLevel(os.environ.get("WEBHOOK_EXECUTOR_LOGLEVEL", "INFO").upper())


def _log(level: str, msg: Any, cid: str = "-", event_id: str = "-", **extra):
    """
    Lightweight structured logger wrapper. `msg` can be str or serializable object.
    Extra will be included in the JSON payload.
    """
    try:
        payload = {"msg": msg}
        if extra:
            payload["extra"] = extra
        j = json.dumps(payload, default=str)
    except Exception:
        j = json.dumps({"msg": str(msg)})
    extra_dict = {"cid": cid, "event_id": event_id}
    if level.lower() == "info":
        logger.info(j, extra=extra_dict)
    elif level.lower() == "warning":
        logger.warning(j, extra=extra_dict)
    elif level.lower() == "error":
        logger.error(j, extra=extra_dict)
    else:
        logger.debug(j, extra=extra_dict)


# Feature flag: enable dedupe/persistent registry only if explicitly turned on.
_ENABLE_DEDUP = os.environ.get("WEBHOOK_ENABLE_DEDUP", "false").lower() in ("1", "true", "yes")

# Configurable processed-registry path (used only when dedupe enabled)
PROCESSED_REGISTRY_PATH = os.environ.get(
    "WEBHOOK_PROCESSED_PATH",
    os.path.join(os.getcwd(), "webhook_processed.jsonl")
) if _ENABLE_DEDUP else None

# Retry config (always present)
_ORDER_RETRY_ATTEMPTS = int(os.environ.get("WEBHOOK_ORDER_RETRIES", "3"))
_ORDER_RETRY_BASE = float(os.environ.get("WEBHOOK_ORDER_RETRY_BASE", "0.5"))
_ORDER_RETRY_MAX = float(os.environ.get("WEBHOOK_ORDER_RETRY_MAX", "5.0"))


class _NoopRegistry:
    """No-op registry used when dedupe is disabled (fast, no file IO)."""
    def contains(self, event_id: str) -> bool:
        return False

    def add(self, event_id: str, meta: Optional[Dict[str, Any]] = None) -> None:
        # no-op
        return None


class ProcessedRegistry:
    """
    Simple persistent registry of processed event_ids stored as JSONL lines.
    Each line: {"event_id": "...", "ts": ..., "meta": {...}}
    """

    def __init__(self, path: str):
        self.path = path
        self._lock = threading.Lock()
        self._seen = set()
        try:
            os.makedirs(os.path.dirname(self.path) or ".", exist_ok=True)
        except Exception:
            pass
        self._load()

    def _load(self):
        if not os.path.exists(self.path):
            return
        try:
            with open(self.path, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        rec = json.loads(line)
                        eid = rec.get("event_id")
                        if eid:
                            self._seen.add(eid)
                    except Exception:
                        # skip malformed lines
                        continue
        except Exception:
            # best-effort: if we cannot load, start empty
            pass

    def contains(self, event_id: str) -> bool:
        with self._lock:
            return event_id in self._seen

    def add(self, event_id: str, meta: Optional[Dict[str, Any]] = None) -> None:
        rec = {"event_id": event_id, "ts": time.time(), "meta": meta or {}}
        line = json.dumps(rec, default=str)
        with self._lock:
            with open(self.path, "a", encoding="utf-8") as f:
                f.write(line + "\n")
            self._seen.add(event_id)


# Choose registry implementation depending on the feature flag.
if _ENABLE_DEDUP and PROCESSED_REGISTRY_PATH:
    try:
        _PROCESSED_REGISTRY = ProcessedRegistry(PROCESSED_REGISTRY_PATH)
    except Exception as e:
        _log("warning", f"failed to initialize processed registry (falling back to noop): {e}")
        _PROCESSED_REGISTRY = _NoopRegistry()
else:
    _PROCESSED_REGISTRY = _NoopRegistry()


def _generate_event_id(event: Dict[str, Any]) -> str:
    """
    Deterministic event id:
     - If event contains 'id' or 'event_id', prefer that.
     - Else, compute sha256 of canonical json of the 'payload' if present, else of the whole event.
    """
    if not isinstance(event, dict):
        event = {"raw": event}
    for key in ("event_id", "id", "evt_id"):
        if key in event and event.get(key):
            return str(event.get(key))

    core = event.get("payload", event)
    try:
        s = json.dumps(core, sort_keys=True, separators=(",", ":"), default=str)
    except Exception:
        s = str(core)
    return hashlib.sha256(s.encode("utf-8")).hexdigest()


def _generate_pid() -> str:
    return f"evt-{int(time.time()*1000)}-{uuid.uuid4().hex[:8]}"


def _retry_call(func: Callable, attempts: int = _ORDER_RETRY_ATTEMPTS,
                base: float = _ORDER_RETRY_BASE, maxi: float = _ORDER_RETRY_MAX, *args, **kwargs):
    """
    Retry helper with exponential backoff. Retries on any Exception raised by func.
    Logs with correlation info when available (expects 'cid' and 'event_id' in kwargs optionally).
    """
    last_exc = None
    delay = base
    # capture correlation info for logging (use these even if we remove them from kwargs)
    cid = kwargs.get("cid", "-")
    event_id = kwargs.get("event_id", "-")

    # sanitize kwargs so we don't forward internal-only tracing keys (like 'cid') to brokers
    if kwargs and 'cid' in kwargs:
        kwargs = dict(kwargs)
        kwargs.pop('cid', None)

    for attempt in range(1, attempts + 1):
        try:
            return func(*args, **kwargs)
        except Exception as e:
            last_exc = e
            if attempt == attempts:
                _log("error", f"order call failed after {attempt} attempts: {e}", cid=cid, event_id=event_id)
                raise
            _log("warning", f"order call attempt {attempt} failed; retrying after {delay}s: {e}", cid=cid, event_id=event_id)
            time.sleep(min(delay, maxi))
            delay = min(delay * 2.0, maxi)
    if last_exc:
        raise last_exc



def _extract_order_price_from(order: Any) -> Optional[float]:
    """Best-effort extract numeric price from broker response dict/object."""
    if order is None:
        return None
    if isinstance(order, dict):
        for k in ("price", "filled_price", "avg_price"):
            v = order.get(k)
            if v is None:
                continue
            try:
                return float(v)
            except Exception:
                continue
    try:
        v = getattr(order, "price", None)
        if v is not None:
            return float(v)
    except Exception:
        pass
    return None


def process_event(event: Dict[str, Any], broker, risk_manager) -> Dict[str, Any]:
    """
    Idempotent processing of a single webhook event.
    Returns a result dict with 'event_id' and 'cid' included.
    """
    if not isinstance(event, dict):
        return {"status": "error", "reason": "event must be a dict", "event": event}

    # correlation id for tracing
    cid = event.get("cid") or event.get("correlation_id") or uuid.uuid4().hex
    # compute stable event id
    event_id = _generate_event_id(event)

    _log("info", "processing event", cid=cid, event_id=event_id, event=event)

    # Dedup check using registry (noop when dedup disabled)
    try:
        if _PROCESSED_REGISTRY.contains(event_id):
            _log("info", "duplicate event detected; skipping", cid=cid, event_id=event_id)
            return {"status": "duplicate", "reason": "event_already_processed", "event": event, "event_id": event_id, "cid": cid}
    except Exception as e:
        # registry errors are non-fatal
        _log("warning", f"processed-registry check failed: {e}; continuing", cid=cid, event_id=event_id)

    # parse fields
    try:
        strategy = event.get("strategy")
        signal = (event.get("signal") or "").lower()
        symbol = event.get("symbol")
        amount = event.get("amount", None)
        price = event.get("price", None)
    except Exception as e:
        res = {"status": "error", "reason": f"invalid event format: {e}", "event": event, "event_id": event_id, "cid": cid}
        try:
            _PROCESSED_REGISTRY.add(event_id, {"status": "error", "reason": "invalid_format"})
        except Exception:
            pass
        return res

    base_meta = {"event": event, "event_id": event_id, "cid": cid}

    # Basic validation
    if not symbol or not signal:
        res = {"status": "error", "reason": "missing symbol or signal", **base_meta}
        try:
            _PROCESSED_REGISTRY.add(event_id, {"status": "error", "reason": "missing_symbol_or_signal"})
        except Exception:
            pass
        return res

    # BUY / LONG
    if signal in ("buy", "long", "buy_option"):
        # risk check
        try:
            if risk_manager is not None and not risk_manager.can_open_new():
                res = {"status": "rejected", "reason": "max_concurrent_deals", **base_meta}
                try:
                    _PROCESSED_REGISTRY.add(event_id, {"status": "rejected", "reason": "max_concurrent_deals"})
                except Exception:
                    pass
                return res
        except Exception as e:
            res = {"status": "error", "reason": f"risk_manager error: {e}", **base_meta}
            try:
                _PROCESSED_REGISTRY.add(event_id, {"status": "error", "reason": "risk_mgr_check_failed"})
            except Exception:
                pass
            return res

        # order amount fallback
        order_amount = amount
        if order_amount is None and risk_manager is not None:
            order_amount = getattr(risk_manager, "initial_balance", None)
            if order_amount is None:
                order_amount = 1.0
            order_amount = float(order_amount) * 0.01

        # place order with retry (pass correlation info but Broker should filter unexpected kwargs)
        try:
            order = _retry_call(
                broker.place_order,
                attempts=_ORDER_RETRY_ATTEMPTS,
                base=_ORDER_RETRY_BASE,
                maxi=_ORDER_RETRY_MAX,
                symbol=symbol, side="buy", amount=float(order_amount), price=price,
                cid=cid, event_id=event_id
            )
        except Exception as e:
            res = {"status": "error", "reason": f"broker place_order failed after retries: {e}", "event": event, **base_meta}
            try:
                _PROCESSED_REGISTRY.add(event_id, {"status": "error", "reason": "broker_place_failed"})
            except Exception:
                pass
            return res

        # register in risk manager
        pid = _generate_pid()
        try:
            if risk_manager is not None:
                entry_price = None
                if price is not None:
                    try:
                        entry_price = float(price)
                    except Exception:
                        entry_price = None

                if entry_price is None:
                    cand = _extract_order_price_from(order)
                    entry_price = float(cand) if cand is not None else 0.0

                size = None
                if isinstance(order, dict):
                    s = order.get("size", None)
                    if s is not None:
                        try:
                            size = float(s)
                        except Exception:
                            size = None

                risk_manager.open_position(
                    pid=pid,
                    side="long",
                    entry_price=float(entry_price or 0.0),
                    amount=float(order_amount),
                    size=size,
                    strategy=strategy
                )
        except Exception as e:
            res = {"status": "error", "reason": f"risk_manager.open_position failed: {e}", "order": order, "event": event, **base_meta}
            try:
                _PROCESSED_REGISTRY.add(event_id, {"status": "error", "reason": "rm_open_failed", "order_id": (order or {}).get("id") if isinstance(order, dict) else getattr(order, "id", None)})
            except Exception:
                pass
            return res

        res = {"status": "ok", "action": "buy", "order": order, "pid": pid, **base_meta}
        # persist processed marker (noop when dedupe disabled)
        try:
            _PROCESSED_REGISTRY.add(event_id, {"status": "ok", "action": "buy", "pid": pid, "order_id": (order or {}).get("id") if isinstance(order, dict) else getattr(order, "id", None)})
        except Exception:
            _log("warning", "failed to persist processed mark for event", cid=cid, event_id=event_id)

        # notify (best-effort)
        try:
            msg = f"Webhook: BUY OK — signal={signal} symbol={symbol} strat={strategy} pid={pid}"
            _notifier.send_async(msg, channels=["telegram"])
        except Exception:
            pass
        return res

    # SELL / EXIT / SHORT
    if signal in ("sell", "exit", "short"):
        if risk_manager is None:
            order_amount = amount or 1.0
            try:
                order = _retry_call(
                    broker.place_order,
                    attempts=_ORDER_RETRY_ATTEMPTS,
                    base=_ORDER_RETRY_BASE,
                    maxi=_ORDER_RETRY_MAX,
                    symbol=symbol, side="sell", amount=float(order_amount), price=price,
                    cid=cid, event_id=event_id
                )
                res = {"status": "ok", "action": "sell", "order": order, **base_meta}
                try:
                    _PROCESSED_REGISTRY.add(event_id, {"status": "ok", "action": "sell", "order_id": (order or {}).get("id") if isinstance(order, dict) else getattr(order, "id", None)})
                except Exception:
                    pass
                return res
            except Exception as e:
                res = {"status": "error", "reason": f"broker place_order failed: {e}", "event": event, **base_meta}
                try:
                    _PROCESSED_REGISTRY.add(event_id, {"status": "error", "reason": "broker_place_failed_sell"})
                except Exception:
                    pass
                return res

        # find open position to close
        found_pid = None
        for pid, pos in list(risk_manager.list_positions().items()):
            if strategy:
                if pos.get("strategy") == strategy:
                    found_pid = pid
                    break
            else:
                found_pid = pid
                break

        if not found_pid:
            res = {"status": "rejected", "reason": "no matching position to close", "event": event, **base_meta}
            try:
                _PROCESSED_REGISTRY.add(event_id, {"status": "rejected", "reason": "no_matching_position"})
            except Exception:
                pass
            return res

        pos = risk_manager.get_position(found_pid)
        if pos is None:
            res = {"status": "error", "reason": "selected position disappeared", "pid": found_pid, "event": event, **base_meta}
            try:
                _PROCESSED_REGISTRY.add(event_id, {"status": "error", "reason": "position_missing", "pid": found_pid})
            except Exception:
                pass
            return res

        sell_amount = pos.get("size") or pos.get("amount") or amount or 1.0
        try:
            order = _retry_call(
                broker.place_order,
                attempts=_ORDER_RETRY_ATTEMPTS,
                base=_ORDER_RETRY_BASE,
                maxi=_ORDER_RETRY_MAX,
                symbol=symbol, side="sell", amount=float(sell_amount), price=price,
                cid=cid, event_id=event_id
            )
        except Exception as e:
            res = {"status": "error", "reason": f"broker place_order failed: {e}", "pid": found_pid, "event": event, **base_meta}
            try:
                _PROCESSED_REGISTRY.add(event_id, {"status": "error", "reason": "broker_place_failed_sell", "pid": found_pid})
            except Exception:
                pass
            return res

        # close in risk manager
        try:
            risk_manager.close_position(found_pid)
        except Exception as e:
            res = {"status": "partial", "reason": f"order_placed_rm_close_failed: {e}", "order": order, "pid": found_pid, **base_meta}
            try:
                _PROCESSED_REGISTRY.add(event_id, {"status": "partial", "reason": "rm_close_failed", "pid": found_pid})
            except Exception:
                pass
            return res

        res = {"status": "ok", "action": "sell", "order": order, "pid": found_pid, **base_meta}
        try:
            _PROCESSED_REGISTRY.add(event_id, {"status": "ok", "action": "sell", "pid": found_pid, "order_id": (order or {}).get("id") if isinstance(order, dict) else getattr(order, "id", None)})
        except Exception:
            pass

        try:
            msg = f"Webhook: SELL OK — signal={signal} symbol={symbol} strat={strategy} pid={found_pid}"
            _notifier.send_async(msg, channels=["telegram"])
        except Exception:
            pass
        return res

    # unknown signal
    res = {"status": "ignored", "reason": "unknown signal", **base_meta}
    try:
        _PROCESSED_REGISTRY.add(event_id, {"status": "ignored", "reason": "unknown_signal"})
    except Exception:
        pass
    return res


def process_file(path: str, broker, risk_manager, processed_path: Optional[str] = None) -> List[Dict[str, Any]]:
    """
    Process a jsonlines file where each line is a JSON event.
    If processed_path provided, append a JSON record for each processed event with result metadata.
    Returns the list of result dicts.
    """
    results: List[Dict[str, Any]] = []
    if not os.path.exists(path):
        raise FileNotFoundError(path)

    if processed_path:
        os.makedirs(os.path.dirname(processed_path) or ".", exist_ok=True)

    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                event = json.loads(line)
            except Exception as e:
                res = {"status": "error", "reason": f"failed to parse json: {e}", "line": line}
                results.append(res)
                if processed_path:
                    with open(processed_path, "a", encoding="utf-8") as pf:
                        pf.write(json.dumps(res, default=str) + "\n")
                continue

            try:
                r = process_event(event, broker, risk_manager)
            except Exception as e:
                r = {"status": "error", "reason": f"executor exception: {e}", "event": event}

            results.append(r)
            if processed_path:
                try:
                    with open(processed_path, "a", encoding="utf-8") as pf:
                        pf.write(json.dumps(r, default=str) + "\n")
                except Exception:
                    _log("warning", "failed to write processed_path entry", cid=r.get("cid", "-"), event_id=r.get("event_id", "-"))

            # best-effort notification
            try:
                ev_sig = event.get("signal", "<no-signal>")
                ev_sym = event.get("symbol", "<no-symbol>")
                ev_strat = event.get("strategy", "<no-strategy>")
                status = r.get("status", "unknown")
                pid = r.get("pid") or (r.get("order") or {}).get("id")
                msg = f"Webhook: {status.upper()} — signal={ev_sig} symbol={ev_sym} strat={ev_strat}"
                if pid:
                    msg += f" pid={pid}"
                try:
                    _notifier.send_async(msg, channels=["telegram"])
                except Exception:
                    pass
            except Exception:
                pass

    return results
