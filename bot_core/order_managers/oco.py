"""
Simple OCOManager used by tests and webhook executor.
This is intentionally small / synchronous — production systems should add
persistence, cancellation hooks, eventing, and safety checks.
"""

from typing import Any, Dict, Optional

class OCOManager:
    """
    Manage placing an OCO pair (primary + secondary). The manager will
    attempt to place the 'primary' order first, then place the 'secondary'
    order which is typically the stop/limit opposite leg.
    Both primary and secondary can be either dicts with keys that the broker.place_order
    expects (symbol, side, amount, price, order_type) or (symbol, side, amount, price).
    """

    def __init__(self, broker: Any):
        self.broker = broker

    def _normalize(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        # keep minimal normalization so we pass tests and most mock brokers
        out = {}
        out['symbol'] = payload.get('symbol') or payload.get('symbol_id') or payload.get('instrument')
        out['side'] = payload.get('side') or payload.get('direction')
        # amount may be under different keys
        out['amount'] = payload.get('amount') or payload.get('size') or payload.get('qty') or payload.get('quantity')
        out['price'] = payload.get('price') if 'price' in payload else payload.get('limit_price')
        out['order_type'] = payload.get('order_type') or payload.get('type') or payload.get('ord_type') or 'limit'
        # remove Nones
        return {k: v for k, v in out.items() if v is not None}

    def place_oco(self, primary: Dict[str, Any], secondary: Dict[str, Any]) -> Dict[str, Any]:
        """
        Place the primary and secondary orders and return a dict with both results.
        Primary is placed first. If primary placement fails, raises the exception.
        If secondary fails, we return primary result but raise a warning in the returned dict.
        """
        p = self._normalize(primary or {})
        s = self._normalize(secondary or {})

        if not p.get('symbol') or not p.get('side'):
            raise ValueError("primary must include symbol and side")
        if not s.get('symbol') or not s.get('side'):
            raise ValueError("secondary must include symbol and side")

        # Place primary
        primary_res = None
        secondary_res = None
        try:
            primary_res = self.broker.place_order(
                symbol=p['symbol'],
                side=p['side'],
                amount=float(p.get('amount', 0)),
                price=p.get('price'),
                order_type=p.get('order_type', 'limit')
            )
        except Exception as e:
            # bubble up: tests expect a failure to raise so caller can detect
            raise

        # Place secondary (best-effort; if it fails, return info but do not delete primary)
        try:
            secondary_res = self.broker.place_order(
                symbol=s['symbol'],
                side=s['side'],
                amount=float(s.get('amount', 0)),
                price=s.get('price'),
                order_type=s.get('order_type', 'limit')
            )
        except Exception as e:
            # report that secondary failed
            return {
                "primary": primary_res,
                "secondary": None,
                "secondary_error": str(e)
            }

        return {"primary": primary_res, "secondary": secondary_res}
    # bot_core/order_managers/oco.py

def _extract_order_id(order: Any) -> Optional[str]:
    """Best-effort extract id from broker returned order."""
    if order is None:
        return None
    if isinstance(order, dict):
        for k in ("id", "order_id", "orderId"):
            if k in order and order[k]:
                return str(order[k])
    try:
        for attr in ("id", "order_id", "orderId"):
            v = getattr(order, attr, None)
            if v:
                return str(v)
    except Exception:
        pass
    return None

class OCOManager:
    """
    Minimal OCO manager for tests:
      - place_oco(primary, secondary) -> places two orders via broker.place_order and records mapping
      - reconcile_orders() -> checks stored pairs, if one side filled, cancel the other
    This implementation is intentionally small and defensive to work with the test mocks.
    """
    def __init__(self, broker):
        self.broker = broker
        # map primary_id -> pair dict {'primary': ..., 'secondary': ..., 'primary_id': ..., 'secondary_id': ...}
        self._pairs: Dict[str, Dict[str, Any]] = {}

    def place_oco(self, primary: Dict[str, Any], secondary: Dict[str, Any]) -> Dict[str, Any]:
        """
        Place two orders via broker and remember the pair keyed by primary_id.
        Expects `primary` and `secondary` to contain keys like symbol, side, amount, price, order_type.
        Returns a dict containing nested 'primary' and 'secondary' plus top-level ids.
        """
        # convert input shapes to broker.place_order args (best-effort)
        def _place(o):
            symbol = o.get("symbol")
            side = o.get("side")
            amount = float(o.get("amount")) if o.get("amount") is not None else None
            price = o.get("price", None)
            otype = o.get("order_type", o.get("orderType", "market"))
            # Some brokers expect order_type as 'type' or 'order_type'. We'll stick with place_order signature:
            # broker.place_order(symbol, side, amount, price=None, order_type="market")
            try:
                return self.broker.place_order(symbol=symbol, side=side, amount=amount, price=price, order_type=otype)
            except TypeError:
                # try positional fallback
                return self.broker.place_order(symbol, side, amount, price)
            except Exception:
                # last resort, try fewer args
                try:
                    return self.broker.place_order(symbol=symbol, side=side, amount=amount)
                except Exception as e:
                    raise

        primary_resp = _place(primary)
        secondary_resp = _place(secondary)

        pid = _extract_order_id(primary_resp)
        sid = _extract_order_id(secondary_resp)

        result = {
            "primary": primary_resp if isinstance(primary_resp, dict) else {"id": pid, "raw": primary_resp},
            "secondary": secondary_resp if isinstance(secondary_resp, dict) else {"id": sid, "raw": secondary_resp},
        }
        if pid:
            result["primary_id"] = pid
        if sid:
            result["secondary_id"] = sid

        # remember the pair keyed by primary id (only if we have a primary id)
        if pid:
            self._pairs[pid] = {
                "primary_id": pid,
                "secondary_id": sid,
                "primary": result["primary"],
                "secondary": result["secondary"],
            }

        return result

    def _get_order_status(self, oid: str) -> Optional[str]:
        """Best-effort get status for order id from broker (fetch_order / get_order / direct dict)."""
        if oid is None:
            return None
        # try common method names
        for fn in ("fetch_order", "fetchOrder", "get_order", "getOrder", "fetch_order_info"):
            f = getattr(self.broker, fn, None)
            if callable(f):
                try:
                    o = f(oid)
                    if isinstance(o, dict):
                        return o.get("status")
                    # try attributes
                    s = getattr(o, "status", None) or getattr(o, "state", None)
                    if s:
                        return s
                except Exception:
                    continue
        # try direct lookup (used by some tests / mocks)
        try:
            orders = getattr(self.broker, "orders", None)
            if isinstance(orders, dict) and oid in orders:
                return orders[oid].get("status")
        except Exception:
            pass
        return None

    def reconcile_orders(self) -> Dict[str, Any]:
        """
        Iterate known pairs and if one side is filled, cancel the other.
        Returns a summary dict of actions taken.
        """
        summary = {"checked": 0, "cancelled": [], "errors": []}
        # iterate copy because we may modify _pairs while looping
        for pid, pair in list(self._pairs.items()):
            summary["checked"] += 1
            sid = pair.get("secondary_id")
            try:
                p_status = self._get_order_status(pid)
                s_status = self._get_order_status(sid) if sid else None

                # If primary filled -> cancel secondary (unless already filled/cancelled)
                if p_status and str(p_status).lower() in ("filled", "closed", "done"):
                    if sid and (not s_status or str(s_status).lower() not in ("filled", "closed", "done", "canceled", "cancelled")):
                        try:
                            # cancel secondary via broker
                            cancel_fn = getattr(self.broker, "cancel_order", None) or getattr(self.broker, "cancelOrder", None)
                            if cancel_fn is None:
                                raise RuntimeError("broker has no cancel_order")
                            cancel_fn(sid)
                            summary["cancelled"].append({"pair_primary": pid, "cancelled": sid})
                        except Exception as e:
                            summary["errors"].append({"pair_primary": pid, "secondary": sid, "error": str(e)})
                    # remove the pair after reconciliation
                    self._pairs.pop(pid, None)
                    continue

                # If secondary filled -> cancel primary
                if s_status and str(s_status).lower() in ("filled", "closed", "done"):
                    if pid and (not p_status or str(p_status).lower() not in ("filled", "closed", "done", "canceled", "cancelled")):
                        try:
                            cancel_fn = getattr(self.broker, "cancel_order", None) or getattr(self.broker, "cancelOrder", None)
                            if cancel_fn is None:
                                raise RuntimeError("broker has no cancel_order")
                            cancel_fn(pid)
                            summary["cancelled"].append({"pair_primary": pid, "cancelled": pid})
                        except Exception as e:
                            summary["errors"].append({"pair_primary": pid, "primary": pid, "error": str(e)})
                    self._pairs.pop(pid, None)
                    continue

                # otherwise leave pair in place
            except Exception as e:
                summary["errors"].append({"pair_primary": pid, "error": str(e)})
        return summary
