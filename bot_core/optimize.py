import yaml
import pandas as pd
from bot_core.intraday_trading_bot import backtest  # reuse your backtest()
from datetime import datetime

def load_opt_config():
    with open("config.yaml","r") as f:
        cfg = yaml.safe_load(f)
    return cfg.get("optimization", {})

def generate_grid(opt_cfg):
    # sl in points, tp in points, fib tolerance list
    sl_start, sl_end, sl_step = opt_cfg["sl_points"].values()
    tp_start, tp_end, tp_step = opt_cfg["tp_points"].values()
    fib_list = opt_cfg["fib_tolerance"]

    grid = []
    for sl in range(sl_start, sl_end+1, sl_step):
        for tp in range(tp_start, tp_end+1, tp_step):
            for fib in fib_list:
                grid.append({"sl": sl/10000, "tp": tp/10000, "fib_tol": fib})
    return grid

def run_grid(symbol, tf="15m", bars=300):
    opt_cfg = load_opt_config()
    grid = generate_grid(opt_cfg)
    results = []
    for params in grid:
        stats = backtest(symbol, tf, params["sl"], params["tp"])
        results.append({
            **params,
            "symbol": symbol,
            **stats
        })
    df = pd.DataFrame(results)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    filename = f"opt_results_{symbol}_{timestamp}.csv"
    df.to_csv(filename, index=False)
    print(f"Saved optimization results to {filename}")

if __name__ == "__main__":
    import sys
    if len(sys.argv) < 2:
        print("Usage: python optimize.py SYMBOL [TIMEFRAME]")
    else:
        sym = sys.argv[1]
        tf = sys.argv[2] if len(sys.argv) > 2 else "15m"
        run_grid(sym, tf)
