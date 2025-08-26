# backend/exchanges/broker.py
from typing import Optional, Dict, Any
import pandas as pd

from .factory import create_adapter
from .adapter_base import ExchangeAdapter

class BrokerError(Exception):
    pass

class Broker:
    """
    Unified broker interface that wraps an ExchangeAdapter.

    Usage examples:
      # by adapter name + config
      broker = Broker(adapter_name='binance', config={'client': my_client})
      broker.connect()
      broker.fetch_ticker('BTC/USDT')

      # or by passing an instantiated adapter
      adapter = create_adapter('binance', {'client': my_client})
      broker = Broker(adapter_instance=adapter)
      broker.connect()
    """

    def __init__(
        self,
        adapter_name: Optional[str] = None,
        adapter_instance: Optional[ExchangeAdapter] = None,
        config: Optional[Dict[str, Any]] = None
    ):
        self.config = config or {}
        self.adapter = adapter_instance
        self.adapter_name = adapter_name
        if self.adapter is None and self.adapter_name is None:
            raise BrokerError("Either adapter_name or adapter_instance must be provided.")

    def connect(self) -> bool:
        """Instantiate adapter (if needed) and connect."""
        if self.adapter is None:
            self.adapter = create_adapter(self.adapter_name, self.config)
        ok = self.adapter.connect()
        if not ok:
            raise BrokerError("Adapter failed to connect")
        return True

    def fetch_ticker(self, symbol: str) -> Dict[str, Any]:
        if hasattr(self.adapter, "fetch_ticker"):
            return self.adapter.fetch_ticker(symbol)
        raise BrokerError("Adapter does not implement fetch_ticker")

    def fetch_balance(self) -> Dict[str, Any]:
        if hasattr(self.adapter, "fetch_balance"):
            return self.adapter.fetch_balance()
        raise BrokerError("Adapter does not implement fetch_balance")

    def place_order(self, symbol: str, side: str, amount: float, price: Optional[float] = None, order_type: str = "market") -> Dict[str, Any]:
        if hasattr(self.adapter, "place_order"):
            return self.adapter.place_order(symbol, side, amount, price, order_type)
        raise BrokerError("Adapter does not implement place_order")
    def fetch_order(self, order_id: str, symbol: Optional[str] = None) -> Dict[str, Any]:
        if hasattr(self.adapter, "fetch_order"):
            return self.adapter.fetch_order(order_id, symbol)
        raise BrokerError("Adapter does not implement fetch_order")

    def fetch_open_orders(self, symbol: Optional[str] = None) -> list:
        if hasattr(self.adapter, "fetch_open_orders"):
            return self.adapter.fetch_open_orders(symbol)
        raise BrokerError("Adapter does not implement fetch_open_orders")

    def cancel_order(self, order_id: str, symbol: Optional[str] = None) -> Dict[str, Any]:
        if hasattr(self.adapter, "cancel_order"):
            return self.adapter.cancel_order(order_id, symbol)
        raise BrokerError("Adapter does not implement cancel_order")

    def _rows_to_ohlcv_df(self, rows):
        """
        Convert common ccxt-like rows to a standardized DataFrame:
        rows: iterable of [timestamp_ms, open, high, low, close, volume] or similar.
        """
        try:
            df = pd.DataFrame(rows)
            if df.empty:
                return pd.DataFrame(columns=["open","high","low","close","volume"])
            # If first column looks like a timestamp in ms or s, convert to datetime
            first_col = df.columns[0]
            if pd.api.types.is_integer_dtype(df[first_col]) or pd.api.types.is_float_dtype(df[first_col]):
                # decide ms vs s by magnitude (simple heuristic)
                sample = int(df[first_col].iloc[0])
                if sample > 1e12:
                    # ms
                    df['datetime'] = pd.to_datetime(df[first_col], unit='ms', utc=True)
                else:
                    df['datetime'] = pd.to_datetime(df[first_col], unit='s', utc=True)
                df.set_index('datetime', inplace=True)
                # expected order: ts, open, high, low, close, volume
                if df.shape[1] >= 6:
                    df.columns = ['timestamp','open','high','low','close','volume'] + list(df.columns[6:])
                    return df[['open','high','low','close','volume']]
                elif df.shape[1] >= 5:
                    df.columns = ['timestamp','open','high','low','close'] + list(df.columns[5:])
                    return df[['open','high','low','close']]
            # fallback: try to map named columns if present
            lower_cols = [str(c).lower() for c in df.columns]
            mapping = {}
            for c in ['open','high','low','close','volume','time','timestamp']:
                if c in lower_cols:
                    mapping[ df.columns[lower_cols.index(c)] ] = c
            df = df.rename(columns=mapping)
            # ensure columns
            for c in ['open','high','low','close']:
                if c not in df.columns:
                    df[c] = None
            return df[[c for c in ['open','high','low','close'] if c in df.columns] + (['volume'] if 'volume' in df.columns else [])]
        except Exception:
            return pd.DataFrame(columns=["open","high","low","close","volume"])

    def fetch_ohlcv(self, symbol: str, timeframe: Any, limit: int = 500) -> pd.DataFrame:
        """
        Return a pandas DataFrame of OHLCV if adapter supports it.

        Delegation order:
         1) adapter.fetch_ohlcv(...)
         2) adapter.client.fetch_ohlcv(...) (ccxt-like)
         3) adapter.client.get_ohlcv(...) (custom)
         4) adapter.client.copy_rates_from_pos(...) (MT5)
         5) return empty standardized DataFrame
        """
        # 1) Adapter implements fetch_ohlcv itself
        if hasattr(self.adapter, "fetch_ohlcv"):
            try:
                df = self.adapter.fetch_ohlcv(symbol, timeframe, limit)
                if isinstance(df, pd.DataFrame):
                    return df
                # try to convert iterable->DataFrame
                return self._rows_to_ohlcv_df(df)
            except Exception:
                # fallthrough to client delegation
                pass

        client = getattr(self.adapter, "client", None)
        if client:
            # 2) ccxt-like fetch_ohlcv
            if hasattr(client, "fetch_ohlcv"):
                try:
                    rows = client.fetch_ohlcv(symbol, timeframe, limit)
                    return self._rows_to_ohlcv_df(rows)
                except Exception:
                    pass
            # 3) custom get_ohlcv
            if hasattr(client, "get_ohlcv"):
                try:
                    rows = client.get_ohlcv(symbol, timeframe, limit)
                    return self._rows_to_ohlcv_df(rows)
                except Exception:
                    pass
            # 4) MetaTrader5 style: copy_rates_from_pos or copy_rates_from
            for mt_method in ("copy_rates_from_pos", "copy_rates_from", "copy_rates_range"):
                if hasattr(client, mt_method):
                    try:
                        # MT5 returns numpy structured array; adapter may already handle conversion,
                        # but if raw here, we'll attempt minimal conversion similar to MT5 adapter.
                        rates = getattr(client, mt_method)(symbol, timeframe, 0, limit)
                        df = pd.DataFrame(rates)
                        if 'time' in df.columns:
                            df['datetime'] = pd.to_datetime(df['time'], unit='s', utc=True)
                            df.set_index('datetime', inplace=True)
                        # normalize column names
                        if 'tick_volume' in df.columns:
                            df = df.rename(columns={'tick_volume':'volume'})
                        cols = ['open','high','low','close']
                        for c in cols:
                            if c not in df.columns:
                                df[c] = None
                        return df[['open','high','low','close'] + (['volume'] if 'volume' in df.columns else [])]
                    except Exception:
                        pass

        # fallback: empty frame with expected columns
        return pd.DataFrame(columns=["open", "high", "low", "close", "volume"])

    def disconnect(self) -> None:
        if hasattr(self.adapter, "disconnect"):
            self.adapter.disconnect()
