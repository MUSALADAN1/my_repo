"""
Compatibility shim for the legacy `bot_core.exchanges_old` package.

Many older modules in the codebase import get_adapter from
bot_core.exchanges_old; here we forward those calls to the
canonical backend.exchanges.create_adapter (if available).

This shim intentionally minimizes behavior — it's only for compatibility
during migration / testing.
"""
from typing import Any, Dict, Optional

# Try to delegate to the modern backend.exchanges factory first.
try:
    from backend.exchanges import create_adapter as _create_adapter
    from backend.exchanges import list_adapters as _list_adapters  # optional helper
    from backend.exchanges import list_aliases as _list_aliases
except Exception:
    _create_adapter = None
    _list_adapters = None
    _list_aliases = None

def get_adapter(name: str, config: Optional[Dict[str, Any]] = None):
    """
    Legacy-compatible get_adapter(name, config) -> adapter instance.

    Delegates to backend.exchanges.create_adapter if available; otherwise raises ImportError.
    """
    if _create_adapter is None:
        raise ImportError("backend.exchanges.create_adapter not available; cannot create adapter.")
    return _create_adapter(name, config)

def list_adapters():
    """Return discovered adapter classes (or None if backend not available)."""
    if _list_adapters is None:
        return {}
    return _list_adapters()

def list_aliases():
    """Return alias mapping (or {} if backend not available)."""
    if _list_aliases is None:
        return {}
    return _list_aliases()

__all__ = ["get_adapter", "list_adapters", "list_aliases"]
