# bot_core/multitimeframe.py
"""
Multi-timeframe utilities.

Provides:
 - resample_ohlcv(df, timeframe): resample an OHLCV DataFrame to a coarser timeframe.
 - align_multi_timeframes(df, base_tf, target_tfs): return dict of aligned dataframes
   keyed by timeframe. The alignment uses the base timeframe's index as the driving axis.
 - MultiTimeframeWindow: helper to request synchronized windows (sliding) across TFs.

Assumptions:
 - Input `df` is a pandas.DataFrame with a DatetimeIndex and at least columns: ['open','high','low','close','volume']
 - Timeframe strings are compatible with pandas offset aliases (e.g., '5T', '15T', '1H', '1D').
"""

from typing import Dict, List, Optional
import pandas as pd


def _ensure_ohlcv_columns(df: pd.DataFrame) -> pd.DataFrame:
    # Keep only relevant columns and ensure they exist; avoid failing when volume missing.
    cols = {c: c for c in df.columns}
    for required in ["open", "high", "low", "close"]:
        if required not in df.columns:
            raise ValueError(f"DataFrame missing required OHLC column: {required}")
    # volume optional
    return df


def resample_ohlcv(df: pd.DataFrame, timeframe: str, how_volume: str = "sum") -> pd.DataFrame:
    """
    Resample a high-frequency OHLCV DataFrame to a coarser timeframe.

    Parameters:
      - df: DataFrame with DatetimeIndex and columns open, high, low, close, (volume optional)
      - timeframe: pandas offset alias like '5T', '15T', '1H'
      - how_volume: aggregation for volume ('sum' or 'mean')

    Returns:
      DataFrame indexed by resampled period end (pandas default).
    """
    if df is None or df.empty:
        return pd.DataFrame(columns=["open", "high", "low", "close", "volume"])

    df = _ensure_ohlcv_columns(df)

    o = df["open"].resample(timeframe).first()
    h = df["high"].resample(timeframe).max()
    l = df["low"].resample(timeframe).min()
    c = df["close"].resample(timeframe).last()

    if "volume" in df.columns:
        if how_volume == "sum":
            v = df["volume"].resample(timeframe).sum()
        else:
            v = df["volume"].resample(timeframe).mean()
    else:
        v = pd.Series(index=o.index, data=0.0, name="volume")

    out = pd.DataFrame({"open": o, "high": h, "low": l, "close": c, "volume": v})
    # Drop empty groups (periods with NaN close)
    out = out.dropna(subset=["close"])
    return out


def align_multi_timeframes(df: pd.DataFrame, base_tf: str, target_tfs: List[str]) -> Dict[str, pd.DataFrame]:
    """
    Given a high-frequency df and a base timeframe string (e.g., '5T'), resample the df to:
       - base_tf (if different from input freq)
       - each target_tfs value (coarser)
    Then align each resampled frame to the base_tf index by forward-filling the coarser bars
    so each base bar has an associated coarser bar value.

    Returns a dict mapping timeframe -> DataFrame aligned to base index.
    """
    if df is None or df.empty:
        return {tf: pd.DataFrame(columns=["open", "high", "low", "close", "volume"]) for tf in [base_tf] + target_tfs}

    # Resample to base timeframe first (use last period convention)
    base_df = resample_ohlcv(df, base_tf)
    aligned: Dict[str, pd.DataFrame] = {base_tf: base_df}

    # For each target timeframe, resample and reindex to base index using forward/back fill strategy.
    for tf in target_tfs:
        if tf == base_tf:
            aligned[tf] = base_df
            continue
        res = resample_ohlcv(df, tf)
        # we want to map each base timestamp to the most recent coarser bar that includes it.
        # resampled bars are at period end; we can reindex using asof (merge_asof) or forward-fill after reindex.
        # Convert index to series to allow merge_asof
        res = res.sort_index()
        base_index = base_df.index.sort_values()
        # create DataFrame with base_index to left-join via merge_asof
        left = pd.DataFrame(index=base_index)
        left = left.reset_index().rename(columns={"index": "time"})
        right = res.reset_index().rename(columns={"index": "time"})
        # merge_asof requires both sorted
        merged = pd.merge_asof(left, right, on="time", direction="backward")
        merged = merged.set_index("time")
        # merged columns may have open/high/..; ensure columns exist
        merged = merged[["open", "high", "low", "close", "volume"]]
        aligned[tf] = merged

    return aligned


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
        # create base resampled df
        all_tfs = [self.base_tf] + self.target_tfs
        aligned = align_multi_timeframes(self.df, self.base_tf, self.target_tfs)
        base_df = aligned[self.base_tf]
        # iterate over rolling windows on base index
        for i in range(self.window, len(base_df) + 1):
            window_base = base_df.iloc[i - self.window:i].copy()
            # for each tf, take aligned rows with same timestamps
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
