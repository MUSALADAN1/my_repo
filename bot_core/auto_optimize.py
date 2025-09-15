# auto_optimize.py
import yaml, pandas as pd, numpy as np
from datetime import datetime
import os, sys

def load_cfg():
    with open("config.yaml","r") as f:
        return yaml.safe_load(f)

def save_cfg(cfg):
    with open("config.yaml","w") as f:
        yaml.safe_dump(cfg, f, sort_keys=False)

def gen_grid(opt_cfg):
    """
    Build arrays of SL, TP and fib‐tolerance values.
    If the old 'sl_points'/'tp_points' keys exist, use them for a multi‐point grid.
    Otherwise fall back to the single optimized values (sl, tp, fib_tol).
    """
    # STOP‐LOSS grid
    if "sl_points" in opt_cfg:
        start, end, step = (
            opt_cfg["sl_points"]["start"],
            opt_cfg["sl_points"]["end"],
            opt_cfg["sl_points"]["step"]
        )
        sls = np.arange(start, end + step/2, step)
    else:
        sls = [opt_cfg["sl"]]

    # TAKE‐PROFIT grid
    if "tp_points" in opt_cfg:
        start, end, step = (
            opt_cfg["tp_points"]["start"],
            opt_cfg["tp_points"]["end"],
            opt_cfg["tp_points"]["step"]
        )
        tps = np.arange(start, end + step/2, step)
    else:
        tps = [opt_cfg["tp"]]

    # FIB TOLERANCE grid
    if "fib_tolerance" in opt_cfg:
        fibs = opt_cfg["fib_tolerance"]
    else:
        fibs = [opt_cfg["fib_tol"]]

    # Cartesian product of all combinations
    grid = []
    for sl in sls:
        for tp in tps:
            for fib in fibs:
                grid.append((sl, tp, fib))
    return grid


def find_best(symbol, tf, grid):
    from bot_core.intraday_trading_bot import backtest  # imported here to avoid circular import
    """
    grid: list of (sl, tp, fib_tol) tuples
    """
    results = []
    for sl, tp, fib_tol in grid:
        stats = backtest(symbol, tf, sl, tp)
        # include fib_tol in the output so we can write it back
        results.append({
            "sl":      sl,
            "tp":      tp,
            "fib_tol": fib_tol,
            **stats
        })
    df = pd.DataFrame(results)
    # now pick the row with highest win_rate, then profit_factor
    best = df.sort_values(
        ["win_rate", "profit_factor"], ascending=[False, False]
    ).iloc[0].to_dict()
    return best


def main():
    cfg = load_cfg()
    opt_ranges = cfg["optimization"]  # must have sl_points, tp_points, fib_tolerance
    tf = cfg.get("opt_timeframe","15m")
    out = {}
    for sym in cfg["symbols"]:
        print(f"→ Optimizing {sym}…")
        grid = gen_grid(opt_ranges)
        best = find_best(sym, tf, grid)
        out[sym] = best
        print(f"   • {sym} → sl={best['sl']}, tp={best['tp']}, fib_tol={best['fib_tol']}")
    cfg["optimization_per_symbol"] = out
    save_cfg(cfg)
    print("✅ config.yaml updated with per‑symbol optimal parameters.")

if __name__=="__main__":
    main()
