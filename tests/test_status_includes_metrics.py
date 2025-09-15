# tests/test_status_includes_metrics.py
from backend import status_server
from types import SimpleNamespace

def test_build_status_includes_metrics(monkeypatch):
    # Fake metrics snapshot
    fake_metrics = {"signals_skipped_by_zone": 3, "signals_skipped_by_zone_by_strategy": {"TrendFollowing": 3}}
    # Fake manager object exposing get_metrics_snapshot (and minimal strategies/zones)
    fake_mgr = SimpleNamespace(
        strategies=[],
        get_metrics_snapshot=lambda: fake_metrics,
        last_metrics=fake_metrics,
        get_zones_snapshot=lambda: [{"type":"resistance","center":100.0,"strength":1.0}]
    )
    # Monkeypatch the discovery function to return our fake manager
    monkeypatch.setattr(status_server, "_locate_strategy_manager", lambda: fake_mgr)
    payload = status_server._status_from_manager(fake_mgr)
    assert "metrics" in payload
    assert payload["metrics"] == fake_metrics
    assert "zones" in payload
    assert isinstance(payload["zones"], list)
    assert "strategies" in payload
    assert isinstance(payload["strategies"], list)
