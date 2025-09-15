# backend/exchanges/bybit_adapter.py
from typing import Dict, Any
from .adapter_base import ExchangeAdapter

class BybitAdapter(ExchangeAdapter):
    def connect(self) -> bool:
        client = self.config.get("client")
        if client:
            self.client = client
            self.connected = True
            return True
        self.client = None
        self.connected = True
        return True

    def fetch_ticker(self, symbol: str) -> Dict[str, Any]:
        return {"symbol": symbol, "bid": 0.0, "ask": 0.0, "last": 0.0}

    def fetch_balance(self) -> Dict[str, Any]:
        return {"total": {}, "free": {}, "used": {}}

    def place_order(self, symbol: str, side: str, amount: float, price: float = None, order_type: str = "market") -> Dict[str, Any]:
        return {"id": "bybit-mock-1", "status": "filled", "symbol": symbol}
