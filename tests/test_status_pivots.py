import pandas as pd
from backend import status_server

def test_status_includes_pivots_from_last_ohlcv():
    # fake manager with last_metrics containing last_ohlcv (single row)
    class FakeMgr:
        last_metrics = {
            "last_ohlcv": [
                {"open": 100.0, "high": 105.0, "low": 95.0, "close": 100.0, "volume": 1.0, "time": "2025-01-01T00:00:00Z"}
            ]
        }

    mgr = FakeMgr()
    out = status_server._status_from_manager(mgr)
    assert "pivots" in out
    pivs = out["pivots"]
    assert isinstance(pivs, list)
    assert len(pivs) >= 1
    # check pivot P = 100.0 (classic)
    assert round(float(pivs[0]["P"]), 6) == 100.0
