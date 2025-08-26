# backend/exchanges/adapter_base.py
from abc import ABC, abstractmethod
from typing import Any, Dict

class ExchangeAdapter(ABC):
    """
    Abstract base class for exchange adapters.
    Concrete adapters must implement the abstract methods below.
    Adapters should be lightweight wrappers around exchange SDKs/clients.
    """

    def __init__(self, config: Dict[str, Any]):
        self.config = config or {}
        self.connected = False
        self.client = None

    @abstractmethod
    def connect(self) -> bool:
        """Establish connection / auth with the exchange. Return True on success."""
        raise NotImplementedError

    @abstractmethod
    def fetch_ticker(self, symbol: str) -> Dict[str, Any]:
        """Return basic ticker info for symbol (bid/ask/last)."""
        raise NotImplementedError

    @abstractmethod
    def fetch_balance(self) -> Dict[str, Any]:
        """Return a representation of balances."""
        raise NotImplementedError

    @abstractmethod
    def place_order(self, symbol: str, side: str, amount: float, price: float = None, order_type: str = "market") -> Dict[str, Any]:
        """Place an order and return a dict with at least an 'id' and 'status'."""
        raise NotImplementedError

    def disconnect(self) -> None:
        """Gracefully close connections if any."""
        self.connected = False
        self.client = None
