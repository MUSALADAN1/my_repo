# tests/test_services_daemon.py
import time
from backend.services.daemon import ServiceRunner


class DummyOCO:
    def __init__(self):
        self.calls = 0

    def reconcile_orders(self):
        # simulate a quick reconciliation call
        self.calls += 1


class DummyTWAP:
    def __init__(self):
        self.started = False
        self.stopped = False

    def start(self):
        self.started = True

    def stop(self):
        self.stopped = True

    # optional maintenance hook (exercised by runner if present)
    def periodic_maintenance(self):
        # no-op; present to assert runner calls it w/out error
        return True


def test_service_runner_reconciles_and_controls_twap():
    oco = DummyOCO()
    twap = DummyTWAP()
    runner = ServiceRunner(broker=None, oco_manager=oco, twap_executor=twap, reconcile_interval=0.05)

    # start the service loop
    runner.start()
    # let it run a short while so the loop fires multiple times
    time.sleep(0.25)
    runner.stop(timeout=1.0)

    assert oco.calls >= 2, "expected at least two reconcile calls"
    assert twap.started is True
    assert twap.stopped is True
