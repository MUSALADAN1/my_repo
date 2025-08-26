import math
from bot_core import fibonacci

def approx(a, b, tol=1e-6):
    return abs(a - b) <= tol

def test_retracement_basic():
    high = 110.0
    low = 100.0
    retr = fibonacci.retracement_levels(high, low)
    # 0.5 retracement expected at midpoint 105.0
    assert approx(retr[0.5], 105.0)
    # 0.618 expected 110 - 10*0.618 = 103.82
    assert approx(retr[0.618], 110.0 - 10.0 * 0.618)

def test_extension_basic():
    high = 110.0
    low = 100.0
    ext = fibonacci.extension_levels(high, low)
    # extension 1.0 expected at 110 + 10*1.0 = 120.0
    assert approx(ext[1.0], 120.0)
    # extension 1.618 expected at 110 + 10*1.618 = 126.18
    assert approx(ext[1.618], 110.0 + 10.0 * 1.618)

def test_levels_from_series_sequence():
    highs = [100, 101, 102, 110.0]
    lows = [95, 96, 98, 100.0]
    out = fibonacci.levels_from_series(highs, lows)
    assert "retracements" in out and "extensions" in out
    assert approx(out["retracements"][0.5], 105.0)
    assert approx(out["extensions"][1.0], 120.0)
