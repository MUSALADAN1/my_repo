# tests/test_trend_zone_filter.py
import pandas as pd
import numpy as np
import pytest
from bot_core.strategies.trend_following import TrendFollowingStrategy

def make_uptrend_df(n=40, start=100.0, end=105.0):
    prices = np.linspace(start, end, n)
    idx = pd.date_range("2025-01-01", periods=n, freq="H")
    high = prices + 0.01
    low = prices - 0.01
    df = pd.DataFrame({
        "open": prices,
        "high": high,
        "low": low,
        "close": prices
    }, index=idx)
    return df

def test_zone_filter_blocks_long(monkeypatch):
    """
    Ensure that when zone_filter is enabled and a nearby resistance zone is reported,
    the TrendFollowingStrategy does NOT emit a normal 'long' signal.

    Historically the strategy returned `None` when skipping; newer code returns an explicit
    marker dict `{"skipped_by_zone": True, ...}`. Accept both.
    """
    df = make_uptrend_df(n=40, start=100.0, end=105.0)
    params = {"short": 3, "long": 6, "momentum_threshold": 0.0,
              "zone_filter": True, "zone_margin": 0.01, "zone_lookback": 40, "min_zone_strength": 0.0}
    strat = TrendFollowingStrategy(params=params)

    last_price = float(df["close"].iloc[-1])

    # fake sr_zones_from_series to always return a resistance centered at last_price
    def fake_zones(h, l, left=3, right=3, price_tolerance=0.002, min_points=1):
        return [{"type": "resistance", "center": last_price, "strength": 10.0,
                 "min_price": last_price - 0.001, "max_price": last_price + 0.001}]

    monkeypatch.setattr("bot_core.strategies.trend_following.sr_zones_from_series", fake_zones)

    res = strat.on_bar(df)

    # Accept either legacy None OR explicit skip marker dict.
    if res is None:
        assert True
        return

    # must be a dict with skipped_by_zone marker (new behaviour)
    assert isinstance(res, dict), f"expected None or dict, got {type(res)}"
    assert res.get("skipped_by_zone") is True or res.get("reason") == "near_resistance", \
        f"expected skip marker, got {res}"
