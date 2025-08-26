# bot_core/elliott.py
"""
Lightweight Elliott-wave scaffolding.

Provides:
 - find_swings(close_series, left=2, right=2) -> list of (idx, price, type) where type in {"peak","trough"}
 - detect_impulse(close_series, min_swings=9) -> dict {
      "impulse": bool,
      "direction": "up"|"down"|None,
      "swings": [ { "idx": index, "price": float, "type": "peak"/"trough" }, ... ]
   }

This is intentionally conservative — a deterministic helper suitable for filtering and UX.
"""
from typing import List, Dict, Any, Optional
import pandas as pd
import numpy as np


def find_swings(close: pd.Series, left: int = 2, right: int = 2) -> List[Dict[str, Any]]:
    """
    Find simple local peaks and troughs by comparing a point to `left` previous and `right` next bars.
    Returns list of dicts: {"idx": Timestamp|int, "price": float, "type": "peak"|"trough"}
    """
    if close is None or len(close) == 0:
        return []

    prices = close.values
    idxs = close.index
    n = len(prices)
    swings = []

    for i in range(left, n - right):
        window_prev = prices[i - left : i]
        window_next = prices[i + 1 : i + 1 + right]
        val = prices[i]

        # peak: strictly greater than all neighbors
        if len(window_prev) > 0 and len(window_next) > 0:
            if val > window_prev.max() and val > window_next.max():
                swings.append({"idx": idxs[i], "price": float(val), "type": "peak", "pos": i})
            # trough: strictly less than all neighbors
            elif val < window_prev.min() and val < window_next.min():
                swings.append({"idx": idxs[i], "price": float(val), "type": "trough", "pos": i})
    return swings


def _swings_to_sequence(swings: List[Dict[str, Any]]) -> List[str]:
    """Return sequence of 'peak'/'trough' types from swings in chronological order."""
    return [s["type"] for s in sorted(swings, key=lambda s: s["pos"])]


def detect_impulse(close: pd.Series, min_swings: int = 9, left: int = 2, right: int = 2) -> Dict[str, Any]:
    """
    Naive detection of a 5-wave impulse candidate:
      - compute swings
      - require at least `min_swings` swings (9 points typical for 5 waves + corrections)
      - determine overall direction by comparing first and last swing prices
      - ensure swings alternate (peak <-> trough) predominantly

    Returns a dict:
      {
        "impulse": bool,
        "direction": "up"|"down"|None,
        "swings": [ ... ],
        "reason": str (optional)
      }
    """
    out = {"impulse": False, "direction": None, "swings": [], "reason": None}
    if close is None or len(close) < (left + right + 1):
        out["reason"] = "not_enough_bars"
        return out

    swings = find_swings(close, left=left, right=right)
    out["swings"] = swings

    if len(swings) < min_swings:
        out["reason"] = "not_enough_swings"
        return out

    # sort swings by position
    swings_sorted = sorted(swings, key=lambda s: s["pos"])
    seq = _swings_to_sequence(swings_sorted)

    # check alternation (count adjacent equal types)
    equal_adj = sum(1 for i in range(1, len(seq)) if seq[i] == seq[i - 1])
    alternation_ratio = 1.0 - (equal_adj / max(1, (len(seq) - 1)))

    # overall direction heuristic: compare first and last swing price
    first_price = swings_sorted[0]["price"]
    last_price = swings_sorted[-1]["price"]
    direction = "up" if last_price > first_price else "down" if last_price < first_price else None

    # basic acceptance criteria:
    # - alternation_ratio reasonably high (>0.6)
    # - direction exists
    # - swings count threshold met
    if alternation_ratio >= 0.6 and direction is not None:
        out["impulse"] = True
        out["direction"] = direction
        out["reason"] = "ok"
    else:
        out["impulse"] = False
        out["direction"] = direction
        out["reason"] = f"alternation_ratio={alternation_ratio:.2f}"

    return out
