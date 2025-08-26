# bot_core/exchanges/adapter.py
"""
Unified exchange/broker adapter interface.

This defines the minimal abstract API that all exchange/broker adapters should
implement so the rest of the bot can interact with exchanges in a uniform way.
"""

from __future__ import annotations
import abc
import uuid
from dataclasses import dataclass, field
from enum import Enum
from typing import Callable, Dict, List, Optional, Tuple, Any


class ExchangeError(Exception):
    """Generic exchange/broker error."""


class OrderStatus(str, Enum):
    OPEN = "open"
    FILLED = "filled"
    CANCELED = "canceled"
    REJECTED = "rejected"
    PARTIAL = "partial"


@dataclass
class OrderRequest:
    symbol: str
    side: str  # "buy" or "sell"
    amount: float
    price: Optional[float] = None
    order_type: str = "limit"  # "limit", "market", "stop", etc.
    meta: Dict[str, Any] = field(default_factory=dict)


@dataclass
class Order:
    id: str
    symbol: str
    side: str
    amount: float
    price: Optional[float]
    filled: float = 0.0
    status: OrderStatus = OrderStatus.OPEN
    meta: Dict[str, Any] = field(default_factory=dict)


@dataclass
class Ticker:
    symbol: str
    bid: Optional[float] = None
    ask: Optional[float] = None
    last: Optional[float] = None
    timestamp: Optional[str] = None
    raw: Dict[str, Any] = field(default_factory=dict)


# OHLCV tuple: (timestamp, open, high, low, close, volume)
OHLCV = Tuple[Any, float, float, float, float, float]


class ExchangeAdapter(abc.ABC):
    """
    Abstract base class for exchange adapters.

    Implementations should be lightweight and thread-safe where possible.
    """

    def __init__(self, config: Optional[Dict[str, Any]] = None) -> None:
        self.config = config or {}
        self._connected = False

    # --- lifecycle / connectivity -------------------------------------------------
    @abc.abstractmethod
    def connect(self) -> None:
        """Establish connection / authenticate if needed."""

    @abc.abstractmethod
    def disconnect(self) -> None:
        """Tear down connections / cleanup."""

    def is_connected(self) -> bool:
        """Return connection state (implementor may override)."""
        return bool(self._connected)

    # --- market data -------------------------------------------------------------
    @abc.abstractmethod
    def fetch_ticker(self, symbol: str) -> Ticker:
        """Return a Ticker for the symbol."""

    @abc.abstractmethod
    def fetch_ohlcv(self, symbol: str, timeframe: str, limit: int = 100) -> List[OHLCV]:
        """
        Return list of OHLCV tuples for the given symbol and timeframe.
        Each OHLCV is (timestamp, open, high, low, close, volume).
        """

    # --- account / balances ------------------------------------------------------
    @abc.abstractmethod
    def fetch_balance(self) -> Dict[str, float]:
        """Return a mapping of asset -> balance (available)."""

    # --- orders ------------------------------------------------------------------
    @abc.abstractmethod
    def create_order(self, req: OrderRequest) -> Order:
        """Create / place an order on the exchange (or simulate it)."""

    @abc.abstractmethod
    def fetch_order(self, order_id: str) -> Optional[Order]:
        """Return order by ID or None if not found."""

    @abc.abstractmethod
    def fetch_open_orders(self, symbol: Optional[str] = None) -> List[Order]:
        """Return all open/pending orders, optionally filtered by symbol."""

    @abc.abstractmethod
    def cancel_order(self, order_id: str) -> bool:
        """Attempt to cancel order; return True if cancelled."""

    # --- optional websockets / streaming hooks ----------------------------------
    def subscribe_trades(self, symbol: str, callback: Callable[[Dict[str, Any]], None]) -> None:
        """
        Optional: subscribe to trade stream for symbol. Default no-op.
        Implementors may provide a background thread / callback invocation.
        """
        raise NotImplementedError("subscribe_trades not implemented by this adapter")

    # --- small helpers -----------------------------------------------------------
    @staticmethod
    def _generate_id(prefix: str = "o") -> str:
        return f"{prefix}-{uuid.uuid4().hex[:12]}"
