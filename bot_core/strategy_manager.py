# bot_core/strategy_manager.py
from typing import List, Dict, Any, Optional, Union, Type
import importlib
import pandas as pd
import copy

from bot_core.strategies.plugin_base import StrategyPlugin, StrategyContext

class StrategyManagerError(Exception):
    pass

class StrategyManager:
    """
    Loads and manages multiple StrategyPlugin instances.

    - register_strategy: accepts a StrategyPlugin subclass, an instance, or module path string.
    - initialize_all(broker): calls initialize(context) for each strategy.
    - run_backtest(broker, symbol, timeframe, limit): simple sequential feeder that
       fetches OHLCV from broker.fetch_ohlcv() and calls on_bar for each strategy with the cumulative DataFrame.
    """

    def __init__(self):
        self.strategies: List[StrategyPlugin] = []
        # in-memory metrics snapshot updated by runs
        self.last_metrics: Dict[str, Any] = {
            "signals_skipped_by_zone": 0,
            "signals_skipped_by_zone_by_strategy": {}
        }

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

    def _is_skip_signal(self, res: Dict[str, Any]) -> bool:
        """
        Heuristic to identify an explicit 'skip' marker returned by strategies.
        Recognizes:
         - res.get('skip') is truthy
         - res.get('skipped') is truthy
         - res.get('signal') == 'skip'
         - res.get('reason') contains 'resistance'/'support'/'skip'
        """
        if not isinstance(res, dict):
            return False
        if res.get("skip") or res.get("skipped"):
            return True
        if res.get("signal") == "skip":
            return True
        reason = res.get("reason")
        if isinstance(reason, str):
            reason_l = reason.lower()
            if "resistance" in reason_l or "support" in reason_l or "skip" in reason_l:
                return True
        return False

    def _record_zone_skip(self, strategy_name: str):
        self.last_metrics.setdefault("signals_skipped_by_zone", 0)
        self.last_metrics["signals_skipped_by_zone"] += 1
        by_strat = self.last_metrics.setdefault("signals_skipped_by_zone_by_strategy", {})
        by_strat[strategy_name] = by_strat.get(strategy_name, 0) + 1

    def run_backtest(self, broker, symbol: str, timeframe: Any, limit: int = 500):
        """
        Very small deterministic backtest runner:
        - fetches OHLCV DataFrame from broker.fetch_ohlcv()
        - iterates rows in chronological order, building a cumulative df slice,
          and calls each strategy.on_bar(cumulative_df)
        - collects (and returns) signals emitted by strategies (if any)

        While running, updates self.last_metrics with skip counters (zone-filtered signals).
        """
        df = broker.fetch_ohlcv(symbol, timeframe, limit=limit)
        if df is None or df.empty:
            return {"status": "no_data", "signals": [], "metrics": copy.deepcopy(self.last_metrics)}

        # reset metrics for this run (we keep last_metrics as last snapshot)
        self.last_metrics["signals_skipped_by_zone"] = 0
        self.last_metrics["signals_skipped_by_zone_by_strategy"] = {}

        signals = []
        # ensure df is sorted ascending by index
        df = df.sort_index()

        for i in range(1, len(df)+1):
            window = df.iloc[:i].copy()
            for s in self.strategies:
                try:
                    res = s.on_bar(window)
                    if isinstance(res, dict) and res:
                        # detect skip signals (zone filtering or other skip markers)
                        if self._is_skip_signal(res):
                            # increment metrics but still keep a small record for visibility
                            strat_name = getattr(s, "name", s.__class__.__name__)
                            self._record_zone_skip(strat_name)
                            res_meta = dict(res)
                            res_meta.setdefault("strategy", strat_name)
                            res_meta.setdefault("bar_time", window.index[-1])
                            # indicate a skip marker so consumers can treat specially
                            res_meta["skipped"] = True
                            signals.append(res_meta)
                            # optional hook
                            try:
                                s.on_signal(res_meta)
                            except Exception:
                                # ignore errors from on_signal hooks
                                pass
                            # do not treat as a normal trading signal
                            continue

                        # normal signal path
                        res_meta = dict(res)
                        res_meta.setdefault("strategy", getattr(s, "name", s.__class__.__name__))
                        res_meta.setdefault("bar_time", window.index[-1])
                        signals.append(res_meta)
                        # optional hook
                        try:
                            s.on_signal(res_meta)
                        except Exception:
                            pass
                except Exception as e:
                    # do not stop other strategies; simply collect error info
                    signals.append({"strategy": getattr(s, "name", s.__class__.__name__), "error": str(e)})

        return {"status": "ok", "signals": signals, "metrics": copy.deepcopy(self.last_metrics)}

    def get_metrics_snapshot(self) -> Dict[str, Any]:
        """
        Return a shallow copy of the last metrics snapshot. Safe for external callers
        (e.g., status server) to include in API responses.
        """
        return copy.deepcopy(self.last_metrics or {})
