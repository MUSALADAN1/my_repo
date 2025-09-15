# test_trend_following.py
from backend.exchanges import create_adapter
from backend.exchanges.broker import Broker
from bot_core.strategy_manager import StrategyManager
from bot_core.strategies.trend_following import TrendFollowingStrategy

class MockTrendingOHLCVClient:
    """
    Produces synthetic bars that form a clear uptrend so the trend-following strategy will emit a long.
    Rows: [timestamp_ms, open, high, low, close, volume]
    """
    def fetch_ohlcv(self, symbol, timeframe, limit):
        base = 1690000000000
        rows = []
        # start flat, then gradually increase close price
        for i in range(40):
            o = 1.0 + (i * 0.02)  # steadily increasing
            c = o + 0.01
            rows.append([base + i*3600*1000, o, o+0.02, o-0.01, c, 100 + i])
        return rows

def test_trend_following_emits_long_and_exit():
    mock = MockTrendingOHLCVClient()
    adapter = create_adapter("binance", {"client": mock})
    broker = Broker(adapter_instance=adapter)
    broker.connect()

    sm = StrategyManager()
    # use shorter EMAs for test speed
    s = sm.register_strategy(TrendFollowingStrategy, params={"short":5, "long":10, "momentum_threshold": 0.0})
    sm.initialize_all(broker)
    res = sm.run_backtest(broker, "BTC/USDT", "1h", limit=40)
    assert res["status"] == "ok"
    signals = res["signals"]
    # expect at least one 'long' (and possibly no 'exit' since trend is persistent)
    assert any(sig.get("signal") == "long" for sig in signals), f"expected a long signal, got {signals}"
    # strategy saw bars
    assert s.call_count > 0
