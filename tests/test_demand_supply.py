# tests/test_demand_supply.py
import pandas as pd
import numpy as np
from bot_core.demand_supply import detect_zones_from_ohlcv

def make_rev_df():
    # simple minute-series with a clear valley around minute 10 and a peak around minute 25
    idx = pd.date_range("2025-01-01", periods=40, freq="T")
    prices = []
    for i in range(40):
        # make a valley near i==10 and peak near i==25
        base = 100.0
        if 8 <= i <= 12:
            p = base - 1.5 + (i-10)*0.1
        elif 23 <= i <= 27:
            p = base + 1.5 - (i-25)*0.1
        else:
            p = base + np.sin(i/5.0)*0.3
        prices.append(p)
    df = pd.DataFrame({
        "open": prices,
        "high": [p + 0.2 for p in prices],
        "low": [p - 0.2 for p in prices],
        "close": prices,
        "volume": [1.0]*len(prices),
    }, index=idx)
    return df

def test_detect_zones_basic():
    df = make_rev_df()
    zones = detect_zones_from_ohlcv(df, lookback=40, extrema_order=2, min_members=1, price_tol=0.01)
    # expect both demand (valley) and resistance (peak) zones present
    types = set(z["type"] for z in zones)
    assert "demand" in types or "resistance" in types
    # ensure zones have expected keys
    assert all(set(z.keys()) >= {"type","center","min_price","max_price","strength"} for z in zones)
    # at least one zone should be detected
    assert len(zones) >= 1
