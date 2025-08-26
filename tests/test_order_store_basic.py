# tests/test_order_store_basic.py
import tempfile
from bot_core.storage.order_store import OrderSQLiteStore

def test_order_store_basic(tmp_path):
    db = str(tmp_path / "orders.sqlite")
    store = OrderSQLiteStore(db)
    order = {
        "id": "ord-1",
        "status": "submitted",
        "symbol": "BTC/USDT",
        "side": "buy",
        "amount": 0.001,
        "price": 100.0,
        "order_type": "limit",
        "strategy": "s1",
    }
    oid = store.persist_order(order)
    assert oid == "ord-1"
    got = store.get_order("ord-1")
    assert got is not None
    assert got["status"] == "submitted"
    assert got["symbol"] == "BTC/USDT"

    # update status
    store.update_order("ord-1", status="filled", price=101.0)
    got = store.get_order("ord-1")
    assert got["status"] == "filled"
    assert float(got["price"]) == 101.0
