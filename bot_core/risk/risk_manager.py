# bot_core/risk/risk_manager.py
"""
Risk management utilities.

RiskManager responsibilities (simple, deterministic):
 - Track open positions (long/short) and compute/update per-position trailing stop
   using a percentage-based trailing stop rule.
 - Enforce a maximum number of concurrent deals (max_concurrent_deals).
 - Track equity peak and compute drawdown; emit an alert if drawdown exceeds threshold.

Positions are stored as simple dicts (no execution plumbing). This module is intentionally
small and easy to integrate with Backtester or live execution.

API overview:

rm = RiskManager(max_concurrent_deals=3, trailing_stop_pct=0.02, drawdown_alert_pct=0.2)
rm.can_open_new() -> bool
rm.open_position(pid, side='long', entry_price=100.0, amount=100.0, strategy='x')
rm.update_price(pid, price) -> new_stop
rm.should_close(pid, price) -> bool
rm.close_position(pid)
rm.record_equity(equity_value) -> (drawdown_pct, alert_flag)
rm.get_position(pid) -> position dict or None
"""

from typing import Dict, Optional, Tuple
import math

class RiskManagerError(Exception):
    pass

class RiskManager:
    def __init__(self,
                max_concurrent_deals: int = 5,
                trailing_stop_pct: float = 0.02,
                drawdown_alert_pct: float = 0.2,
                trailing_stop_mode: str = "pct",
                atr_period: int = 14,
                atr_multiplier: float = 3.0):
        if max_concurrent_deals < 1:
            raise RiskManagerError("max_concurrent_deals must be >= 1")
        if trailing_stop_pct < 0 or drawdown_alert_pct < 0:
            raise RiskManagerError("percentages must be non-negative")
    
        # validate trailing stop mode
        if trailing_stop_mode not in ("pct", "atr"):
            raise RiskManagerError("trailing_stop_mode must be 'pct' or 'atr'")
    
        self.max_concurrent_deals = int(max_concurrent_deals)
        self.trailing_stop_pct = float(trailing_stop_pct)
        self.drawdown_alert_pct = float(drawdown_alert_pct)
    
        # trailing stop configuration
        self.trailing_stop_mode = trailing_stop_mode
        self.atr_period = int(atr_period)
        self.atr_multiplier = float(atr_multiplier)
    
        # positions: pid -> position dict with keys:
        #  {'pid','side','entry_price','size','amount','strategy','peak_price','stop'}
        self.positions: Dict[str, Dict] = {}
    
        # equity tracking
        self.equity_peak: float = 0.0
        self.equity_trough: float = 0.0
    

    # ---------- position management ----------
    def can_open_new(self) -> bool:
        """Return True if we are below the concurrent deals limit."""
        return len(self.positions) < self.max_concurrent_deals

    def open_position(self, pid: str, side: str, entry_price: float, amount: float,
                      size: Optional[float] = None, atr: Optional[float] = None,
                      strategy: Optional[str] = None) -> Dict:
        """
        Register a new position.
    
        Optional:
          - size: explicit size units; if None, computed as amount / entry_price
          - atr: if trailing_stop_mode == 'atr' you can pass a numeric ATR value
                 to initialize the ATR-based stop at opening.
        """
        if not self.can_open_new():
            raise RiskManagerError("max concurrent deals reached")
    
        if pid in self.positions:
            raise RiskManagerError("position already exists")
    
        if side not in ("long", "short"):
            raise RiskManagerError("side must be 'long' or 'short'")
    
        entry_price = float(entry_price)
        amount = float(amount)
        if size is None:
            size = amount / entry_price if entry_price != 0 else 0.0
        peak = entry_price  # initial peak for trailing logic
    
        # compute initial stop depending on configured mode
        if self.trailing_stop_mode == "atr" and (atr is not None):
            # ATR-based initial stop: price +/- atr_multiplier * ATR
            if side == "long":
                stop = entry_price - (self.atr_multiplier * float(atr))
            else:
                stop = entry_price + (self.atr_multiplier * float(atr))
        else:
            # percentage-based fallback
            if side == "long":
                stop = entry_price * (1.0 - self.trailing_stop_pct)
            else:
                stop = entry_price * (1.0 + self.trailing_stop_pct)
    
        pos = {
            "pid": pid,
            "side": side,
            "entry_price": entry_price,
            "amount": amount,
            "size": float(size),
            "strategy": strategy,
            "peak_price": peak,
            "stop": float(stop),
        }
        self.positions[pid] = pos
        return pos


    def get_position(self, pid: str) -> Optional[Dict]:
        return self.positions.get(pid)

    def close_position(self, pid: str) -> Optional[Dict]:
        """Remove position and return it, or None if not present."""
        return self.positions.pop(pid, None)

    # ---------- trailing stop logic ----------
    def update_price(self, pid: str, price: float, atr: Optional[float] = None) -> float:
        """
        Update internal peak and trailing stop for the given position id based on new market price.
        Returns the updated stop level (float).
    
        If trailing_stop_mode == 'atr' and an `atr` value is provided, the trailing stop uses
        price +/- atr_multiplier * atr; otherwise uses percentage-based logic.
        """
        pos = self.positions.get(pid)
        if pos is None:
            raise RiskManagerError("position not found")
    
        price = float(price)
        side = pos["side"]
        old_peak = pos["peak_price"]
        old_stop = pos["stop"]
    
        if side == "long":
            # update peak if price moved higher
            if price > old_peak:
                pos["peak_price"] = price
                if self.trailing_stop_mode == "atr" and (atr is not None):
                    # ATR-based: stop = price - k * ATR, but never move stop down (only up)
                    new_stop_val = price - (self.atr_multiplier * float(atr))
                    new_stop = max(old_stop, new_stop_val)
                else:
                    # percentage-based: stop = price * (1 - pct)
                    new_stop = max(old_stop, price * (1.0 - self.trailing_stop_pct))
                pos["stop"] = float(new_stop)
            # else: price not higher, leave stop unchanged
        else:
            # short: favorable price move is price going down
            if price < old_peak:
                pos["peak_price"] = price
                if self.trailing_stop_mode == "atr" and (atr is not None):
                    # ATR-based for short: stop = price + k * ATR (never move stop up toward price)
                    new_stop_val = price + (self.atr_multiplier * float(atr))
                    new_stop = min(old_stop, new_stop_val)
                else:
                    new_stop = min(old_stop, price * (1.0 + self.trailing_stop_pct))
                pos["stop"] = float(new_stop)
    
        return float(pos["stop"])
    

    def should_close(self, pid: str, price: float) -> bool:
        """
        Return True if the provided price has hit/exceeded the trailing stop for this position.
        For longs: price <= stop -> close
        For shorts: price >= stop -> close
        """
        pos = self.positions.get(pid)
        if pos is None:
            raise RiskManagerError("position not found")
        price = float(price)
        side = pos["side"]
        stop = float(pos["stop"])
        if side == "long":
            return price <= stop
        else:
            return price >= stop

    # ---------- equity & drawdown ----------
    def record_equity(self, equity_value: float) -> Tuple[Optional[float], bool]:
        """
        Feed equity values to the manager. Returns (current_drawdown_fraction, alert_flag)
        drawdown_fraction is negative or zero (e.g. -0.2 means 20% drawdown).
        If drawdown exceeds drawdown_alert_pct the alert_flag is True.
        """
        if equity_value is None:
            return None, False
        equity_value = float(equity_value)
        if self.equity_peak is None:
            self.equity_peak = equity_value
            self.equity_trough = equity_value
            return 0.0, False

        # update peak and trough
        if equity_value > self.equity_peak:
            self.equity_peak = equity_value
            self.equity_trough = equity_value
        elif equity_value < self.equity_trough:
            self.equity_trough = equity_value

        # compute drawdown relative to peak
        if self.equity_peak == 0:
            dd = 0.0
        else:
            dd = (equity_value - self.equity_peak) / self.equity_peak

        alert = abs(dd) >= float(self.drawdown_alert_pct)
        return float(dd), bool(alert)

    # ---------- helpers ----------
    def list_positions(self) -> Dict[str, Dict]:
        return dict(self.positions)
