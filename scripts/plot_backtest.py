#!/usr/bin/env python3
"""
scripts/plot_backtest.py

Simple CLI: given a backtest folder (where Backtester saved trade_log.csv and equity_curve.csv)
produce PNGs for equity curve and drawdown.
Usage:
  python scripts/plot_backtest.py /path/to/backtest_folder
If no arg is provided, uses current working directory.
"""

import sys
import os

# ensure project root is on sys.path so `import bot_core` works when running script directly
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))         # scripts/
PROJECT_ROOT = os.path.abspath(os.path.join(SCRIPT_DIR, ".."))  # project root
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from bot_core.analytics.plotting import plot_from_folder

def main():
    folder = sys.argv[1] if len(sys.argv) > 1 else os.getcwd()
    folder = os.path.abspath(folder)
    try:
        out = plot_from_folder(folder, out_dir=folder)
        print("Plots created:")
        for k, v in out.items():
            print(f" - {k}: {v}")
    except Exception as e:
        print("Failed to create plots:", e)
        raise

if __name__ == "__main__":
    main()
