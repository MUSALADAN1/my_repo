# test_grid_strategy.py
from backend.exchanges import create_adapter
from backend.exchanges.broker import Broker
from bot_core.strategy_manager import StrategyManager
from bot_core.strategies.grid_strategy import GridTradingStrategy

class MockOHLCVClientCrossing:
    """
    Generates a short sequence of OHLCV rows specifically crafted to cross grid levels.
    Each row is [timestamp_ms, open, high, low, close, volume]
    Sequence:
      - start above grid_start
      - fall to cross multiple grid levels
      - then rise to cross upwards
    """
    def fetch_ohlcv(self, symbol, timeframe, limit):
        base = 1690000000000
        rows = []
        # Start above grid_start
        rows.append([base + 0*3600*1000, 105.0, 105.5, 104.5, 105.0, 100])
        # drop below first level (expect buy at first level)
        rows.append([base + 1*3600*1000, 103.0, 103.5, 102.5, 99.5, 100])
        # drop further cross another level
        rows.append([base + 2*3600*1000, 99.5, 99.9, 99.0, 95.0, 100])
        # rise back crossing an intermediate level -> expect sell
        rows.append([base + 3*3600*1000, 95.0, 98.0, 94.5, 100.0, 100])
        # more bars (no additional crossings)
        rows.append([base + 4*3600*1000, 100.0, 100.5, 99.5, 101.0, 100])
        return rows

def test_grid_strategy_emits_signals_on_crossing():
    mock = MockOHLCVClientCrossing()
    adapter = create_adapter("binance", {"client": mock})
    broker = Broker(adapter_instance=adapter)
    # connect to ensure adapter.client is available
    broker.connect()

    sm = StrategyManager()
    # create grid from 100 -> 80 with 5 levels: [100,95,90,85,80]
    s = sm.register_strategy(GridTradingStrategy, params={"grid_start":100,"grid_end":80,"levels":5})
    sm.initialize_all(broker)
    res = sm.run_backtest(broker, "BTC/USDT", "1h", limit=10)
    assert res["status"] == "ok"
    signals = res["signals"]
    # expect at least one buy and one sell across the sequence
    assert any(sig.get("signal") == "buy" for sig in signals), f"expected a buy signal, got {signals}"
    assert any(sig.get("signal") == "sell" for sig in signals), f"expected a sell signal, got {signals}"
    # ensure the strategy saw bars
    assert s.call_count > 0
