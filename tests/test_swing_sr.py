# tests/test_swing_sr.py
import pandas as pd
import numpy as np
from bot_core.indicators import swing_points, sr_levels_from_swings

def test_swing_points_detects_peak_and_trough():
    # synthetic peak at center index 5
    high = pd.Series([1,1,1,2,4,8,4,2,1,1,1], dtype=float)
    low = high - 0.5
    df = swing_points(high, low, left=2, right=2)
    assert df["swing_high"].sum() >= 1
    # peak at index 5 should be detected
    assert bool(df.loc[5, "swing_high"]) is True

    # synthetic trough at center index 5
    low2 = pd.Series([5,5,5,4,2,0,2,4,5,5,5], dtype=float)
    high2 = low2 + 0.5
    df2 = swing_points(high2, low2, left=2, right=2)
    assert df2["swing_low"].sum() >= 1
    assert bool(df2.loc[5, "swing_low"]) is True

def test_sr_levels_from_swings_returns_levels():
    high = pd.Series([1,1,1,2,4,8,4,2,1,1,1], dtype=float)
    low = high - 0.5
    levels = sr_levels_from_swings(high, low, left=2, right=2)
    # expect at least one resistance level
    assert any(l["type"] == "resistance" for l in levels)
    assert any(isinstance(l["price"], float) for l in levels)
