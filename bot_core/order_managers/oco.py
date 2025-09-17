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