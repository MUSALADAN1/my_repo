# bot_core/strategies/trend_following.py
from typing import Dict, Any, Optional
import pandas as pd
import numpy as np
from bot_core.indicators import ema as central_ema, sr_zones_from_series
from bot_core.strategies.plugin_base import StrategyPlugin

class TrendFollowingStrategy(StrategyPlugin):
    """
    Simple trend-following strategy using EMA cross + momentum threshold,
    with optional S/R zone filtering to avoid entries near strong zones.

    Params (via params dict):
      - short: int (short EMA span, default 12)
      - long: int (long EMA span, default 26)
      - momentum_period: int (difference period for momentum, default 3)
      - momentum_threshold: float (min difference short_long to consider as momentum, default 0.0)
      - zone_filter: bool (enable S/R zone filtering, default False)
      - zone_margin: float (relative margin to consider 'near' a zone, default 0.001 -> 0.1%)
      - zone_lookback: int (how many bars to use to detect swings/zones, default 200)
      - min_zone_strength: float (ignore zones with strength < this, default 0.0)
      - name: optional
    """

    def __init__(self, name: str = "trend_following", params: Dict[str, Any] = None):
        super().__init__(name, params or {})
        self.short = int(self.params.get("short", 12))
        self.long = int(self.params.get("long", 26))
        self.momentum_period = int(self.params.get("momentum_period", 3))
        self.momentum_threshold = float(self.params.get("momentum_threshold", 0.0))

        # Zone filtering params (opt-in; default False to preserve existing behavior)
        self.zone_filter = bool(self.params.get("zone_filter", False))
        self.zone_margin = float(self.params.get("zone_margin", 0.001))  # relative fraction (0.001 = 0.1%)
        self.zone_lookback = int(self.params.get("zone_lookback", 200))
        self.min_zone_strength = float(self.params.get("min_zone_strength", 0.0))

        self.in_long = False
        self.call_count = 0

    def _is_near_strong_resistance(self, price: float, highs: pd.Series, lows: pd.Series) -> bool:
        """
        Return True if `price` is within `zone_margin` (relative) of any resistance zone
        whose strength >= min_zone_strength.
        """
        try:
            zones = sr_zones_from_series(highs, lows, left=3, right=3,
                                         price_tolerance=0.002, min_points=1)
        except Exception:
            # if zone detection fails for any reason, conservatively return False (do not block)
            return False

        for z in zones:
            if z.get("type") != "resistance":
                continue
            if float(z.get("strength", 0.0)) < float(self.min_zone_strength):
                continue
            center = float(z.get("center", 0.0))
            if center == 0:
                rel = abs(price - center)
            else:
                rel = abs(price - center) / float(price)
            if rel <= float(self.zone_margin):
                return True
        return False

    def _is_near_strong_support(self, price: float, highs: pd.Series, lows: pd.Series) -> bool:
        """
        Analogous check for support zones (used if implementing short filters).
        """
        try:
            zones = sr_zones_from_series(highs, lows, left=3, right=3,
                                         price_tolerance=0.002, min_points=1)
        except Exception:
            return False

        for z in zones:
            if z.get("type") != "support":
                continue
            if float(z.get("strength", 0.0)) < float(self.min_zone_strength):
                continue
            center = float(z.get("center", 0.0))
            if center == 0:
                rel = abs(price - center)
            else:
                rel = abs(price - center) / float(price)
            if rel <= float(self.zone_margin):
                return True
        return False

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
        cur_price = float(close.iloc[-1])

        # If zone filtering enabled, prepare recent highs/lows
        highs = df['high'].astype(float).iloc[-self.zone_lookback:] if 'high' in df.columns else close
        lows = df['low'].astype(float).iloc[-self.zone_lookback:] if 'low' in df.columns else close

        # basic momentum check using difference of EMAs (or could use ROC)
        if diff >= self.momentum_threshold and not self.in_long:
            # check for nearby resistance zone that would make a long entry unwise
            if self.zone_filter and self._is_near_strong_resistance(cur_price, highs, lows):
                # return explicit marker so StrategyManager can record zone-skip metrics
                return {
                    "skipped_by_zone": True,
                    "reason": "near_resistance",
                    "short_ema": cur_short,
                    "long_ema": cur_long,
                    "momentum": diff
                }

            self.in_long = True
            return {"signal": "long", "short_ema": cur_short, "long_ema": cur_long, "momentum": diff}
        if diff < 0 and self.in_long:
            self.in_long = False
            return {"signal": "exit", "short_ema": cur_short, "long_ema": cur_long, "momentum": diff}
        return None

def create_strategy(params: Dict[str, Any] = None):
    name = (params or {}).get("name", "trend_following")
    return TrendFollowingStrategy(name, params or {})
