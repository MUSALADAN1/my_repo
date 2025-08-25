# tests/test_multitimeframe.py
import pandas as pd
import numpy as np
from bot_core.multitimeframe import resample_ohlcv, align_multi_timeframes, MultiTimeframeWindow

def make_minute_df(n=60, start="2025-01-01 00:00:00", freq="1T"):
    idx = pd.date_range(start=start, periods=n, freq=freq)
    np.random.seed(0)
    price = 100 + np.cumsum(np.random.randn(n) * 0.1)
    high = price + np.random.rand(n) * 0.05
    low = price - np.random.rand(n) * 0.05
    open_ = pd.Series(price).shift(1).fillna(price[0])
    close = pd.Series(price)
    vol = (np.random.rand(n) * 10).round(3)
    df = pd.DataFrame({"open": open_, "high": high, "low": low, "close": close, "volume": vol}, index=idx)
    return df

def test_resample_ohlcv_basic():
    df = make_minute_df(n=30)
    df5 = resample_ohlcv(df, "5T")
    # 30 minutes -> 6 five-minute bars
    assert len(df5) == 6
    assert set(["open","high","low","close","volume"]).issubset(df5.columns)

def test_align_multi_timeframes():
    df = make_minute_df(n=60)
    aligned = align_multi_timeframes(df, base_tf="1T", target_tfs=["5T","15T"])
    assert "1T" in aligned and "5T" in aligned and "15T" in aligned
    base_idx = aligned["1T"].index
    # aligned frames should have the same index as base
    assert list(aligned["5T"].index) == list(base_idx)
    assert list(aligned["15T"].index) == list(base_idx)

def test_multiwindow_snapshot():
    df = make_minute_df(n=120)
    mtw = MultiTimeframeWindow(df, base_tf="1T", target_tfs=["5T"], window=10)
    snapshot = mtw.snapshot(lookback=10)
    assert "1T" in snapshot and "5T" in snapshot
    assert len(snapshot["1T"]) == 10
    assert len(snapshot["5T"]) == 10
