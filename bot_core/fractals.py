# bot_core/fractals.py
"""
Simple fractal detector (Bill Williams style / swing fractals).

Exports:
  - detect_fractals(df, order=2) -> List[dict]
    Each fractal dict:
      {
        "type": "bear" | "bull",
        "time": pd.Timestamp,
        "price": float,
        "index": int  # positional index in original df (optional)
      }

A "bear" fractal (swing high) occurs when the high of a bar is greater than the highs
of `order` bars on both sides. A "bull" fractal (swing low) occurs when the low of a bar
is less than the lows of `order` bars on both sides.

This implementation is intentionally simple and deterministic to make unit testing easy.
"""
from typing import List, Dict, Any
import pandas as pd
import numpy as np


def detect_fractals(df: pd.DataFrame, order: int = 2) -> List[Dict[str, Any]]:
    """
    Detect fractals in an OHLCV DataFrame.

    Parameters
    ----------
    df : pd.DataFrame
        Must contain at least "high" and "low" columns and be indexed by datetime.
    order : int
        Number of bars on each side to require for the fractal definition.

    Returns
    -------
    List[Dict[str, Any]]
        List of fractal dictionaries sorted by index ascending.
    """
    if df is None or len(df) == 0:
        return []

    if "high" not in df.columns or "low" not in df.columns:
        raise ValueError("DataFrame must contain 'high' and 'low' columns")

    highs = df["high"].values
    lows = df["low"].values
    idx = df.index

    n = len(df)
    out: List[Dict[str, Any]] = []

    # iterate skipping the edges where there isn't a full neighborhood
    for i in range(order, n - order):
        center_high = highs[i]
        center_low = lows[i]

        # skip nan centers
        if np.isnan(center_high) or np.isnan(center_low):
            continue

        left_highs = highs[i-order:i]
        right_highs = highs[i+1:i+1+order]
        left_lows = lows[i-order:i]
        right_lows = lows[i+1:i+1+order]

        # Bear (swing high): center high strictly greater than neighbors
        if center_high > np.nanmax(left_highs) and center_high > np.nanmax(right_highs):
            out.append({
                "type": "bear",
                "time": idx[i],
                "price": float(center_high),
                "index": i
            })
        # Bull (swing low): center low strictly less than neighbors
        if center_low < np.nanmin(left_lows) and center_low < np.nanmin(right_lows):
            out.append({
                "type": "bull",
                "time": idx[i],
                "price": float(center_low),
                "index": i
            })

    # Sort by index/time to be deterministic
    out_sorted = sorted(out, key=lambda x: x["index"])
    return out_sorted
