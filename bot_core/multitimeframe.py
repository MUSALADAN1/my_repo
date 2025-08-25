# bot_core/multitimeframe.py
from typing import List, Dict, Optional
import pandas as pd
import numpy as np


def _ensure_datetime_index(df: pd.DataFrame) -> pd.DataFrame:
    """
    Ensure the DataFrame has a DatetimeIndex. If df has a column named 'time', use it.
    Otherwise try to convert the existing index to datetime.
    The returned frame is sorted ascending by index.
    """
    if df is None:
        return pd.DataFrame()
    df = df.copy()
    # If there is a 'time' column, prefer that
    if "time" in df.columns:
        df.index = pd.to_datetime(df["time"])
        df = df.drop(columns=["time"], errors="ignore")
    else:
        # Ensure index is datetime-like
        if not isinstance(df.index, pd.DatetimeIndex):
            try:
                df.index = pd.to_datetime(df.index)
            except Exception:
                # fallback: try to coerce any column named like 'timestamp' etc.
                for cand in ("timestamp", "datetime", "date"):
                    if cand in df.columns:
                        df.index = pd.to_datetime(df[cand])
                        df = df.drop(columns=[cand], errors="ignore")
                        break
    # sort ascending and drop exact duplicate index entries (keep first)
    df = df.sort_index()
    if df.index.duplicated().any():
        df = df[~df.index.duplicated(keep="first")]
    return df


def _normalize_ohlcv_columns(df: pd.DataFrame) -> pd.DataFrame:
    """
    Ensure we have columns: open, high, low, close, volume
    Accept common alternatives (VOL, vol, Volume).
    """
    df = df.copy()
    # lowercase column map
    col_map = {c.lower(): c for c in df.columns}
    needed = {}
    for want in ("open", "high", "low", "close", "volume"):
        if want in col_map:
            needed[want] = col_map[want]
        else:
            # try some common alternates for volume
            if want == "volume":
                for alt in ("vol", "v"):
                    if alt in col_map:
                        needed[want] = col_map[alt]
                        break
    # build result with exact names (fill missing columns with NaN series)
    out = pd.DataFrame(index=df.index)
    for want in ("open", "high", "low", "close", "volume"):
        src = needed.get(want)
        if src is not None and src in df.columns:
            out[want] = df[src].astype(float)
        else:
            out[want] = pd.Series(index=df.index, dtype="float64")
    return out


def resample_ohlcv(df: pd.DataFrame, timeframe: str) -> pd.DataFrame:
    """
    Resample OHLCV to given timeframe.

    Uses grouping by `index.floor(timeframe)` to produce stable, predictable bins
    for synthetic minute-level data (e.g. 00:00..00:04 -> 00:00 for '5T').

    Returns DataFrame indexed by the floored timestamp with columns
      ['open','high','low','close','volume'].
    """
    if df is None:
        return pd.DataFrame(columns=["open", "high", "low", "close", "volume"])

    df = _ensure_datetime_index(df)
    if df.empty:
        return pd.DataFrame(columns=["open", "high", "low", "close", "volume"])

    odf = _normalize_ohlcv_columns(df)

    # compute floored timestamps for grouping
    try:
        # pandas accepts offsets like "5T", "1H", "15min"
        group_keys = odf.index.floor(timeframe)
    except Exception:
        # fallback: if floor fails (older pandas), approximate using resample as last resort
        o = odf["open"].resample(timeframe).first()
        h = odf["high"].resample(timeframe).max()
        l = odf["low"].resample(timeframe).min()
        c = odf["close"].resample(timeframe).last()
        v = odf["volume"].resample(timeframe).sum()
        res = pd.concat([o, h, l, c, v], axis=1)
        res.columns = ["open", "high", "low", "close", "volume"]
        res = res.dropna(how="all", subset=["open", "close"])
        return res

    grouped = odf.groupby(group_keys)

    o = grouped["open"].first()
    h = grouped["high"].max()
    l = grouped["low"].min()
    c = grouped["close"].last()
    v = grouped["volume"].sum()

    res = pd.concat([o, h, l, c, v], axis=1)
    res.columns = ["open", "high", "low", "close", "volume"]

    # The index of res is the floored timestamps. Keep them as DatetimeIndex.
    res.index = pd.to_datetime(res.index)

    # Drop fully empty bars (no open/close)
    res = res.dropna(how="all", subset=["open", "close"])

    # Sort index and return
    res = res.sort_index()
    return res


def align_multi_timeframes(df: pd.DataFrame, base_tf: str, target_tfs: List[str]) -> Dict[str, pd.DataFrame]:
    """
    Return a dict mapping timeframe -> DataFrame, with every target timeframe aligned to the
    base timeframe index (forward-filled to the base bars).

    - base_tf is returned as resample_ohlcv(df, base_tf)
    - for each target_tf: resample_ohlcv(df, target_tf), then reindex to base index
      using forward-fill so each base bar knows which target bar it sits inside.
    """
    if df is None:
        return {base_tf: pd.DataFrame(columns=["open", "high", "low", "close", "volume"])}

    base_df = resample_ohlcv(df, base_tf)

    aligned = {base_tf: base_df}

    for tf in (target_tfs or []):
        tgt = resample_ohlcv(df, tf)
        # align target bars to base index using ffill: each base timestamp gets corresponding latest target bar
        if not tgt.empty and not base_df.empty:
            # reindex target to base index using forward-fill; ensures shape same as base
            try:
                tgt_aligned = tgt.reindex(base_df.index, method="ffill")
            except Exception:
                # fallback: create a DataFrame with same index and forward-filled values manually
                tgt_aligned = tgt.reindex(base_df.index)
                tgt_aligned = tgt_aligned.fillna(method="ffill")
        else:
            # no target bars or no base bars -> empty aligned with base index
            tgt_aligned = pd.DataFrame(index=base_df.index, columns=["open", "high", "low", "close", "volume"])
        aligned[tf] = tgt_aligned

    return aligned


class MultiTimeframeWindow:
    """
    Helper that keeps a historical base DataFrame and provides aligned snapshots
    across multiple timeframes.

    Usage:
      mtw = MultiTimeframeWindow(df, base_tf="1T", target_tfs=["5T","15T"], window=100)
      sn = mtw.snapshot(lookback=20)  # returns dict mapping tf->DataFrame (last `lookback` base bars)
    """
    def __init__(self, df: pd.DataFrame, base_tf: str = "1T", target_tfs: Optional[List[str]] = None, window: int = 200):
        self.df = _ensure_datetime_index(df) if df is not None else pd.DataFrame()
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

        last_base = base.tail(lookback)
        snapshot = {self.base_tf: last_base.copy()}

        for tf in self.target_tfs:
            df_t = aligned.get(tf)
            if df_t is None:
                snapshot[tf] = pd.DataFrame(index=last_base.index, columns=["open", "high", "low", "close", "volume"])
            else:
                # ensure order matches last_base index
                df_sel = df_t.reindex(last_base.index)
                snapshot[tf] = df_sel.copy()
        return snapshot
