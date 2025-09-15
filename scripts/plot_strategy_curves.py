#!/usr/bin/env python3
# scripts/plot_strategy_curves.py
"""
Wrapper script to call strategy_curves on a backtest folder.

Usage:
  python scripts/plot_strategy_curves.py demo_results

This script ensures the project root is on sys.path so imports like
`from bot_core.analytics.strategy_curves import ...` work when run directly.
"""
import os
import sys

# --- ensure project root on sys.path (same pattern as other scripts) ---
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))         # scripts/
PROJECT_ROOT = os.path.abspath(os.path.join(SCRIPT_DIR, ".."))  # project root
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

# now normal imports
from bot_core.analytics.strategy_curves import compute_strategy_cum_pnl_series, plot_strategy_curves
import pandas as pd

def main():
    folder = sys.argv[1] if len(sys.argv) > 1 else "demo_results"
    folder = os.path.abspath(folder)
    trade_csv = os.path.join(folder, "trade_log.csv")
    equity_csv = os.path.join(folder, "equity_curve.csv")

    if not os.path.exists(trade_csv) or not os.path.exists(equity_csv):
        print("Missing trade_log.csv or equity_curve.csv in", folder)
        sys.exit(1)

    trades = pd.read_csv(trade_csv, parse_dates=["time"]).to_dict(orient="records")
    # read equity curve CSV (index col 0)
    eq = pd.read_csv(equity_csv, index_col=0, parse_dates=True)
    idx = pd.DatetimeIndex(eq.index)
    sdict = compute_strategy_cum_pnl_series(trades, idx)
    saved = plot_strategy_curves(sdict, folder)
    print("Saved plots:", saved)

if __name__ == "__main__":
    main()
