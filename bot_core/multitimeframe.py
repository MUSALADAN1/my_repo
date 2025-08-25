# bot_core/multitimeframe.py
"""
Multi-timeframe utilities: OHLCV resampling, alignment and a small window helper.

Functions provided:
  - resample_ohlcv(df, timeframe) -> DataFrame with columns: open, high, low, close, volume
  - align_multi_timeframes(df, base_tf, target_tfs) -> dict: { tf: df_resampled_aligned_to_base_index }
  - MultiTimeframeWindow: lightweight helper to hold a raw base-resolution frame and produce snapshots.

This implementation is defensive: accepts 'time' column, upper/lower case columns,
ensures DatetimeIndex, sorts, and reindexes target timeframes to the base timeframe index
(using forward-fill) so snapshots are aligned for multi-timeframe strategies.
"""
from typing import List, Dict, Optional
import pandas as pd
import numpy as np


def _ensure_datetime_index(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    if not isinstance(df.index, pd.DatetimeIndex):
        # prefer explicit 'time' column if present
        if "time" in df.columns:
            df.index = pd.to_datetime(df["time"])
        else:
            # try converting the existing index
            df.index = pd.to_datetime(df.index)
    # sort by index ascending
    df = df.sort_index()
    return df


def _normalize_ohlcv_columns(df: pd.DataFrame) -> pd.DataFrame:
    """
    Return a DataFrame with lowercased standard columns:
      'open','high','low','close','volume'
    If a column is missing we create an empty Series (NaN) for it.
    """
    df = df.copy()
    # map column lower -> original
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
    Resample a base-resolution OHLCV DataFrame into the requested timeframe.

    Args:
      df: DataFrame with datetime-like index (or 'time' column) and OHLCV-ish columns.
      timeframe: pandas offset alias, e.g. "5T" or "5min" (tests use "5T").

    Returns:
      DataFrame indexed by resampled period timestamps with columns:
      ['open','high','low','close','volume'].

    Notes:
      - We use label='left', closed='left' (bars open at left edge) which works well for
        aligning minute -> multi-minute bars in tests. Adjust if you prefer right-labeling.
    """
    if df is None or len(df) == 0:
        return pd.DataFrame(columns=["open", "high", "low", "close", "volume"])

    odf = _ensure_datetime_index(df)
    odf = _normalize_ohlcv_columns(odf)

    # Use resample aggregations explicitly
    # label='left' closed='left' so a 5-min bar starting at 00:00 covers [00:00,00:05)
    try:
        o = odf["open"].resample(timeframe, label="left", closed="left").first()
        h = odf["high"].resample(timeframe, label="left", closed="left").max()
        l = odf["low"].resample(timeframe, label="left", closed="left").min()
        c = odf["close"].resample(timeframe, label="left", closed="left").last()
        v = odf["volume"].resample(timeframe, label="left", closed="left").sum()
    except Exception:
        # fallback: compute grouping by flooring timestamps (more manual)
        group_keys = odf.index.floor(timeframe)
        grouped = odf.groupby(group_keys)
        o = grouped["open"].first()
        h = grouped["high"].max()
        l = grouped["low"].min()
        c = grouped["close"].last()
        v = grouped["volume"].sum()

    out = pd.DataFrame({"open": o, "high": h, "low": l, "close": c, "volume": v})
    # Drop any fully-empty bars (both open and close missing)
    mask = ~(out["open"].isna() & out["close"].isna())
    out = out.loc[mask]
    # ensure ascending index and return
    out = out.sort_index()
    return out


def align_multi_timeframes(df: pd.DataFrame, base_tf: str, target_tfs: List[str]) -> Dict[str, pd.DataFrame]:
    """
    Resample the provided df to base_tf and each target_tf, then align all target dfs to the
    base timeframe index.

    Returns a dict mapping timeframe -> resampled_dataframe_aligned_to_base_index

    Alignment policy:
      - Resampled base = resample_ohlcv(df, base_tf)
      - For each target: resample_ohlcv(df, target_tf) then reindex to base.index
        using forward-fill (method='ffill') so each base bar has the most recent target bar value.
    """
    if df is None or len(df) == 0:
        return {base_tf: pd.DataFrame(columns=["open", "high", "low", "close", "volume"])}

    base_res = resample_ohlcv(df, base_tf)
    result = {base_tf: base_res}

    for tf in (target_tfs or []):
        t_res = resample_ohlcv(df, tf)
        if t_res is None or len(t_res) == 0:
            # create empty df indexed as base but with NaNs
            aligned = pd.DataFrame(index=base_res.index, columns=["open", "high", "low", "close", "volume"])
        else:
            # we want each base timestamp to have corresponding target bar values
            # reindex target to base index using forward-fill to capture "latest available" target bar
            aligned = t_res.reindex(base_res.index, method="ffill")
            # if front rows are NaN after ffill (no earlier target bars), leave them as NaN
            aligned = aligned.loc[base_res.index]
        result[tf] = aligned

    return result


class MultiTimeframeWindow:
    """
    A small helper class holding a base-resolution DataFrame and providing aligned snapshots
    for multiple target timeframes.

    Example:
      mtw = MultiTimeframeWindow(df_minute, base_tf="1T", target_tfs=["5T","15T"], window=100)
      snap = mtw.snapshot(lookback=20)   # returns dict: { "1T": df_last20base, "5T": df_last20aligned, ... }
    """
    def __init__(self, df: pd.DataFrame, base_tf: str = "1T", target_tfs: Optional[List[str]] = None, window: int = 200):
        self.df = df.copy() if df is not None else pd.DataFrame()
        self.base_tf = base_tf
        self.target_tfs = target_tfs or []
        self.window = int(window)

    def update(self, df: pd.DataFrame):
        self.df = df.copy()

    def snapshot(self, lookback: Optional[int] = None) -> Dict[str, pd.DataFrame]:
        """
        Return the latest aligned snapshot across requested timeframes.
        lookback: number of base bars to include (defaults to the window size)
        """
        lookback = int(lookback or self.window)
        if self.df is None or len(self.df) == 0:
            return {self.base_tf: pd.DataFrame(columns=["open", "high", "low", "close", "volume"])}

        aligned = align_multi_timeframes(self.df, self.base_tf, self.target_tfs)
        base = aligned.get(self.base_tf, pd.DataFrame())
        if len(base) < lookback:
            raise ValueError("not enough bars for requested lookback")

        out = {}
        start = len(base) - lookback
        idx = base.index[start:]
        for tf, df_tf in aligned.items():
            # df_tf is already reindexed to base.index (for targets) or naturally base (for base_tf)
            # take the same last lookback rows for each timeframe (so they align by row)
            out[tf] = df_tf.loc[idx].copy()
        return out
