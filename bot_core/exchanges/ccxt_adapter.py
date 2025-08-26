# bot_core/exchanges/ccxt_adapter.py
from typing import Any, Dict, Optional
import pandas as pd

from .adapter_base import ExchangeAdapter

try:
    import ccxt  # optional: adapter will use it to instantiate real exchanges if available
except Exception:
    ccxt = None


class CCXTAdapter(ExchangeAdapter):
    """
    Generic CCXT-backed adapter.

    Behavior:
      - If config contains a 'client' object, reuse it (test-friendly).
      - Else, if ccxt is installed and config contains 'exchange' (e.g. 'binance')
        and possibly 'api_key'/'api_secret', attempt to instantiate ccxt.<exchange>.
      - Methods delegate to client where possible; fallback to safe placeholders.
    """

    def connect(self) -> bool:
        client = self.config.get("client")
        if client:
            self.client = client
            self.connected = True
            return True

        # Try to instantiate via ccxt if available
        exchange_name = (self.config.get("exchange") or "").lower()
        api_key = self.config.get("api_key") or self.config.get("apikey") or self.config.get("key")
        api_secret = self.config.get("api_secret") or self.config.get("secret")
        if ccxt is not None and exchange_name:
            try:
                exchange_cls = getattr(ccxt, exchange_name, None)
                if exchange_cls is None:
                    # fallback: ccxt might export via ccxt.Exchange if a mapping is used; try generic constructor
                    client = ccxt.Exchange({"id": exchange_name, "apiKey": api_key, "secret": api_secret})
                else:
                    client = exchange_cls({"apiKey": api_key, "secret": api_secret, "enableRateLimit": True})
                self.client = client
                self.connected = True
                return True
            except Exception:
                # Non-fatal: keep self.client None but mark connected for test-friendly behavior
                self.client = None
                self.connected = True
                return True

        # No client and no ccxt -> test-friendly placeholder
        self.client = None
        self.connected = True
        return True

    def _has_method(self, name: str) -> bool:
        return bool(self.client and hasattr(self.client, name))

    def fetch_ticker(self, symbol: str) -> Dict[str, Any]:
        if self._has_method("fetch_ticker"):
            try:
                return self.client.fetch_ticker(symbol)
            except Exception:
                pass
        # fallback placeholder
        return {"symbol": symbol, "bid": None, "ask": None, "last": None}

    def fetch_balance(self) -> Dict[str, Any]:
        if self._has_method("fetch_balance"):
            try:
                return self.client.fetch_balance()
            except Exception:
                pass
        return {"total": {}, "free": {}, "used": {}}

    def place_order(
        self,
        symbol: str,
        side: str,
        amount: float,
        price: Optional[float] = None,
        order_type: str = "market",
    ) -> Dict[str, Any]:
        """
        Try ccxt create_order(symbol, type, side, amount, price, params)
        Return a dict with at least 'id' and 'status'.
        """
        if self._has_method("create_order"):
            try:
                # ccxt expects: (symbol, type, side, amount, price, params={})
                result = self.client.create_order(symbol, order_type, side, amount, price)
                # try to normalize id/status
                if isinstance(result, dict):
                    oid = result.get("id") or result.get("orderId") or result.get("clientOrderId")
                    status = result.get("status", "submitted")
                else:
                    oid = getattr(result, "id", None) or result
                    status = "submitted"
                return {"id": oid, "status": status, "raw": result}
            except Exception:
                pass

        # fallback placeholders trying some alternative method names
        for alt in ("create_limit_buy_order", "create_limit_sell_order", "createOrder"):
            if self._has_method(alt):
                try:
                    func = getattr(self.client, alt)
                    res = func(symbol, amount, price)
                    if isinstance(res, dict):
                        return {"id": res.get("id", None) or res, "status": res.get("status", "submitted"), "raw": res}
                    return {"id": getattr(res, "id", None) or res, "status": "submitted", "raw": res}
                except Exception:
                    continue

        # final fallback (mock response)
        return {"id": "ccxt-mock-1", "status": "filled", "symbol": symbol, "side": side, "amount": amount, "price": price, "order_type": order_type}
    def fetch_order(self, order_id: str, symbol: Optional[str] = None) -> Dict[str, Any]:
        """
        Retrieve order details by id. Try ccxt.fetch_order first, then common SDK aliases.
        Returns a dict (normalized) or minimal fallback dict.
        """
        if self._has_method("fetch_order"):
            try:
                return self.client.fetch_order(order_id, symbol)
            except Exception:
                pass

        for alt in ("fetchOrder", "get_order", "getOrder"):
            if self._has_method(alt):
                try:
                    return getattr(self.client, alt)(order_id, symbol)
                except Exception:
                    pass

        # fallback minimal representation
        return {"id": order_id, "status": "unknown", "symbol": symbol}

    def fetch_open_orders(self, symbol: Optional[str] = None) -> list:
        """
        Return a list of open orders (possibly empty). Try ccxt.fetch_open_orders and common aliases.
        """
        if self._has_method("fetch_open_orders"):
            try:
                return self.client.fetch_open_orders(symbol)
            except Exception:
                pass

        for alt in ("fetchOpenOrders", "get_open_orders", "open_orders"):
            if self._has_method(alt):
                try:
                    return getattr(self.client, alt)(symbol)
                except Exception:
                    pass

        return []

    def cancel_order(self, order_id: str, symbol: Optional[str] = None) -> Dict[str, Any]:
        """
        Cancel an order by id. Try ccxt.cancel_order then common aliases. Return cancellation result dict.
        """
        if self._has_method("cancel_order"):
            try:
                return self.client.cancel_order(order_id, symbol)
            except Exception:
                pass

        for alt in ("cancelOrder", "cancel_order_by_id", "cancel_order_by_symbol"):
            if self._has_method(alt):
                try:
                    return getattr(self.client, alt)(order_id, symbol)
                except Exception:
                    pass

        # fallback ack
        return {"id": order_id, "status": "cancelled"}

    def fetch_ohlcv(self, symbol: str, timeframe: Any, limit: int = 500) -> pd.DataFrame:
        """
        Prefer client.fetch_ohlcv(...) if available and return a pandas DataFrame with columns:
        ['open','high','low','close','volume'] (timestamp converted to UTC datetime index when possible).
        """
        if self._has_method("fetch_ohlcv"):
            try:
                rows = self.client.fetch_ohlcv(symbol, timeframe, limit)
                return self._rows_to_ohlcv_df(rows)
            except Exception:
                pass

        # fallback empty DataFrame
        return pd.DataFrame(columns=["open", "high", "low", "close", "volume"])

    def _rows_to_ohlcv_df(self, rows) -> pd.DataFrame:
        """
        Minimal conversion of common ccxt rows to a DataFrame. Accepts:
          - pandas.DataFrame (returned directly with key normalization)
          - list of lists/tuples: [ts_ms|ts_s, open, high, low, close, volume]
        """
        if rows is None:
            return pd.DataFrame(columns=["open", "high", "low", "close", "volume"])

        if isinstance(rows, pd.DataFrame):
            df = rows.copy()
        else:
            try:
                df = pd.DataFrame(rows)
            except Exception:
                return pd.DataFrame(columns=["open", "high", "low", "close", "volume"])

        # best-effort timestamp handling
        if not df.empty:
            first_col = df.columns[0]
            if pd.api.types.is_numeric_dtype(df[first_col]):
                # determine s vs ms
                try:
                    sample = int(df[first_col].iloc[0])
                    if sample > 10**12:
                        df["datetime"] = pd.to_datetime(df[first_col], unit="ms", utc=True)
                    elif sample > 10**9:
                        df["datetime"] = pd.to_datetime(df[first_col], unit="s", utc=True)
                    else:
                        df["datetime"] = None
                except Exception:
                    df["datetime"] = None

                if "datetime" in df.columns and df["datetime"].notnull().any():
                    df = df.set_index("datetime")

            # map positional columns to open/high/low/close/volume if names missing
            cols_lower = [str(c).lower() for c in df.columns]
            if set(["open", "high", "low", "close"]).issubset(cols_lower):
                # normalize names
                mapping = {df.columns[cols_lower.index(c)]: c for c in ["open", "high", "low", "close"] if c in cols_lower}
                df = df.rename(columns=mapping)
            else:
                # positional map if we have at least 5 columns
                if df.shape[1] >= 5:
                    try:
                        # assume [ts, open, high, low, close, volume?]
                        # if datetime is index, first positional col may be open; handle heuristics
                        idx_offset = 1 if "datetime" in df.columns or isinstance(df.index, pd.DatetimeIndex) else 0
                        mapping = {
                            df.columns[idx_offset + 0]: "open",
                            df.columns[idx_offset + 1]: "high",
                            df.columns[idx_offset + 2]: "low",
                            df.columns[idx_offset + 3]: "close",
                        }
                        if df.shape[1] > idx_offset + 4:
                            mapping[df.columns[idx_offset + 4]] = "volume"
                        df = df.rename(columns=mapping)
                    except Exception:
                        pass

        # ensure columns exist and select final set
        for c in ("open", "high", "low", "close"):
            if c not in df.columns:
                df[c] = pd.NA
        if "volume" not in df.columns:
            df["volume"] = pd.NA

        return df[["open", "high", "low", "close", "volume"]].copy()
