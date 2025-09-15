# test_mt5_adapter_fetch_ohlcv_mock.py
import pandas as pd
from backend.exchanges import create_adapter

class MockOHLCVClient:
    # ccxt-like: returns [ timestamp_ms, open, high, low, close, volume ] rows
    def fetch_ohlcv(self, symbol, timeframe, limit):
        now = 1690000000000
        rows = []
        for i in range(10):
            rows.append([now + i*3600*1000, 1.0+i, 1.1+i, 0.9+i, 1.05+i, 100 + i])
        return rows

def test_mt5_adapter_fetch_ohlcv_with_mock():
    mock = MockOHLCVClient()
    adapter = create_adapter("mt5", {"client": mock})
    assert adapter.connect() is True
    df = adapter.fetch_ohlcv("EURUSD", "1h", limit=10)
    assert isinstance(df, pd.DataFrame)
    assert "open" in df.columns and "close" in df.columns
    assert len(df) == 10
