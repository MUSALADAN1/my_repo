# bot_core/strategies/grid_strategy.py
from typing import Dict, Any, List, Optional
import numpy as np
import pandas as pd

from bot_core.strategies.plugin_base import StrategyPlugin

class GridTradingStrategy(StrategyPlugin):
    """
    Grid trading strategy plugin.

    Params accepted (via params dict):
      - grid_start: float (upper price)
      - grid_end: float (lower price)
      - levels: int (number of grid levels, inclusive)
      - step: Optional[float] (alternative to levels; if provided will compute levels by step)
      - name: Optional[str] (strategy name)

    Behavior (simple, deterministic for testing):
      - Levels are computed between grid_start and grid_end (inclusive).
      - On each bar the strategy compares the previous bar close and current close:
          - If the price *crossed down* through a level (prev_close > level >= current_close) -> emit {"signal":"buy", "level": level, "price": current_close}
          - If the price *crossed up* through a level (prev_close < level <= current_close) -> emit {"signal":"sell", "level": level, "price": current_close}
      - Emits at most one signal per bar (first matching level in sorted order).
    """

    def __init__(self, name: str = "grid_strategy", params: Dict[str, Any] = None):
        super().__init__(name, params or {})
        self.grid_start: float = float(self.params.get("grid_start", 100.0))
        self.grid_end: float = float(self.params.get("grid_end", 80.0))
        self.levels_count: int = int(self.params.get("levels", 5))
        self.step: Optional[float] = self.params.get("step", None)
        self.levels: List[float] = []
        self.call_count = 0
        self._build_levels()

    def _build_levels(self):
        # If explicit step provided, compute levels by stepping down from start to end
        if self.step:
            levels = []
            p = self.grid_start
            # ensure descending
            while p >= self.grid_end:
                levels.append(round(p, 8))
                p = p - float(self.step)
            if levels[-1] != self.grid_end:
                levels.append(self.grid_end)
            self.levels = sorted(list(set(levels)), reverse=False)  # ascending
            return

        # otherwise use np.linspace to create inclusive levels_count points
        if self.levels_count <= 1:
            self.levels = [self.grid_start]
        else:
            arr = np.linspace(self.grid_start, self.grid_end, self.levels_count)
            # want ascending order for easier comparison
            self.levels = sorted([float(round(x, 8)) for x in arr], reverse=False)

    def on_bar(self, df: pd.DataFrame):
        self.call_count += 1
        # need at least two bars to detect crossing
        if len(df) < 2:
            return None

        prev_close = float(df['close'].iloc[-2])
        curr_close = float(df['close'].iloc[-1])

        # check crossing for each level (sorted ascending)
        # Detect downward cross (buy) first (prev > level >= curr), then upward (sell)
        for level in self.levels:
            # downward cross
            if prev_close > level >= curr_close:
                return {"signal": "buy", "level": float(level), "price": curr_close}
        for level in self.levels:
            # upward cross
            if prev_close < level <= curr_close:
                return {"signal": "sell", "level": float(level), "price": curr_close}

        return None

# factory helper for StrategyManager import-by-path
def create_strategy(params: Dict[str, Any] = None):
    name = (params or {}).get("name", "grid_strategy")
    return GridTradingStrategy(name, params or {})
