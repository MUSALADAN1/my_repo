# test_options_strategy.py
from backend.exchanges import create_adapter
from backend.exchanges.broker import Broker
from bot_core.strategy_manager import StrategyManager
from bot_core.strategies.options_strategy import OptionsStrategy

class MockRisingOHLCVClient:
    """
    Produce steadily rising close prices so call option delta increases above threshold.
    Rows: [timestamp_ms, open, high, low, close, volume]
    """
    def fetch_ohlcv(self, symbol, timeframe, limit):
        base = 1690000000000
        rows = []
        # start below strike and increase above strike halfway
        for i in range(30):
            close = 90.0 + i * 1.0  # from 90 -> 119
            o = close - 0.5
            h = close + 0.5
            l = close - 0.9
            rows.append([base + i*3600*1000, o, h, l, close, 100 + i])
        return rows

def test_options_strategy_emits_buy_option_signal():
    mock = MockRisingOHLCVClient()
    adapter = create_adapter("binance", {"client": mock})
    broker = Broker(adapter_instance=adapter)
    broker.connect()

    sm = StrategyManager()
    # strike at 100, expiry 30 bars, vol moderate. Threshold 0.6 -> expect buy when spot sufficiently > strike
    s = sm.register_strategy(OptionsStrategy, params={
        "option_type": "call",
        "strike": 100.0,
        "expiry_bars": 30,
        "vol": 0.2,
        "delta_threshold": 0.6,
        # bars_per_year reduce so T not tiny; keep default for hourly fine
        "bars_per_year": 365.0 * 24.0
    })
    sm.initialize_all(broker)
    res = sm.run_backtest(broker, "BTC/USDT", "1h", limit=30)
    assert res["status"] == "ok"
    signals = [sig for sig in res["signals"] if sig.get("signal") == "buy_option"]
    assert len(signals) >= 1, f"expected at least one buy_option signal, got {res['signals']}"
    assert s.call_count > 0
