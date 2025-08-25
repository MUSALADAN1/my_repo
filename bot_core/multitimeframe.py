# bot_core/multitimeframe.py
"""
Multi-timeframe utilities: OHLCV resampling, alignment and a small window helper.

This implementation is defensive:
 - accepts 'time' column or a DatetimeIndex
 - normalizes column names (case-insensitive)
 - uses pd.Grouper for robust grouping; falls back to index.floor grouping
 - reindexes target timeframes to base timeframe index using forward-fill
"""
from typing import List, Dict, Optional
import pandas as pd
import numpy as np


def _ensure_datetime_index(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    if not isinstance(df.index, pd.DatetimeIndex):
        if "time" in df.columns:
            df.index = pd.to_datetime(df["time"])
        else:
            df.index = pd.to_datetime(df.index)
    df = df.sort_index()
    return df


def _normalize_ohlcv_columns(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    col_map = {c.lower(): c for c in df.columns}
    cols = {}
    for name in ("open", "high", "low", "close", "volume"):
        if name in col_map:
            cols[name] = df[col_map[name]].astype(float)
        else:
            cols[name] = pd.Series(index=df.index, dtype=float)
    out = pd.DataFrame(cols, index=df.index)
    return out


def resample_ohlcv(df: pd.DataFrame, timeframe: str) -> pd.DataFrame:
    """
    Resample OHLCV DataFrame to the given timeframe (pandas freq string).
    Returns DataFrame with columns ['open','high','low','close','volume'] indexed by period start.
    """
    if df is None or len(df) == 0:
        return pd.DataFrame(columns=["open", "high", "low", "close", "volume"])

    odf = _ensure_datetime_index(df)
    odf = _normalize_ohlcv_columns(odf)

    # Primary attempt: use pd.Grouper (robust across index types)
    try:
        grouped = odf.groupby(pd.Grouper(freq=timeframe, label="left", closed="left"))
        o = grouped["open"].first()
        h = grouped["high"].max()
        l = grouped["low"].min()
        c = grouped["close"].last()
        v = grouped["volume"].sum()
        out = pd.DataFrame({"open": o, "high": h, "low": l, "close": c, "volume": v})
    except Exception:
        # Fallback: group by index.floor(timeframe)
        group_keys = odf.index.floor(timeframe)
        grouped = odf.groupby(group_keys)
        o = grouped["open"].first()
        h = grouped["high"].max()
        l = grouped["low"].min()
        c = grouped["close"].last()
        v = grouped["volume"].sum()
        out = pd.DataFrame({"open": o, "high": h, "low": l, "close": c, "volume": v})
        # ensure proper index type
        out.index = pd.to_datetime(out.index)

    # Drop bars which have no meaningful OHLC (both open and close missing)
    out = out.sort_index()
    mask_keep = ~(out["open"].isna() & out["close"].isna())
    out = out.loc[mask_keep]
    return out


def align_multi_timeframes(df: pd.DataFrame, base_tf: str, target_tfs: List[str]) -> Dict[str, pd.DataFrame]:
    """
    Resample df to base_tf and each target_tf, then align targets to base index (ffill).
    Returns dict: { base_tf: df_base, target_tf: df_target_aligned_to_base_index, ... }
    """
    if df is None or len(df) == 0:
        return {base_tf: pd.DataFrame(columns=["open", "high", "low", "close", "volume"])}

    base_res = resample_ohlcv(df, base_tf)
    result = {base_tf: base_res}

    for tf in (target_tfs or []):
        t_res = resample_ohlcv(df, tf)
        if t_res is None or len(t_res) == 0:
            aligned = pd.DataFrame(index=base_res.index, columns=["open", "high", "low", "close", "volume"])
        else:
            # Reindex the target to base index using forward-fill to provide latest target bar for each base bar
            aligned = t_res.reindex(base_res.index, method="ffill")
            aligned = aligned.loc[base_res.index]
        result[tf] = aligned

    return result


class MultiTimeframeWindow:
    """
    Helper holding a raw (base-resolution) df and providing aligned snapshots.
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
            return {self.base_tf: pd.DataFrame(columns=["open", "high", "low", "close", "volume"])}

        aligned = align_multi_timeframes(self.df, self.base_tf, self.target_tfs)
        base = aligned.get(self.base_tf, pd.DataFrame())
        if len(base) < lookback:
            raise ValueError("not enough bars for requested lookback")

        start = len(base) - lookback
        idx = base.index[start:]
        out = {}
        for tf, df_tf in aligned.items():
            # For target tfs, df_tf is already reindexed to base.index (or NaN where no data)
            out[tf] = df_tf.loc[idx].copy()
        return out
