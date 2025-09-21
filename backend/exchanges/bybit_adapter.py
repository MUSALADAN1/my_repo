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
    # --- compatibility wrappers added automatically to satisfy tests / upstream clients ---
    def cancel_order(self, *args, **kwargs):
        """Cancel an order. Delegates to underlying client if available."""
        client = getattr(self, "client", None)
        if client is None:
            raise NotImplementedError("cancel_order not implemented and no client available")
        fn = getattr(client, "cancel_order", None) or getattr(client, "cancelOrder", None)
        if fn is None:
            raise NotImplementedError("underlying client has no cancel_order method")
        return fn(*args, **kwargs)

    def fetch_open_orders(self, *args, **kwargs):
        """Return open orders. Delegates to underlying client if available."""
        client = getattr(self, "client", None)
        if client is None:
            raise NotImplementedError("fetch_open_orders not implemented and no client available")
        fn = getattr(client, "fetch_open_orders", None) or getattr(client, "fetchOpenOrders", None)
        if fn is None:
            # fallback tries
            fn = getattr(client, "fetch_orders", None) or getattr(client, "fetchOrders", None)
            if fn is None:
                raise NotImplementedError("underlying client has no fetch_open_orders/fetch_orders method")
        return fn(*args, **kwargs)

    def fetch_order(self, *args, **kwargs):
        """Return a single order. Delegates to underlying client if available."""
        client = getattr(self, "client", None)
        if client is None:
            raise NotImplementedError("fetch_order not implemented and no client available")
        fn = getattr(client, "fetch_order", None) or getattr(client, "fetchOrder", None) or getattr(client, "fetch_order_info", None)
        if fn is None:
            raise NotImplementedError("underlying client has no fetch_order method")
        return fn(*args, **kwargs)
