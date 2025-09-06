# my_trading_bot/bot_core/exchanges/base_adapter.py
"""
Base exchange/broker adapter interface.

All adapters (MT5, Binance, Bybit, KuCoin, etc.) will inherit from this base class
so the rest of the bot can call a single, consistent API.
"""

from abc import ABC, abstractmethod
from typing import Any, Dict, List, Optional


class AdapterError(Exception):
    """Generic adapter-level exception."""
    pass


class BaseAdapter(ABC):
    """Abstract base class for all exchange/broker adapters."""

    def __init__(self, config: Optional[Dict[str, Any]] = None):
        self.config = config or {}

    # --- connection lifecycle ---
    @abstractmethod
    def connect(self) -> None:
        """Connect/authenticate to the exchange/broker."""
        raise NotImplementedError

    @abstractmethod
    def disconnect(self) -> None:
        """Disconnect/cleanup."""
        raise NotImplementedError

    @abstractmethod
    def is_connected(self) -> bool:
        """Return True if connection is active."""
        raise NotImplementedError

    # --- market data ---
    @abstractmethod
    def fetch_ticker(self, symbol: str) -> Dict[str, Any]:
        """Get the latest ticker for a symbol."""
        raise NotImplementedError

    def fetch_ohlcv(
        self,
        symbol: str,
        timeframe: str,
        since: Optional[int] = None,
        limit: Optional[int] = 1000
    ) -> List[Dict[str, Any]]:
        """Get OHLCV candles (open, high, low, close, volume)."""
        raise NotImplementedError

    # --- account / positions ---
    @abstractmethod
    def fetch_balance(self) -> Dict[str, Any]:
        """Return account balance information."""
        raise NotImplementedError

    @abstractmethod
    def fetch_positions(self) -> List[Dict[str, Any]]:
        """Return open positions."""
        raise NotImplementedError

    # --- orders ---
    @abstractmethod
    def create_order(
        self,
        symbol: str,
        side: str,
        type: str,
        amount: float,
        price: Optional[float] = None,
        params: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        """Place an order."""
        raise NotImplementedError

    @abstractmethod
    def cancel_order(self, order_id: str, symbol: Optional[str] = None) -> Dict[str, Any]:
        """Cancel an order."""
        raise NotImplementedError

    @abstractmethod
    def fetch_order(self, order_id: str, symbol: Optional[str] = None) -> Dict[str, Any]:
        """Fetch a single order by id."""
        raise NotImplementedError

    @abstractmethod
    def fetch_open_orders(self, symbol: Optional[str] = None) -> List[Dict[str, Any]]:
        """List open orders."""
        raise NotImplementedError

    # --- utilities ---
    def normalize_symbol(self, symbol: str) -> str:
        """Optional: convert 'EURUSD' → 'EUR/USD' depending on exchange."""
        return symbol
