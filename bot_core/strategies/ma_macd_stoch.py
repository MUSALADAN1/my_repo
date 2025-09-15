# bot_core/strategies/ma_macd_stoch.py
"""
Simple MA + MACD + Stochastic strategy plugin.
Exports: signal_from_df(df, config) -> dict with keys:
  'signal' ('buy'|'sell'|'hold'), 'reason', 'price', 'stop', 'atr', 'size_pct'
"""

from typing import Dict, Any
import pandas as pd
# Import the indicators module as a namespace to avoid name mismatch issues
from bot_core import indicators as ind

def signal_from_df(df: pd.DataFrame, config: Dict[str, Any] = None) -> Dict[str, Any]:
    """
    df must contain: 'high','low','open','close','volume' sorted oldest->newest.
    config (optional): ma_window, risk_pct, sl_atr_mult
    """
    if config is None:
        config = {}
    ma_window = int(config.get('ma_window', 50))
    risk_pct = float(config.get('risk_pct', 1.0))  # percent of equity risk per trade
    sl_atr_mult = float(config.get('sl_atr_mult', 1.5))

    # Basic validation
    if not {'high','low','open','close'}.issubset(df.columns):
        raise ValueError("df must contain 'high','low','open','close' columns")

    close = df['close']
    high = df['high']
    low = df['low']

    # Indicators — call via ind.<fn>()
    ma_val = float(ind.sma(close, ma_window).iloc[-1])
    macd_df = ind.macd(close)
    macd_line = float(macd_df['macd'].iloc[-1])
    macd_signal = float(macd_df['signal'].iloc[-1])
    st = ind.stochastic(high, low, close)
    k = float(st['%K'].iloc[-1]) if not pd.isna(st['%K'].iloc[-1]) else None
    d = float(st['%D'].iloc[-1]) if not pd.isna(st['%D'].iloc[-1]) else None

    # ATR for sizing and stop
    atr_series = ind.atr(high, low, close, window=14, method='wilder')
    atr_value = float(atr_series.iloc[-1])

    price = float(close.iloc[-1])
    reason_list = []
    signal = 'hold'

    # Trend filter
    trend_bull = price > ma_val
    trend_bear = price < ma_val

    # MACD confirmation
    macd_bull = macd_line > macd_signal
    macd_bear = macd_line < macd_signal

    # Stochastic conditions (if available)
    st_oversold = (k is not None and d is not None and k < 20 and d < 20)
    st_overbought = (k is not None and d is not None and k > 80 and d > 80)

    # Entry rules
    if trend_bull and macd_bull and st_oversold:
        signal = 'buy'
        reason_list.append('trend_bull & macd_bull & stoch_oversold')
    elif trend_bear and macd_bear and st_overbought:
        signal = 'sell'
        reason_list.append('trend_bear & macd_bear & stoch_overbought')
    else:
        reason_list.append('no clear confluence')

    # Suggested stop using ATR multiplier
    stop = None
    if signal == 'buy':
        stop = price - sl_atr_mult * atr_value
    elif signal == 'sell':
        stop = price + sl_atr_mult * atr_value

    # Heuristic position size (as % of equity) — bot must compute actual lot size using account equity
    if stop is not None:
        sl_distance = max(1e-8, abs(price - stop))
        # This returns a heuristic size_pct between 0.01 and 0.2
        size_pct = max(0.01, min(0.2, (risk_pct * atr_value) / sl_distance))
    else:
        size_pct = 0.0

    return {
        'signal': signal,
        'reason': ';'.join(reason_list),
        'price': price,
        'stop': float(stop) if stop is not None else None,
        'atr': atr_value,
        'size_pct': float(size_pct),
    }
