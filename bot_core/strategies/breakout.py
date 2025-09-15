# bot_core/strategies/breakout.py
from typing import Dict, Any, Optional
import pandas as pd
import numpy as np

from bot_core.strategies.plugin_base import StrategyPlugin

class BreakoutStrategy(StrategyPlugin):
    """
    Simple breakout strategy:
      - Computes rolling highest high and lowest low over 'lookback' bars (excluding current bar).
      - If current close > prior_high * (1 + threshold) => emit {"signal":"long"}
      - If current close < prior_low * (1 - threshold) => emit {"signal":"short"} or {"signal":"exit"} depending on design
      - Avoids repeated emits by tracking last_signal.

    Params:
      - lookback: int (number of bars to compute high/low from; default 20)
      - threshold: float (fractional threshold, e.g., 0.001 => 0.1% above high to confirm breakout)
      - momentum_bars: int (optional, require close > SMA(momentum_bars) for confirmation)
      - name: optional
    """
    def __init__(self, name: str = "breakout", params: Dict[str, Any] = None):
        super().__init__(name, params or {})
        self.lookback = int(self.params.get("lookback", 20))
        self.threshold = float(self.params.get("threshold", 0.0))
        self.momentum_bars = int(self.params.get("momentum_bars", 0))
        self.last_signal: Optional[str] = None
        self.call_count = 0

    def on_bar(self, df: pd.DataFrame):
        self.call_count += 1
        if len(df) < self.lookback + 1:
            return None

        # prior window excludes current bar
        prior = df.iloc[-(self.lookback+1):-1]
        if prior.empty:
            return None

        prior_high = float(prior['high'].max())
        prior_low = float(prior['low'].min())
        curr_close = float(df['close'].iloc[-1])

        # optional momentum confirmation using SMA
        if self.momentum_bars and len(df) >= self.momentum_bars:
            sma = df['close'].astype(float).rolling(self.momentum_bars).mean().iloc[-1]
        else:
            sma = None

        # breakout up
        if curr_close > prior_high * (1.0 + self.threshold):
            if self.last_signal != "long":
                # optional momentum check
                if sma is None or curr_close > sma:
                    self.last_signal = "long"
                    return {"signal": "long", "price": curr_close, "prior_high": prior_high}
        # breakout down
        if curr_close < prior_low * (1.0 - self.threshold):
            if self.last_signal != "short":
                if sma is None or curr_close < sma:
                    self.last_signal = "short"
                    return {"signal": "short", "price": curr_close, "prior_low": prior_low}

        return None

def create_strategy(params: Dict[str, Any] = None):
    name = (params or {}).get("name", "breakout")
    return BreakoutStrategy(name, params or {})
