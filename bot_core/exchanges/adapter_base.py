# bot_core/exchanges/adapter_base.py
"""
Base exchange adapter for the trading bot.

This file defines the canonical ExchangeAdapter used by the bot_core exchange
package. It includes small helper utilities to safely forward kwargs to
underlying exchange client methods (to avoid TypeError when callers pass
extra metadata like cid/event_id).
"""

from abc import ABC, abstractmethod
from typing import Any, Dict, Optional, List
import inspect
import logging

logger = logging.getLogger(__name__)


class ExchangeAdapter(ABC):
    """
    Abstract base class for exchange adapters.

    Concrete adapters should inherit from this class and implement the
    abstract methods below. Methods accept **kwargs defensively to allow the
    orchestration/webhook code to pass metadata without breaking adapters.
    """

    def __init__(self, config: Optional[Dict[str, Any]] = None) -> None:
        self.config: Dict[str, Any] = config or {}
        self._connected = False
        self.client = None  # optional underlying SDK/client

    # ---------------------------
    # Helper: defensive kwargs
    # ---------------------------
    def _filter_kwargs_for(self, func, kwargs: Optional[Dict[str, Any]]) -> Dict[str, Any]:
        """
        Inspect `func` signature and return a dict with only the kwargs it
        accepts. This prevents passing unexpected keys (cid/event_id) to
        third-party clients.
        """
        if not kwargs:
            return {}
        try:
            sig = inspect.signature(func)
            accepted: Dict[str, Any] = {}
            for name, param in sig.parameters.items():
                # skip 'self'
                if name == "self":
                    continue
                if param.kind in (inspect.Parameter.POSITIONAL_OR_KEYWORD, inspect.Parameter.KEYWORD_ONLY):
                    if name in kwargs:
                        accepted[name] = kwargs[name]
            return accepted
        except Exception as e:
            logger.debug("Could not inspect signature for %s: %s", getattr(func, "__name__", str(func)), e)
            return {}

    def call_filtered(self, func, *args, **kwargs):
        """
        Call `func(*args, **filtered_kwargs)` where filtered_kwargs is the
        subset of kwargs that `func` accepts.
        """
        filtered = self._filter_kwargs_for(func, kwargs or {})
        return func(*args, **filtered)

    # ---------------------------
    # Lifecycle / connectivity
    # ---------------------------
    
    def connect(self, **kwargs) -> bool:
        """Establish connection to the exchange (authenticate if required)."""
        raise NotImplementedError

    def disconnect(self) -> None:
        """Optional: gracefully close connections."""
        self._connected = False
        self.client = None

    # ---------------------------
    # Market data / account
    # ---------------------------
    
    def fetch_ticker(self, symbol: str, **kwargs) -> Dict[str, Any]:
        """Return basic ticker info for symbol (bid/ask/last)."""
        raise NotImplementedError

    
    def fetch_balance(self, **kwargs) -> Dict[str, Any]:
        """Return a representation of balances."""
        raise NotImplementedError

    def fetch_ohlcv(self, symbol: str, timeframe: str = "1h", since: int = None, limit: int = 500, **kwargs) -> List:
        """
        Optional: return OHLCV data (list of rows or DataFrame-like).

        Default implementation raises NotImplementedError so minimal/dummy adapters
        do not need to implement this method unless they require OHLCV support.
        """
        raise NotImplementedError("fetch_ohlcv is not implemented for this adapter")


    # ---------------------------
    # Orders
    # ---------------------------

    def place_order(self, symbol: str, side: str, amount: float, price: float = None,
                    order_type: str = "market", **kwargs) -> Dict[str, Any]:
        """
        Place an order; default behavior:
          - If adapter implements legacy `create_order` (some adapters do), call that.
          - Otherwise raise NotImplementedError so callers can detect absence.
        """
        # support adapters that implement `create_order` (alternate naming)
        create_fn = getattr(self, "create_order", None)
        if callable(create_fn):
            # map parameters to common create_order signature
            params = kwargs.pop("params", None)
            # create_order typically expects (symbol, side, type, amount, price, params)
            return create_fn(symbol, side, order_type, amount, price, params or kwargs)
        raise NotImplementedError("place_order not implemented for this adapter")

    def cancel_order(self, order_id: str, **kwargs) -> Dict[str, Any]:
        """Cancel given order_id; default raises NotImplementedError."""
        raise NotImplementedError("cancel_order not implemented for this adapter")

    def fetch_order(self, order_id: str, symbol: Optional[str] = None, **kwargs) -> Dict[str, Any]:
        """Fetch a single order by id; default raises NotImplementedError."""
        raise NotImplementedError("fetch_order not implemented for this adapter")

    def fetch_open_orders(self, symbol: Optional[str] = None, **kwargs) -> List[Dict[str, Any]]:
        """List open orders; default raises NotImplementedError."""
        raise NotImplementedError("fetch_open_orders not implemented for this adapter")


    # ---------------------------
    # Utilities
    # ---------------------------
    def normalize_symbol(self, symbol: str) -> str:
        """Optional: convert 'EURUSD' -> 'EUR/USD' depending on exchange."""
        return symbol
