"""
Fibonacci retracement & extension utilities.

Functions:
- retracement_levels(high, low, levels=...): returns dict[level -> price]
- extension_levels(high, low, levels=...): returns dict[level -> price]
- levels_from_series(high_series, low_series, take_last=True): convenience for pandas Series

The implementation handles both increasing and decreasing directions
(i.e. high may be greater than low or vice-versa).
"""

from typing import Iterable, Dict, Sequence, Union, Tuple
import math

Number = Union[int, float]


DEFAULT_RETRACEMENT_LEVELS: Sequence[float] = (0.236, 0.382, 0.5, 0.618, 0.764)
DEFAULT_EXTENSION_LEVELS: Sequence[float] = (0.382, 0.618, 1.0, 1.382, 1.618)


def _normalize_points(high: Number, low: Number) -> Tuple[Number, Number, Number]:
    """
    Return (top, bottom, diff) where top >= bottom.
    """
    if math.isnan(high) or math.isnan(low):
        raise ValueError("high and low must be numbers (not NaN).")
    top = max(high, low)
    bottom = min(high, low)
    diff = top - bottom
    return top, bottom, diff


def retracement_levels(
    high: Number,
    low: Number,
    levels: Iterable[float] = DEFAULT_RETRACEMENT_LEVELS,
) -> Dict[float, float]:
    """
    Given a swing high and swing low, compute retracement price levels.

    For a typical upward swing (low -> high), retracement price at level L is:
        price = high - (high - low) * L

    For a downward swing (high -> low), same formula works after normalization.

    Returns a dict mapping level (e.g. 0.382) -> price (float).
    """
    top, bottom, diff = _normalize_points(high, low)
    # For both directions we compute the retracement prices relative to top->bottom.
    result: Dict[float, float] = {}
    for L in levels:
        price = top - diff * L
        result[float(L)] = float(price)
    return result


def extension_levels(
    high: Number,
    low: Number,
    levels: Iterable[float] = DEFAULT_EXTENSION_LEVELS,
) -> Dict[float, float]:
    """
    Given a swing high and swing low, compute extension price levels.

    Extensions assume the move from bottom -> top defines the base distance `diff`.
    An extension level E price is:
        extension_price = top + diff * E

    For the opposite direction, normalization ensures consistent output.

    Returns dict mapping level -> price.
    """
    top, bottom, diff = _normalize_points(high, low)
    result: Dict[float, float] = {}
    for E in levels:
        price = top + diff * E
        result[float(E)] = float(price)
    return result


def levels_from_series(
    high_series,
    low_series,
    *,
    take_last: bool = True,
    retr_levels: Iterable[float] = DEFAULT_RETRACEMENT_LEVELS,
    ext_levels: Iterable[float] = DEFAULT_EXTENSION_LEVELS,
) -> Dict[str, Dict[float, float]]:
    """
    Convenience wrapper that accepts pandas Series or sequences of highs/lows.
    If take_last=True (default) it uses the last values of the series to compute levels.

    Returns:
      {
        "retracements": {level: price, ...},
        "extensions": {level: price, ...},
        "high": float(high_val),
        "low": float(low_val)
      }
    """
    try:
        # duck-typing: support pandas Series or plain sequences
        high_val = float(high_series.iloc[-1]) if hasattr(high_series, "iloc") else float(high_series[-1])
        low_val = float(low_series.iloc[-1]) if hasattr(low_series, "iloc") else float(low_series[-1])
    except Exception as e:
        raise ValueError("Could not extract last high/low from provided series") from e

    retr = retracement_levels(high_val, low_val, retr_levels)
    ext = extension_levels(high_val, low_val, ext_levels)
    return {"retracements": retr, "extensions": ext, "high": float(high_val), "low": float(low_val)}
