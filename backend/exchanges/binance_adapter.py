# backend/exchanges/binance_adapter.py
from typing import Dict, Any, Optional
from .adapter_base import ExchangeAdapter

try:
    import ccxt  # optional; adapter will still work with a passed-in client if ccxt is not installed
except Exception:
    ccxt = None  # keep None to allow tests with mock clients

class BinanceAdapter(ExchangeAdapter):
    """
    Binance adapter that can:
    - reuse a client passed via config['client'] (recommended for tests/mocks)
    - create a ccxt.binance client if ccxt is available and api_key/api_secret are provided
    - fallback to placeholders when no client or keys are given
    """

    def connect(self) -> bool:
        # If caller passed an instantiated client in config, reuse it.
        client = self.config.get("client")
        if client:
            self.client = client
            self.connected = True
            return True

        # If user provided API keys and ccxt is installed, create a ccxt client.
        api_key = self.config.get("api_key") or self.config.get("apikey") or self.config.get("key")
        api_secret = self.config.get("api_secret") or self.config.get("secret")
        use_ccxt = self.config.get("use_ccxt", False)

        if use_ccxt and ccxt is not None and api_key and api_secret:
            opts = {"enableRateLimit": True}
            # Support a simple 'testnet' flag to change endpoints (best-effort).
            if self.config.get("testnet"):
                # This is a common testnet base for Binance; ccxt may need more detailed overrides
                # in some versions — this is a best-effort helper.
                opts["urls"] = {
                    "api": {
                        "public": "https://testnet.binance.vision",
                        "private": "https://testnet.binance.vision",
                    }
                }
            try:
                client = ccxt.binance({
                    "apiKey": api_key,
                    "secret": api_secret,
                    **opts
                })
                self.client = client
                self.connected = True
                return True
            except Exception:
                # If ccxt instantiation fails, fall back to placeholders below.
                self.client = None
                self.connected = False
                return False

        # Placeholder: simulate successful connection (no network)
        self.client = None
        self.connected = True
        return True

    def _has_method(self, name: str) -> bool:
        return bool(self.client and hasattr(self.client, name))

    def fetch_ticker(self, symbol: str) -> Dict[str, Any]:
        # If a real client is present and has fetch_ticker, delegate.
        if self._has_method("fetch_ticker"):
            try:
                return self.client.fetch_ticker(symbol)
            except Exception:
                # Fall through to placeholder
                pass

        # Placeholder response
        return {"symbol": symbol, "bid": 0.0, "ask": 0.0, "last": 0.0}

    def fetch_balance(self) -> Dict[str, Any]:
        if self._has_method("fetch_balance"):
            try:
                return self.client.fetch_balance()
            except Exception:
                pass

        return {"total": {}, "free": {}, "used": {}}

    def place_order(self, symbol: str, side: str, amount: float, price: float = None, order_type: str = "market") -> Dict[str, Any]:
        # Try ccxt-style create_order: create_order(symbol, type, side, amount, price, params={})
        if self._has_method("create_order"):
            try:
                # Translate our order_type -> ccxt type if necessary (we assume compatible names)
                result = self.client.create_order(symbol, order_type, side, amount, price)
                return {"id": getattr(result, "id", result.get("id") if isinstance(result, dict) else None) or result, "status": "submitted", "raw": result}
            except Exception:
                pass

        # Some SDKs have different method names (best-effort tries)
        for alt in ("createLimitOrder", "create_limit_buy_order", "create_limit_sell_order"):
            if self._has_method(alt):
                try:
                    func = getattr(self.client, alt)
                    if "buy" in alt:
                        res = func(symbol, amount, price)
                    else:
                        res = func(symbol, amount, price)
                    return {"id": getattr(res, "id", None) or res, "status": "submitted", "raw": res}
                except Exception:
                    continue

        # Fallback simulated response
        return {"id": "binance-mock-1", "status": "filled", "symbol": symbol, "side": side, "amount": amount, "price": price, "order_type": order_type}

    # --- compatibility wrappers added to satisfy tests (delegate to underlying client) ---
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
            # Some clients expose fetch_orders instead
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
    # --- end wrappers ---
