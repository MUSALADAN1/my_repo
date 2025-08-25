# bot_core/multitimeframe.py
"""
Multi-timeframe utilities: resample OHLCV, align multiple timeframes, and
a small MultiTimeframeWindow to produce aligned snapshots for strategy inputs.

Functions / classes:
  - resample_ohlcv(df, timeframe) -> DataFrame with open/high/low/close/volume
  - align_multi_timeframes(df, base_tf, target_tfs) -> dict{tf: df_resampled}
  - MultiTimeframeWindow(df, base_tf, target_tfs, window) -> snapshot/lookups
"""
from typing import List, Dict, Optional
import pandas as pd
import numpy as np


def _ensure_datetime_index(df: pd.DataFrame) -> pd.DataFrame:
    """
    Make sure df has a sorted DatetimeIndex. Accepts:
      - df already having a DatetimeIndex
      - df having a 'time' / 'timestamp' / 'datetime' column
      - otherwise try to coerce the existing index to datetime
    Returns a copy with a DatetimeIndex.
    """
    if not isinstance(df, pd.DataFrame):
        raise ValueError("expected a pandas DataFrame")

    df = df.copy()

    # prefer explicit time-like column
    time_candidates = [c for c in ("time", "timestamp", "datetime", "date", "ts") if c in df.columns]
    if time_candidates:
        col = time_candidates[0]
        df.index = pd.to_datetime(df[col])
        df = df.drop(columns=[col], errors="ignore")
    else:
        # if index already datetime-like, keep it; otherwise try to convert
        if not isinstance(df.index, pd.DatetimeIndex):
            try:
                df.index = pd.to_datetime(df.index)
            except Exception:
                # last resort: try a 'time' field inside object columns
                raise ValueError("DataFrame must have a datetime-like index or a time/timestamp column")

    # drop rows with NaT index and sort by index
    df = df[~df.index.isna()]
    df = df.sort_index()
    return df


def _ensure_ohlcv_columns(df: pd.DataFrame) -> pd.DataFrame:
    """
    Ensure the DataFrame contains the canonical OHLCV columns.
    If columns exist in different case, attempt case-insensitive match.
    """
    df = df.copy()

    # canonical names we want
    wanted = ["open", "high", "low", "close", "volume"]
    colmap = {}
    lower_map = {c.lower(): c for c in df.columns}

    for w in wanted:
        if w in df.columns:
            colmap[w] = w
        elif w in lower_map:
            colmap[w] = lower_map[w]
        else:
            # allow missing volume (set zeros)
            if w == "volume":
                df["volume"] = 0.0
                colmap["volume"] = "volume"
            else:
                raise ValueError(f"missing required OHLC column: {w}")

    # rename into canonical names
    df = df.rename(columns={colmap[k]: k for k in colmap if colmap[k] != k})
    # coerce numeric
    for k in wanted:
        df[k] = pd.to_numeric(df[k], errors="coerce")
    return df[wanted]


def resample_ohlcv(df: pd.DataFrame, timeframe: str) -> pd.DataFrame:
    """
    Resample minute/bar-level OHLCV DataFrame to another timeframe.

    Args:
      df: DataFrame indexed by datetime (or with 'time' column) with open/high/low/close/volume.
      timeframe: pandas offset alias, e.g. "5T", "1H", "15min", etc.

    Returns:
      DataFrame indexed by DatetimeIndex (resample labels) with columns open,high,low,close,volume.

    Notes:
      - The function sorts by time and drops fully-empty bars.
      - Uses left-labeled, left-closed bins to align with the tests' expectations.
    """
    if df is None or len(df) == 0:
        return pd.DataFrame(columns=["open", "high", "low", "close", "volume"])

    df = _ensure_datetime_index(df)
    df = _ensure_ohlcv_columns(df)

    # Use left-labeled, left-closed bins (so a 00:00-00:04 group is labeled 00:00 for "5T").
    # This tends to match the way many synthetic test DataFrames are constructed.
    try:
        o = df["open"].resample(timeframe, label="left", closed="left").first()
        h = df["high"].resample(timeframe, label="left", closed="left").max()
        l = df["low"].resample(timeframe, label="left", closed="left").min()
        c = df["close"].resample(timeframe, label="left", closed="left").last()
        v = df["volume"].resample(timeframe, label="left", closed="left").sum()
    except Exception:
        # Fallback for older pandas or if label/closed args are not supported
        o = df["open"].resample(timeframe).first()
        h = df["high"].resample(timeframe).max()
        l = df["low"].resample(timeframe).min()
        c = df["close"].resample(timeframe).last()
        v = df["volume"].resample(timeframe).sum()

    res = pd.concat([o, h, l, c, v], axis=1)
    res.columns = ["open", "high", "low", "close", "volume"]

    # Drop bars that have no price information (both open and close NaN)
    res = res.dropna(how="all", subset=["open", "close"])
    return res



def align_multi_timeframes(df: pd.DataFrame, base_tf: str, target_tfs: List[str]) -> Dict[str, pd.DataFrame]:
    """
    Produce resampled, aligned DataFrames for base and each target timeframe.

    Returns a dict keyed by timeframe string. Each value is a resampled OHLCV DataFrame.
    The base timeframe's index will be used as the alignment index (i.e., other
    frames are reindexed to base index using forward/backward fill for price
    columns where appropriate).

    This is intentionally conservative: when reindexing, it forward-fills last
    known OHLC price into the label (so a higher timeframe's last bar value will
    be available aligned to the base timeframe's tick).
    """
    if df is None or len(df) == 0:
        return {base_tf: pd.DataFrame(columns=["open", "high", "low", "close", "volume"])}

    df = _ensure_datetime_index(df)
    # resample base
    frames: Dict[str, pd.DataFrame] = {}
    frames[base_tf] = resample_ohlcv(df, base_tf)

    # for each target, resample and reindex to the base index
    base_index = frames[base_tf].index

    for tf in target_tfs:
        r = resample_ohlcv(df, tf)
        if r.empty:
            # create empty with same index as base
            frames[tf] = pd.DataFrame(index=base_index, columns=["open", "high", "low", "close", "volume"])
            continue
        # Reindex target to base index using 'ffill' for price columns and 0 for volume
        # First expand r to include base timestamps
        r_expanded = r.reindex(sorted(r.index.union(base_index)))
        # Forward fill prices (carry last bar forward)
        r_ffill = r_expanded.ffill()
        # Now select rows corresponding to base_index
        r_aligned = r_ffill.reindex(base_index)
        # volume: since volume is per target bar, we don't have a meaningful per-base volume.
        # We'll fill NaN with 0 for volume.
        if "volume" in r_aligned.columns:
            r_aligned["volume"] = r_aligned["volume"].fillna(0.0)
        frames[tf] = r_aligned[["open", "high", "low", "close", "volume"]]

    return frames


class MultiTimeframeWindow:
    """
    Wrapper around a single OHLCV DataFrame to produce aligned snapshots across timeframes.

    Usage:
      mtw = MultiTimeframeWindow(df, base_tf="1T", target_tfs=["5T","15T"], window=50)
      snap = mtw.snapshot(lookback=20)
      # snap is dict: {"1T": df_base_last20, "5T": df_5T_aligned_last20, ...}
    """

    def __init__(self, df: pd.DataFrame, base_tf: str = "1T", target_tfs: Optional[List[str]] = None, window: int = 100):
        self.df = _ensure_datetime_index(df) if (df is not None and len(df) > 0) else pd.DataFrame()
        self.base_tf = base_tf
        self.target_tfs = target_tfs or []
        self.window = int(window)

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

        out: Dict[str, pd.DataFrame] = {}
        # slice last lookback bars (chronological)
        base_tail = base.iloc[-lookback:].copy()
        out[self.base_tf] = base_tail

        # for each target tf, take the corresponding rows aligned to the base tail index
        for tf in self.target_tfs:
            tf_df = aligned.get(tf, pd.DataFrame())
            # If the aligned tf has the same index as base, just take last lookback rows
            if isinstance(tf_df.index, pd.DatetimeIndex):
                tf_tail = tf_df.reindex(base_tail.index).copy()
            else:
                tf_tail = tf_df.iloc[-lookback:].copy()
                tf_tail.index = base_tail.index  # best-effort mapping
            out[tf] = tf_tail

        return out

    def window_slice(self, end_time=None, lookback: Optional[int] = None) -> Dict[str, pd.DataFrame]:
        """
        Alternative: allow requesting a slice that ends at end_time (datetime-like) and spans lookback bars.
        If end_time is None it uses the latest available index.
        """
        lookback = int(lookback or self.window)
        if self.df is None or len(self.df) == 0:
            return {self.base_tf: pd.DataFrame(columns=["open", "high", "low", "close", "volume"])}

        aligned = align_multi_timeframes(self.df, self.base_tf, self.target_tfs)
        base = aligned.get(self.base_tf, pd.DataFrame())
        if base.empty:
            return {self.base_tf: base}

        if end_time is None:
            end_idx = base.index[-1]
        else:
            end_idx = pd.to_datetime(end_time)
            # find nearest timestamp <= end_idx
            idxs = base.index[base.index <= end_idx]
            if len(idxs) == 0:
                raise ValueError("end_time is before available data")
            end_idx = idxs[-1]

        # find starting index
        pos = base.index.get_indexer([end_idx], method="ffill")[0]
        start_pos = max(0, pos - lookback + 1)
        base_slice = base.iloc[start_pos: pos + 1].copy()
        out = {self.base_tf: base_slice}
        for tf in self.target_tfs:
            tf_df = aligned.get(tf, pd.DataFrame())
            tf_slice = tf_df.reindex(base_slice.index).copy()
            out[tf] = tf_slice
        return out
