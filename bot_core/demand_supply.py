# bot_core/demand_supply.py
"""
Simple demand/supply zone detector.

Exports:
  - find_local_extrema(series, order=3) -> list of (idx, value, "peak"|"valley")
  - cluster_levels(levels, price_tol=0.005) -> list of clusters (center, members)
  - detect_zones_from_ohlcv(df, lookback=100, extrema_order=3, min_members=2, price_tol=0.005)
    -> list of zone dicts: { type, center, min_price, max_price, strength }

Notes:
  - This is intentionally simple and deterministic (not ML).
  - It returns zones in the same simple dict format your status server and frontend expect.
"""
from typing import List, Tuple, Dict, Any
import pandas as pd
import numpy as np


def find_local_extrema(series: pd.Series, order: int = 3) -> List[Tuple[pd.Timestamp, float, str]]:
    """
    Find local peaks (resistance) and valleys (demand) in a price series.

    - order: number of bars on each side to consider for local extremum (higher -> fewer extremas)
    - returns list of tuples (index_timestamp, price_value, "peak" or "valley")
    """
    if series is None or len(series) == 0:
        return []

    vals = series.values
    idx = series.index
    n = len(vals)
    extrema = []

    # For each point, check if it's strictly the max/min in the neighborhood
    for i in range(order, n - order):
        window = vals[i - order : i + order + 1]
        v = vals[i]
        if v == np.nan:
            continue
        # strict peak
        if v == window.max() and np.count_nonzero(window == v) == 1:
            extrema.append((idx[i], float(v), "peak"))
        # strict valley
        elif v == window.min() and np.count_nonzero(window == v) == 1:
            extrema.append((idx[i], float(v), "valley"))
    return extrema


def cluster_levels(levels: List[float], price_tol: float = 0.005) -> List[Dict[str, Any]]:
    """
    Cluster price levels (floats) into buckets using a relative tolerance.

    - price_tol is relative tolerance (e.g. 0.005 = 0.5%).
    - returns list of clusters: {"center": float, "members": [float,...]}
    """
    if not levels:
        return []

    # Sort levels
    levels_sorted = sorted(levels)
    clusters: List[List[float]] = []
    for lvl in levels_sorted:
        if not clusters:
            clusters.append([lvl])
            continue
        last = clusters[-1]
        center = sum(last) / len(last)
        # relative tolerance based on center magnitude
        tol = abs(center) * price_tol
        if abs(lvl - center) <= tol:
            last.append(lvl)
        else:
            clusters.append([lvl])

    # Turn into dicts
    out = []
    for c in clusters:
        center = sum(c) / len(c)
        out.append({"center": float(center), "members": [float(x) for x in c], "count": len(c)})
    return out


def detect_zones_from_ohlcv(
    df: pd.DataFrame,
    price_col: str = "high",
    lookback: int = 200,
    extrema_order: int = 3,
    min_members: int = 2,
    price_tol: float = 0.005,
) -> List[Dict[str, Any]]:
    """
    Detect demand (valleys) and supply (peaks) zones from an OHLCV DataFrame.

    - df: DataFrame indexed by DatetimeIndex with typical OHLCV columns.
    - price_col: which column to use for extrema detection; use 'high' for peaks, 'low' for valleys (we'll check both).
    - lookback: how many most recent bars to analyze.
    - extrema_order: neighborhood size for local extrema detection.
    - min_members: minimum cluster size to be considered a zone.
    - price_tol: relative tolerance used to group nearby levels into one zone.

    Returns list of dicts:
      {"type": "resistance"|"demand", "center": float, "min_price": float, "max_price": float, "strength": int}
    """
    if df is None or len(df) == 0:
        return []

    odf = df.copy().dropna(how="all")
    # Use the last `lookback` rows (or fewer if not available)
    odf = odf.iloc[-lookback:]

    # Prefer 'high' for peaks, 'low' for valleys, but we'll use both series
    highs = odf["high"] if "high" in odf.columns else odf["close"]
    lows = odf["low"] if "low" in odf.columns else odf["close"]

    peaks = find_local_extrema(highs, order=extrema_order)
    valleys = find_local_extrema(lows, order=extrema_order)

    peak_prices = [p for (_ts, p, kind) in peaks if kind == "peak"]
    valley_prices = [p for (_ts, p, kind) in valleys if kind == "valley"]

    # cluster peaks and valleys separately
    peak_clusters = cluster_levels(peak_prices, price_tol=price_tol)
    valley_clusters = cluster_levels(valley_prices, price_tol=price_tol)

    zones = []
    # Build zone dicts from clusters (peaks -> resistance, valleys -> demand)
    for pc in peak_clusters:
        if pc["count"] < max(1, min_members):
            continue
        center = pc["center"]
        member_prices = pc["members"]
        min_p = min(member_prices)
        max_p = max(member_prices)
        zones.append({
            "type": "resistance",
            "center": float(center),
            "min_price": float(min_p),
            "max_price": float(max_p),
            "strength": int(pc["count"])
        })

    for vc in valley_clusters:
        if vc["count"] < max(1, min_members):
            continue
        center = vc["center"]
        member_prices = vc["members"]
        min_p = min(member_prices)
        max_p = max(member_prices)
        zones.append({
            "type": "demand",
            "center": float(center),
            "min_price": float(min_p),
            "max_price": float(max_p),
            "strength": int(vc["count"])
        })

    # Sort zones by strength desc then center
    zones_sorted = sorted(zones, key=lambda z: (-z["strength"], z["center"]))
    return zones_sorted


# convenience alias used elsewhere if needed
sr_zones_from_series = detect_zones_from_ohlcv
