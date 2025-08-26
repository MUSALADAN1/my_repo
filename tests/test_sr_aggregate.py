# tests/test_sr_aggregate.py
import pandas as pd
from bot_core.sr import aggregate_zones_from_df

def make_minute_df(n=30, start="2025-01-01"):
    idx = pd.date_range(start=start, periods=n, freq="T")
    # create a gentle uptrend with noise
    import numpy as np
    base = 100 + (np.arange(n) * 0.05)
    high = base + np.random.RandomState(0).randn(n) * 0.2 + 0.2
    low = base + np.random.RandomState(1).randn(n) * 0.2 - 0.2
    close = base + np.random.RandomState(2).randn(n) * 0.1
    openv = base + np.random.RandomState(3).randn(n) * 0.1
    vol = (np.abs(np.random.RandomState(4).randn(n)) * 10).round(3)
    return pd.DataFrame({"open": openv, "high": high, "low": low, "close": close, "volume": vol}, index=idx)

def test_aggregate_zones_basic():
    df = make_minute_df(40)
    zones = aggregate_zones_from_df(df)
    assert isinstance(zones, list)
    # aggregator guarantees at least one zone (synthetic fallback)
    assert len(zones) >= 1
    z = zones[0]
    assert "center" in z and "min_price" in z and "max_price" in z and "strength" in z
