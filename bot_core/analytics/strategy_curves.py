# bot_core/analytics/strategy_curves.py
"""
Compute and plot per-strategy cumulative PnL series from a backtest trade_log.

Functions:
 - compute_strategy_cum_pnl_series(trade_log, equity_index) -> Dict[str, pd.Series]
 - plot_strategy_curves(series_dict, out_dir, combined_name="strategy_equity_curves.png")

This module expects trade_log items where SELL records contain:
  - "time" (ISO string or pandas timestamp)
  - "pnl" (float)
  - "strategy" (string)

The produced series are aligned to `equity_index` (DatetimeIndex). Each strategy series
is the cumulative sum of its closed-trade PnLs at the nearest past bar time.
"""
from typing import List, Dict, Any, Optional
import os
import pandas as pd
import matplotlib.pyplot as plt


def compute_strategy_cum_pnl_series(trade_log: List[Dict[str, Any]],
                                    equity_index: pd.DatetimeIndex) -> Dict[str, pd.Series]:
    """
    Build cumulative PnL series per strategy.

    - trade_log: list of trade dicts (uses SELL trades with 'pnl' and 'strategy')
    - equity_index: DatetimeIndex (typically equity_series.index from backtester)

    Returns: dict mapping strategy name -> pd.Series indexed by equity_index with cumulative pnl.
    """
    # initialize DataFrame of zeros
    idx = pd.DatetimeIndex(equity_index)
    if idx.empty:
        return {}

    # collect strategy names
    strategies = set()
    for t in trade_log:
        if t.get("type") == "SELL" and "pnl" in t:
            strategies.add(t.get("strategy") or "unknown")
    if not strategies:
        return {}

    df = pd.DataFrame(0.0, index=idx, columns=sorted(list(strategies)))

    # place PnL at the nearest past bar for each SELL trade
    for t in trade_log:
        if t.get("type") != "SELL" or "pnl" not in t:
            continue
        strat = t.get("strategy") or "unknown"
        try:
            ts = pd.to_datetime(t.get("time"))
            # map to nearest previous index (pad)
            pos = idx.get_indexer([ts], method="pad")[0]
            if pos == -1:
                # if no previous index, place at first bar
                pos = 0
            df.iloc[pos, df.columns.get_loc(strat)] += float(t.get("pnl", 0.0))
        except Exception:
            # as fallback, append to last index
            df.iloc[-1, df.columns.get_loc(strat)] += float(t.get("pnl", 0.0))

    # cumulative sum to get equity-like curve
    series_dict: Dict[str, pd.Series] = {}
    for col in df.columns:
        s = df[col].cumsum()
        s.name = col
        series_dict[col] = s

    return series_dict


def plot_strategy_curves(series_dict: Dict[str, pd.Series],
                         out_dir: str,
                         combined_name: str = "strategy_equity_curves.png",
                         individual: bool = True) -> Dict[str, str]:
    """
    Plot combined per-strategy curves and optional individual PNGs.

    - series_dict: mapping strategy -> pd.Series (indexed by datetime)
    - out_dir: path where PNGs will be saved (created if missing)
    - combined_name: filename for combined plot saved in out_dir
    - individual: also write one PNG per strategy

    Returns dict with saved paths: {"combined": path, "strategy_name": path, ...}
    """
    os.makedirs(out_dir, exist_ok=True)
    saved: Dict[str, str] = {}

    if not series_dict:
        return saved

    # combined plot
    plt.figure(figsize=(10, 5))
    for name, s in series_dict.items():
        plt.plot(s.index, s.values, label=name)
    plt.legend(loc="best", fontsize="small")
    plt.title("Per-strategy cumulative PnL")
    plt.xlabel("Time")
    plt.ylabel("Cumulative PnL")
    plt.grid(alpha=0.25)
    combined_path = os.path.join(out_dir, combined_name)
    plt.tight_layout()
    plt.savefig(combined_path)
    plt.close()
    saved["combined"] = combined_path

    if individual:
        for name, s in series_dict.items():
            plt.figure(figsize=(8, 4))
            plt.plot(s.index, s.values)
            plt.title(f"{name} cumulative PnL")
            plt.xlabel("Time")
            plt.ylabel("Cumulative PnL")
            plt.grid(alpha=0.25)
            fname = f"strategy_{name.replace(' ', '_')}.png"
            p = os.path.join(out_dir, fname)
            plt.tight_layout()
            plt.savefig(p)
            plt.close()
            saved[name] = p

    return saved


# convenience CLI for quick runs (scriptable)
if __name__ == "__main__":
    import sys
    if len(sys.argv) < 3:
        print("Usage: python -m bot_core.analytics.strategy_curves <trade_log.csv> <equity_csv> [out_dir]")
        sys.exit(1)
    trade_csv = sys.argv[1]
    equity_csv = sys.argv[2]
    out_dir = sys.argv[3] if len(sys.argv) > 3 else os.path.dirname(trade_csv) or "."
    try:
        trades = pd.read_csv(trade_csv, parse_dates=["time"]).to_dict(orient="records")
    except Exception as e:
        print("Failed to read trade log:", e)
        sys.exit(2)
    try:
        eq = pd.read_csv(equity_csv, index_col=0, parse_dates=True, squeeze=True)
        # ensure index is datetime index
        eq_idx = pd.DatetimeIndex(eq.index)
    except Exception as e:
        print("Failed to read equity CSV:", e)
        sys.exit(3)
    sdict = compute_strategy_cum_pnl_series(trades, eq_idx)
    out = plot_strategy_curves(sdict, out_dir)
    print("Saved plots:", out)
