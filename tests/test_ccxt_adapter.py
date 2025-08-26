# tests/test_ccxt_adapter.py
import pandas as pd
from bot_core.exchanges.ccxt_adapter import CCXTAdapter

class MockClient:
    def fetch_ticker(self, symbol):
        return {"symbol": symbol, "bid": 1.0, "ask": 2.0, "last": 1.5}

    def fetch_balance(self):
        return {"total": {"USD": 1000}, "free": {}, "used": {}}

    def create_order(self, symbol, order_type, side, amount, price=None, params=None):
        return {"id": "mock-ord-1", "status": "open", "symbol": symbol, "side": side, "amount": amount, "price": price}

    def fetch_ohlcv(self, symbol, timeframe, limit):
        # return a single row: [timestamp (s), open, high, low, close, volume]
        return [[1600000000, 100.0, 105.0, 95.0, 102.0, 10.0]]

def test_ccxt_adapter_with_mock_client():
    client = MockClient()
    cfg = {"client": client}
    a = CCXTAdapter(cfg)
    assert a.connect() is True

    t = a.fetch_ticker("BTC/USDT")
    assert isinstance(t, dict)
    assert t["symbol"] == "BTC/USDT"

    bal = a.fetch_balance()
    assert isinstance(bal, dict)
    assert "total" in bal

    order = a.place_order("BTC/USDT", "buy", 0.01, price=102.0, order_type="limit")
    assert isinstance(order, dict)
    assert "id" in order

    df = a.fetch_ohlcv("BTC/USDT", "1m", limit=1)
    assert isinstance(df, pd.DataFrame)
    assert set(["open","high","low","close","volume"]).issubset(df.columns)
    assert len(df) == 1
