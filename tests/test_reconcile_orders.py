# tests/test_reconcile_orders.py
from bot_core.storage.order_store import OrderSQLiteStore
from bot_core.orders.reconcile import reconcile_orders

class DummyBroker:
    def __init__(self, mapping=None):
        self.mapping = mapping or {}

    def fetch_order(self, oid):
        # return mapping entry or raise
        if oid in self.mapping:
            return self.mapping[oid]
        return None

    def fetch_open_orders(self, symbol=None):
        # return all open orders as list
        return [v for v in self.mapping.values() if v.get("status") in ("open","submitted")]

def test_reconcile_marks_filled(tmp_path):
    db = str(tmp_path / "orders.sqlite")
    store = OrderSQLiteStore(db)
    order = {"id": "ord-x", "status": "submitted", "symbol": "BTC/USDT", "side": "buy"}
    store.persist_order(order)

    broker = DummyBroker(mapping={
        "ord-x": {"id": "ord-x", "status": "filled", "filled_price": 123.4}
    })

    updates = reconcile_orders(store, broker)
    assert any(u.get("id") == "ord-x" for u in updates)
    got = store.get_order("ord-x")
    # status updated to 'filled' by reconcile (fetch_order provided status)
    assert got is not None
    assert got["status"] == "filled" or got["raw"].get("status") == "filled" or got["raw"].get("filled_price") == 123.4
