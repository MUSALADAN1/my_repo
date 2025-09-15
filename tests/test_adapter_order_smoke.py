# tests/test_adapter_order_smoke.py
from bot_core.exchanges import adapter_manager

def test_adapter_create_order_smoke():
    # Try to init an adapter in dry_run mode
    try:
        adapter_manager.init_adapter("mt5", {"dry_run": True})
    except Exception:
        # adapter may not be available; ensure get_adapter raises gracefully
        try:
            adapter_manager.get_adapter("mt5")
        except RuntimeError:
            assert True
            return

    adapter = adapter_manager.get_adapter("mt5")
    assert adapter is not None
    assert hasattr(adapter, "create_order")
    assert hasattr(adapter, "modify_position")

    # call create_order in dry_run; should return a dict-like result without raising
    # pass required 'type' parameter expected by MT5Adapter.create_order
    res = adapter.create_order(symbol="EURUSDm", side="buy", type="market", amount=0.01, price=None, params={})
    assert res is not None
    if isinstance(res, dict):
        assert "id" in res or "status" in res or "raw" in res
