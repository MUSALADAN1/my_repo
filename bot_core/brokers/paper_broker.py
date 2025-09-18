# bot_core/brokers/paper_broker.py
import threading
import time
import uuid
from typing import Dict, Any, Optional, List

class PaperBroker:
    """
    Very small paper-trading broker used for tests / simulated live mode.

    Features:
    - place_order(symbol, side, amount, price=None, order_type='market', **kwargs)
    - cancel_order(order_id)
    - fetch_open_orders()
    - basic in-memory order store with immediate fills for market orders
    - simple limit order handling: stays open until manually filled or canceled
    """
    def __init__(self, starting_prices: Optional[Dict[str, float]] = None):
        self._lock = threading.Lock()
        self.orders: Dict[str, Dict[str, Any]] = {}
        self.starting_prices = starting_prices or {}
        # mapping symbol -> last_price
        self.last_price = dict(self.starting_prices)

    def _new_id(self) -> str:
        return "o-" + uuid.uuid4().hex[:8]

    def place_order(self, symbol: str, side: str, amount: float,
                    price: Optional[float] = None, order_type: str = "market", **kwargs) -> Dict[str, Any]:
        with self._lock:
            oid = self._new_id()
            now = time.time()
            order = {
                "id": oid,
                "symbol": symbol,
                "side": side,
                "amount": float(amount),
                "price": price,
                "order_type": order_type,
                "status": "submitted",
                "created_ts": now,
                "updated_ts": now,
                "meta": dict(kwargs),
            }
            # immediate fill for market orders (use last_price if available)
            if order_type.lower() == "market":
                fill_price = None
                if price is not None:
                    try:
                        fill_price = float(price)
                    except Exception:
                        fill_price = None
                if fill_price is None:
                    fill_price = float(self.last_price.get(symbol, 0.0))
                order.update({"status": "filled", "filled_price": fill_price, "filled_ts": now})
            else:
                # limit/other: keep open
                order["status"] = "open"
            self.orders[oid] = order
            return order

    def cancel_order(self, order_id: str) -> Dict[str, Any]:
        with self._lock:
            o = self.orders.get(order_id)
            if o is None:
                raise KeyError(f"order not found: {order_id}")
            if o.get("status") in ("filled", "canceled"):
                return o
            o["status"] = "canceled"
            o["updated_ts"] = time.time()
            return o

    def fetch_open_orders(self, symbol: Optional[str] = None) -> List[Dict[str, Any]]:
        with self._lock:
            res = []
            for o in list(self.orders.values()):
                if o.get("status") == "open":
                    if symbol is None or o.get("symbol") == symbol:
                        res.append(o.copy())
            return res

    def fetch_order(self, order_id: str) -> Optional[Dict[str, Any]]:
        with self._lock:
            o = self.orders.get(order_id)
            return None if o is None else o.copy()

    # helper for tests / sim: set last price for symbol
    def set_last_price(self, symbol: str, price: float) -> None:
        with self._lock:
            self.last_price[symbol] = float(price)

    # helper to simulate a fill of a limit order (used by tests)
    def simulate_fill(self, order_id: str, price: Optional[float] = None) -> Dict[str, Any]:
        with self._lock:
            o = self.orders.get(order_id)
            if o is None:
                raise KeyError(order_id)
            if o.get("status") == "filled":
                return o
            now = time.time()
            fill_price = price if price is not None else o.get("price") or self.last_price.get(o["symbol"], 0.0)
            o.update({"status": "filled", "filled_price": fill_price, "filled_ts": now, "updated_ts": now})
            return o
