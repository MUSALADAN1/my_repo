# bot_core/strategies/options_strategy.py
from typing import Dict, Any, Optional
import math
import pandas as pd

from bot_core.strategies.plugin_base import StrategyPlugin

SQRT2 = math.sqrt(2.0)

def _std_norm_cdf(x: float) -> float:
    """Standard normal CDF using math.erf (no external deps)."""
    return 0.5 * (1.0 + math.erf(x / SQRT2))

def black_scholes_price_and_delta(
    S: float,
    K: float,
    T: float,
    sigma: float,
    r: float = 0.0,
    option_type: str = "call"
) -> Dict[str, float]:
    """
    Compute Black-Scholes european price and delta for a call or put.
    Returns dict {"price": float, "delta": float}.
    T is time to expiry in years. sigma is annual volatility (decimal).
    """
    S = float(S)
    K = float(K)
    sigma = float(sigma)
    r = float(r)
    # handle T == 0 (expiry): option value is intrinsic
    if T <= 0 or sigma <= 0:
        if option_type == "call":
            price = max(0.0, S - K)
            delta = 1.0 if S > K else 0.0
        else:
            price = max(0.0, K - S)
            delta = -1.0 if S < K else 0.0
        return {"price": float(price), "delta": float(delta)}

    sqrtT = math.sqrt(T)
    try:
        d1 = (math.log(S / K) + (r + 0.5 * sigma * sigma) * T) / (sigma * sqrtT)
    except Exception:
        # fallback numeric stability: use very small d1/d2
        d1 = 0.0
    d2 = d1 - sigma * sqrtT

    Nd1 = _std_norm_cdf(d1)
    Nd2 = _std_norm_cdf(d2)

    discount = math.exp(-r * T)
    if option_type == "call":
        price = S * Nd1 - K * discount * Nd2
        delta = Nd1
    else:
        # put price by parity or closed form
        N_neg_d1 = _std_norm_cdf(-d1)
        N_neg_d2 = _std_norm_cdf(-d2)
        price = K * discount * N_neg_d2 - S * N_neg_d1
        delta = Nd1 - 1.0

    return {"price": float(price), "delta": float(delta)}

class OptionsStrategy(StrategyPlugin):
    """
    Options strategy scaffold that prices a single leg (European) option each bar.

    Params:
      - option_type: "call" or "put" (default "call")
      - strike: float (required)
      - expiry_bars: int (number of bars until expiry from strategy start; required)
      - vol: float (annual vol as decimal, default 0.2)
      - r: float (risk-free rate, default 0.0)
      - delta_threshold: float (emit buy when delta >= this, default 0.6)
      - bars_per_year: float (how many bars represent a year; default 365*24 for hourly bars)
      - name: optional
    Behavior:
      - Tracks bars elapsed; computes T = max(0, (expiry_bars - elapsed) / bars_per_year)
      - Prices option and computes delta via Black-Scholes each bar
      - Emits {"signal":"buy_option","type":..., "delta":..., "price":..., "strike":..., "expiry_remaining": ...}
        when delta >= delta_threshold (only once per satisfying bar)
    """
    def __init__(self, name: str = "options_strategy", params: Dict[str, Any] = None):
        super().__init__(name, params or {})
        p = self.params
        self.option_type = (p.get("option_type") or "call").lower()
        if self.option_type not in ("call", "put"):
            self.option_type = "call"
        self.strike = float(p.get("strike", 100.0))
        self.expiry_bars = int(p.get("expiry_bars", 30))
        self.vol = float(p.get("vol", 0.20))
        self.r = float(p.get("r", 0.0))
        self.delta_threshold = float(p.get("delta_threshold", 0.6))
        # bars_per_year maps bars -> years (default assumes hourly bars: 365*24)
        self.bars_per_year = float(p.get("bars_per_year", 365.0 * 24.0))
        self.bars_elapsed = 0
        self.call_count = 0

    def initialize(self, context):
        super().initialize(context)
        self.bars_elapsed = 0

    def on_bar(self, df: pd.DataFrame):
        self.call_count += 1
        # need at least 1 bar to price
        if len(df) < 1:
            return None
        self.bars_elapsed += 1
        expiry_remaining = max(0, self.expiry_bars - self.bars_elapsed)
        T = max(0.0, float(expiry_remaining) / float(self.bars_per_year))

        S = float(df['close'].iloc[-1])
        res = black_scholes_price_and_delta(S, self.strike, T, self.vol, self.r, self.option_type)
        price = res["price"]
        delta = res["delta"]

        if delta >= self.delta_threshold:
            return {
                "signal": "buy_option",
                "option_type": self.option_type,
                "strike": self.strike,
                "expiry_remaining_bars": expiry_remaining,
                "price": float(price),
                "delta": float(delta),
            }
        return None

def create_strategy(params: Dict[str, Any] = None):
    name = (params or {}).get("name", "options_strategy")
    return OptionsStrategy(name, params or {})
