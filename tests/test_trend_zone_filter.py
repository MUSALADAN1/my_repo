# tests/test_trend_zone_filter.py
import pandas as pd
import numpy as np
from bot_core.strategies.trend_following import TrendFollowingStrategy

def make_uptrend_df(n=30, start=100.0, end=102.0):
    prices = np.linspace(start, end, n)
    high = prices + 0.01
    low = prices - 0.01
    df = pd.DataFrame({
        "open": prices,
        "high": high,
        "low": low,
        "close": prices
    })
    return df

def test_zone_filter_blocks_long(monkeypatch):
    df = make_uptrend_df(n=40, start=100.0, end=105.0)
    params = {"short": 3, "long": 6, "momentum_threshold": 0.0,
              "zone_filter": True, "zone_margin": 0.01, "zone_lookback": 40, "min_zone_strength": 0.0}
    strat = TrendFollowingStrategy(params=params)

    last_price = float(df["close"].iloc[-1])
    def fake_zones(h, l, left=3, right=3, price_tolerance=0.002, min_points=1):
        return [{"type": "resistance", "center": last_price, "strength": 10.0, "min_price": last_price - 0.001, "max_price": last_price + 0.001}]
    monkeypatch.setattr("bot_core.strategies.trend_following.sr_zones_from_series", fake_zones)

    res = strat.on_bar(df)
    assert res is None

def test_without_zone_filter_allows_long():
    df = make_uptrend_df(n=40, start=100.0, end=105.0)
    params = {"short": 3, "long": 6, "momentum_threshold": 0.0,
              "zone_filter": False}
    strat = TrendFollowingStrategy(params=params)

    res = strat.on_bar(df)
    assert isinstance(res, dict)
    assert res.get("signal") == "long"
