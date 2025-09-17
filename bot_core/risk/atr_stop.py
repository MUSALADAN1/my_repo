# bot_core/risk/atr_stop.py
from typing import Optional
import pandas as pd


def compute_atr(df: pd.DataFrame, period: int = 14) -> pd.Series:
    """
    Compute Average True Range (ATR) using simple moving average of True Range.
    Expects df with columns: ['high','low','close'] and index sorted ascending.
    Returns a pandas Series aligned with df (NaN for the first rows before ATR is available).
    """
    if not {"high", "low", "close"}.issubset(df.columns):
        raise ValueError("DataFrame must contain 'high','low','close' columns")

    high = df["high"]
    low = df["low"]
    close = df["close"]

    prev_close = close.shift(1)

    tr1 = high - low
    tr2 = (high - prev_close).abs()
    tr3 = (low - prev_close).abs()

    tr = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)
    atr = tr.rolling(window=period, min_periods=period).mean()

    return atr


def compute_static_stop(entry_price: float, atr: float, multiplier: float = 1.5, side: str = "long") -> Optional[float]:
    """
    Compute a static stop price based on ATR.
    - side: "long" or "short"
    - multiplier: how many ATRs away to place stop
    Returns stop price or None if atr is None/NaN.
    """
    try:
        if atr is None or (isinstance(atr, float) and (atr != atr)):  # check NaN
            return None
        atr_val = float(atr)
    except Exception:
        return None

    if side.lower() in ("long", "buy"):
        return float(entry_price) - multiplier * atr_val
    elif side.lower() in ("short", "sell"):
        return float(entry_price) + multiplier * atr_val
    else:
        raise ValueError("side must be 'long' or 'short'")


class TrailingStopManager:
    """
    Manage a trailing stop for a single position.
    For long positions it keeps track of the highest price seen and sets the stop
    to (highest_price - trailing_atr_mult * atr).
    For short positions it tracks the lowest price and sets the stop to
    (lowest_price + trailing_atr_mult * atr).
    """

    def __init__(self, entry_price: float, side: str = "long", trailing_atr_mult: float = 1.0):
        self.side = side.lower()
        if self.side not in ("long", "short"):
            raise ValueError("side must be 'long' or 'short'")
        self.entry_price = float(entry_price)
        self.trailing_atr_mult = float(trailing_atr_mult)
        if self.side == "long":
            self.best_price = float(entry_price)  # highest seen
        else:
            self.best_price = float(entry_price)  # lowest seen
        # last computed stop (None until an ATR sample is provided)
        self.stop_price: Optional[float] = None

    def update(self, market_price: float, atr: Optional[float]) -> Optional[float]:
        """
        Update best_price and compute new stop using provided ATR (most recent).
        Returns the new stop price (may be same as previous) or None if atr is missing.
        """
        mp = float(market_price)
        if self.side == "long":
            if mp > self.best_price:
                self.best_price = mp
            if atr is None or (isinstance(atr, float) and (atr != atr)):
                return None
            self.stop_price = self.best_price - self.trailing_atr_mult * float(atr)
            # ensure stop not above current market (optional: ensure stop <= market)
            return self.stop_price
        else:
            # short
            if mp < self.best_price:
                self.best_price = mp
            if atr is None or (isinstance(atr, float) and (atr != atr)):
                return None
            self.stop_price = self.best_price + self.trailing_atr_mult * float(atr)
            return self.stop_price

    def get_stop(self) -> Optional[float]:
        return self.stop_price
