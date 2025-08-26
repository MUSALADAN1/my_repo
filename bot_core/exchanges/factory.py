# bot_core/exchanges/factory.py
"""
Central adapter factory for exchange adapters.

This module is the canonical source-of-truth for adapter registration.
Adapters should be implemented under bot_core.exchanges (e.g. binance_adapter.py).
"""
from typing import Dict, Optional

# import local adapters (these should exist under bot_core/exchanges/)
from .binance_adapter import BinanceAdapter  # type: ignore
from .bybit_adapter import BybitAdapter      # type: ignore
from .kucoin_adapter import KuCoinAdapter    # type: ignore
from .mt5_adapter import MT5Adapter          # type: ignore

_ADAPTERS = {
    "binance": BinanceAdapter,
    "bybit": BybitAdapter,
    "kucoin": KuCoinAdapter,
    "mt5": MT5Adapter,
}


def create_adapter(name: str, config: Optional[Dict] = None):
    """
    Factory helper to instantiate an adapter by short name.

    Example:
        create_adapter("binance", {"api_key": "...", "api_secret": "..."})
    Returns:
        Adapter instance (constructed with config dict).
    """
    name_key = (name or "").lower()
    cls = _ADAPTERS.get(name_key)
    if not cls:
        raise ValueError(f"No adapter registered for '{name}'. Available: {list(_ADAPTERS.keys())}")
    return cls(config or {})
