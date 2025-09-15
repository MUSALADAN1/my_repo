# test_backtester.py
import pandas as pd
from backend.exchanges import create_adapter
from backend.exchanges.broker import Broker
from bot_core.strategy_manager import StrategyManager
from bot_core.strategies.plugin_base import StrategyPlugin
from bot_core.backtester import Backtester

class DeterministicSignalStrategy(StrategyPlugin):
    """
    Emits a buy at 3rd bar and an exit at 7th bar (1-based count).
    This keeps signals deterministic for the test.
    """
    def __init__(self, name="det_strategy", params=None):
        super().__init__(name, params or {})
        self.call_count = 0

    def on_bar(self, df: pd.DataFrame):
        self.call_count += 1
        # emit buy on 3rd bar
        if len(df) == 3:
            return {"signal": "buy", "amount": 100.0}
        # emit exit on 7th bar
        if len(df) == 7:
            return {"signal": "exit"}
        return None

def test_backtester_runs_and_produces_metrics(tmp_path):
    # create small synthetic OHLCV client with known closes
    class MockClient:
        def fetch_ohlcv(self, symbol, timeframe, limit):
            base = 1690000000000
            rows = []
            # 10 bars with increasing close
            for i in range(10):
                o = 100 + i
                c = o + 0.5
                rows.append([base + i*3600*1000, o, o+1, o-1, c, 100 + i])
            return rows

    client = MockClient()
    adapter = create_adapter("binance", {"client": client})
    broker = Broker(adapter_instance=adapter)
    broker.connect()

    # register strategy
    sm = StrategyManager()
    s = sm.register_strategy(DeterministicSignalStrategy)
    sm.initialize_all(broker)

    bt = Backtester(initial_balance=10000.0, fee=0.0, bars_per_year=365*24.0)
    out = bt.run(broker, sm, "BTC/USDT", "1h", limit=10, save_path=str(tmp_path))

    # basic assertions
    assert "trade_log" in out and isinstance(out["trade_log"], list)
    assert "equity" in out and hasattr(out["equity"], "iloc")
    assert "metrics" in out and isinstance(out["metrics"], dict)
    # expect at least 1 closed trade (buy at bar3, exit at bar7)
    sell_trades = [t for t in out["trade_log"] if t.get("type") == "SELL"]
    assert len(sell_trades) >= 1
    # metrics contain final_balance and total_return
    assert "final_balance" in out["metrics"] and "total_return" in out["metrics"]
