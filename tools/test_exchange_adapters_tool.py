# test_exchange_adapters.py
from backend.exchanges import create_adapter

def test_create_and_basic_calls():
    for name in ["binance", "bybit", "kucoin", "mt5"]:
        adapter = create_adapter(name, {"api_key": "x", "api_secret": "y"})
        assert adapter is not None
        # connect should be a non-network placeholder that returns True
        assert adapter.connect() is True
        ticker = adapter.fetch_ticker("BTC/USDT")
        assert isinstance(ticker, dict)
        balance = adapter.fetch_balance()
        assert isinstance(balance, dict)
        ordr = adapter.place_order("BTC/USDT", "buy", 0.001)
        assert isinstance(ordr, dict)
        # basic contract: order dict should contain id or status
        assert "status" in ordr or "id" in ordr
