# tests/test_atr_stop.py
import pandas as pd
import numpy as np
from bot_core.risk.atr_stop import compute_atr, compute_static_stop, TrailingStopManager

def make_simple_ohlc(n=20, base=100.0):
    # generate OHLC with small random moves but deterministic seed
    np.random.seed(0)
    highs = []
    lows = []
    closes = []
    price = base
    for i in range(n):
        move = (np.random.rand() - 0.5) * 2.0  # in [-1, 1]
        o = price
        h = o + abs(move) * 1.2 + 0.1
        l = o - abs(move) * 1.1 - 0.1
        c = o + move
        highs.append(h)
        lows.append(l)
        closes.append(c)
        price = c
    idx = pd.date_range("2025-01-01", periods=n, freq="H")
    return pd.DataFrame({"high": highs, "low": lows, "close": closes}, index=idx)

def test_compute_atr_basic():
    df = make_simple_ohlc(n=30)
    atr = compute_atr(df, period=5)
    # ATR should be NaN for first (period-1) rows and then finite
    assert atr.iloc[:4].isna().all()
    assert atr.iloc[4:].notna().any()
    # values should be non-negative
    assert (atr.dropna() >= 0).all()

def test_compute_static_stop_long_short():
    atr_val = 2.5
    entry = 100.0
    stop_long = compute_static_stop(entry, atr_val, multiplier=1.5, side="long")
    stop_short = compute_static_stop(entry, atr_val, multiplier=2.0, side="short")
    assert stop_long == 100.0 - 1.5 * 2.5
    assert stop_short == 100.0 + 2.0 * 2.5

def test_trailing_stop_manager_long_moves_up_and_stop_moves_up():
    df = make_simple_ohlc(n=20)
    atr = compute_atr(df, period=3)
    # start entry at first close
    entry_price = df["close"].iloc[2]
    mgr = TrailingStopManager(entry_price, side="long", trailing_atr_mult=1.0)
    prev_stop = None
    # iterate through subsequent prices and check stop updates
    for i in range(3, 20):
        price = df["close"].iloc[i]
        atr_val = atr.iloc[i] if not pd.isna(atr.iloc[i]) else None
        new_stop = mgr.update(price, atr_val)
        # stop should be None until atr becomes available
        if atr_val is None:
            assert new_stop is None
        else:
            assert isinstance(new_stop, float)
            # stop should not exceed best price
            assert new_stop <= mgr.best_price
            prev_stop = new_stop

def test_trailing_stop_manager_short_moves_down_and_stop_moves_down():
    df = make_simple_ohlc(n=20)
    atr = compute_atr(df, period=3)
    entry_price = df["close"].iloc[2]
    mgr = TrailingStopManager(entry_price, side="short", trailing_atr_mult=0.5)
    prev_stop = None
    for i in range(3, 20):
        price = df["close"].iloc[i]
        atr_val = atr.iloc[i] if not pd.isna(atr.iloc[i]) else None
        new_stop = mgr.update(price, atr_val)
        if atr_val is None:
            assert new_stop is None
        else:
            assert isinstance(new_stop, float)
            # for short, stop should be >= best_price
            assert new_stop >= mgr.best_price
            prev_stop = new_stop
