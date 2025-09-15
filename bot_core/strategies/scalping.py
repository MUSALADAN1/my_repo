# bot_core/strategies/scalping.py
from typing import Dict, Any, Optional
import pandas as pd
import numpy as np

from bot_core.strategies.plugin_base import StrategyPlugin

def atr(df: pd.DataFrame, period: int = 14) -> pd.Series:
    """
    Simple ATR calculation returning a Series aligned with df index.
    df must contain columns: high, low, close
    """
    high = df['high'].astype(float)
    low = df['low'].astype(float)
    close = df['close'].astype(float)
    prev_close = close.shift(1).fillna(close.iloc[0])
    tr1 = high - low
    tr2 = (high - prev_close).abs()
    tr3 = (low - prev_close).abs()
    tr = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)
    atr_series = tr.rolling(period, min_periods=1).mean()
    return atr_series

class ScalpingStrategy(StrategyPlugin):
    """
    Simple scalping strategy for tests.
    - Uses a short moving average and ATR-based threshold to detect quick momentum bursts.
    - Emits {"signal":"long"} when momentum up + price > short_ma and not already long.
    - Emits {"signal":"exit"} when price falls below short_ma (exit) or after max_hold_bars.

    Params:
      - short_ma: int (default 3)
      - atr_period: int (default 5)
      - atr_multiplier: float (default 0.5) -> requires delta > atr * multiplier to consider momentum
      - max_hold_bars: int (default 5) -> force exit after this many bars in position
    """
    def __init__(self, name: str = "scalping", params: Dict[str, Any] = None):
        super().__init__(name, params or {})
        self.short_ma = int(self.params.get("short_ma", 3))
        self.atr_period = int(self.params.get("atr_period", 5))
        self.atr_multiplier = float(self.params.get("atr_multiplier", 0.5))
        self.max_hold_bars = int(self.params.get("max_hold_bars", 5))
        self.in_long = False
        self.hold_bars = 0
        self.call_count = 0

    def on_bar(self, df: pd.DataFrame):
        self.call_count += 1
        if len(df) < 2:
            return None

        close = df['close'].astype(float)
        prev_close = close.iloc[-2]
        curr_close = close.iloc[-1]
        short_ma = close.rolling(self.short_ma).mean().iloc[-1]
        atr_series = atr(df, self.atr_period)
        curr_atr = float(atr_series.iloc[-1]) if len(atr_series) else 0.0

        # If in position, increment hold counter and possibly exit
        if self.in_long:
            self.hold_bars += 1
            # exit if price drops below short_ma or exceeded max hold
            if curr_close < short_ma or self.hold_bars >= self.max_hold_bars:
                self.in_long = False
                self.hold_bars = 0
                return {"signal": "exit", "price": float(curr_close)}
            return None

        # detect momentum: price jump greater than threshold (delta > atr * multiplier)
        delta = curr_close - prev_close
        threshold = curr_atr * self.atr_multiplier
        if curr_close > short_ma and delta >= threshold and delta > 0:
            self.in_long = True
            self.hold_bars = 0
            return {"signal": "long", "price": float(curr_close), "delta": float(delta), "atr": float(curr_atr)}

        return None

def create_strategy(params: Dict[str, Any] = None):
    name = (params or {}).get("name", "scalping")
    return ScalpingStrategy(name, params or {})
