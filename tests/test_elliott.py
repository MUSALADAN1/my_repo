# tests/test_elliott.py
import pandas as pd
from bot_core.elliott import find_swings, detect_impulse

def make_elliott_like_series():
    """
    Construct a simple synthetic close series containing a clear 'up' 5-wave like structure:
    This has a series of ups and small retraces so find_swings+detect_impulse can detect it.
    """
    # We'll create a sequence with alternating local highs/lows:
    # base 100 -> up 102 -> down 101 -> up 103 -> down 102 -> up 104 -> down 103 -> up 105 -> down 104 -> up 106
    prices = [
        100, 101, 102, 101.5, 101,   # initial moves
        102.5, 103, 102.3, 102.8,    # wave 1->2
        103.5, 104, 103.4, 103.9,    # wave 3->4
        104.5, 105, 104.2, 104.8,    # etc
        105.5, 106, 105.6
    ]
    idx = pd.date_range("2025-01-01", periods=len(prices), freq="T")
    return pd.Series(prices, index=idx)

def test_find_swings_and_detect_impulse_basic():
    s = make_elliott_like_series()
    swings = find_swings(s, left=1, right=1)
    # we expect to find at least some swings
    assert isinstance(swings, list)
    assert len(swings) >= 5

    res = detect_impulse(s, min_swings=5, left=1, right=1)
    assert isinstance(res, dict)
    # If sequence is constructed upward, we expect an 'up' direction and positive impulse detection
    assert res["direction"] == "up"
    assert res["impulse"] is True
