# bot_core/indicators.py
"""
Unified, vectorized indicator utilities for strategies.

This module intentionally keeps both snake_case names (sma, ema, rsi, macd_series, ...)
and provides uppercase wrappers for backward compatibility (SMA, RSI) if older code uses them.

Functions:
  - sma, SMA
  - ema
  - macd_series (returns DataFrame with macd, signal, hist)
  - rsi, RSI
  - stochastic
  - bollinger_bands
  - true_range
  - atr
  - parabolic_sar
"""

from typing import Iterable, Union, Dict
import pandas as pd
import numpy as np
import math

SeriesLike = Union[pd.Series, Iterable, list, np.ndarray]

# ----------------------------
# Helpers
# ----------------------------
def _ensure_series(x: SeriesLike) -> pd.Series:
    if isinstance(x, pd.Series):
        return x.astype(float)
    return pd.Series(list(x)).astype(float)


# ----------------------------
# Moving averages
# ----------------------------
def sma(series: SeriesLike, window: int) -> pd.Series:
    """
    Simple Moving Average.
    """
    s = _ensure_series(series)
    return s.rolling(window=window, min_periods=1).mean()

# Uppercase wrapper for backward compatibility
def SMA(series: pd.Series, window: int) -> pd.Series:
    return sma(series, window)


def ema(series: SeriesLike, span: int) -> pd.Series:
    """
    Exponential moving average (pandas ewm with adjust=False).
    """
    s = _ensure_series(series)
    return s.ewm(span=span, adjust=False).mean()


# ----------------------------
# MACD
# ----------------------------
def macd_series(series: SeriesLike, fast: int = 12, slow: int = 26, signal: int = 9) -> pd.DataFrame:
    """
    Return macd, signal, hist as a DataFrame.
    """
    s = _ensure_series(series)
    fast_ema = s.ewm(span=fast, adjust=False).mean()
    slow_ema = s.ewm(span=slow, adjust=False).mean()
    macd = fast_ema - slow_ema
    sig = macd.ewm(span=signal, adjust=False).mean()
    hist = macd - sig
    return pd.DataFrame({"macd": macd, "signal": sig, "hist": hist})

# Backward compatible name if other code expects 'macd'
def macd(close: SeriesLike, fast_period: int = 12, slow_period: int = 26, signal_period: int = 9) -> pd.DataFrame:
    return macd_series(close, fast=fast_period, slow=slow_period, signal=signal_period)


# ----------------------------
# RSI
# ----------------------------
def rsi(series: SeriesLike, period: int = 14) -> pd.Series:
    """
    Relative Strength Index (Wilder smoothing via ewm alpha=1/period).
    Returns 0-100 scaled values.
    """
    s = _ensure_series(series)
    delta = s.diff().fillna(0.0)
    gain = delta.clip(lower=0.0)
    loss = -delta.clip(upper=0.0)

    avg_gain = gain.ewm(alpha=1.0/period, adjust=False, min_periods=period).mean()
    avg_loss = loss.ewm(alpha=1.0/period, adjust=False, min_periods=period).mean()

    rs = avg_gain / avg_loss.replace(0, np.nan)
    rsi_series = 100.0 - (100.0 / (1.0 + rs))
    rsi_series = rsi_series.fillna(100.0).clip(lower=0.0, upper=100.0)
    return rsi_series

# Backward compatible wrapper
def RSI(series: pd.Series, window: int = 14) -> pd.Series:
    return rsi(series, period=window)


# ----------------------------
# Stochastic Oscillator
# ----------------------------
def stochastic(high: SeriesLike, low: SeriesLike, close: SeriesLike, k_window: int = 14, d_window: int = 3) -> pd.DataFrame:
    """
    %K and %D of the stochastic oscillator.
    """
    high_s = _ensure_series(high)
    low_s = _ensure_series(low)
    close_s = _ensure_series(close)

    lowest_low = low_s.rolling(k_window, min_periods=1).min()
    highest_high = high_s.rolling(k_window, min_periods=1).max()
    denom = (highest_high - lowest_low).replace(0, np.nan)
    percent_k = 100.0 * (close_s - lowest_low) / denom
    percent_k = percent_k.fillna(0.0)
    percent_d = percent_k.rolling(d_window, min_periods=1).mean()
    return pd.DataFrame({"%K": percent_k, "%D": percent_d})


# ----------------------------
# Bollinger Bands
# ----------------------------
def bollinger_bands(close: SeriesLike, window: int = 20, num_std: float = 2.0) -> pd.DataFrame:
    s = _ensure_series(close)
    mid = s.rolling(window, min_periods=1).mean()
    std = s.rolling(window, min_periods=1).std(ddof=0)
    upper = mid + std * num_std
    lower = mid - std * num_std
    bandwidth = (upper - lower) / mid.replace(0, np.nan)
    percent_b = (s - lower) / (upper - lower).replace(0, np.nan)
    return pd.DataFrame({"mid": mid, "upper": upper, "lower": lower, "bandwidth": bandwidth, "percent_b": percent_b})


# ----------------------------
# True Range & ATR
# ----------------------------
def true_range(high: SeriesLike, low: SeriesLike, close: SeriesLike) -> pd.Series:
    high_s = _ensure_series(high)
    low_s = _ensure_series(low)
    close_s = _ensure_series(close)
    prev_close = close_s.shift(1)
    tr1 = high_s - low_s
    tr2 = (high_s - prev_close).abs()
    tr3 = (low_s - prev_close).abs()
    tr = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)
    return tr

def atr(high: SeriesLike, low: SeriesLike, close: SeriesLike, window: int = 14, method: str = "sma") -> pd.Series:
    tr = true_range(high, low, close)
    if method == "sma":
        return tr.rolling(window, min_periods=1).mean()
    elif method == "wilder":
        return tr.ewm(alpha=1.0/window, adjust=False, min_periods=1).mean()
    else:
        raise ValueError("method must be 'sma' or 'wilder'")

# ADX (Average Directional Index) and DI (Directional Indicators)
def adx(high: SeriesLike, low: SeriesLike, close: SeriesLike, period: int = 14) -> pd.DataFrame:
    """
    Compute ADX, +DI and -DI using Wilder's smoothing.

    Returns a DataFrame with columns:
      - 'adx' : Average Directional Index
      - 'plus_di' : +DI (Directional Indicator)
      - 'minus_di' : -DI (Directional Indicator)

    Args:
        high, low, close: Series-like price arrays
        period: lookback period for ADX (default 14)
    """
    # Ensure series
    high_s = _ensure_series(high).astype(float)
    low_s = _ensure_series(low).astype(float)
    close_s = _ensure_series(close).astype(float)

    # True Range
    tr = true_range(high_s, low_s, close_s)

    # Wilder-style smoothing (approx via ewm with alpha=1/period, adjust=False)
    # Directional Movements
    up_move = high_s.diff()
    down_move = -low_s.diff()

    plus_dm = ((up_move > down_move) & (up_move > 0)) * up_move
    minus_dm = ((down_move > up_move) & (down_move > 0)) * down_move

    # Smooth TR and DM using Wilder's smoothing (alpha = 1/period)
    atr_sm = tr.ewm(alpha=1.0 / period, adjust=False).mean()
    plus_dm_sm = plus_dm.ewm(alpha=1.0 / period, adjust=False).mean()
    minus_dm_sm = minus_dm.ewm(alpha=1.0 / period, adjust=False).mean()

    # Prevent division by zero
    with pd.option_context("mode.use_inf_as_na", True):
        plus_di = 100.0 * (plus_dm_sm / atr_sm)
        minus_di = 100.0 * (minus_dm_sm / atr_sm)

    # DX and ADX
    denom = (plus_di + minus_di).replace(0, np.nan)
    dx = 100.0 * ( (plus_di - minus_di).abs() / denom )
    dx = dx.fillna(0.0)

    adx_s = dx.ewm(alpha=1.0 / period, adjust=False).mean()

    result = pd.DataFrame({
        "adx": adx_s,
        "plus_di": plus_di.fillna(0.0),
        "minus_di": minus_di.fillna(0.0),
    }, index=close_s.index)

    return result


# Backward-compatible uppercase alias
def ADX(high: SeriesLike, low: SeriesLike, close: SeriesLike, period: int = 14) -> pd.DataFrame:
    return adx(high, low, close, period=period)

def ichimoku(
    high: SeriesLike,
    low: SeriesLike,
    close: SeriesLike,
    tenkan: int = 9,
    kijun: int = 26,
    senkou_b: int = 52,
    shift: int = 26,
) -> pd.DataFrame:
    """
    Ichimoku Kinko Hyo indicator.

    Returns a DataFrame with columns:
      - 'tenkan'     : Tenkan-sen (conversion line)
      - 'kijun'      : Kijun-sen (base line)
      - 'senkou_a'   : Senkou Span A (leading span A) shifted forward by `shift`
      - 'senkou_b'   : Senkou Span B (leading span B) shifted forward by `shift`
      - 'chikou'     : Chikou Span (lagging span) shifted backward by `shift`

    Args:
        high, low, close: series-like inputs
        tenkan: period for Tenkan-sen (default 9)
        kijun: period for Kijun-sen (default 26)
        senkou_b: period for Senkou Span B (default 52)
        shift: forward shift (usually equal to kijun, default 26)
    """
    # ensure series
    high_s = _ensure_series(high).astype(float)
    low_s = _ensure_series(low).astype(float)
    close_s = _ensure_series(close).astype(float)

    # Tenkan-sen (Conversion Line): (9-period high + 9-period low) / 2
    tenkan_high = high_s.rolling(window=tenkan, min_periods=1).max()
    tenkan_low = low_s.rolling(window=tenkan, min_periods=1).min()
    tenkan_s = (tenkan_high + tenkan_low) / 2.0

    # Kijun-sen (Base Line): (26-period high + 26-period low) / 2
    kijun_high = high_s.rolling(window=kijun, min_periods=1).max()
    kijun_low = low_s.rolling(window=kijun, min_periods=1).min()
    kijun_s = (kijun_high + kijun_low) / 2.0

    # Senkou Span A (Leading Span A): (Tenkan + Kijun) / 2 shifted forward by `shift`
    senkou_a = ((tenkan_s + kijun_s) / 2.0).shift(shift)

    # Senkou Span B (Leading Span B): (52-period high + 52-period low) / 2 shifted forward by `shift`
    senkou_b_high = high_s.rolling(window=senkou_b, min_periods=1).max()
    senkou_b_low = low_s.rolling(window=senkou_b, min_periods=1).min()
    senkou_b_s = ((senkou_b_high + senkou_b_low) / 2.0).shift(shift)

    # Chikou Span (Lagging Span): close shifted backward by `shift` (i.e., lead index by -shift)
    chikou = close_s.shift(-shift)

    result = pd.DataFrame(
        {
            "tenkan": tenkan_s,
            "kijun": kijun_s,
            "senkou_a": senkou_a,
            "senkou_b": senkou_b_s,
            "chikou": chikou,
        },
        index=close_s.index,
    )

    return result


# Uppercase alias for backward compatibility / style
def ICHIMOKU(
    high: SeriesLike,
    low: SeriesLike,
    close: SeriesLike,
    tenkan: int = 9,
    kijun: int = 26,
    senkou_b: int = 52,
    shift: int = 26,
) -> pd.DataFrame:
    return ichimoku(high, low, close, tenkan=tenkan, kijun=kijun, senkou_b=senkou_b, shift=shift)

# ----------------------------
# Parabolic SAR
# ----------------------------
def parabolic_sar(high: SeriesLike, low: SeriesLike, step: float = 0.02, max_af: float = 0.2) -> pd.Series:
    """
    Parabolic SAR implementation. Returns a pd.Series of SAR values aligned to input index.
    Uses the standard acceleration factor logic.
    """
    high_s = _ensure_series(high)
    low_s = _ensure_series(low)
    n = len(high_s)
    if n == 0:
        return pd.Series(dtype='float64')

    sar = pd.Series(index=high_s.index, dtype='float64')

    # initialize
    if n == 1:
        sar.iloc[0] = low_s.iloc[0]
        return sar

    up_trend = high_s.iloc[1] > high_s.iloc[0]
    ep = high_s.iloc[0] if up_trend else low_s.iloc[0]
    af = step
    sar.iloc[0] = low_s.iloc[0] if up_trend else high_s.iloc[0]

    for i in range(1, n):
        prev_sar = sar.iloc[i - 1]
        if up_trend:
            calc = prev_sar + af * (ep - prev_sar)
            if i >= 2:
                calc = min(calc, low_s.iloc[i - 1], low_s.iloc[i - 2])
            else:
                calc = min(calc, low_s.iloc[i - 1])
            if low_s.iloc[i] < calc:
                # flip to downtrend
                up_trend = False
                sar.iloc[i] = ep
                ep = low_s.iloc[i]
                af = step
            else:
                sar.iloc[i] = calc
                if high_s.iloc[i] > ep:
                    ep = high_s.iloc[i]
                    af = min(af + step, max_af)
        else:
            calc = prev_sar + af * (ep - prev_sar)
            if i >= 2:
                calc = max(calc, high_s.iloc[i - 1], high_s.iloc[i - 2])
            else:
                calc = max(calc, high_s.iloc[i - 1])
            if high_s.iloc[i] > calc:
                up_trend = True
                sar.iloc[i] = ep
                ep = high_s.iloc[i]
                af = step
            else:
                sar.iloc[i] = calc
                if low_s.iloc[i] < ep:
                    ep = low_s.iloc[i]
                    af = min(af + step, max_af)

    return sar
