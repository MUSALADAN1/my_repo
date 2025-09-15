# bot_core/strategies/dca_strategy.py
from typing import Dict, Any, Optional
import pandas as pd

from bot_core.strategies.plugin_base import StrategyPlugin

class DCAStrategy(StrategyPlugin):
    """
    Simple Dollar-Cost Averaging strategy plugin.

    Params:
      - interval_bars: int   -> place a buy every N bars (default 5)
      - total_steps: int     -> number of buys to perform (default 4)
      - amount_per_step: float -> nominal amount per buy (for signal metadata)
      - name: Optional[str]
    Behavior (deterministic, test-friendly):
      - Counts bars; on every Nth bar emits {"signal":"buy", "step": k, "amount": amount_per_step}
      - Stops emitting after total_steps buys.
    """
    def __init__(self, name: str = "dca_strategy", params: Dict[str, Any] = None):
        super().__init__(name, params or {})
        self.interval = int(self.params.get("interval_bars", 5))
        self.total_steps = int(self.params.get("total_steps", 4))
        self.amount_per_step = float(self.params.get("amount_per_step", 1.0))
        self.buy_count = 0
        self.bar_count = 0
        self.call_count = 0

    def on_bar(self, df: pd.DataFrame):
        self.call_count += 1
        self.bar_count += 1
        if self.buy_count >= self.total_steps:
            return None
        if self.bar_count % self.interval == 0:
            self.buy_count += 1
            return {
                "signal": "buy",
                "step": self.buy_count,
                "amount": float(self.amount_per_step),
                "bar_time": df.index[-1] if hasattr(df, 'index') and len(df) else None
            }
        return None

def create_strategy(params: Dict[str, Any] = None):
    name = (params or {}).get("name", "dca_strategy")
    return DCAStrategy(name, params or {})
