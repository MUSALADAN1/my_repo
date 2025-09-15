# test_broker_interface.py
import pandas as pd
from backend.exchanges.broker import Broker

class MockClient:
    def fetch_ticker(self, symbol):
        return {"symbol": symbol, "bid": 1.0, "ask": 2.0, "last": 1.5}

    def fetch_balance(self):
        return {"total": {"USDT": 1000}, "free": {"USDT": 900}, "used": {}}

    def create_order(self, symbol, order_type, side, amount, price=None):
        return {"id": "order-1", "status": "ok"}

    def fetch_ohlcv(self, symbol, timeframe, limit):
        base = 1690000000000
        rows = []
        for i in range(limit):
            rows.append([base + i * 3600 * 1000, 1.0 + i, 1.1 + i, 0.9 + i, 1.05 + i, 100 + i])
        return rows

def test_broker_with_mock_client():
    mock = MockClient()
    broker = Broker(adapter_name='binance', config={'client': mock})
    assert broker.connect() is True

    t = broker.fetch_ticker("BTC/USDT")
    assert isinstance(t, dict) and t["symbol"] == "BTC/USDT"

    b = broker.fetch_balance()
    assert isinstance(b, dict) and "total" in b

    o = broker.place_order("BTC/USDT", "buy", 0.01)
    assert isinstance(o, dict)

    df = broker.fetch_ohlcv("BTC/USDT", "1h", limit=5)
    assert isinstance(df, pd.DataFrame)
    assert len(df) == 5
