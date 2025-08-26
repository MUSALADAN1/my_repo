# tests/test_ccxt_adapter_orders.py
import pytest
from bot_core.exchanges.ccxt_adapter import CCXTAdapter

class FakeClient:
    def __init__(self):
        self.calls = []
    def create_order(self, symbol, otype, side, amount, price=None, params=None):
        self.calls.append(("create_order", symbol, otype, side, amount, price, params))
        return {"id": "ord-123", "status": "open", "symbol": symbol}
    def fetch_order(self, oid, symbol=None):
        self.calls.append(("fetch_order", oid, symbol))
        return {"id": oid, "status": "open", "symbol": symbol}
    def fetch_open_orders(self, symbol=None):
        self.calls.append(("fetch_open_orders", symbol))
        return [{"id": "ord-123", "status": "open", "symbol": symbol}]
    def cancel_order(self, oid, symbol=None):
        self.calls.append(("cancel_order", oid, symbol))
        return {"id": oid, "status": "cancelled"}

def test_ccxt_adapter_orders_flow():
    client = FakeClient()
    adapter = CCXTAdapter({"client": client})
    assert adapter.connect() is True

    # place order -> normalized dict with id
    placed = adapter.place_order("BTC/USDT", "buy", 0.01, price=1000.0, order_type="limit")
    assert isinstance(placed, dict)
    assert placed.get("id") == "ord-123"

    # fetch order
    fetched = adapter.fetch_order("ord-123", "BTC/USDT")
    assert fetched.get("id") == "ord-123"

    # open orders
    open_list = adapter.fetch_open_orders("BTC/USDT")
    assert isinstance(open_list, list) and len(open_list) == 1

    # cancel
    cancelled = adapter.cancel_order("ord-123", "BTC/USDT")
    assert cancelled.get("status") in ("cancelled", "canceled")
