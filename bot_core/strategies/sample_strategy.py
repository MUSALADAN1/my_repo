# bot_core/strategies/sample_strategy.py
from typing import Dict, Any
import pandas as pd
from bot_core.strategies.plugin_base import StrategyPlugin

class MovingAverageCrossoverStrategy(StrategyPlugin):
    """
    Simple MA crossover that emits:
      - {'signal': 'long'} when short_ma > long_ma
      - {'signal': 'exit'} when short_ma crosses below long_ma
    Keeps an internal counter for unit tests to assert on_bar was called.
    """
    def __init__(self, name: str = "ma_crossover", params: Dict[str, Any] = None):
        super().__init__(name, params or {})
        self.short = int(self.params.get("short", 5))
        self.long = int(self.params.get("long", 20))
        self.call_count = 0
        self.last_signal = None

    def on_bar(self, df: pd.DataFrame):
        self.call_count += 1
        if len(df) < self.long:
            return None  # not enough data yet
        close = df['close'].astype(float)
        short_ma = close.rolling(self.short).mean().iloc[-1]
        long_ma = close.rolling(self.long).mean().iloc[-1]
        if short_ma > long_ma and self.last_signal != "long":
            self.last_signal = "long"
            return {"signal": "long", "short_ma": float(short_ma), "long_ma": float(long_ma)}
        elif short_ma < long_ma and self.last_signal == "long":
            self.last_signal = "exit"
            return {"signal": "exit", "short_ma": float(short_ma), "long_ma": float(long_ma)}
        return None

# helper factories expected by StrategyManager when importing by path
def create_strategy(params: Dict[str, Any] = None):
    return MovingAverageCrossoverStrategy("ma_crossover", params or {})
