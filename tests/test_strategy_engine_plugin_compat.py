# tests/test_strategy_engine_plugin_compat.py
from bot_core.strategies.engine import StrategyManager
from bot_core.strategies.plugin_base import StrategyPlugin, StrategyContext

class DummyPlugin(StrategyPlugin):
    def __init__(self, name: str = "dummy_plugin", params: dict = None):
        super().__init__(name, params or {})
        self.inited = False
        self.call_count = 0

    def initialize(self, context: StrategyContext):
        super().initialize(context)
        self.inited = True

    def on_bar(self, df):
        self.call_count += 1
        return {"signal": "test", "count": self.call_count}

def test_plugin_registration_and_run():
    mgr = StrategyManager()
    p = DummyPlugin()
    # register w/o context
    mgr.register(p)
    # enable and run
    mgr.enable("dummy_plugin")
    res = mgr.run_on_bar(ohlcv={"close": 100})
    assert "dummy_plugin" in res
    assert res["dummy_plugin"]["signal"] == "test"
    # attach context and ensure initialize gets called for new registrations
    class FakeBroker: pass
    ctx = StrategyContext(broker=FakeBroker(), config={"x": 1})
    mgr.set_context(ctx)
    # register second plugin to check initialize() call path
    p2 = DummyPlugin(name="dummy2")
    mgr.register(p2)
    assert getattr(p2, "inited", False) is True
    # run again
    mgr.enable("dummy2")
    out = mgr.run_on_bar(ohlcv={"close": 101})
    assert "dummy2" in out
