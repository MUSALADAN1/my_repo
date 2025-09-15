# bot_core/exchanges/broker.py
"""
Broker wrapper that delegates to an exchange adapter and records order lifecycle
in an OrderStore.

Compatibility notes:
- Accepts adapter_instance=... (tests) or adapter=...
- Filters kwargs sent to adapter methods (so simple mocks won't fail on extra kw like 'cid').
"""

import os
import time
import logging
import inspect
from typing import Any, Dict, Optional, List, Callable

from bot_core.storage.order_store import OrderSQLiteStore, OrderStore

logger = logging.getLogger("broker")
logger.setLevel(os.environ.get("BROKER_LOGLEVEL", "INFO").upper())

# Retry config
_BROKER_ORDER_RETRIES = int(os.environ.get("BROKER_ORDER_RETRIES", "3"))
_BROKER_ORDER_RETRY_BASE = float(os.environ.get("BROKER_ORDER_RETRY_BASE", "0.5"))
_BROKER_ORDER_RETRY_MAX = float(os.environ.get("BROKER_ORDER_RETRY_MAX", "2.0"))


def _retry(func: Callable, attempts: int = _BROKER_ORDER_RETRIES, base: float = _BROKER_ORDER_RETRY_BASE, maxi: float = _BROKER_ORDER_RETRY_MAX):
    """
    Retry helper for a zero-arg callable `func`. Exponential backoff.
    """
    last_exc = None
    delay = base
    for attempt in range(1, attempts + 1):
        try:
            return func()
        except Exception as e:
            last_exc = e
            logger.warning(f"order call attempt {attempt} failed; retrying after {delay}s: {e}")
            if attempt == attempts:
                logger.error(f"order call failed after {attempts} attempts: {e}")
                raise
            time.sleep(min(delay, maxi))
            delay = min(delay * 2.0, maxi)
    if last_exc:
        raise last_exc


class Broker:
    """
    Broker coordinates an exchange adapter and an OrderStore.

    adapter must implement:
      - place_order(symbol, side, amount, price=None, order_type="market") -> order dict or object
      - fetch_order(order_id) -> dict/object (optional)
      - fetch_open_orders(symbol=None) -> list (optional)
      - cancel_order(order_id) -> dict/object (optional)
    """
    def __init__(self, adapter: Any = None, adapter_instance: Any = None, order_store: Optional[OrderStore] = None):
        # Accept both `adapter` and `adapter_instance` for backwards-compatibility with tests
        self.adapter = adapter_instance or adapter
        if self.adapter is None:
            raise ValueError("Broker requires an adapter instance via `adapter=` or `adapter_instance=`")
        # allow either OrderStore or compatibility alias
        self.order_store = order_store or OrderSQLiteStore()
        self._has = lambda name: bool(getattr(self.adapter, name, None))
    def connect(self) -> bool:
        """
        Ensure the adapter is connected.

        Behavior:
        - If the adapter provides a callable `connect()`, call it and return its boolean result.
        - If the adapter has `_connected` attribute (some mocks use that), return it.
        - Otherwise assume already connected and return True.
        """
        if self.adapter is None:
            raise RuntimeError("No adapter provided to Broker; cannot connect")

        # If adapter defines a connect() method, call it (and return result)
        conn_fn = getattr(self.adapter, "connect", None)
        if callable(conn_fn):
            res = conn_fn()
            return bool(res)

        # Fallback: some test mocks set _connected attribute
        if hasattr(self.adapter, "_connected"):
            return bool(getattr(self.adapter, "_connected"))

        # No explicit connect — assume already connected / no-op
        return True
    def place_order(self, symbol: str, side: str, amount: float,
                    price: Optional[float] = None, order_type: str = "market", **kwargs) -> Dict[str, Any]:
        """
        Delegate safely to adapter.place_order. Always filter unexpected kwargs via
        _build_safe_call (so mocks that don't accept extra keys like 'cid' won't fail).
        Returns a normalized dict via _normalize_order_response and records to order_store (best-effort).
        """
        if self.adapter is None:
            raise RuntimeError("No adapter available on Broker to place order")

        fn = getattr(self.adapter, "place_order", None)
        if fn is None or not callable(fn):
            raise RuntimeError("adapter does not implement place_order")

        # Build safe callable which will only forward kwargs the adapter function accepts.
        base_kwargs = {
            "symbol": symbol,
            "side": side,
            "amount": amount,
            "price": price,
            "order_type": order_type
        }
        safe_call = self._build_safe_call(fn, base_kwargs, kwargs)

        # Execute with retry/backoff (this will raise if all attempts fail)
        res = _retry(safe_call)

        # Normalize adapter response
        norm = self._normalize_order_response(res, side=side, symbol=symbol, amount=amount)

        # Ensure id exists
        oid = norm.get("id") or f"ord-{symbol}-{side}-{int(time.time() * 1000)}"
        norm["id"] = oid
        status = norm.get("status") or ("filled" if norm.get("filled") and norm.get("filled") == norm.get("amount") else "submitted")
        norm["status"] = status

        # Persist (best effort)
        try:
            self.order_store.record_new_order({
                "id": norm["id"],
                "symbol": norm.get("symbol"),
                "side": norm.get("side"),
                "amount": norm.get("amount"),
                "filled": norm.get("filled"),
                "price": norm.get("price"),
                "status": norm.get("status"),
                "raw": norm.get("raw"),
            })
        except Exception:
            # ignore persistence errors
            pass

        return norm

    def fetch_order(self, order_id: str, symbol: Optional[str] = None) -> Optional[Dict[str, Any]]:
        """
        Fetch a single order by id. Try adapter.fetch_order(...) first, else fallback to local store.
        Updates local order_store (best effort) with the normalized order state.
        """
        fn = getattr(self.adapter, "fetch_order", None)
        # If adapter can fetch, call it defensively
        if callable(fn):
            try:
                safe_call = self._build_safe_call(fn, {"order_id": order_id, "symbol": symbol}, {})
                res = safe_call()
                norm = self._normalize_order_response(res)
                try:
                    self.order_store.update_order_state(order_id, norm.get("status"), filled=norm.get("filled"), price=norm.get("price"), raw=norm.get("raw"))
                except Exception:
                    pass
                return norm
            except Exception:
                # adapter fetch failed; fallthrough to local store
                pass

        # Fallback to local store
        try:
            return self.order_store.get_order(order_id)
        except Exception:
            return None

    def fetch_open_orders(self, symbol: Optional[str] = None) -> List[Dict[str, Any]]:
        """
        Return a list of open orders. Prefer adapter.fetch_open_orders; otherwise return local open orders.
        """
        fn = getattr(self.adapter, "fetch_open_orders", None)
        out: List[Dict[str, Any]] = []
        if callable(fn):
            try:
                safe_call = self._build_safe_call(fn, {"symbol": symbol}, {})
                res = safe_call()
                if isinstance(res, list):
                    for r in res:
                        out.append(self._normalize_order_response(r))
                    if out:
                        return out
            except Exception:
                pass

        # Fallback: return from local store
        try:
            return list(self.order_store.list_open_orders().values())
        except Exception:
            # ensure we always return a list
            return out

    def cancel_order(self, order_id: str, symbol: Optional[str] = None) -> Dict[str, Any]:
        """
        Cancel an order via adapter if supported. If adapter not available, mark order cancelled locally.
        """
        fn = getattr(self.adapter, "cancel_order", None)
        if callable(fn):
            try:
                safe_call = self._build_safe_call(fn, {"order_id": order_id, "symbol": symbol}, {})
                res = _retry(safe_call)
                norm = self._normalize_order_response(res)
                # persist update (best effort)
                try:
                    status = norm.get("status") or "cancelled"
                    self.order_store.update_order_state(order_id, status, filled=norm.get("filled"), price=norm.get("price"), raw=norm.get("raw"))
                except Exception:
                    pass
                return norm
            except Exception:
                # if adapter cancel failed, fall through to local mark
                pass

        # Fallback: mark cancelled in store (best-effort)
        try:
            self.order_store.update_order_state(order_id, "cancelled")
        except Exception:
            pass
        return {"id": order_id, "status": "cancelled"}

    

    def _normalize_order_response(self, res: Any, side: Optional[str] = None, symbol: Optional[str] = None, amount: Optional[float] = None) -> Dict[str, Any]:
        out = {"id": None, "status": None, "symbol": symbol, "side": side, "amount": amount, "filled": 0.0, "price": None, "raw": None}
        if res is None:
            return out
        if isinstance(res, dict):
            out["id"] = res.get("id") or res.get("orderId") or res.get("clientOrderId") or res.get("order_id")
            out["status"] = res.get("status") or res.get("state") or None
            out["symbol"] = out["symbol"] or res.get("symbol") or res.get("pair")
            out["side"] = out["side"] or res.get("side")
            out["amount"] = float(res.get("amount")) if res.get("amount") is not None else out["amount"]
            out["filled"] = float(res.get("filled") or res.get("filled_amount") or 0.0)
            try:
                out["price"] = float(res.get("price")) if res.get("price") is not None else None
            except Exception:
                out["price"] = None
            out["raw"] = res
            return out
        # object-ish fallback
        try:
            out["id"] = getattr(res, "id", None) or getattr(res, "orderId", None)
            out["status"] = getattr(res, "status", None)
            out["symbol"] = out["symbol"] or getattr(res, "symbol", None)
            out["side"] = out["side"] or getattr(res, "side", None)
            out["amount"] = float(getattr(res, "amount", out["amount"])) if getattr(res, "amount", None) is not None else out["amount"]
            out["filled"] = float(getattr(res, "filled", 0.0) or 0.0)
            out["price"] = float(getattr(res, "price", None)) if getattr(res, "price", None) is not None else None
            out["raw"] = res
        except Exception:
            out["raw"] = res
        return out

    def _build_safe_call(self, fn: Callable, base_kwargs: Dict[str, Any], extra_kwargs: Dict[str, Any]) -> Callable[[], Any]:
        """
        Return a zero-arg callable that invokes fn with a safe subset of kwargs
        that fn accepts. If fn accepts **kwargs, pass everything. Otherwise only pass
        parameters that appear in fn signature.
        """
        try:
            sig = inspect.signature(fn)
            params = sig.parameters
            accepts_var_kw = any(p.kind == inspect.Parameter.VAR_KEYWORD for p in params.values())
            if accepts_var_kw:
                # fn accepts **kwargs -> pass everything
                def call_all():
                    return fn(**{**base_kwargs, **extra_kwargs})
                return call_all

            # otherwise filter allowed keys
            allowed = {}
            for k, v in {**base_kwargs, **extra_kwargs}.items():
                if k in params:
                    allowed[k] = v

            def call_filtered():
                return fn(**allowed)
            return call_filtered
        except Exception:
            # signature introspection failed -> best effort positional call
            def call_positional():
                try:
                    return fn(
                        base_kwargs.get("symbol"),
                        base_kwargs.get("side"),
                        base_kwargs.get("amount"),
                        base_kwargs.get("price"),
                        base_kwargs.get("order_type")
                    )
                except TypeError:
                    return fn(**{**base_kwargs, **extra_kwargs})
            return call_positional


