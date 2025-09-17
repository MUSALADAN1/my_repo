# tests/test_webhook_oco.py
import json
from bot_core.order_managers.oco import OCOManager
from backend.webhook_executor import process_event

class MockBroker:
    def __init__(self):
        self.orders = {}
    def place_order(self, symbol, side, amount, price=None, order_type="market", **kw):
        oid = f"o-{len(self.orders)+1}"
        self.orders[oid] = {"id": oid, "symbol": symbol, "side": side, "amount": amount, "price": price, "status": "submitted"}
        return self.orders[oid]
    def fetch_order(self, order_id):
        return self.orders.get(order_id)
    def cancel_order(self, order_id):
        o = self.orders.get(order_id)
        if o:
            o["status"] = "cancelled"
        return {"id": order_id, "status": "cancelled"}

def test_process_event_place_oco_and_reconcile():
    broker = MockBroker()
    rm = None
    oco_mgr = OCOManager(broker)

    event = {
        "id": "evt-1",
        "oco": {
            "primary": {"symbol": "BTC/USDT", "side": "buy", "amount": 0.1, "price": 40000.0, "order_type": "limit"},
            "secondary": {"symbol": "BTC/USDT", "side": "sell", "amount": 0.1, "price": 42000.0, "order_type": "limit"}
        }
    }

    res = process_event(event, broker, rm, oco_manager=oco_mgr)
    assert res["status"] == "ok"
    assert res["action"] == "place_oco"
    oco_info = res["oco"]
    assert "primary_id" in oco_info and "secondary_id" in oco_info

    # simulate primary filled, reconcile, expect secondary cancelled
    broker.orders[oco_info["primary_id"]]["status"] = "filled"
    oco_mgr.reconcile_orders()

    sec = broker.fetch_order(oco_info["secondary_id"])
    assert sec["status"] == "cancelled"
