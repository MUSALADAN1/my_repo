# tests/test_pivots.py
import pandas as pd
import numpy as np
from bot_core.indicators import pivot_points, support_resistance_levels

def test_pivot_points_basic():
    np.random.seed(3)
    n = 20
    price = pd.Series(np.cumsum(np.random.randn(n)*0.4 + 0.05) + 1.2)
    high = price + (np.random.rand(n) * 0.03)
    low = price - (np.random.rand(n) * 0.03)
    close = price

    df = pivot_points(high, low, close)
    assert set(["pp","r1","s1","r2","s2","r3","s3"]).issubset(set(df.columns))
    assert len(df) == n

    latest = support_resistance_levels(high, low, close)
    assert all(k in latest for k in ["pp","r1","s1","r2","s2","r3","s3"])
    assert isinstance(latest["pp"], float)
