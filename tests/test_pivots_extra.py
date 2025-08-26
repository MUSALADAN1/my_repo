import pandas as pd
import numpy as np
from bot_core import pivots as piv

def test_classic_pivots_scalar():
    # a simple known example
    H, L, C = 105.0, 95.0, 100.0
    r = piv.classic_pivots(H, L, C)
    assert round(r["P"], 6) == 100.0
    assert round(r["R1"], 6) == 105.0
    assert round(r["S1"], 6) == 95.0
    assert round(r["R2"], 6) == 110.0
    assert round(r["S2"], 6) == 90.0
    assert round(r["R3"], 6) == 115.0
    assert round(r["S3"], 6) == 85.0

def test_fibonacci_pivots_scalar():
    H, L, C = 105.0, 95.0, 100.0
    r = piv.fibonacci_pivots(H, L, C)
    # approximate checks
    assert abs(r["P"] - 100.0) < 1e-6
    assert abs(r["R1"] - 103.82) < 1e-6
    assert abs(round(r["R2"], 2) - 106.18) < 1e-6
    assert abs(round(r["S1"], 2) - 96.18) < 1e-6

def test_pivots_from_df():
    # build a tiny df
    idx = pd.date_range("2025-01-01", periods=1, freq="T")
    df = pd.DataFrame({"open":[100.0], "high":[105.0], "low":[95.0], "close":[100.0], "volume":[1.0]}, index=idx)
    out = piv.pivots_from_df(df, method="classic")
    assert list(out.columns) == ["P", "R1", "R2", "R3", "S1", "S2", "S3"]
    # check the only row
    row = out.iloc[-1]
    assert round(row["P"], 6) == 100.0
    assert round(row["R1"], 6) == 105.0
    assert round(row["S3"], 6) == 85.0
