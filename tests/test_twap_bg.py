# tests/test_twap_bg.py
import time
import threading
from bot_core.execution.twap_bg import BackgroundTWAPExecutor


class MockBroker:
    def __init__(self):
        self.orders = {}
        self._counter = 0
        self.lock = threading.Lock()
        # control fail counts per call index
        self.fail_first_n = 0
        self._calls = 0

    def place_order(self, symbol, side, amount, price=None, **kwargs):
        with self.lock:
            self._calls += 1
            if self._calls <= self.fail_first_n:
                raise RuntimeError("temporary broker error")
            self._counter += 1
            oid = f"mord-{self._counter}"
            rec = {"id": oid, "symbol": symbol, "side": side, "amount": amount, "price": price}
            self.orders[oid] = rec
            return rec


def test_background_twap_runs_to_completion():
    broker = MockBroker()
    bg = BackgroundTWAPExecutor(broker, default_order_delay=0.0)
    job_id = bg.start_job("BTC/USDT", "buy", total_amount=1.0, slices=4, duration_seconds=0.0)
    start = time.time()
    while time.time() - start < 2.0:
        status = bg.get_status(job_id)
        if status in ("completed", "failed"):
            break
        time.sleep(0.01)
    assert bg.get_status(job_id) == "completed"
    results = bg.get_results(job_id)
    assert results is not None and len(results) == 4


def test_background_twap_retry_on_transient_failure():
    broker = MockBroker()
    # first call will fail once, then succeed
    broker.fail_first_n = 1
    # set small retry base to keep test fast
    bg = BackgroundTWAPExecutor(broker, default_order_delay=0.0, order_retry_attempts=3, order_retry_base=0.01, order_retry_max=0.02)
    job_id = bg.start_job("BTC/USDT", "buy", total_amount=0.2, slices=2, duration_seconds=0.0)
    start = time.time()
    while time.time() - start < 2.0:
        status = bg.get_status(job_id)
        if status in ("completed", "failed"):
            break
        time.sleep(0.005)
    assert bg.get_status(job_id) == "completed"
    results = bg.get_results(job_id)
    assert results is not None and len(results) == 2


def test_background_twap_can_cancel_midway():
    broker = MockBroker()
    bg = BackgroundTWAPExecutor(broker, default_order_delay=0.05)
    job_id = bg.start_job("ETH/USDT", "sell", total_amount=0.5, slices=10, duration_seconds=0.5)
    time.sleep(0.12)
    ok = bg.cancel_job(job_id)
    assert ok is True
    time.sleep(0.05)
    status = bg.get_status(job_id)
    assert status in ("canceled", "completed", "failed")
    results = bg.get_results(job_id)
    assert results is not None and 0 < len(results) < 10
