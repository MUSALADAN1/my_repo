# tests/test_oco_manager.py
import time
from bot_core.order_managers.oco import OCOManager

class MockBroker:
    def __init__(self):
        self.orders = {}
    def place_order(self, symbol, side, amount, price=None, order_type="market"):
        oid = f"o-{len(self.orders)+1}"
        self.orders[oid] = {"id": oid, "symbol": symbol, "side": side, "amount": amount, "price": price, "status": "submitted"}
        return self.orders[oid]
    def cancel_order(self, order_id):
        o = self.orders.get(order_id)
        if o:
            o["status"] = "cancelled"
        return {"id": order_id, "status": "cancelled"}
    def fetch_order(self, order_id):
        return self.orders.get(order_id)

def test_oco_manager_primary_fills_first():
    broker = MockBroker()
    oco = OCOManager(broker)

    primary = {"symbol": "BTC/USDT", "side": "buy", "amount": 0.1, "price": 50000.0}
    secondary = {"symbol": "BTC/USDT", "side": "sell", "amount": 0.1, "price": 52000.0}

    # place OCO
    res = oco.place_oco(primary, secondary)
    assert "primary_id" in res and "secondary_id" in res

    # simulate primary filled
    broker.orders[res["primary_id"]]["status"] = "filled"

    # run reconciliation
    oco.reconcile_orders()

    # secondary should be cancelled
    sec = broker.fetch_order(res["secondary_id"])
    assert sec["status"] == "cancelled"

def test_oco_manager_secondary_fills_first():
    broker = MockBroker()
    oco = OCOManager(broker)

    primary = {"symbol": "BTC/USDT", "side": "buy", "amount": 0.1, "price": 50000.0}
    secondary = {"symbol": "BTC/USDT", "side": "sell", "amount": 0.1, "price": 52000.0}

    res = oco.place_oco(primary, secondary)
    # simulate secondary filled first
    broker.orders[res["secondary_id"]]["status"] = "filled"
    oco.reconcile_orders()
    prim = broker.fetch_order(res["primary_id"])
    assert prim["status"] == "cancelled"
