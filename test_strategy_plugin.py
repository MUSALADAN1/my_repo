# test_strategy_plugin.py
import pandas as pd
from backend.exchanges import create_adapter
from bot_core.strategy_manager import StrategyManager
from bot_core.strategies.sample_strategy import MovingAverageCrossoverStrategy

class MockOHLCVClient:
    # returns 30 bars of synthetic increasing close prices
    def fetch_ohlcv(self, symbol, timeframe, limit):
        base = 1690000000000
        rows = []
        for i in range(30):
            # timestamp, open, high, low, close, volume
            o = 1.0 + i*0.01
            c = o + 0.005
            rows.append([base + i*3600*1000, o, o+0.01, o-0.01, c, 100 + i])
        return rows

def test_strategy_manager_backtest_runs_and_emits_signals():
    mock = MockOHLCVClient()
    broker = create_adapter("binance", {"client": mock})
    # Wrap with Broker via factory to use fetch_ohlcv delegation
    from backend.exchanges.broker import Broker
    b = Broker(adapter_instance=broker)

    # IMPORTANT: connect the broker so adapter.client is set from config
    b.connect()

    sm = StrategyManager()
    # register by class
    s = sm.register_strategy(MovingAverageCrossoverStrategy, params={"short":3, "long":8})
    sm.initialize_all(b)
    result = sm.run_backtest(b, "BTC/USDT", "1h", limit=30)
    assert result["status"] == "ok"
    # Expect at least one signal (with steadily increasing prices, short MA crosses long eventually)
    assert isinstance(result["signals"], list)
    assert len(result["signals"]) >= 1
    # ensure the strategy recorded on_bar calls
    assert s.call_count > 0
