# tests/test_broker_order_delegation.py
from bot_core.exchanges.broker import Broker
# tests/test_broker_order_delegation.py (snippet)

from bot_core.exchanges.adapter_base import ExchangeAdapter

class DummyAdapter(ExchangeAdapter):
    def __init__(self, config: dict = None):
        # forward config like a real adapter would
        super().__init__(config or {})
    def connect(self):
        self.connected = True
        return True
    def fetch_ticker(self, s): return {}
    def fetch_balance(self): return {}
    def place_order(self, symbol, side, amount, price=None, order_type="market"): return {"id":"o1"}
    def fetch_order(self, oid, symbol=None): return {"id":oid}
    def fetch_open_orders(self, symbol=None): return [{"id":"o1"}]
    def cancel_order(self, oid, symbol=None): return {"id":oid,"status":"cancelled"}


def test_broker_delegates_orders():
    ad = DummyAdapter({})
    br = Broker(adapter_instance=ad)
    br.connect()
    p = br.place_order("X", "buy", 1.0)
    assert p.get("id") == "o1"

    f = br.fetch_order("o1")
    assert f.get("id") == "o1"

    opens = br.fetch_open_orders("X")
    assert isinstance(opens, list) and opens[0]["id"] == "o1"

    c = br.cancel_order("o1")
    assert c.get("status") == "cancelled"
