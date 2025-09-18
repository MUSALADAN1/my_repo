# tests/test_twap.py
import time
from bot_core.execution.twap import TWAPExecutor


class MockBroker:
    def __init__(self):
        # dict of order id -> order record
        self.orders = {}
        self._counter = 0

    def place_order(self, symbol, side, amount, price=None, **kwargs):
        self._counter += 1
        oid = f"mord-{self._counter}"
        rec = {"id": oid, "symbol": symbol, "side": side, "amount": amount, "price": price}
        # keep a simple mapping
        self.orders[oid] = rec
        return rec

    def fetch_open_orders(self, symbol=None):
        # for this mock every order is considered open (simple)
        return list(self.orders.values())


def approx_equal(a, b, tol=1e-9):
    return abs(a - b) <= tol


def test_twap_slices_calls_broker_correctly():
    broker = MockBroker()
    twap = TWAPExecutor(broker, order_delay_seconds=0.0)  # avoid sleeps in tests

    results = twap.execute("BTC/USDT", "buy", total_amount=1.0, duration_seconds=0.0, slices=4, price=None)
    assert len(results) == 4
    assert all(approx_equal(r["amount"], 0.25) for r in results)
    assert len(broker.orders) == 4


def test_twap_with_price_and_duration_respects_total_amount():
    broker = MockBroker()
    twap = TWAPExecutor(broker, order_delay_seconds=0.0)

    results = twap.execute("ETH/USDT", "sell", total_amount=0.3, duration_seconds=0.1, slices=3, price=100.0)
    assert len(results) == 3
    total = sum(r["amount"] for r in results)
    assert approx_equal(total, 0.3)
    assert all(r["price"] == 100.0 for r in results)
