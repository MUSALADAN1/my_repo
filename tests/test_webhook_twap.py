# tests/test_webhook_twap.py
import time
from bot_core.execution.twap_bg import BackgroundTWAPExecutor
from backend.webhook_executor import process_event

class MockBroker:
    def __init__(self):
        self.orders = {}
        self._id = 0
    def place_order(self, symbol, side, amount, price=None, **kwargs):
        self._id += 1
        oid = f"m-{self._id}"
        rec = {"id": oid, "symbol": symbol, "side": side, "amount": amount, "price": price}
        self.orders[oid] = rec
        return rec

def test_process_event_starts_twap_job():
    broker = MockBroker()
    rm = None
    twap_executor = BackgroundTWAPExecutor(broker, default_order_delay=0.0)
    event = {
        "id": "evt-twap-1",
        "twap": {
            "symbol": "BTC/USDT",
            "side": "buy",
            "total_amount": 0.4,
            "slices": 4,
            "duration_seconds": 0.0
        }
    }
    res = process_event(event, broker, rm, twap_executor=twap_executor)
    assert res["status"] == "ok"
    assert res["action"] == "start_twap"
    job_id = res["job_id"]
    # wait for job to finish
    start = time.time()
    while time.time() - start < 2.0:
        st = twap_executor.get_status(job_id)
        if st in ("completed","failed"):
            break
        time.sleep(0.01)
    assert twap_executor.get_status(job_id) == "completed"
    results = twap_executor.get_results(job_id)
    assert results is not None and len(results) == 4
