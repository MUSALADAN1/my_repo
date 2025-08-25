# bot_core/strategy_manager.py
from typing import List, Dict, Any, Optional, Union, Type
import importlib
import pandas as pd

from bot_core.strategies.plugin_base import StrategyPlugin, StrategyContext

class StrategyManagerError(Exception):
    pass

class StrategyManager:
    """
    Loads and manages multiple StrategyPlugin instances.

    - register_strategy: accepts a StrategyPlugin subclass, an instance, or module path string.
    - initialize_all(broker): calls initialize(context) for each strategy.
    - run_backtest(broker, symbol, timeframe, limit): simple sequential feeder that
       fetches OHLCV from broker and calls on_bar for each strategy with the cumulative DataFrame.
    """

    def __init__(self):
        self.strategies: List[StrategyPlugin] = []

    def _import_from_path(self, path: str):
        """
        Import a module path like 'bot_core.strategies.sample_strategy' and return module.
        """
        mod = importlib.import_module(path)
        return mod

    def register_strategy(self, strategy_ref: Union[str, Type[StrategyPlugin], StrategyPlugin], params: Optional[Dict[str, Any]] = None):
        """
        strategy_ref can be:
         - module path string (import path) which must expose `StrategyClass` or `create_strategy`
         - a StrategyPlugin subclass (class object)
         - an already instantiated StrategyPlugin

        params: passed into constructor as params dict for class instantiation
        """
        params = params or {}
        if isinstance(strategy_ref, str):
            mod = self._import_from_path(strategy_ref)
            # prefer explicit factory `create_strategy` then `StrategyClass`
            if hasattr(mod, "create_strategy"):
                inst = mod.create_strategy(params)
            elif hasattr(mod, "StrategyClass"):
                cls = getattr(mod, "StrategyClass")
                inst = cls(params.get("name", cls.__name__), params)
            else:
                raise StrategyManagerError(f"Module {strategy_ref} must expose create_strategy() or StrategyClass")
        elif isinstance(strategy_ref, type) and issubclass(strategy_ref, StrategyPlugin):
            inst = strategy_ref(strategy_ref.__name__, params)
        elif isinstance(strategy_ref, StrategyPlugin):
            inst = strategy_ref
        else:
            raise StrategyManagerError("Unsupported strategy_ref type")

        self.strategies.append(inst)
        return inst

    def initialize_all(self, broker, global_params: Optional[Dict[str, Any]] = None):
        ctx = StrategyContext(broker, global_params or {})
        for s in self.strategies:
            s.initialize(ctx)

    def run_backtest(self, broker, symbol: str, timeframe: Any, limit: int = 500):
        """
        Very small deterministic backtest runner:
        - fetches OHLCV DataFrame from broker.fetch_ohlcv()
        - iterates rows in chronological order, building a cumulative df slice,
          and calls each strategy.on_bar(cumulative_df)
        - collects (and returns) signals emitted by strategies (if any)
        - collects metrics: signals_skipped_by_zone and per-strategy counts
        """
        df = broker.fetch_ohlcv(symbol, timeframe, limit=limit)
        if df is None or df.empty:
            return {"status": "no_data", "signals": [], "metrics": {}}

        signals = []
        metrics: Dict[str, Any] = {
            "signals_skipped_by_zone": 0,
            "signals_skipped_by_zone_by_strategy": {}
        }

        # ensure df is sorted ascending by index
        df = df.sort_index()

        for i in range(1, len(df)+1):
            window = df.iloc[:i].copy()
            for s in self.strategies:
                try:
                    res = s.on_bar(window)
                    # If a strategy returns an explicit "skipped_by_zone" marker (dict),
                    # record metrics and also append an annotated entry to signals for visibility.
                    if isinstance(res, dict) and res.get("skipped_by_zone"):
                        res_meta = dict(res)
                        res_meta.setdefault("strategy", s.name)
                        res_meta.setdefault("bar_time", window.index[-1])
                        res_meta.setdefault("skipped", True)
                        signals.append(res_meta)
                        # increment global and per-strategy counters
                        metrics["signals_skipped_by_zone"] += 1
                        metrics["signals_skipped_by_zone_by_strategy"].setdefault(s.name, 0)
                        metrics["signals_skipped_by_zone_by_strategy"][s.name] += 1
                        # optional hook (strategy-level)
                        try:
                            s.on_signal(res_meta)
                        except Exception:
                            pass
                        # continue to next strategy
                        continue

                    # Normal signal handling
                    if isinstance(res, dict) and res:
                        res_meta = dict(res)
                        res_meta.setdefault("strategy", s.name)
                        res_meta.setdefault("bar_time", window.index[-1])
                        signals.append(res_meta)
                        try:
                            s.on_signal(res_meta)
                        except Exception:
                            pass
                except Exception as e:
                    # do not stop other strategies; simply collect error info
                    signals.append({"strategy": s.name, "error": str(e)})

        return {"status": "ok", "signals": signals, "metrics": metrics}
