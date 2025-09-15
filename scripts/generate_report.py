#!/usr/bin/env python3
"""
scripts/generate_report.py

Usage:
  python scripts/generate_report.py [backtest_folder]

Defaults to current working directory if no folder provided.
"""
import sys
import os

# ensure project root on sys.path so imports work
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.abspath(os.path.join(SCRIPT_DIR, ".."))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from bot_core.analytics.report import generate_html_report

def main():
    folder = sys.argv[1] if len(sys.argv) > 1 else os.getcwd()
    folder = os.path.abspath(folder)
    out = generate_html_report(folder)
    print(f"Report generated: {out}")

if __name__ == "__main__":
    main()
