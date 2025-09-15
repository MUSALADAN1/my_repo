# test_breakout.py
from backend.exchanges import create_adapter
from backend.exchanges.broker import Broker
from bot_core.strategy_manager import StrategyManager
from bot_core.strategies.breakout import BreakoutStrategy

class MockBreakoutOHLCVClient:
    """
    Builds synthetic data that forms a range for many bars, then has a clear breakout up,
    followed by a breakout down later.
    Row format: [timestamp_ms, open, high, low, close, volume]
    """
    def fetch_ohlcv(self, symbol, timeframe, limit):
        base = 1690000000000
        rows = []
        # Create 25 bars of tight range around 100.0 (no breakout)
        for i in range(25):
            rows.append([base + i*3600*1000, 99.8, 100.2, 99.5, 100.0, 100])
        # breakout up bar
        rows.append([base + 25*3600*1000, 100.0, 105.0, 100.0, 105.0, 500])
        # consolidation
        rows.append([base + 26*3600*1000, 105.0, 105.5, 104.5, 105.2, 200])
        # drop and breakout down (low)
        rows.append([base + 27*3600*1000, 105.2, 105.3, 94.0, 94.0, 800])
        return rows

def test_breakout_emits_long_and_short():
    mock = MockBreakoutOHLCVClient()
    adapter = create_adapter("binance", {"client": mock})
    broker = Broker(adapter_instance=adapter)
    broker.connect()

    sm = StrategyManager()
    # lookback 20 so first 25 range bars populate prior window; threshold 0.0 to detect exact breakout
    s = sm.register_strategy(BreakoutStrategy, params={"lookback":20, "threshold": 0.0})
    sm.initialize_all(broker)
    res = sm.run_backtest(broker, "BTC/USDT", "1h", limit=30)
    assert res["status"] == "ok"
    signals = res["signals"]
    # Expect at least one long and one short across timeline
    assert any(sig.get("signal") == "long" for sig in signals), f"expected a long breakout, got {signals}"
    assert any(sig.get("signal") == "short" for sig in signals), f"expected a short breakout, got {signals}"
    assert s.call_count > 0
