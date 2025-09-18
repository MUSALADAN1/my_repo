# bot_core/execution/twap.py
"""
Simple TWAP Executor

- Splits a total_amount into `slices` equal parts and places them one-by-one via broker.place_order.
- Supports optional duration_seconds to distribute slices over time (delay = duration_seconds / slices).
- For tests we allow overriding the delay by passing order_delay_seconds to the constructor (set to 0 to avoid sleeps).
- Sanitizes kwargs so tracing keys like 'cid' / 'event_id' won't be forwarded to brokers that don't accept them.

This is intentionally small and synchronous so it's easy to test and reason about.
Later we can add:
 - async / background mode
 - smarter sizing (remainder allocation)
 - VWAP mode with volume buckets
 - retry & backoff for each slice (or delegate to webhook_executor._retry_call)
"""
from __future__ import annotations

import time
from typing import Any, Dict, List, Optional


class TWAPExecutor:
    def __init__(self, broker, order_delay_seconds: Optional[float] = None):
        """
        :param broker: broker object with place_order(symbol, side, amount, price=None, **kwargs)
        :param order_delay_seconds: if provided, use this fixed delay between slices.
                                     Otherwise delay is computed from duration_seconds / slices.
        """
        self.broker = broker
        self.order_delay_seconds = order_delay_seconds

    def _sanitize_kwargs(self, kwargs: Dict[str, Any]) -> Dict[str, Any]:
        kw = dict(kwargs)
        kw.pop("cid", None)
        kw.pop("event_id", None)
        return kw

    def execute(
        self,
        symbol: str,
        side: str,
        total_amount: float,
        duration_seconds: float = 0.0,
        slices: int = 1,
        price: Optional[float] = None,
        extra: Optional[Dict[str, Any]] = None,
    ) -> List[Any]:
        """
        Execute TWAP synchronously.

        Returns list of broker responses (whatever broker.place_order returns).

        Basic behaviour:
          - slice_amount = total_amount / slices
          - for i in 0..slices-1:
              - place_order(symbol, side, amount=slice_amount, price=price, **extra)
              - sleep(delay) unless it's the last slice

        Note: for production you may want to:
          - allocate remainders so sum(slice_amounts) == total_amount exactly
          - perform async execution, or a scheduled background job
          - use better error handling & retry
        """
        if slices < 1:
            raise ValueError("slices must be >= 1")

        slice_amount = float(total_amount) / float(slices)
        delay = float(duration_seconds) / float(slices) if slices > 0 else 0.0

        results = []
        for i in range(slices):
            kwargs: Dict[str, Any] = {"symbol": symbol, "side": side, "amount": slice_amount}
            if price is not None:
                kwargs["price"] = price
            if extra:
                kwargs.update(extra)
            kwargs = self._sanitize_kwargs(kwargs)
            res = self.broker.place_order(**kwargs)
            results.append(res)

            # Sleep between slices (no sleep after last slice)
            if i < slices - 1:
                to_sleep = self.order_delay_seconds if self.order_delay_seconds is not None else delay
                if to_sleep and to_sleep > 0:
                    time.sleep(to_sleep)

        return results
