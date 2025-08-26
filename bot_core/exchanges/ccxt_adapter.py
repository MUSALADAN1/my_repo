# bot_core/exchanges/ccxt_adapter.py
"""CCXT-based adapter implementing the BaseAdapter interface.

- Dry-run by default (config['dry_run']=True).
- If dry_run is False and ccxt is not installed, AdapterError will be raised.
- For live usage, pass config with {'exchange': 'binance', 'apiKey': '...', 'secret': '...', ...}
"""

from typing import Any, Dict, List, Optional, Union
import time

from bot_core.exchanges.base_adapter import BaseAdapter, AdapterError
from bot_core.exchanges.mt5_utils import rates_to_dataframe  # reuse for DF conversion

# Try to import ccxt; allow module to be absent for dry-run/testing environments.
try:
    import ccxt  # type: ignore
except Exception:
    ccxt = None  # type: ignore


class CCXTAdapter(BaseAdapter):
    """Adapter using ccxt.Exchange interfaces."""

    def __init__(self, config: Optional[Dict[str, Any]] = None):
        super().__init__(config=config)
        self.dry_run = bool(self.config.get("dry_run", True))
        self.exchange_name = str(self.config.get("exchange", "binance"))
        self._exchange = None
        self._connected = False

    # ---------------- Connection lifecycle ----------------
    def connect(self) -> None:
        """Initialize ccxt exchange instance (or enable dry-run)."""
        if self.dry_run:
            self._connected = True
            return

        if ccxt is None:
            raise AdapterError("ccxt library not available. Install with `pip install ccxt` for live usage.")

        try:
            ex_cls = getattr(ccxt, self.exchange_name)
        except Exception as exc:
            raise AdapterError(f"Exchange '{self.exchange_name}' not found in ccxt: {exc}")

        # Build credentials dict: allow passing API keys and extra params in config
        creds = {}
        for k in ("apiKey", "secret", "password", "uid"):
            if k in self.config:
                creds[k] = self.config[k]
        # allow any other ccxt params in config['ccxt_params']
        ccxt_params = self.config.get("ccxt_params", {})
        creds.update(ccxt_params)

        try:
            self._exchange = ex_cls(creds)
            # enable rateLimit handling
            if getattr(self._exchange, "rateLimit", None) is not None:
                self._exchange.enableRateLimit = True
            # If exchange has load_markets, call it to validate keys (safe)
            try:
                self._exchange.load_markets()
            except Exception:
                # If keys invalid, some exchanges will still allow public calls; allow that.
                pass
            self._connected = True
        except Exception as exc:
            raise AdapterError(f"Failed to initialize ccxt exchange: {exc}")

    def disconnect(self) -> None:
        """Close/cleanup exchange object."""
        if self.dry_run:
            self._exchange = None
            self._connected = False
            return
        try:
            # ccxt doesn't always have explicit close; try safe methods
            if self._exchange is not None:
                close = getattr(self._exchange, "close", None)
                if callable(close):
                    close()
            self._exchange = None
            self._connected = False
        except Exception as exc:
            raise AdapterError(f"CCXT disconnect failed: {exc}")

    def is_connected(self) -> bool:
        if self.dry_run:
            return self._connected
        return bool(self._exchange is not None)

    # ---------------- Market data ----------------
    def fetch_ticker(self, symbol: str) -> Dict[str, Any]:
        """Return ticker dict {symbol, bid, ask, last, timestamp}."""
        if self.dry_run:
            return {"symbol": symbol, "bid": 0.0, "ask": 0.0, "last": 0.0, "timestamp": int(time.time() * 1000)}
        if ccxt is None or self._exchange is None:
            raise AdapterError("Exchange not initialized or ccxt not installed.")
        try:
            t = self._exchange.fetch_ticker(symbol)
            return {
                "symbol": symbol,
                "bid": float(t.get("bid") or 0.0),
                "ask": float(t.get("ask") or 0.0),
                "last": float(t.get("last") or t.get("close") or 0.0),
                "timestamp": int(t.get("timestamp") or int(time.time() * 1000)),
                "info": t.get("info"),
            }
        except Exception as exc:
            raise AdapterError(f"fetch_ticker failed: {exc}")

    def fetch_ohlcv(
        self, symbol: str, timeframe: str, since: Optional[int] = None, limit: Optional[int] = 1000, as_dataframe: bool = False
    ) -> Union[List[Dict[str, Any]], "pd.DataFrame"]:
        """
        timeframe: ccxt string like '1m','5m','1h','1d'
        since: milliseconds timestamp or None
        """
        if self.dry_run:
            now_ms = int(time.time() * 1000)
            sample = [
                {"timestamp": now_ms - 60000 * 2, "open": 100.0, "high": 101.0, "low": 99.0, "close": 100.5, "volume": 1.0},
                {"timestamp": now_ms - 60000 * 1, "open": 100.5, "high": 101.5, "low": 100.0, "close": 101.0, "volume": 2.0},
                {"timestamp": now_ms, "open": 101.0, "high": 102.0, "low": 100.5, "close": 101.5, "volume": 1.5},
            ]
            return rates_to_dataframe(sample) if as_dataframe else sample

        if ccxt is None or self._exchange is None:
            raise AdapterError("Exchange not initialized or ccxt not installed.")
        try:
            # ccxt.fetch_ohlcv returns list of lists: [timestamp, open, high, low, close, volume]
            ohlcv = self._exchange.fetch_ohlcv(symbol, timeframe=timeframe, since=since, limit=limit)
            candles = []
            for row in ohlcv:
                ts = int(row[0])  # ccxt timestamps are in milliseconds
                o = float(row[1])
                h = float(row[2])
                l = float(row[3])
                c = float(row[4])
                v = float(row[5]) if len(row) > 5 else 0.0
                candles.append({"timestamp": ts, "open": o, "high": h, "low": l, "close": c, "volume": v})
            return rates_to_dataframe(candles) if as_dataframe else candles
        except Exception as exc:
            raise AdapterError(f"fetch_ohlcv failed: {exc}")

    # ---------------- Account / positions ----------------
    def fetch_balance(self) -> Dict[str, Any]:
        if self.dry_run:
            return {"total": {}, "free": {}, "used": {}}
        if ccxt is None or self._exchange is None:
            raise AdapterError("Exchange not initialized or ccxt not installed.")
        try:
            bal = self._exchange.fetch_balance()
            return bal
        except Exception as exc:
            raise AdapterError(f"fetch_balance failed: {exc}")

    def fetch_positions(self) -> List[Dict[str, Any]]:
        # Many ccxt exchanges don't expose positions for spot; for derivatives some do via fetch_positions or fetch_open_positions
        if self.dry_run:
            return []
        if ccxt is None or self._exchange is None:
            raise AdapterError("Exchange not initialized or ccxt not installed.")
        try:
            if hasattr(self._exchange, "fetch_positions"):
                pos = self._exchange.fetch_positions()
                return pos or []
            # fallback: try fetch_open_orders or empty
            return []
        except Exception as exc:
            raise AdapterError(f"fetch_positions failed: {exc}")

    # ---------------- Orders ----------------
    def create_order(self, symbol: str, side: str, type: str, amount: float, price: Optional[float] = None, params: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        params = params or {}
        if self.dry_run:
            return {"id": f"dry-{int(time.time())}", "symbol": symbol, "side": side, "type": type, "amount": amount, "price": price, "status": "open", "info": "dry_run"}
        if ccxt is None or self._exchange is None:
            raise AdapterError("Exchange not initialized or ccxt not installed.")
        try:
            # ccxt create_order signature: (symbol, type, side, amount, price=None, params={})
            order = self._exchange.create_order(symbol, type, side, amount, price, params)
            return order
        except Exception as exc:
            raise AdapterError(f"create_order failed: {exc}")

    def cancel_order(self, order_id: str, symbol: Optional[str] = None) -> Dict[str, Any]:
        if self.dry_run:
            return {"id": order_id, "status": "canceled", "info": "dry_run"}
        if ccxt is None or self._exchange is None:
            raise AdapterError("Exchange not initialized or ccxt not installed.")
        try:
            res = self._exchange.cancel_order(order_id, symbol) if symbol else self._exchange.cancel_order(order_id)
            return res
        except Exception as exc:
            raise AdapterError(f"cancel_order failed: {exc}")

    def fetch_order(self, order_id: str, symbol: Optional[str] = None) -> Dict[str, Any]:
        if self.dry_run:
            return {"id": order_id, "status": "open", "info": "dry_run"}
        if ccxt is None or self._exchange is None:
            raise AdapterError("Exchange not initialized or ccxt not installed.")
        try:
            return self._exchange.fetch_order(order_id, symbol) if symbol else self._exchange.fetch_order(order_id)
        except Exception as exc:
            raise AdapterError(f"fetch_order failed: {exc}")

    def fetch_open_orders(self, symbol: Optional[str] = None) -> List[Dict[str, Any]]:
        if self.dry_run:
            return []
        if ccxt is None or self._exchange is None:
            raise AdapterError("Exchange not initialized or ccxt not installed.")
        try:
            return self._exchange.fetch_open_orders(symbol) if symbol else self._exchange.fetch_open_orders()
        except Exception as exc:
            raise AdapterError(f"fetch_open_orders failed: {exc}")
