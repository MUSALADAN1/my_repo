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

    import os
from uuid import uuid4
import logging

logger = logging.getLogger(__name__)

def _is_dry_run_enabled() -> bool:
    v = os.getenv("DRY_RUN", "1")
    return str(v).lower() in ("1", "true", "yes", "on")

def place_order(symbol: str, side: str, amount: float, price: float = None, order_type: str = "market", **kwargs) -> Dict[str, Any]:
        """
        Place order via adapter, store lifecycle in order_store.
        Robustly avoids forwarding unexpected kwargs to adapter.

        If DRY_RUN env var is enabled (default), *simulate* the order and persist
        a dry-run order in the order_store to keep downstream code/tests working.
        """
        # Safe default: simulate order instead of calling exchange live
        if _is_dry_run_enabled():
            oid = f"dryrun-{uuid4().hex[:12]}"
            logger.info("DRY_RUN enabled: simulating order %s %s %s@%s id=%s", side, amount, symbol, price, oid)
            norm = {
                "id": oid,
                "symbol": symbol,
                "side": side,
                "amount": amount,
                "price": price,
                "filled": False,
                "status": "dry_run",
                "raw": {"dry_run": True, "provided_kwargs": kwargs}
            }
            # persist simulated order so tests and order_store consumers still see it
            try:
                self.order_store.record_new_order({
                    "id": norm["id"],
                    "symbol": norm["symbol"],
                    "side": norm["side"],
                    "amount": norm["amount"],
                    "filled": norm["filled"],
                    "price": norm["price"],
                    "status": norm["status"],
                    "raw": norm["raw"]
                })
            except Exception as e:
                logger.debug("Failed to persist dry-run order: %s", e)
            return norm

        # --- live path (unchanged behavior) ---
        fn = getattr(self.adapter, "place_order", None)
        if fn is None:
            raise RuntimeError("adapter does not implement place_order")

        base_kwargs = {"symbol": symbol, "side": side, "amount": amount, "price": price, "order_type": order_type}
        safe_call = self._build_safe_call(fn, base_kwargs, kwargs)

        # perform call with retries
        res = _retry(safe_call)

        norm = self._normalize_order_response(res, side=side, symbol=symbol, amount=amount)
        # ensure id exists
        oid = norm["id"] or f"ord-{symbol}-{side}-{int(time.time()*1000)}"
        norm["id"] = oid
        status = norm["status"] or ("filled" if norm.get("filled") and norm.get("filled") == norm.get("amount") else "submitted")

        # persist
        try:
            self.order_store.record_new_order({
                "id": norm["id"],
                "symbol": norm["symbol"],
                "side": norm["side"],
                "amount": norm["amount"],
                "filled": norm["filled"],
                "price": norm["price"],
                "status": status,
                "raw": norm["raw"]
            })
        except Exception as e:
            # ignore persisting errors for now
            logger.debug("Failed to persist order: %s", e)

        return norm


        return {
            "id": norm["id"],
            "status": status,
            "symbol": norm["symbol"],
            "side": norm["side"],
            "amount": norm["amount"],
            "filled": norm["filled"],
            "price": norm["price"],
            "raw": norm["raw"]
        }

def fetch_order(self, order_id: str) -> Optional[Dict[str, Any]]:
        fn = getattr(self.adapter, "fetch_order", None)
        res = None
        if fn:
            try:
                res = fn(order_id)
            except Exception:
                res = None

        if res:
            norm = self._normalize_order_response(res)
            try:
                status = norm["status"] or "submitted"
                self.order_store.update_order_state(order_id, status, filled=norm.get("filled"), price=norm.get("price"), raw=norm.get("raw"))
            except Exception:
                pass
            return norm
        return self.order_store.get_order(order_id)

def fetch_open_orders(self, symbol: Optional[str] = None) -> List[Dict[str, Any]]:
        fn = getattr(self.adapter, "fetch_open_orders", None)
        out = []
        if fn:
            try:
                res_list = fn(symbol) if self._has("fetch_open_orders") else None
                if isinstance(res_list, list):
                    for r in res_list:
                        norm = self._normalize_order_response(r)
                        out.append(norm)
                        try:
                            self.order_store.record_new_order({
                                "id": norm["id"],
                                "symbol": norm["symbol"],
                                "side": norm["side"],
                                "amount": norm["amount"],
                                "filled": norm["filled"],
                                "price": norm["price"],
                                "status": norm["status"] or "submitted",
                                "raw": norm["raw"]
                            })
                        except Exception:
                            pass
                    if out:
                        return out
            except Exception:
                pass

        open_map = self.order_store.list_open_orders()
        return list(open_map.values())

def cancel_order(order_id: str) -> Dict[str, Any]:
    fn = getattr(self.adapter, "cancel_order", None)
    res = None
    if fn:
        safe_call = self._build_safe_call(fn, {"order_id": order_id}, {})
        try:
                res = _retry(safe_call)
        except Exception:
                try:
                    res = fn(order_id)
                except Exception:
                    raise

        norm = self._normalize_order_response(res) if res else {"id": order_id, "status": "cancelled"}
        status = norm.get("status") or "cancelled"
        try:
            self.order_store.update_order_state(order_id, status, filled=norm.get("filled"), price=norm.get("price"), raw=norm.get("raw"))
        except Exception:
            pass
        return norm

    def reconcile_order(self, order_id: str) -> Optional[Dict[str, Any]]:
        fn = getattr(self.adapter, "fetch_order", None)
        if not fn:
            return None
        try:
            res = fn(order_id)
            norm = self._normalize_order_response(res)
            status = norm.get("status") or "submitted"
            self.order_store.update_order_state(order_id, status, filled=norm.get("filled"), price=norm.get("price"), raw=norm.get("raw"))
            return norm
        except Exception:
            return None
