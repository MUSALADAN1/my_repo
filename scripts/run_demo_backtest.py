#!/usr/bin/env python3
"""
scripts/run_demo_backtest.py

Demo runner that:
 - creates synthetic OHLCV data,
 - plugs it into the Broker via a mock client,
 - registers a few strategies with StrategyManager,
 - runs a backtest feed,
 - logs signals and (simulated) orders to CSV.

Safe: no network calls, uses existing adapter/placeholders.
"""

import os
import sys
import csv
import json
from datetime import datetime, timezone, timedelta

# ensure project root is on sys.path so `import backend` works when running script directly
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))         # scripts/
PROJECT_ROOT = os.path.abspath(os.path.join(SCRIPT_DIR, ".."))  # project root
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

import pandas as pd
from backend.exchanges import create_adapter
from backend.exchanges.broker import Broker
from bot_core.strategy_manager import StrategyManager

# Backtester + RiskManager
from bot_core.backtester import Backtester
from bot_core.risk.risk_manager import RiskManager

# Import strategies you added earlier
from bot_core.strategies.sample_strategy import MovingAverageCrossoverStrategy
from bot_core.strategies.grid_strategy import GridTradingStrategy
from bot_core.strategies.dca_strategy import DCAStrategy


# ---------- Config ----------
SYMBOL = "BTC/USDT"
TIMEFRAME = "1h"   # our mock client accepts any string for timeframe
NBARS = 200        # number of synthetic bars
OUT_SIGNALS = "demo_signals.csv"
OUT_ORDERS = "demo_orders.csv"

# ---------- Synthetic OHLCV generator ----------
class SyntheticOHLCVClient:
    """
    Produces NBARS synthetic OHLCV rows:
      [timestamp_ms, open, high, low, close, volume]
    Simple sinusoidal + trend + noise pattern so strategies produce some signals.
    """
    def __init__(self, nbars=NBARS, start_price=100.0):
        self.nbars = nbars
        self.start_price = start_price

    def fetch_ohlcv(self, symbol, timeframe, limit):
        import math, random
        base_ts = int(datetime.now(timezone.utc).timestamp() * 1000) - (self.nbars * 3600 * 1000)
        rows = []
        price = self.start_price
        for i in range(self.nbars):
            # a slow uptrend + sinusoidal wave + small noise
            trend = 0.02 * i / max(1, self.nbars)        # small drift
            wave = math.sin(i * 0.12) * 1.5
            noise = (random.random() - 0.5) * 0.6
            open_p = price + trend + wave * 0.2 + noise * 0.2
            high_p = open_p + abs(wave) * 0.6 + 0.2
            low_p = open_p - abs(wave) * 0.6 - 0.2
            close_p = open_p + wave * 0.1 + (random.random() - 0.5) * 0.3
            vol = 100 + int(abs(wave) * 50 + random.random() * 20)
            ts = base_ts + i * 3600 * 1000  # hourly bars
            rows.append([ts, round(open_p, 6), round(high_p, 6), round(low_p, 6), round(close_p, 6), vol])
            price = close_p  # next open evolves from close
        # return last `limit` bars
        return rows[-limit:]

# ---------- Demo runner ----------
def run_demo():
    # prepare client + adapter + broker
    client = SyntheticOHLCVClient(nbars=NBARS, start_price=100.0)
    adapter = create_adapter("binance", {"client": client})
    broker = Broker(adapter_instance=adapter)
    broker.connect()

    # prepare strategy manager and register three strategies
    sm = StrategyManager()
    sm.register_strategy(MovingAverageCrossoverStrategy, params={"short":5, "long":20})
    sm.register_strategy(GridTradingStrategy, params={"grid_start":110.0, "grid_end":80.0, "levels":6})
    sm.register_strategy(DCAStrategy, params={"interval_bars": 30, "total_steps": 3, "amount_per_step": 1.0})
    sm.initialize_all(broker)

    print("Running demo backtest (using Backtester + RiskManager)...")
    # create Backtester and RiskManager (example parameters)
    bt = Backtester(initial_balance=10000.0, fee=0.0, bars_per_year=365*24.0)
    rm = RiskManager(max_concurrent_deals=2, trailing_stop_pct=0.03, drawdown_alert_pct=0.2)

    # run backtest and save results into demo_results/
    save_dir = os.path.join(os.getcwd(), "demo_results")
    result = bt.run(broker, sm, SYMBOL, TIMEFRAME, limit=NBARS, save_path=save_dir, risk_manager=rm)

    # Keep a simple raw signals CSV for quick inspection (optional)
    try:
        raw_res = sm.run_backtest(broker, SYMBOL, TIMEFRAME, limit=NBARS)
        raw_signals = raw_res.get("signals", [])
    except Exception:
        raw_signals = []

    signals_path = os.path.join(os.getcwd(), OUT_SIGNALS)
    if raw_signals:
        keys = set()
        for s in raw_signals:
            keys.update(s.keys())
        keys = sorted(list(keys))
        with open(signals_path, "w", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=keys)
            writer.writeheader()
            for s in raw_signals:
                row = dict(s)
                if "bar_time" in row and not isinstance(row["bar_time"], str):
                    row["bar_time"] = str(row["bar_time"])
                writer.writerow(row)
        print(f"Signals saved to {signals_path}")
    else:
        print("No raw signals to save (or none returned).")

    # Print summary of backtest outputs
    trade_log = result.get("trade_log", [])
    equity = result.get("equity", None)
    metrics = result.get("metrics", {})

    print(f"Backtest trade count: {len(trade_log)}")
    print(f"Backtest metrics: {metrics}")
    print(f"Equity series points: {len(equity) if equity is not None else 0}")

    print(f"Backtest artifacts saved to: {save_dir}")
    print("Demo finished. Inspect demo_results/trade_log.csv, equity_curve.csv, metrics.json")


if __name__ == "__main__":
    run_demo()
