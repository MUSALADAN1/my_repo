# bot_core/strategies/plugin_base.py
from typing import Any, Dict, Optional
from abc import ABC, abstractmethod

class StrategyContext:
    """
    Context passed to strategies on initialize. Contains broker and optional metadata.
    """
    def __init__(self, broker, config: Optional[Dict[str, Any]] = None):
        self.broker = broker
        self.config = config or {}

class StrategyPlugin(ABC):
    """
    Base class for pluggable strategy plugins.

    Lifecycle hooks:
      - initialize(context): called once before any data is fed
      - on_bar(df): called with the DataFrame window (index=datetime)
      - on_tick(tick): optional tick-level handler
      - on_signal(signal): called when strategy generates a signal (optional)
      - on_exit(): cleanup
    """

    def __init__(self, name: str, params: Optional[Dict[str, Any]] = None):
        self.name = name
        self.params = params or {}
        self.context: Optional[StrategyContext] = None

    def initialize(self, context: StrategyContext) -> None:
        """Called once when strategy is registered/started."""
        self.context = context

    @abstractmethod
    def on_bar(self, df):
        """
        Called for each bar (cumulative window). Strategies should return a dict or None.
        Example return: {"signal": "long", "confidence": 0.8}
        """
        raise NotImplementedError

    def on_tick(self, tick: Dict[str, Any]) -> None:
        """Optional: tick-level event."""
        return None

    def on_signal(self, signal: Dict[str, Any]) -> None:
        """Optional: called when strategy wants to publish a signal."""
        return None

    def on_exit(self) -> None:
        """Optional cleanup when strategy manager stops."""
        return None
