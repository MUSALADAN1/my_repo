# tests/test_twap_bg.py
import time
import threading
from bot_core.execution.twap_bg import BackgroundTWAPExecutor


class MockBroker:
    def __init__(self):
        self.orders = {}
        self._counter = 0
        self.lock = threading.Lock()

    def place_order(self, symbol, side, amount, price=None, **kwargs):
        with self.lock:
            self._counter += 1
            oid = f"mord-{self._counter}"
            rec = {"id": oid, "symbol": symbol, "side": side, "amount": amount, "price": price}
            self.orders[oid] = rec
            return rec


def test_background_twap_runs_to_completion():
    broker = MockBroker()
    # no sleep between slices (fast)
    bg = BackgroundTWAPExecutor(broker, default_order_delay=0.0)
    job_id = bg.start_job("BTC/USDT", "buy", total_amount=1.0, slices=4, duration_seconds=0.0)
    # wait for thread to complete (busy wait with timeout)
    start = time.time()
    while time.time() - start < 2.0:
        status = bg.get_status(job_id)
        if status in ("completed", "failed"):
            break
        time.sleep(0.01)
    assert bg.get_status(job_id) == "completed"
    results = bg.get_results(job_id)
    assert results is not None and len(results) == 4


def test_background_twap_can_cancel_midway():
    broker = MockBroker()
    # small delay so we can cancel while running
    bg = BackgroundTWAPExecutor(broker, default_order_delay=0.05)
    job_id = bg.start_job("ETH/USDT", "sell", total_amount=0.5, slices=10, duration_seconds=0.5)
    # allow some slices to be placed
    time.sleep(0.12)
    # cancel
    ok = bg.cancel_job(job_id)
    assert ok is True
    # wait a short moment for worker to acknowledge cancel
    time.sleep(0.05)
    status = bg.get_status(job_id)
    assert status in ("canceled", "completed", "failed")
    results = bg.get_results(job_id)
    # after cancel we must have placed at least 1 slice and fewer than total
    assert results is not None and 0 < len(results) < 10
