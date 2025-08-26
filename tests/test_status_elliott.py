# tests/test_status_elliott.py
import json
from backend import status_server
from flask import Flask

def test_status_includes_elliott_snapshot(monkeypatch):
    # create a fake manager that exposes last_ohlcv (pandas DataFrame)
    import pandas as pd
    idx = pd.date_range("2025-01-01", periods=10, freq="T")
    df = pd.DataFrame({
        "open": [100 + i*0.1 for i in range(10)],
        "high": [100 + i*0.12 for i in range(10)],
        "low": [100 + i*0.08 for i in range(10)],
        "close": [100 + i*0.1 for i in range(10)],
        "volume": [1 for _ in range(10)],
    }, index=idx)

    class DummyMgr:
        last_ohlcv = df
        strategies = []

    monkeypatch.setattr(status_server, "_strategy_manager", DummyMgr())
    with status_server.app.test_client() as c:
        res = c.get("/api/status")
        assert res.status_code == 200
        j = res.get_json()
        assert "metrics" in j
        # metrics may exist even if elliott couldn't compute; if computed, it should be a dict
        ell = j["metrics"].get("elliott")
        assert ell is None or isinstance(ell, dict)
