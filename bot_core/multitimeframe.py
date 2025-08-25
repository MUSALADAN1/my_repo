# bot_core/multitimeframe.py
"""
Multi-timeframe utilities: OHLCV resampling, alignment and a small window helper.

This version is intentionally simple and robust:
 - ensures DatetimeIndex (strips tz info)
 - normalizes columns to lowercase open/high/low/close/volume
 - uses DataFrame.resample(...).agg(...) which is stable across pandas versions
 - aligns target TFs to base TF by reindex+ffill
"""
from typing import List, Dict, Optional
import pandas as pd
import numpy as np


def _make_dt_index(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    # if there is a 'time' column prefer that, else use the index
    if "time" in df.columns:
        df.index = pd.to_datetime(df["time"])
    else:
        df.index = pd.to_datetime(df.index)
    # drop tzinfo to avoid tz-aware / tz-naive mismatches
    if isinstance(df.index, pd.DatetimeIndex) and df.index.tz is not None:
        df.index = df.index.tz_convert(None)
    df = df.sort_index()
    return df


def _ohlcv_lowercase(df: pd.DataFrame) -> pd.DataFrame:
    """
    Return DataFrame with columns open,high,low,close,volume (floats).
    If the input is missing a column it will be created with NaNs.
    """
    df = df.copy()
    # map any existing column to lowercase name
    lower_map = {c.lower(): c for c in df.columns}
    out = {}
    for name in ("open", "high", "low", "close", "volume"):
        if name in lower_map:
            out[name] = pd.to_numeric(df[lower_map[name]], errors="coerce").astype(float)
        else:
            # missing column -> NaN series with same index
            out[name] = pd.Series(index=df.index, dtype=float)
    return pd.DataFrame(out, index=df.index)


def resample_ohlcv(df: pd.DataFrame, timeframe: str) -> pd.DataFrame:
    """
    Resample OHLCV DataFrame to given timeframe (pandas frequency string).
    Returns DataFrame indexed by period start with columns open,high,low,close,volume.
    """
    if df is None or len(df) == 0:
        return pd.DataFrame(columns=["open", "high", "low", "close", "volume"])

    odf = _make_dt_index(df)
    odf = _ohlcv_lowercase(odf)

    # Use DataFrame.resample. This should be the most reliable across pandas versions.
    try:
        agg = odf.resample(timeframe, label="left", closed="left").agg({
            "open": "first",
            "high": "max",
            "low": "min",
            "close": "last",
            "volume": "sum",
        })
    except Exception:
        # fallback: try without label/closed (older pandas could raise)
        agg = odf.resample(timeframe).agg({
            "open": "first",
            "high": "max",
            "low": "min",
            "close": "last",
            "volume": "sum",
        })

    # sort and drop groups where there was absolutely no data (both open and close NaN)
    agg = agg.sort_index()
    keep_mask = ~(agg["open"].isna() & agg["close"].isna())
    agg = agg.loc[keep_mask]
    return agg


def align_multi_timeframes(df: pd.DataFrame, base_tf: str, target_tfs: Optional[List[str]] = None) -> Dict[str, pd.DataFrame]:
    """
    Resample `df` to base_tf and each target_tf and return a dict of DataFrames.
    Target TF DataFrames are reindexed to base index and forward-filled so each base bar
    has the current target bar value.
    """
    target_tfs = target_tfs or []
    if df is None or len(df) == 0:
        return {base_tf: pd.DataFrame(columns=["open","high","low","close","volume"])}

    base = resample_ohlcv(df, base_tf)
    out = {base_tf: base}

    for tf in target_tfs:
        tdf = resample_ohlcv(df, tf)
        # reindex to base index. If tdf empty, create NaN frame then reindex
        if tdf is None or len(tdf) == 0:
            aligned = pd.DataFrame(index=base.index, columns=["open","high","low","close","volume"])
        else:
            # reindex using forward-fill so each base row has most recent target bar
            aligned = tdf.reindex(base.index, method="ffill")
            aligned = aligned.loc[base.index]
        out[tf] = aligned
    return out


class MultiTimeframeWindow:
    """
    Holds raw dataframe and provides aligned snapshots.

    Usage:
       mtw = MultiTimeframeWindow(df, base_tf='1T', target_tfs=['5T'], window=10)
       snap = mtw.snapshot(lookback=10)  # returns dict of dataframes keyed by timeframe
    """
    def __init__(self, df: pd.DataFrame, base_tf: str = "1T", target_tfs: Optional[List[str]] = None, window: int = 200):
        self.df = df.copy() if df is not None else pd.DataFrame()
        self.base_tf = base_tf
        self.target_tfs = target_tfs or []
        self.window = int(window)

    def update(self, df: pd.DataFrame):
        self.df = df.copy()

    def snapshot(self, lookback: Optional[int] = None) -> Dict[str, pd.DataFrame]:
        lookback = int(lookback or self.window)
        if self.df is None or len(self.df) == 0:
            return {self.base_tf: pd.DataFrame(columns=["open","high","low","close","volume"])}
        aligned = align_multi_timeframes(self.df, self.base_tf, self.target_tfs)
        base = aligned.get(self.base_tf, pd.DataFrame())
        if len(base) < lookback:
            raise ValueError("not enough bars for requested lookback")
        start = len(base) - lookback
        idx = base.index[start:]
        result = {}
        for tf, df_tf in aligned.items():
            # ensure DataFrame exists for tf
            if df_tf is None:
                result[tf] = pd.DataFrame(index=idx, columns=["open","high","low","close","volume"])
            else:
                result[tf] = df_tf.loc[idx].copy()
        return result
