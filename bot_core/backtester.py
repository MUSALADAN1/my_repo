# bot_core/backtester.py
"""
Backtester & analytics.

Main class: Backtester
 - run(broker, strategy_manager, symbol, timeframe, limit, initial_balance, bars_per_year)
 - Produces: trade_log (list of dicts), equity_series (pd.Series indexed by bar datetime),
   metrics (dict)
 - Writes CSVs when requested.
"""
from typing import List, Dict, Any, Optional, Tuple
import math
import pandas as pd
import numpy as np
from datetime import datetime
import os
import json

class BacktestError(Exception):
    pass

class Backtester:
    def __init__(self, initial_balance: float = 10000.0, fee: float = 0.0, bars_per_year: float = 365.0*24.0):
        self.initial_balance = float(initial_balance)
        self.fee = float(fee)
        self.bars_per_year = float(bars_per_year)

    def _resolve_price_for_signal(self, signal: Dict[str, Any], df: pd.DataFrame) -> Optional[float]:
        """
        Determine the execution price for a signal:
         - If signal contains 'price', use it.
         - Else, use close price at bar_time (if provided and present in df index).
         - Else, use last available close in df.
        """
        if signal is None:
            return None
        if "price" in signal and signal.get("price") is not None:
            try:
                return float(signal.get("price"))
            except Exception:
                pass
        bar_time = signal.get("bar_time")
        if bar_time is not None:
            try:
                ts = pd.to_datetime(bar_time)
                if ts in df.index:
                    return float(df.loc[ts, "close"])
                pos = df.index.get_indexer([ts], method="pad")
                if pos[0] != -1:
                    return float(df.iloc[pos[0]]["close"])
            except Exception:
                pass
        # fallback to last close
        if not df.empty and "close" in df.columns:
            return float(df["close"].iloc[-1])
        return None

    def _process_signals_into_trades(self, signals: List[Dict[str,Any]], df: pd.DataFrame, risk_manager=None) -> Tuple[List[Dict[str, Any]], pd.Series]:
        """
        Simulate a simple execution model with optional RiskManager integration.

        If `risk_manager` is provided, it will be used to:
         - enforce max concurrent deals when opening positions
         - register open positions via risk_manager.open_position(pid, ...)
         - update trailing stops via risk_manager.update_price(pid, price) on each bar
         - auto-close positions when risk_manager.should_close(pid, price) returns True

        Behavior when risk_manager is None: same as previous (backwards-compatible).
        """
        # helper to extract a sortable time from a signal
        def _signal_time(sig):
            t = sig.get("bar_time", None)
            if t is None:
                return pd.Timestamp.min
            try:
                return pd.to_datetime(t)
            except Exception:
                return pd.Timestamp.min

        # sort signals by time to deterministically apply them
        signals_sorted = sorted(signals, key=_signal_time)

        balance = float(self.initial_balance)
        position = None  # single-position model: dict with entry_price, size, amount, entry_time, strategy, pid
        trade_log: List[Dict[str,Any]] = []

        # create equity series per bar
        equity_idx = []
        equity_vals = []

        # Create a lookup of signals by nearest bar index to quickly apply at bar iteration
        signals_by_bar: Dict[pd.Timestamp, List[Dict[str,Any]]] = {}
        for sig in signals_sorted:
            t = sig.get("bar_time", None)
            if t is None:
                key = df.index[0] if len(df.index) > 0 else None
            else:
                try:
                    ts = pd.to_datetime(t)
                    pos = df.index.get_indexer([ts], method="pad")
                    key = df.index[pos[0]] if (len(df.index) > 0 and pos[0] != -1) else (df.index[0] if len(df.index) > 0 else None)
                except Exception:
                    key = df.index[0] if len(df.index) > 0 else None
            if key is not None:
                signals_by_bar.setdefault(key, []).append(sig)

        # track positions opened via risk_manager -> map pid -> position dict
        rm_positions: Dict[str, Dict[str, Any]] = {}

        # iterate rows in chronological order and apply signals at that bar, compute equity
        for idx, row in df.iterrows():
            # apply signals for this bar (if any) in order
            for sig in signals_by_bar.get(idx, []):
                sig_type = (sig.get("signal") or "").lower()
                exec_price = self._resolve_price_for_signal(sig, df)
                if exec_price is None or exec_price == 0:
                    continue

                # determine amount to use
                amount = sig.get("amount", None)
                if amount is None:
                    # default allocation 5% of current balance
                    amount = balance * 0.05

                # If a RiskManager is provided, honor its max-concurrent and trailing-stop behavior
                if risk_manager is not None:
                    # BUY / LONG (open position if allowed and none currently open)
                    if sig_type in ("buy", "long", "buy_option"):
                        if position is None:
                            if not risk_manager.can_open_new():
                                # record a rejected attempt (helpful for analytics)
                                trade_log.append({
                                    "type": "REJECTED",
                                    "time": idx,
                                    "price": exec_price,
                                    "amount": amount,
                                    "reason": "max_concurrent_deals",
                                    "strategy": sig.get("strategy")
                                })
                                continue
                            # generate pid and open with risk manager
                            pid = f"pos_{len(rm_positions)+1}_{int(idx.value)}"
                            size = amount / exec_price if exec_price > 0 else 0.0
                            # open position in RiskManager (best-effort)
                            try:
                                risk_manager.open_position(pid=pid, side="long", entry_price=exec_price, amount=amount, size=size, strategy=sig.get("strategy"))
                            except Exception:
                                # ignore RM open failure but continue to simulate trade log
                                pass
                            # runtime position record
                            position = {
                                "entry_time": idx,
                                "entry_price": exec_price,
                                "size": float(size),
                                "amount": float(amount),
                                "strategy": sig.get("strategy"),
                                "pid": pid
                            }
                            rm_positions[pid] = position
                            fee_cost = amount * self.fee
                            balance -= fee_cost
                            trade_log.append({
                                "type": "BUY",
                                "time": idx,
                                "price": exec_price,
                                "size": size,
                                "amount": amount,
                                "fee": fee_cost,
                                "strategy": sig.get("strategy"),
                                "pid": pid
                            })
                        else:
                            # already in a position; ignore or log
                            trade_log.append({
                                "type": "IGNORED",
                                "time": idx,
                                "price": exec_price,
                                "amount": amount,
                                "reason": "already_in_position",
                                "strategy": sig.get("strategy")
                            })
                        continue

                    # SELL / EXIT / SHORT
                    if sig_type in ("sell", "exit", "short"):
                        if position is not None:
                            pid = position.get("pid")
                            size = position["size"]
                            entry_price = position["entry_price"]
                            pnl = (exec_price - entry_price) * size
                            fee_cost = (exec_price * size) * self.fee
                            balance += position["amount"] + pnl
                            balance -= fee_cost
                            trade_log.append({
                                "type": "SELL",
                                "time": idx,
                                "price": exec_price,
                                "size": size,
                                "amount": exec_price * size,
                                "pnl": pnl,
                                "fee": fee_cost,
                                "strategy": position.get("strategy"),
                                "entry_price": entry_price,
                                "entry_time": position.get("entry_time"),
                                "pid": pid
                            })
                            # close risk manager position if present
                            try:
                                if pid and pid in rm_positions:
                                    risk_manager.close_position(pid)
                            except Exception:
                                pass
                            rm_positions.pop(pid, None)
                            position = None
                        else:
                            trade_log.append({
                                "type": "IGNORED",
                                "time": idx,
                                "price": exec_price,
                                "amount": amount,
                                "reason": "no_position_to_close",
                                "strategy": sig.get("strategy")
                            })
                        continue

                    # other signal types ignored when rm used
                    continue

                # ---------- fallback behavior (risk_manager is None) ----------
                # BUY / LONG (open position if none)
                if sig_type in ("buy", "long", "buy_option"):
                    if position is None:
                        size = amount / exec_price if exec_price > 0 else 0.0
                        position = {
                            "entry_time": idx,
                            "entry_price": exec_price,
                            "size": float(size),
                            "amount": float(amount),
                            "strategy": sig.get("strategy"),
                        }
                        fee_cost = amount * self.fee
                        balance -= fee_cost
                        trade_log.append({
                            "type": "BUY",
                            "time": idx,
                            "price": exec_price,
                            "size": size,
                            "amount": amount,
                            "fee": fee_cost,
                            "strategy": sig.get("strategy")
                        })
                # SELL / EXIT / SHORT close existing long
                elif sig_type in ("sell", "exit", "short"):
                    if position is not None:
                        size = position["size"]
                        entry_price = position["entry_price"]
                        pnl = (exec_price - entry_price) * size
                        fee_cost = (exec_price * size) * self.fee
                        balance += position["amount"] + pnl
                        balance -= fee_cost
                        trade_log.append({
                            "type": "SELL",
                            "time": idx,
                            "price": exec_price,
                            "size": size,
                            "amount": exec_price * size,
                            "pnl": pnl,
                            "fee": fee_cost,
                            "strategy": sig.get("strategy"),
                            "entry_price": entry_price,
                            "entry_time": position.get("entry_time")
                        })
                        position = None
                    # else ignore

            # ----- END processing signals for this bar -----

            # If risk_manager is present, update tracked positions and auto-close any that hit trailing stops.
            if risk_manager is not None and rm_positions:
                to_close = []
                for pid, pos in list(rm_positions.items()):
                    try:
                        risk_manager.update_price(pid, float(row["close"]))
                    except Exception:
                        pass
                    try:
                        if risk_manager.should_close(pid, float(row["close"])):
                            to_close.append(pid)
                    except Exception:
                        pass

                for pid in to_close:
                    runtime_pos = rm_positions.get(pid)
                    if runtime_pos is None:
                        continue
                    last_price = float(row["close"])
                    size = runtime_pos["size"]
                    entry_price = runtime_pos["entry_price"]
                    pnl = (last_price - entry_price) * size
                    fee_cost = (last_price * size) * self.fee
                    balance += runtime_pos["amount"] + pnl
                    balance -= fee_cost
                    trade_log.append({
                        "type": "SELL",
                        "time": idx,
                        "price": last_price,
                        "size": size,
                        "amount": last_price * size,
                        "pnl": pnl,
                        "fee": fee_cost,
                        "strategy": runtime_pos.get("strategy"),
                        "entry_price": entry_price,
                        "entry_time": runtime_pos.get("entry_time"),
                        "pid": pid,
                        "closed_by_trailing_stop": True
                    })
                    try:
                        risk_manager.close_position(pid)
                    except Exception:
                        pass
                    rm_positions.pop(pid, None)
                    if position is not None and position.get("pid") == pid:
                        position = None

            # compute equity at this bar: balance + mark-to-market of open position
            mark = 0.0
            if position is not None:
                mark = position["size"] * float(row["close"])

            if rm_positions and len(rm_positions) > 0:
                if position is None:
                    mark = 0.0
                    for rp in rm_positions.values():
                        mark += float(rp["size"]) * float(row["close"])
                else:
                    # keep current mark (avoid double count)
                    pass

            equity = balance + mark
            equity_idx.append(idx)
            equity_vals.append(equity)

        # if position still open at end, close at last price (handles both non-rm and rm cases)
        if (position is not None or rm_positions) and not df.empty:
            last_price = float(df["close"].iloc[-1])

            # close rm_positions first
            for pid, runtime_pos in list(rm_positions.items()):
                size = runtime_pos["size"]
                entry_price = runtime_pos["entry_price"]
                pnl = (last_price - entry_price) * size
                fee_cost = (last_price * size) * self.fee
                balance += runtime_pos["amount"] + pnl
                balance -= fee_cost
                trade_log.append({
                    "type": "SELL",
                    "time": df.index[-1],
                    "price": last_price,
                    "size": size,
                    "amount": last_price * size,
                    "pnl": pnl,
                    "fee": fee_cost,
                    "strategy": runtime_pos.get("strategy"),
                    "entry_price": entry_price,
                    "entry_time": runtime_pos.get("entry_time"),
                    "pid": pid,
                    "closed_at_end": True
                })
                try:
                    if risk_manager is not None:
                        risk_manager.close_position(pid)
                except Exception:
                    pass
                rm_positions.pop(pid, None)

            # close non-rm position if still present
            if position is not None:
                size = position["size"]
                entry_price = position["entry_price"]
                pnl = (last_price - entry_price) * size
                fee_cost = (last_price * size) * self.fee
                balance += position["amount"] + pnl
                balance -= fee_cost
                trade_log.append({
                    "type": "SELL",
                    "time": df.index[-1],
                    "price": last_price,
                    "size": size,
                    "amount": last_price * size,
                    "pnl": pnl,
                    "fee": fee_cost,
                    "strategy": position.get("strategy"),
                    "entry_price": entry_price,
                    "entry_time": position.get("entry_time"),
                    "closed_at_end": True
                })
                position = None

            equity_idx.append(df.index[-1])
            equity_vals.append(balance)

        equity_series = pd.Series(data=equity_vals, index=pd.DatetimeIndex(equity_idx))
        return trade_log, equity_series

    def _compute_metrics(self, equity_series: pd.Series, trade_log: List[Dict[str,Any]]) -> Dict[str, Any]:
        metrics: Dict[str, Any] = {}
        if equity_series is None or equity_series.empty:
            metrics.update({"total_return": 0.0, "final_balance": self.initial_balance, "num_trades": 0})
            return metrics

        start_equity = float(equity_series.iloc[0])
        final_equity = float(equity_series.iloc[-1])
        total_return = (final_equity / start_equity) - 1.0
        metrics["initial_balance"] = start_equity
        metrics["final_balance"] = final_equity
        metrics["total_return"] = total_return
        metrics["num_trades"] = len([t for t in trade_log if t.get("type") in ("BUY","SELL")]) // 2 if trade_log else 0

        # trade-level stats (global)
        sells = [t for t in trade_log if t.get("type") == "SELL" and "pnl" in t]
        wins = [t for t in sells if t.get("pnl", 0) > 0]
        losses = [t for t in sells if t.get("pnl", 0) <= 0]

        metrics["win_rate"] = (len(wins) / max(1, (len(wins)+len(losses)))) if (len(wins)+len(losses))>0 else None
        metrics["num_wins"] = len(wins)
        metrics["num_losses"] = len(losses)
        metrics["avg_win"] = float(np.mean([t["pnl"] for t in wins])) if wins else 0.0
        metrics["avg_loss"] = float(np.mean([t["pnl"] for t in losses])) if losses else 0.0
        metrics["gross_profit"] = float(np.sum([t["pnl"] for t in wins])) if wins else 0.0
        metrics["gross_loss"] = float(np.sum([t["pnl"] for t in losses])) if losses else 0.0

        # --- per-strategy breakdown ---
        per_strategy: Dict[str, Dict[str, Any]] = {}
        # group SELL trades by their strategy field (fallback to 'unknown')
        for t in sells:
            strat = t.get("strategy") or "unknown"
            entry = per_strategy.setdefault(strat, {"num_trades": 0, "pnl_list": [], "gross_profit": 0.0, "gross_loss": 0.0})
            pnl = float(t.get("pnl", 0.0))
            entry["num_trades"] += 1
            entry["pnl_list"].append(pnl)
            if pnl > 0:
                entry["gross_profit"] += pnl
            else:
                entry["gross_loss"] += pnl

        # compute summary stats per strategy
        for strat, d in per_strategy.items():
            pnl_list = d.get("pnl_list", [])
            wins_s = [p for p in pnl_list if p > 0]
            losses_s = [p for p in pnl_list if p <= 0]
            d["total_pnl"] = float(np.sum(pnl_list)) if pnl_list else 0.0
            d["win_rate"] = (len(wins_s) / max(1, (len(wins_s) + len(losses_s)))) if (len(wins_s) + len(losses_s)) > 0 else None
            d["avg_win"] = float(np.mean(wins_s)) if wins_s else 0.0
            d["avg_loss"] = float(np.mean(losses_s)) if losses_s else 0.0
            d["num_wins"] = len(wins_s)
            d["num_losses"] = len(losses_s)
            # remove pnl_list to keep metrics JSON compact (keep if you prefer)
            d.pop("pnl_list", None)

        metrics["per_strategy"] = per_strategy

        # drawdown
        # fill forward then fill any remaining NaNs with 0.0
        equity = equity_series.ffill().fillna(0.0)
        peak = equity.cummax()
        dd = (equity - peak) / peak
        max_dd = float(dd.min()) if not dd.empty else 0.0
        metrics["max_drawdown"] = float(max_dd)

        # Sharpe ratio: compute periodic returns and annualize using bars_per_year
        returns = equity.pct_change().dropna()
        if returns.empty or returns.std() == 0:
            metrics["sharpe"] = None
        else:
            sharpe = (returns.mean() / returns.std()) * math.sqrt(self.bars_per_year)
            metrics["sharpe"] = float(sharpe)

        return metrics


    def run(self, broker, strategy_manager, symbol: str, timeframe: Any, limit: int = 500,
            save_path: Optional[str] = None, risk_manager=None) -> Dict[str, Any]:
        """
        Run full backtest: fetch data -> run strategies -> simulate trades -> compute metrics.
        If risk_manager is provided, it will be used during execution.
        Returns a dict containing trade_log, equity_series, metrics.
        """
        # fetch data
        df = broker.fetch_ohlcv(symbol, timeframe, limit=limit)
        if df is None or df.empty:
            raise BacktestError("No OHLCV data available for backtest")

        # run strategy_manager to get signals (strategy_manager.run_backtest returns {'status','signals'})
        sm_result = strategy_manager.run_backtest(broker, symbol, timeframe, limit=limit)
        if sm_result.get("status") != "ok":
            # allow empty signals but still simulate with empty list
            signals = sm_result.get("signals", [])
        else:
            signals = sm_result.get("signals", [])

        # process signals into trades and compute equity
        trade_log, equity_series = self._process_signals_into_trades(signals, df, risk_manager=risk_manager)
        metrics = self._compute_metrics(equity_series, trade_log)

        # --- Drawdown alert (best-effort, non-fatal) ---
        try:
            alert_threshold = None
            if risk_manager is not None and hasattr(risk_manager, "drawdown_alert_pct"):
                try:
                    alert_threshold = float(getattr(risk_manager, "drawdown_alert_pct"))
                except Exception:
                    alert_threshold = None

            max_dd = metrics.get("max_drawdown", None)
            if alert_threshold is not None and max_dd is not None:
                try:
                    max_dd_val = float(max_dd)
                    thresh = abs(float(alert_threshold))
                    if abs(max_dd_val) >= thresh:
                        try:
                            from bot_core.notifications.notify import NotificationManager, NotificationError
                            nm = NotificationManager(
                                telegram_token=os.environ.get("TELEGRAM_BOT_TOKEN"),
                                telegram_chat_id=os.environ.get("TELEGRAM_CHAT_ID"),
                                slack_webhook=os.environ.get("SLACK_WEBHOOK_URL"),
                                dry_run=(os.environ.get("TELEGRAM_BOT_TOKEN") is None and os.environ.get("SLACK_WEBHOOK_URL") is None)
                            )
                            msg = (f"Drawdown alert — backtest {symbol} @ {timeframe}: "
                                    f"max_drawdown={max_dd_val:.4f} >= threshold {thresh:.4f}")
                            nm.send(msg, channels=["telegram"])
                        except Exception:
                            pass
                except Exception:
                    pass
        except Exception:
            pass

        # optional saving
        if save_path:
            os.makedirs(save_path, exist_ok=True)
            trade_csv = os.path.join(save_path, "trade_log.csv")
            pd.DataFrame(trade_log).to_csv(trade_csv, index=False)
            equity_csv = os.path.join(save_path, "equity_curve.csv")
            equity_series.to_csv(equity_csv, header=["equity"])
            metrics_file = os.path.join(save_path, "metrics.json")
            with open(metrics_file, "w") as f:
                json.dump(metrics, f, indent=2, default=str)

        return {"trade_log": trade_log, "equity": equity_series, "metrics": metrics}
