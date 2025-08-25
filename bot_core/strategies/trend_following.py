# bot_core/strategies/trend_following.py
from fileinput import close
from typing import Dict, Any, Optional
import pandas as pd
import numpy as np
from bot_core.indicators import ema as central_ema
from bot_core.strategies.plugin_base import StrategyPlugin

class TrendFollowingStrategy(StrategyPlugin):
    """
    Simple trend-following strategy using EMA cross + momentum threshold.

    Params (via params dict):
      - short: int (short EMA span, default 12)
      - long: int (long EMA span, default 26)
      - momentum_period: int (difference period for momentum, default 3)
      - momentum_threshold: float (min difference short_long to consider as momentum, default 0.0)
      - name: optional

    Behavior:
      - When short_ema > long_ema and (short_ema - long_ema) >= momentum_threshold => emit {"signal":"long"}
      - When short_ema < long_ema and previously in long => emit {"signal":"exit"}
      - Returns at most one signal per bar.
    """

    def __init__(self, name: str = "trend_following", params: Dict[str, Any] = None):
        super().__init__(name, params or {})
        self.short = int(self.params.get("short", 12))
        self.long = int(self.params.get("long", 26))
        self.momentum_period = int(self.params.get("momentum_period", 3))
        self.momentum_threshold = float(self.params.get("momentum_threshold", 0.0))
        self.in_long = False
        self.call_count = 0

    def on_bar(self, df: pd.DataFrame):
        self.call_count += 1
        if len(df) < self.long + self.momentum_period:
            return None

        close = df['close'].astype(float)

        # compute EMAs using central ema implementation
        short_ema = central_ema(close, self.short)
        long_ema = central_ema(close, self.long)

        # latest values
        cur_short = float(short_ema.iloc[-1])
        cur_long = float(long_ema.iloc[-1])
        diff = cur_short - cur_long


        # basic momentum check using difference of EMAs (or could use ROC)
        if diff >= self.momentum_threshold and not self.in_long:
            self.in_long = True
            return {"signal": "long", "short_ema": cur_short, "long_ema": cur_long, "momentum": diff}
        if diff < 0 and self.in_long:
            self.in_long = False
            return {"signal": "exit", "short_ema": cur_short, "long_ema": cur_long, "momentum": diff}
        return None

def create_strategy(params: Dict[str, Any] = None):
    name = (params or {}).get("name", "trend_following")
    return TrendFollowingStrategy(name, params or {})
