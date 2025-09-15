# test_scalping.py
from backend.exchanges import create_adapter
from backend.exchanges.broker import Broker
from bot_core.strategy_manager import StrategyManager
from bot_core.strategies.scalping import ScalpingStrategy

class MockScalpOHLCVClient:
    """
    Produces a short sequence designed to trigger a scalping long (sharp uptick) and then an exit.
    Format: [timestamp_ms, open, high, low, close, volume]
    Sequence:
      0: flat
      1: small uptick
      2: sharp uptick (should trigger long)
      3: small pullback but still above short_ma (hold)
      4: drop below short_ma -> exit
    """
    def fetch_ohlcv(self, symbol, timeframe, limit):
        base = 1690000000000
        rows = []
        rows.append([base + 0*3600*1000, 1.00, 1.01, 0.99, 1.00, 100])
        rows.append([base + 1*3600*1000, 1.00, 1.02, 0.99, 1.01, 100])
        # sharp uptick
        rows.append([base + 2*3600*1000, 1.01, 1.06, 1.00, 1.05, 200])
        # small pullback
        rows.append([base + 3*3600*1000, 1.05, 1.055, 1.02, 1.04, 150])
        # drop to exit
        rows.append([base + 4*3600*1000, 1.04, 1.045, 0.98, 0.99, 150])
        return rows

def test_scalping_triggers_long_and_exit():
    mock = MockScalpOHLCVClient()
    adapter = create_adapter("binance", {"client": mock})
    broker = Broker(adapter_instance=adapter)
    broker.connect()

    sm = StrategyManager()
    s = sm.register_strategy(ScalpingStrategy, params={"short_ma":3, "atr_period":3, "atr_multiplier":0.2, "max_hold_bars":3})
    sm.initialize_all(broker)
    res = sm.run_backtest(broker, "BTC/USDT", "1h", limit=10)
    assert res["status"] == "ok"
    signals = res["signals"]
    assert any(sig.get("signal") == "long" for sig in signals), f"expected a long, got {signals}"
    assert any(sig.get("signal") == "exit" for sig in signals), f"expected an exit, got {signals}"
    assert s.call_count > 0
