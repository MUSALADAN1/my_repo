# test_backtest_ma_macd_stoch_mt5.py
"""
Backtest using adapter-backed historical candles and the ma_macd_stoch strategy.
Saves simple trade log and prints final summary.

This file uses backend/exchanges factory -> mt5 adapter so it does not import MetaTrader5 at module import time.
Set USE_MT5 = True and appropriate config if you want to run against a real MT5 terminal.
"""

import pandas as pd
import time
from datetime import datetime, timezone
from bot_core.strategies.ma_macd_stoch import signal_from_df

# Use adapter factory so we can swap exchanges / avoid import-time MT5 init
from backend.exchanges import create_adapter

# ---------- Config (change when running locally) ----------
SYMBOL = "EURUSD"           # change to the symbol available in your MT5 (e.g., EURUSD, GBPUSD)
# TIMEFRAME value semantics depend on the adapter. For MT5, it would be mt5.TIMEFRAME_H1.
# To keep this file import-safe, the concrete timeframe constant is resolved at runtime below.
N_BARS = 500                # how many recent bars to request

# When False, this script will not attempt to initialize a real MT5 terminal on import.
# Set True and provide terminal_path/use_mt5 in config below to run against MT5.
USE_MT5 = False

def run_backtest_from_df(df: pd.DataFrame):
    """
    Run the existing backtest logic using a DataFrame with index=datetime and columns: open, high, low, close, volume(optional).
    This function keeps the backtest logic separate from data acquisition.
    """
    # Basic example backtest loop that calls signal_from_df (your strategy)
    INITIAL_BALANCE = 10000.0
    balance = INITIAL_BALANCE
    position = None
    entry_price = 0.0
    entry_index = None
    trade_log = []

    # ensure we have datetime index and required columns
    if df.empty:
        print("No data provided to backtest.")
        return

    for i in range(20, len(df)):
        window_df = df.iloc[: i+1].copy()
        sig = signal_from_df(window_df)

        # example: open a trade when signal says 'long' or 'short' (your strategy handles details)
        if sig.get("signal") == "long" and position is None:
            entry_price = window_df['close'].iloc[-1]
            entry_index = window_df.index[-1]
            position = "long"
            trade_log.append({'type': 'BUY', 'time': entry_index, 'price': entry_price})
            print(f"[{entry_index}] BUY at {entry_price:.5f}")
        elif sig.get("signal") == "exit" and position == "long":
            exit_price = window_df['close'].iloc[-1]
            pnl = (exit_price - entry_price) / entry_price * balance * 0.1
            balance += pnl
            trade_log.append({'type': 'SELL', 'time': window_df.index[-1], 'price': exit_price, 'pnl': pnl})
            print(f"[{window_df.index[-1]}] SELL at {exit_price:.5f} PnL={pnl:.2f} NewBal={balance:.2f}")
            position = None
            entry_price = 0.0
            entry_index = None

    # Summary
    print("\n📊 BACKTEST SUMMARY")
    print("Initial balance:", INITIAL_BALANCE)
    print("Final balance:", round(balance, 2))
    print("Number of trades:", len([t for t in trade_log if t['type'] in ('BUY','SELL','STOP')])//2 if len(trade_log)>1 else 0)
    # Save trade log CSV
    pd.DataFrame(trade_log).to_csv("backtest_trade_log_mt5.csv", index=False)
    print("Trade log saved to backtest_trade_log_mt5.csv")


if __name__ == "__main__":
    # Create adapter at runtime so imports are safe during pytest collection
    adapter_config = {}
    if USE_MT5:
        adapter_config.update({"use_mt5": True, "terminal_path": None})  # set terminal_path if needed

    adapter = create_adapter("mt5", adapter_config)
    ok = adapter.connect()
    if not ok:
        raise SystemExit("Adapter failed to connect. Check config / MT5 terminal.")

    # NOTE: timeframe constant must be provided correctly for MT5. If using MT5, adapter.fetch_ohlcv expects MT5 timeframe constants.
    # For a portable script you can add a mapping or pass the raw constant. Example for MT5 H1: mt5.TIMEFRAME_H1
    # Here we assume the adapter knows how to interpret the timeframe variable passed below for your local run.
    timeframe = adapter.config.get("timeframe", None)  # adapter-specific
    df = adapter.fetch_ohlcv(SYMBOL, timeframe, limit=N_BARS)

    # If the adapter returned a ccxt-like DataFrame, ensure index is datetime
    if not df.empty and 'open' in df.columns:
        run_backtest_from_df(df)
    else:
        print("No OHLCV data fetched. Set USE_MT5=True and proper config to run against MT5, or pass a client with fetch_ohlcv.")
