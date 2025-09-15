# bot_core/analytics/plotting.py
"""
Plotting helpers for backtest results.

Functions:
 - plot_equity_curve(equity_series, trade_log=None, outpath="equity_curve.png", show=False)
 - load_equity_csv(path) -> pd.Series
 - load_trade_log_csv(path) -> list(dict)
 - plot_from_folder(folder, out_dir=None)

Notes:
 - Uses matplotlib; each chart is a separate figure.
 - Does not set explicit colors/styles (uses matplotlib defaults).
"""

from typing import Optional, List, Dict
import os
import pandas as pd
import matplotlib.pyplot as plt

def load_equity_csv(path: str) -> pd.Series:
    """
    Load equity CSV created by the Backtester (index is datetime).
    Expects a CSV with first column index or a column named 'equity'.
    """
    df = pd.read_csv(path, index_col=0, parse_dates=True)
    # if the CSV contains a single column named 'equity' or unnamed, return that series
    if "equity" in df.columns:
        return df["equity"].astype(float)
    # otherwise, take the first numeric column
    first_col = df.columns[0]
    return df[first_col].astype(float)

def load_trade_log_csv(path: str) -> List[Dict]:
    """
    Load trade_log CSV; returns a list of dicts with 'type' and 'time' and 'price' keys where present.
    """
    df = pd.read_csv(path, parse_dates=["time"])
    records = df.to_dict(orient="records")
    return records

def plot_equity_curve(equity_series: pd.Series, trade_log: Optional[List[Dict]] = None,
                      outpath: str = "equity_curve.png", show: bool = False) -> str:
    """
    Plot equity curve and mark trades from trade_log (if provided).
    - equity_series: pd.Series indexed by datetime
    - trade_log: list of trade dicts with at least keys 'type' and 'time' (and 'price' optional)
    - Writes PNG to outpath and returns outpath
    """
    if equity_series is None or equity_series.empty:
        raise ValueError("Empty equity series")

    fig, ax = plt.subplots(figsize=(10, 5))
    equity_series.plot(ax=ax, title="Equity Curve", grid=True)
    ax.set_ylabel("Equity")

    # Plot trade markers
    if trade_log:
        buys_x = []
        buys_y = []
        sells_x = []
        sells_y = []
        for t in trade_log:
            ttype = (t.get("type") or "").upper()
            ttime = t.get("time")
            # ensure ttime is pd.Timestamp
            try:
                tstamp = pd.to_datetime(ttime)
            except Exception:
                continue

            # find nearest index in equity_series (pad/backfill to previous bar)
            try:
                if tstamp in equity_series.index:
                    price_val = equity_series.loc[tstamp]
                else:
                    pos = equity_series.index.get_indexer([tstamp], method="pad")
                    if pos[0] == -1:
                        # skip if before start
                        continue
                    price_val = equity_series.iloc[pos[0]]
            except Exception:
                # defensive: skip this trade marker if anything odd happens
                continue

            # coerce price_val to a scalar float (handles Series, numpy arrays, lists, etc.)
            try:
                if hasattr(price_val, "iloc"):
                    # pandas Series or DataFrame row -> take last value
                    price = float(price_val.iloc[-1])
                else:
                    price = float(price_val)
            except Exception:
                # if coercion fails, skip marker
                continue

            if ttype == "BUY":
                buys_x.append(pd.to_datetime(tstamp))
                buys_y.append(price)
            elif ttype == "SELL":
                sells_x.append(pd.to_datetime(tstamp))
                sells_y.append(price)

        if buys_x:
            ax.scatter(buys_x, buys_y, marker="^", s=50, label="BUY", zorder=5)
        if sells_x:
            ax.scatter(sells_x, sells_y, marker="v", s=50, label="SELL", zorder=5)
        if buys_x or sells_x:
            ax.legend()

    # save
    outdir = os.path.dirname(outpath) or "."
    os.makedirs(outdir, exist_ok=True)
    fig.tight_layout()
    fig.savefig(outpath)
    if show:
        plt.show()
    plt.close(fig)
    return outpath

def plot_drawdown(equity_series: pd.Series, outpath: str = "drawdown.png", show: bool = False) -> str:
    """
    Plot drawdown series (peak-to-trough percentage).
    """
    if equity_series is None or equity_series.empty:
        raise ValueError("Empty equity series")
    peak = equity_series.cummax()
    drawdown = (equity_series - peak) / peak
    fig, ax = plt.subplots(figsize=(10, 3))
    drawdown.plot(ax=ax, title="Drawdown", grid=True)
    ax.set_ylabel("Drawdown")
    outdir = os.path.dirname(outpath) or "."
    os.makedirs(outdir, exist_ok=True)
    fig.tight_layout()
    fig.savefig(outpath)
    if show:
        plt.show()
    plt.close(fig)
    return outpath

def plot_from_folder(folder: str, out_dir: Optional[str] = None) -> Dict[str, str]:
    """
    Convenience: given a backtest folder that contains 'equity_curve.csv' and 'trade_log.csv',
    produce 'equity_curve.png' and 'drawdown.png' in out_dir (or folder if not provided).
    Returns dict of produced file paths.
    """
    if out_dir is None:
        out_dir = folder
    equity_csv = os.path.join(folder, "equity_curve.csv")
    trade_csv = os.path.join(folder, "trade_log.csv")
    if not os.path.exists(equity_csv):
        raise FileNotFoundError(f"Equity CSV not found: {equity_csv}")
    equity = load_equity_csv(equity_csv)
    trades = []
    if os.path.exists(trade_csv):
        trades = load_trade_log_csv(trade_csv)
    eq_png = os.path.join(out_dir, "equity_curve.png")
    dd_png = os.path.join(out_dir, "drawdown.png")
    plot_equity_curve(equity, trade_log=trades, outpath=eq_png, show=False)
    plot_drawdown(equity, outpath=dd_png, show=False)
    return {"equity": eq_png, "drawdown": dd_png}
