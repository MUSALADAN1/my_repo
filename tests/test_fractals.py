# tests/test_fractals.py
import pandas as pd
from bot_core.fractals import detect_fractals

def make_test_df():
    # Build a simple sequence with a clear bull fractal at index 4 (low) and
    # a bear fractal at index 8 (high). Use 11 bars so order=2 works.
    idx = pd.date_range("2025-01-01", periods=11, freq="T")
    highs = [101, 102, 103, 102, 101.5, 101.6, 101.8, 102.2, 103.5, 102.0, 101.9]
    lows  = [100, 101, 102, 101.8, 100.2, 100.5, 100.8, 101.2, 102.1, 101.0, 100.9]
    df = pd.DataFrame({"open": highs, "high": highs, "low": lows, "close": highs, "volume": [1]*11}, index=idx)
    return df

def test_detect_fractals_basic():
    df = make_test_df()
    fr = detect_fractals(df, order=2)
    # Expect at least one bull and one bear fractal
    types = set([f["type"] for f in fr])
    assert "bull" in types and "bear" in types
    # verify some expected positions by index
    indices = [f["index"] for f in fr]
    assert 4 in indices  # bull at pos 4 (low)
    assert 8 in indices  # bear at pos 8 (high)
