# tests/test_factory_ccxt_adapter.py
import pytest
from bot_core.exchanges.factory import create_adapter
from bot_core.exchanges.ccxt_adapter import CCXTAdapter

def test_create_ccxt_adapter_by_alias():
    a = create_adapter("ccxt", config={"client": None})
    assert isinstance(a, CCXTAdapter)

def test_create_ccxt_adapter_with_exchange_hint():
    a = create_adapter("ccxt:binance", config={})
    assert isinstance(a, CCXTAdapter)
    # verify config propagated (factory injects 'exchange' when using ccxt:NAME)
    assert getattr(a, "config", {}).get("exchange") in ("binance", "Binance", "BINANCE")
