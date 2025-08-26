# backend/exchanges/factory.py
"""
Compatibility shim: re-export create_adapter from bot_core.exchanges.factory.

This keeps older imports like `from backend.exchanges.factory import create_adapter`
working while we centralize adapters under bot_core/exchanges.
"""
from bot_core.exchanges.factory import create_adapter  # re-export

__all__ = ["create_adapter"]
