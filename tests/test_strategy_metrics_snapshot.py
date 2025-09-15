# tests/test_strategy_metrics_snapshot.py
import pandas as pd
from bot_core.strategy_manager import StrategyManager
from bot_core.strategies.plugin_base import StrategyPlugin

class DummyBroker:
    def __init__(self, df):
        self._df = df

    def fetch_ohlcv(self, symbol, timeframe, limit=500):
        return self._df

class SkipOnceStrategy(StrategyPlugin):
    """
    Test helper strategy that returns a skip marker *only* once, when
    the observed window reaches the configured target length.
    """
    def __init__(self, target_len=10, name="SkipOnce", params=None):
        super().__init__(name, params or {})
        self.called = 0
        self.target_len = int(target_len)

    def initialize(self, ctx):
        pass

    def on_bar(self, df):
        # df is the window (growing each step). Only return skip when we reach target_len.
        self.called += 1
        if len(df) >= self.target_len:
            return {"reason": "near_resistance", "skip": True}
        return None

def make_df(n=10):
    idx = pd.date_range("2025-01-01", periods=n, freq="H")
    close = pd.Series([100 + i*0.1 for i in range(n)], index=idx)
    high = close + 0.01
    low = close - 0.01
    df = pd.DataFrame({"open": close, "high": high, "low": low, "close": close, "volume": 1}, index=idx)
    return df

def test_metrics_snapshot_records_zone_skip():
    n = 8
    df = make_df(n)
    broker = DummyBroker(df)
    sm = StrategyManager()
    # create the strategy to skip once when window reaches n
    strat = SkipOnceStrategy(target_len=n)
    sm.register_strategy(strat)
    res = sm.run_backtest(broker, "FAKE", "1h", limit=n)
    assert res["status"] == "ok"
    metrics = sm.get_metrics_snapshot()
    assert metrics["signals_skipped_by_zone"] == 1
    assert metrics["signals_skipped_by_zone_by_strategy"].get("SkipOnce", 0) == 1
