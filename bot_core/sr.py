# bot_core/sr.py
"""
Support/Resistance helper: aggregate zones from pivots, fibonacci, fractals and demand/supply.
This is intentionally defensive — it will attempt to import available modules and fall back to
a simple heuristic zone if nothing else is available.
"""

from typing import List, Dict, Optional, Any, Callable
import math

Zone = Dict[str, Any]


def _normalize_zone(z: Dict[str, Any]) -> Optional[Zone]:
    """
    Ensure zone contains the canonical keys:
      type, center, min_price, max_price, strength
    Return None if insufficient data.
    """
    try:
        ztype = z.get("type", "zone")
        center = float(z.get("center") if z.get("center") is not None else ((z.get("min_price") + z.get("max_price")) / 2))
        min_price = float(z.get("min_price", center - 0.0))
        max_price = float(z.get("max_price", center + 0.0))
        strength = float(z.get("strength", 1.0))
        if math.isnan(center) or math.isnan(min_price) or math.isnan(max_price):
            return None
        if min_price > max_price:
            min_price, max_price = max_price, min_price
        return {"type": ztype, "center": center, "min_price": min_price, "max_price": max_price, "strength": strength}
    except Exception:
        return None


def _merge_overlap(z1: Zone, z2: Zone) -> Zone:
    """
    Merge two overlapping zones: combine ranges and sum strength.
    Type resolution: prefer exact types if equal else 'zone'.
    """
    t = z1["type"] if z1["type"] == z2["type"] else "zone"
    min_p = min(z1["min_price"], z2["min_price"])
    max_p = max(z1["max_price"], z2["max_price"])
    # center as weighted by strength
    total_strength = (z1.get("strength", 1.0) + z2.get("strength", 1.0))
    if total_strength > 0:
        center = (z1["center"] * z1.get("strength", 1.0) + z2["center"] * z2.get("strength", 1.0)) / total_strength
    else:
        center = (z1["center"] + z2["center"]) / 2.0
    return {"type": t, "center": center, "min_price": min_p, "max_price": max_p, "strength": total_strength}


def _overlap(z1: Zone, z2: Zone, tol: float = 0.0) -> bool:
    """Return True if z1 and z2 overlap or are within tol fractional distance of each other."""
    # simple numeric overlap: ranges intersect or are close
    if z1["max_price"] >= z2["min_price"] and z2["max_price"] >= z1["min_price"]:
        return True
    # allow small tolerance relative to width
    width = max(z1["max_price"] - z1["min_price"], z2["max_price"] - z2["min_price"], 1e-9)
    # center distance
    dist = abs(z1["center"] - z2["center"])
    return dist <= tol * width


def _safe_call_candidate(cand_func: Callable, *args, **kwargs):
    try:
        return cand_func(*args, **kwargs)
    except Exception:
        return None


def aggregate_zones_from_df(df, sources: Optional[List[str]] = None, tol: float = 0.003) -> List[Zone]:
    """
    Aggregate SR zones from multiple indicator modules. Returns a list of normalized zones.

    sources: list of module names to attempt in order. Known names:
      'pivots', 'fibonacci', 'fractals', 'demand_supply'
    tol: tolerance used for merging close zones (fractional).
    """
    zones: List[Zone] = []
    if sources is None:
        sources = ["pivots", "fibonacci", "fractals", "demand_supply"]

    # map module name -> list of possible callable names that produce zones
    candidate_names = {
        "pivots": ["pivots_from_df", "get_pivots", "compute_pivots", "pivot_points"],
        "fibonacci": ["fibonacci_levels", "fib_levels", "fibonacci_from_high_low"],
        "fractals": ["detect_fractals", "find_fractals"],
        "demand_supply": ["detect_zones", "find_zones", "detect_demand_supply"],
    }

    for src in sources:
        try:
            mod = __import__("bot_core." + src, fromlist=[src])
        except Exception:
            continue
        funcs = candidate_names.get(src, [])
        for fname in funcs:
                if hasattr(mod, fname):
                    func = getattr(mod, fname)
                    res = _safe_call_candidate(func, df)
                    # handle None or empty
                    if res is None:
                        continue

                    # If module returned a DataFrame (e.g. pivot table), convert rows -> zones
                    try:
                        import pandas as pd  # local import to avoid hard dependency if not needed
                    except Exception:
                        pd = None

                    if pd is not None and isinstance(res, pd.DataFrame):
                        if res.empty:
                            continue
                        # Convert pivot-like columns (P, R1, R2, S1, S2, S3, etc.) into zones
                        for _, row in res.iterrows():
                            for col in row.index:
                                try:
                                    val = row[col]
                                    if val is None or (hasattr(val, "item") and pd.isna(val)):
                                        continue
                                    v = float(val)
                                except Exception:
                                    continue
                                col_up = str(col).upper()
                                if col_up == "P":
                                    ztype = "pivot"
                                elif col_up.startswith("R"):
                                    ztype = "resistance"
                                elif col_up.startswith("S"):
                                    ztype = "support"
                                else:
                                    ztype = "zone"
                                nz = {
                                    "type": ztype,
                                    "center": v,
                                    "min_price": v * 0.999,
                                    "max_price": v * 1.001,
                                    "strength": 1.0,
                                }
                                maybe = _normalize_zone(nz)
                                if maybe:
                                    zones.append(maybe)
                        # first matching function per module consumed
                        break

                    # normalize if dict/list of dicts etc
                    if isinstance(res, dict) and "center" in res:
                        maybe = _normalize_zone(res)
                        if maybe:
                            zones.append(maybe)
                    elif isinstance(res, (list, tuple)):
                        for item in res:
                            if isinstance(item, dict):
                                nz = _normalize_zone(item)
                                if nz:
                                    # boost strength by source type heuristics
                                    if src == "demand_supply":
                                        nz["strength"] = nz.get("strength", 1.0) * 2.0
                                    elif src == "fibonacci":
                                        nz["strength"] = nz.get("strength", 1.0) * 1.5
                                    zones.append(nz)
                    # only call first matching function per module
                    break


    # if no zones found, fallback to a simple zone around latest close
    if not zones:
        try:
            last_price = None
            if hasattr(df, "close"):
                last_price = float(df["close"].iloc[-1])
            elif "close" in getattr(df, "columns", []):
                last_price = float(df["close"].iat[-1])
            if last_price is not None:
                zones.append({
                    "type": "synthetic",
                    "center": last_price,
                    "min_price": last_price * 0.999,
                    "max_price": last_price * 1.001,
                    "strength": 0.1,
                })
        except Exception:
            pass

    # merge overlapping zones
    merged: List[Zone] = []
    for z in zones:
        merged_flag = False
        for i, mz in enumerate(merged):
            if _overlap(mz, z, tol=tol):
                merged[i] = _merge_overlap(mz, z)
                merged_flag = True
                break
        if not merged_flag:
            merged.append(z)

    # sort by strength descending
    merged.sort(key=lambda x: x.get("strength", 0.0), reverse=True)
    return merged
