# test_plotting.py
import pandas as pd
import numpy as np
import os
from pathlib import Path
from bot_core.analytics import plotting

def test_plot_from_folder_creates_pngs(tmp_path):
    # create fake equity CSV
    idx = pd.date_range("2025-01-01", periods=20, freq="H")
    equity = pd.Series(10000 + (np.arange(20) * 5.0), index=idx)
    equity_df = equity.to_frame(name="equity")
    equity_csv = tmp_path / "equity_curve.csv"
    equity_df.to_csv(equity_csv)

    # create fake trade_log CSV (one buy at 3rd bar, one sell at 7th bar)
    trade_csv = tmp_path / "trade_log.csv"
    trades = [
        {"time": str(idx[2]), "type": "BUY", "price": 1010.0},
        {"time": str(idx[6]), "type": "SELL", "price": 1040.0},
    ]
    import csv
    with open(trade_csv, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=["time","type","price"])
        writer.writeheader()
        for r in trades:
            writer.writerow(r)

    # call plotting
    out = plotting.plot_from_folder(str(tmp_path), out_dir=str(tmp_path))
    assert os.path.exists(out["equity"])
    assert os.path.exists(out["drawdown"])
