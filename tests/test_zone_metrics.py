# tests/test_zone_metrics.py
import pandas as pd
import numpy as np
from bot_core.strategy_manager import StrategyManager
from bot_core.strategies.trend_following import TrendFollowingStrategy

class MockBroker:
    def __init__(self, df):
        self._df = df

    def fetch_ohlcv(self, symbol, timeframe, limit=500):
        # return the supplied DataFrame (index ascending)
        return self._df.copy()

def make_uptrend_df(n=30, start=100.0, end=105.0):
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

def test_run_backtest_records_zone_skips(monkeypatch):
    df = make_uptrend_df(n=20, start=100.0, end=105.0)
    broker = MockBroker(df)

    sm = StrategyManager()
    # register TrendFollowingStrategy with zone_filter enabled
    s = sm.register_strategy(TrendFollowingStrategy, params={
        "short": 3, "long": 6, "momentum_threshold": 0.0,
        "zone_filter": True, "zone_margin": 0.05, "zone_lookback": 20
    })
    sm.initialize_all(broker)

    # monkeypatch the sr_zones_from_series used inside trend_following so it always returns
    # a resistance zone centered at the latest price (forcing the strategy to skip due to zone)
    def fake_zones(highs, lows, left=3, right=3, price_tolerance=0.002, min_points=1):
        last_price = float(highs.iloc[-1])
        return [{"type": "resistance", "center": last_price, "strength": 10.0, "min_price": last_price - 0.001, "max_price": last_price + 0.001}]
    monkeypatch.setattr("bot_core.strategies.trend_following.sr_zones_from_series", fake_zones)

    res = sm.run_backtest(broker, "FAKE/SYM", "1h", limit=20)
    assert res["status"] == "ok"
    metrics = res.get("metrics", {})
    # expect at least one skipped_by_zone recorded
    assert metrics.get("signals_skipped_by_zone", 0) >= 1
    assert metrics.get("signals_skipped_by_zone_by_strategy", {}).get(s.name, 0) >= 1
