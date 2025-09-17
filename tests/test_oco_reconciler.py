# tests/test_oco_reconciler.py
import time
from bot_core.order_managers.oco import OCOManager
from bot_core.order_managers.reconciler import BackgroundReconciler

class MockBroker:
    def __init__(self):
        self.orders = {}
        self._cancelled = []

    def place_order(self, symbol, side, amount, price=None, order_type="market", **kw):
        oid = f"o-{len(self.orders)+1}"
        self.orders[oid] = {"id": oid, "symbol": symbol, "side": side, "amount": amount, "price": price, "status": "submitted"}
        return {"id": oid, **self.orders[oid]}

    def cancel_order(self, order_id):
        # mark cancelled in dict and record call
        if order_id in self.orders:
            self.orders[order_id]["status"] = "cancelled"
        self._cancelled.append(order_id)
        return True

def test_background_reconciler_cancels_counterpart():
    broker = MockBroker()
    oco = OCOManager(broker)
    # place pair
    placed = oco.place_oco({"symbol":"BTC/USDT","side":"buy","amount":0.1,"price":40000,"order_type":"limit"},
                           {"symbol":"BTC/USDT","side":"sell","amount":0.1,"price":42000,"order_type":"limit"})
    primary_id = placed.get("primary_id")
    secondary_id = placed.get("secondary_id")
    assert primary_id and secondary_id

    # start background reconciler with tiny interval
    r = BackgroundReconciler(oco, interval=0.05)
    r.start()

    # simulate primary filled
    broker.orders[primary_id]["status"] = "filled"

    # wait short time for background to run
    time.sleep(0.2)

    # assert secondary got cancelled
    assert secondary_id in broker._cancelled

    # stop
    r.stop()
