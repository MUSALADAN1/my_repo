# test_binance_ccxt_adapter.py
from backend.exchanges import create_adapter

class MockCCXTLikeClient:
    def fetch_ticker(self, symbol):
        return {"symbol": symbol, "bid": 123.45, "ask": 123.55, "last": 123.50}

    def fetch_balance(self):
        return {"total": {"USDT": 1000}, "free": {"USDT": 1000}, "used": {}}

    def create_order(self, symbol, order_type, side, amount, price=None):
        return {"id": "mock-order-123", "status": "ok", "symbol": symbol, "side": side, "amount": amount, "price": price, "type": order_type}

def test_binance_adapter_with_mock_client():
    mock = MockCCXTLikeClient()
    adapter = create_adapter("binance", {"client": mock})
    assert adapter.connect() is True
    t = adapter.fetch_ticker("BTC/USDT")
    assert isinstance(t, dict)
    assert t["symbol"] == "BTC/USDT"
    b = adapter.fetch_balance()
    assert isinstance(b, dict) and "total" in b
    order = adapter.place_order("BTC/USDT", "buy", 0.001)
    assert isinstance(order, dict)
    # since our mock returns an id inside the raw dict we handle, ensure id present in 'raw' or response
    assert "raw" in order or "id" in order
