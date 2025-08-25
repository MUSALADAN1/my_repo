# bot_core/multitimeframe.py
"""
Multi-timeframe utilities.

Provides:
 - resample_ohlcv(df, timeframe): resample an OHLCV DataFrame to a coarser timeframe.
 - align_multi_timeframes(df, base_tf, target_tfs): return dict of aligned dataframes
   keyed by timeframe. The alignment uses the base timeframe's index as the driving axis.
 - MultiTimeframeWindow: helper to request synchronized windows (sliding) across TFs.

Defensive behaviour:
 - If df doesn't have a DatetimeIndex, attempts to find a time column (time,timestamp,datetime,date)
   and convert it to a DatetimeIndex.
 - If the index contains duplicates they are collapsed (last occurrence kept) and index is sorted.
 - If OHLCV columns are aligned by position but have different index, alignment by position is used.
"""
from typing import Dict, List, Optional
import pandas as pd


# -------------------------
# Helpers
# -------------------------
def _find_time_column(df: pd.DataFrame) -> Optional[str]:
    """Try common time-like column names."""
    candidates = ["time", "timestamp", "datetime", "date", "ts"]
    for c in candidates:
        if c in df.columns:
            return c
    return None


def _ensure_datetime_index(df: pd.DataFrame) -> pd.DataFrame:
    """
    Ensure DataFrame has a proper DatetimeIndex.

    - If df.index is already DatetimeIndex, we sort & drop duplicates (keep last).
    - Otherwise try to find common time column and set it as index (converted to datetime).
    - Raises ValueError if no datetime can be found.
    """
    if isinstance(df.index, pd.DatetimeIndex):
        # make a copy to avoid mutating original passed object accidentally
        df2 = df.copy()
        # drop duplicate timestamps keeping last (avoid resample confusion)
        if df2.index.duplicated().any():
            df2 = df2[~df2.index.duplicated(keep="last")]
        df2 = df2.sort_index()
        return df2

    # try to find a time-like column
    time_col = _find_time_column(df)
    if time_col:
        df2 = df.copy()
        df2[time_col] = pd.to_datetime(df2[time_col])
        df2 = df2.set_index(time_col)
        # drop duplicate timestamps
        if df2.index.duplicated().any():
            df2 = df2[~df2.index.duplicated(keep="last")]
        df2 = df2.sort_index()
        return df2

    # last attempt: try to coerce index to datetime if it has datetime-like dtype
    try:
        idx = pd.to_datetime(df.index)
        df2 = df.copy()
        df2.index = idx
        if df2.index.duplicated().any():
            df2 = df2[~df2.index.duplicated(keep="last")]
        df2 = df2.sort_index()
        return df2
    except Exception:
        raise ValueError("DataFrame must have a DatetimeIndex or a time-like column (time,timestamp,datetime,date).")


def _ensure_ohlcv_columns(df: pd.DataFrame) -> pd.DataFrame:
    """
    Verify required OHLC columns exist in the DataFrame. We do NOT strictly require 'volume'.
    """
    for required in ["open", "high", "low", "close"]:
        if required not in df.columns:
            raise ValueError(f"DataFrame missing required OHLC column: {required}")
    return df


def _align_series_to_index(s: pd.Series, index: pd.Index) -> pd.Series:
    """
    Return a series aligned to `index`. If s.index equals index, return s.
    If s has the same length but different index, align by position (take s.values).
    Otherwise attempt reindex (which will align by label).
    """
    if not isinstance(s, pd.Series):
        # construct series from iterable by position
        return pd.Series(list(s), index=index).astype(float)

    # exact index match -> keep as-is
    if s.index.equals(index):
        return s.astype(float)

    # same length but different index -> align by position
    if len(s) == len(index):
        return pd.Series(s.values, index=index, name=s.name).astype(float)

    # fallback: reindex by label (may introduce NaNs)
    return s.reindex(index).astype(float)


# -------------------------
# Resampling
# -------------------------
def resample_ohlcv(df: pd.DataFrame, timeframe: str, how_volume: str = "sum") -> pd.DataFrame:
    """
    Resample a high-frequency OHLCV DataFrame to a coarser timeframe.

    Parameters:
      - df: DataFrame with DatetimeIndex or time column, cols open, high, low, close, (volume optional)
      - timeframe: pandas offset alias like '5T', '15T', '1H'
      - how_volume: aggregation for volume ('sum' or 'mean')

    Returns:
      DataFrame indexed by resampled period end (pandas default).
    """
    if df is None or df.empty:
        return pd.DataFrame(columns=["open", "high", "low", "close", "volume"])

    # ensure df has datetime index and required columns
    df = _ensure_datetime_index(df)
    df = _ensure_ohlcv_columns(df)

    idx = df.index
    o_s = _align_series_to_index(df["open"], idx)
    h_s = _align_series_to_index(df["high"], idx)
    l_s = _align_series_to_index(df["low"], idx)
    c_s = _align_series_to_index(df["close"], idx)
    if "volume" in df.columns:
        v_s = _align_series_to_index(df["volume"], idx)
    else:
        v_s = pd.Series(0.0, index=idx, name="volume", dtype=float)

    # Use pandas resample on these aligned series
    o = o_s.resample(timeframe).first()
    h = h_s.resample(timeframe).max()
    l = l_s.resample(timeframe).min()
    c = c_s.resample(timeframe).last()

    if how_volume == "sum":
        v = v_s.resample(timeframe).sum()
    else:
        v = v_s.resample(timeframe).mean()

    out = pd.DataFrame({"open": o, "high": h, "low": l, "close": c, "volume": v})

    # Drop empty groups (periods with NaN close)
    out = out.dropna(subset=["close"])
    return out


# -------------------------
# Alignment across TFs
# -------------------------
def align_multi_timeframes(df: pd.DataFrame, base_tf: str, target_tfs: List[str]) -> Dict[str, pd.DataFrame]:
    """
    Given a high-frequency df and a base timeframe string (e.g., '5T'), resample the df to:
       - base_tf (if different from input freq)
       - each target_tfs value (coarser)
    Then align each resampled frame to the base_tf index by backward-lookup so each base bar
    has the corresponding coarser bar.

    Returns a dict mapping timeframe -> DataFrame aligned to base index.
    """
    if df is None or df.empty:
        return {tf: pd.DataFrame(columns=["open", "high", "low", "close", "volume"]) for tf in [base_tf] + target_tfs}

    # ensure datetime index
    df = _ensure_datetime_index(df)
    base_df = resample_ohlcv(df, base_tf)
    aligned: Dict[str, pd.DataFrame] = {base_tf: base_df}

    for tf in target_tfs:
        if tf == base_tf:
            aligned[tf] = base_df
            continue
        res = resample_ohlcv(df, tf).sort_index()
        base_index = base_df.index.sort_values()

        # left: base times; right: coarser resampled times
        left = pd.DataFrame(index=base_index).reset_index().rename(columns={"index": "time"})
        right = res.reset_index().rename(columns={"index": "time"})

        # merge_asof will pick the latest coarser bar <= base bar time
        merged = pd.merge_asof(left, right, on="time", direction="backward")
        merged = merged.set_index("time")

        # ensure columns
        for col in ["open", "high", "low", "close", "volume"]:
            if col not in merged.columns:
                merged[col] = pd.NA

        merged = merged[["open", "high", "low", "close", "volume"]]
        aligned[tf] = merged

    return aligned


# -------------------------
# MultiTimeframeWindow
# -------------------------
class MultiTimeframeWindow:
    """
    Helper for sliding synchronized windows across multiple timeframes.

    Usage:
        mtw = MultiTimeframeWindow(df, base_tf="5T", target_tfs=["15T","1H"], window=20)
        for w in mtw.windows():  # yields dict: {"5T": df5, "15T": df15, "1H": df1h}
            ... process
    """
    def __init__(self, df: pd.DataFrame, base_tf: str, target_tfs: Optional[List[str]] = None, window: int = 50):
        self.df = df
        self.base_tf = base_tf
        self.target_tfs = target_tfs or []
        self.window = int(window)

    def windows(self):
        all_tfs = [self.base_tf] + self.target_tfs
        aligned = align_multi_timeframes(self.df, self.base_tf, self.target_tfs)
        base_df = aligned[self.base_tf]

        # iterate over rolling windows on base index
        for i in range(self.window, len(base_df) + 1):
            window_base = base_df.iloc[i - self.window:i].copy()
            out = {}
            for tf in all_tfs:
                df_tf = aligned[tf].loc[window_base.index].copy()
                out[tf] = df_tf
            yield out

    def snapshot(self, lookback: Optional[int] = None):
        """
        Return a single snapshot (latest window) aligned across timeframes.
        """
        lookback = lookback or self.window
        aligned = align_multi_timeframes(self.df, self.base_tf, self.target_tfs)
        base = aligned[self.base_tf]
        if len(base) < lookback:
            raise ValueError("not enough bars for requested lookback")
        window_base = base.iloc[-lookback:]
        out = {}
        for tf in [self.base_tf] + self.target_tfs:
            out[tf] = aligned[tf].loc[window_base.index].copy()
        return out
