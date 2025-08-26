# bot_core/exchanges/adapter_manager.py
"""Adapter manager: a tiny global holder and initializer for a single adapter.

Purpose:
- Provide init_adapter(name, config) to create and store one adapter instance.
- Provide get_adapter() to retrieve the current adapter (or raise if not initialized).
- Provide close_adapter() to disconnect and clear the adapter.

This keeps wiring isolated and lets the rest of the code import from bot_core.exchanges.adapter_manager
without knowing which concrete adapter is used.
"""

from typing import Optional, Dict, Any
from bot_core.exchanges import get_adapter  # factory we added earlier

_ADAPTER = None  # type: ignore


def init_adapter(name: str, config: Optional[Dict[str, Any]] = None):
    """
    Initialize and store an adapter instance by name using the factory.

    Example:
        init_adapter("mt5", {"dry_run": True})
    """
    global _ADAPTER
    # if already initialized with same config, keep it
    if _ADAPTER is not None:
        return _ADAPTER
    _ADAPTER = get_adapter(name, config or {})
    # attempt to connect (adapters are conservative/dry-run by default)
    try:
        _ADAPTER.connect()
    except Exception:
        # do not fail hard here; some adapters may lazily connect
        pass
    return _ADAPTER


def get_adapter_instance():
    """Return the initialized adapter instance or raise an error if not initialized."""
    if _ADAPTER is None:
        raise RuntimeError("Adapter not initialized. Call init_adapter(name, config) first.")
    return _ADAPTER


def close_adapter():
    """Disconnect and clear the adapter (safe if adapter not present)."""
    global _ADAPTER
    if _ADAPTER is None:
        return
    try:
        _ADAPTER.disconnect()
    except Exception:
        pass
    _ADAPTER = None
