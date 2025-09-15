# test_dca_strategy.py
from backend.exchanges import create_adapter
from backend.exchanges.broker import Broker
from bot_core.strategy_manager import StrategyManager
from bot_core.strategies.dca_strategy import DCAStrategy

class MockOHLCVClientSeq:
    """
    Produces a sequence of 20 bars (timestamp, open, high, low, close, volume).
    Enough to trigger DCA buys at a few intervals.
    """
    def fetch_ohlcv(self, symbol, timeframe, limit):
        base = 1690000000000
        rows = []
        for i in range(20):
            o = 1.0 + i*0.01
            c = o + 0.005
            rows.append([base + i*3600*1000, o, o+0.01, o-0.01, c, 100 + i])
        return rows

def test_dca_strategy_emits_expected_number_of_buys():
    mock = MockOHLCVClientSeq()
    adapter = create_adapter("binance", {"client": mock})
    broker = Broker(adapter_instance=adapter)
    broker.connect()

    sm = StrategyManager()
    # interval=3 -> buys at bar 3,6,9,...; total_steps=4 -> expect 4 buys
    s = sm.register_strategy(DCAStrategy, params={"interval_bars": 3, "total_steps": 4, "amount_per_step": 2.5})
    sm.initialize_all(broker)
    res = sm.run_backtest(broker, "BTC/USDT", "1h", limit=20)
    assert res["status"] == "ok"
    signals = [sig for sig in res["signals"] if sig.get("signal") == "buy"]
    assert len(signals) == 4, f"expected 4 buy signals, got {len(signals)}: {signals}"
    assert s.call_count > 0
