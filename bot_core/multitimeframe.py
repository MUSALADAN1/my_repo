# bot_core/multitimeframe.py
"""
Multi-timeframe helper utilities.

Provides:
 - resample_ohlcv(df, timeframe) -> DataFrame aggregated to timeframe
 - align_multi_timeframes(df, base_tf, target_tfs) -> dict {tf: df}
 - MultiTimeframeWindow class for sliding-window snapshots across multiple TFs

Design goals:
 - defensive: tolerate missing 'open'/'close' columns (use high/low fallbacks)
 - do not drop buckets just because open/close are NaN if other OHLCV data exist
 - return consistent columns: ['open','high','low','close','volume']
"""
from typing import Dict, List, Optional
import pandas as pd
import numpy as np


DEFAULT_COLUMNS = ["open", "high", "low", "close", "volume"]


def _ensure_datetime_index(df: pd.DataFrame) -> pd.DataFrame:
    # Copy so we don't mutate caller
    odf = df.copy()
    # If 'time' column exists, prefer that (many OHLC loaders use 'time' column)
    if "time" in odf.columns and not isinstance(odf.index, pd.DatetimeIndex):
        try:
            odf = odf.set_index(pd.to_datetime(odf["time"]))
        except Exception:
            # fallthrough: try to coerce existing index
            pass
    if not isinstance(odf.index, pd.DatetimeIndex):
        try:
            odf.index = pd.to_datetime(odf.index)
        except Exception:
            raise ValueError("DataFrame must have a DatetimeIndex or a parseable 'time' column")
    # ensure index is monotonic increasing
    if not odf.index.is_monotonic_increasing:
        odf = odf.sort_index()
    return odf


def _ensure_ohlcv_cols(df: pd.DataFrame) -> pd.DataFrame:
    """
    Ensure the DataFrame has at least the 5 OHLCV columns (may be NaN).
    If columns are named slightly differently, try to map common variants.
    """
    odf = df.copy()
    cols = set(odf.columns)
    # simple mapping attempts
    mapping = {}
    if "vw" in cols and "volume" not in cols:
        mapping["vw"] = "volume"
    if "timestamp" in cols and "time" not in cols:
        mapping["timestamp"] = "time"
    if "bid" in cols and "close" not in cols:
        # don't aggressively remap, leave as-is
        pass
    if mapping:
        odf = odf.rename(columns=mapping)
    for c in DEFAULT_COLUMNS:
        if c not in odf.columns:
            odf[c] = np.nan
    # keep only the default columns (plus any others we don't need)
    odf = odf[[c for c in odf.columns if c in DEFAULT_COLUMNS]]
    return odf


def resample_ohlcv(df: pd.DataFrame, timeframe: str) -> pd.DataFrame:
    """
    Resample an OHLCV DataFrame (with datetime index) into a larger timeframe.

    Returns a DataFrame with columns: ['open','high','low','close','volume'].
    Does NOT drop buckets just because 'open'/'close' are NaN: it will
    attempt to backfill open/close sensibly from high/low/close when possible.

    timeframe: pandas offset alias like "5T", "1H", etc.
    """
    if df is None or len(df) == 0:
        return pd.DataFrame(columns=DEFAULT_COLUMNS)

    odf = _ensure_datetime_index(df)
    odf = _ensure_ohlcv_cols(odf)

    # Resample aggregation (label left, closed left is a reasonable default for OHLCV)
    # Use first/last for open/close; high=max, low=min, volume=sum
    try:
        agg = odf.resample(timeframe, label="left", closed="left").agg({
            "open": "first",
            "high": "max",
            "low": "min",
            "close": "last",
            "volume": "sum",
        })
    except Exception:
        # fallback to a safer grouping by flooring timestamps (handles odd indexes)
        group_keys = odf.index.floor(timeframe)
        grouped = odf.groupby(group_keys)
        agg = pd.DataFrame({
            "open": grouped["open"].first(),
            "high": grouped["high"].max(),
            "low": grouped["low"].min(),
            "close": grouped["close"].last(),
            "volume": grouped["volume"].sum(),
        })
        agg.index.name = odf.index.name

    # if open/close are entirely NaN for a bucket but high/low exist, attempt to compute fallbacks
    # open fallback: first non-na among open, close, high, low (in that order)
    # close fallback: last non-na among close, open, high, low (in that order)
    if len(agg) == 0:
        return agg[DEFAULT_COLUMNS]

    # prepare helpers: compute first/last valid within each resampled bucket
    # This ensures open/close are filled if the original per-row open/close were NaN.
    first_vals = odf.resample(timeframe, label="left", closed="left").first()
    last_vals = odf.resample(timeframe, label="left", closed="left").last()

    # Fill open: prefer aggregated open, else first_vals['close'], else first_vals['high'], else first_vals['low']
    agg["open"] = agg["open"].combine_first(first_vals.get("open"))
    agg["open"] = agg["open"].combine_first(first_vals.get("close"))
    agg["open"] = agg["open"].combine_first(first_vals.get("high"))
    agg["open"] = agg["open"].combine_first(first_vals.get("low"))

    # Fill close: prefer aggregated close, else last_vals['close'], else last_vals['open'], else last_vals['high']
    agg["close"] = agg["close"].combine_first(last_vals.get("close"))
    agg["close"] = agg["close"].combine_first(last_vals.get("open"))
    agg["close"] = agg["close"].combine_first(last_vals.get("high"))
    agg["close"] = agg["close"].combine_first(last_vals.get("low"))

    # If still NaN open/close but high/low exist, fallback to high/low
    agg["open"] = agg["open"].fillna(agg["high"]).fillna(agg["low"])
    agg["close"] = agg["close"].fillna(agg["high"]).fillna(agg["low"])

    # Only drop rows where all OHLCV are NaN (we want buckets where high/low/volume exist to survive)
    agg = agg.dropna(how="all", subset=DEFAULT_COLUMNS)

    # Ensure correct column order and dtypes
    agg = agg.reindex(columns=DEFAULT_COLUMNS)
    return agg


def align_multi_timeframes(df: pd.DataFrame, base_tf: str, target_tfs: List[str]) -> Dict[str, pd.DataFrame]:
    """
    Resample `df` into base_tf and each target tf, and *align* the target frames to the
    base index. The returned dict maps timeframe -> DataFrame where every DataFrame
    shares the same index as the base timeframe (one row per base bar).
    """
    out: Dict[str, pd.DataFrame] = {}

    # handle empty input quickly
    if df is None or len(df) == 0:
        for tf in [base_tf] + list(target_tfs):
            out[tf] = pd.DataFrame(columns=DEFAULT_COLUMNS)
        return out

    # resample base tf
    base_df = resample_ohlcv(df, base_tf)
    out[base_tf] = base_df

    # if base is empty, simply produce empty frames for targets too
    base_index = base_df.index
    if len(base_index) == 0:
        for tf in target_tfs:
            out[tf] = pd.DataFrame(columns=DEFAULT_COLUMNS)
        return out

    # build each target frame and align to base_index
    for tf in target_tfs:
        tf_df = resample_ohlcv(df, tf)

        # if target resample returned nothing, create empty frame indexed as base_index
        if tf_df is None or len(tf_df) == 0:
            out[tf] = pd.DataFrame(index=base_index, columns=DEFAULT_COLUMNS)
            continue

        # create the bucket keys corresponding to each base timestamp:
        # for each base timestamp t, bucket_key = floor(t, tf)
        try:
            bucket_keys = base_index.floor(tf)
        except Exception:
            # fallback: explicit loop floor
            bucket_keys = pd.DatetimeIndex([pd.Timestamp(ts).floor(tf) for ts in base_index])

        # reindex target tf dataframe to those bucket keys so there's one row per base bar
        # then restore the index to the original base timestamps
        aligned = tf_df.reindex(bucket_keys)
        aligned.index = base_index
        # ensure correct columns and order
        aligned = aligned.reindex(columns=DEFAULT_COLUMNS)
        out[tf] = aligned

    return out


class MultiTimeframeWindow:
    """
    Maintains a dataframe and provides aligned snapshots across multiple timeframes.

    Usage:
      mtw = MultiTimeframeWindow(df, base_tf="1T", target_tfs=["5T","15T"], window=50)
      snap = mtw.snapshot(lookback=20)  # returns dict { "1T": df_base_last20, "5T": df_5T_last4, ... }
    """
    def __init__(self, df: Optional[pd.DataFrame] = None, base_tf: str = "1T",
                 target_tfs: Optional[List[str]] = None, window: int = 100):
        self.df = df.copy() if (df is not None) else pd.DataFrame()
        self.base_tf = base_tf
        self.target_tfs = list(target_tfs or [])
        self.window = int(window)

    def update(self, df: pd.DataFrame):
        """Replace internal dataframe."""
        self.df = df.copy()

    def snapshot(self, lookback: Optional[int] = None) -> Dict[str, pd.DataFrame]:
        """
        Return the latest aligned snapshot across requested timeframes.
        lookback: number of base bars to include (defaults to the window size)
        The returned frames all share the same index (the base timeframe) and length == lookback.
        """
        lookback = int(lookback or self.window)
        if self.df is None or len(self.df) == 0:
            return {self.base_tf: pd.DataFrame(columns=DEFAULT_COLUMNS)}

        aligned = align_multi_timeframes(self.df, self.base_tf, self.target_tfs)
        base = aligned.get(self.base_tf, pd.DataFrame())

        if len(base) < lookback:
            raise ValueError("not enough bars for requested lookback")

        # base tail (last `lookback` base bars)
        base_tail = base.iloc[-lookback:].copy()
        res: Dict[str, pd.DataFrame] = {self.base_tf: base_tail}

        # For each target tf we already aligned rows to base index in align_multi_timeframes,
        # so just slice using the base_tail index range (preserves 1:1 per-base mapping).
        start_ts = base_tail.index[0]
        end_ts = base_tail.index[-1]
        for tf in self.target_tfs:
            tf_df = aligned.get(tf, pd.DataFrame(columns=DEFAULT_COLUMNS))
            # ensure it's reindexed to base index length; if not, attempt to re-align
            if not tf_df.index.equals(base.index):
                # fallback: re-align quickly (same logic as align_multi_timeframes)
                try:
                    bucket_keys = base.index.floor(tf)
                except Exception:
                    bucket_keys = pd.DatetimeIndex([pd.Timestamp(ts).floor(tf) for ts in base.index])
                tf_df = tf_df.reindex(bucket_keys)
                tf_df.index = base.index
                tf_df = tf_df.reindex(columns=DEFAULT_COLUMNS)

            # slice to the base_tail timestamps (preserves same length = lookback)
            res[tf] = tf_df.loc[start_ts:end_ts].copy()

        return res
