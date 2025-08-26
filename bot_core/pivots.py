"""
Pivot point utilities.

Provides:
 - classic_pivots(high, low, close) -> dict with P, R1,R2,R3, S1,S2,S3
 - fibonacci_pivots(high, low, close) -> dict with P, R1..S3 (Fibonacci levels)
 - pivots_from_df(df, method="classic") -> DataFrame of pivot levels aligned with df index

The functions accept either scalars (numbers) or pandas.Series (same length as df). When
passed a DataFrame, use pivots_from_df to compute a rolling set of pivot levels.
"""
from typing import Dict, Union
import pandas as pd
import numpy as np

Number = Union[float, int]
SeriesOrNumber = Union[pd.Series, Number]


def _ensure_scalar_values(h: SeriesOrNumber, l: SeriesOrNumber, c: SeriesOrNumber):
    """
    Return (h_val, l_val, c_val) where inputs may be scalars or pandas.Series.
    If any of the inputs is a pandas.Series, we will return the last valid value.
    """
    if isinstance(h, pd.Series) or isinstance(l, pd.Series) or isinstance(c, pd.Series):
        # prefer aligned last non-NaN values
        h_val = float(h.iloc[-1]) if isinstance(h, pd.Series) else float(h)
        l_val = float(l.iloc[-1]) if isinstance(l, pd.Series) else float(l)
        c_val = float(c.iloc[-1]) if isinstance(c, pd.Series) else float(c)
    else:
        h_val = float(h)
        l_val = float(l)
        c_val = float(c)
    return h_val, l_val, c_val


def classic_pivots(high: SeriesOrNumber, low: SeriesOrNumber, close: SeriesOrNumber) -> Dict[str, float]:
    """
    Classic pivot points.

    Formulas:
      P  = (H + L + C) / 3
      R1 = 2*P - L
      S1 = 2*P - H
      R2 = P + (H - L)
      S2 = P - (H - L)
      R3 = H + 2*(P - L)
      S3 = L - 2*(H - P)

    Accepts scalars or pandas.Series. If Series are provided, uses the last value.
    Returns dict of floats.
    """
    H, L, C = _ensure_scalar_values(high, low, close)
    P = (H + L + C) / 3.0
    R1 = 2 * P - L
    S1 = 2 * P - H
    R2 = P + (H - L)
    S2 = P - (H - L)
    R3 = H + 2 * (P - L)
    S3 = L - 2 * (H - P)
    return {"P": P, "R1": R1, "R2": R2, "R3": R3, "S1": S1, "S2": S2, "S3": S3}


def fibonacci_pivots(high: SeriesOrNumber, low: SeriesOrNumber, close: SeriesOrNumber) -> Dict[str, float]:
    """
    Fibonacci pivot levels.

    P = (H + L + C) / 3
    Range = H - L
    R1 = P + Range * 0.382
    R2 = P + Range * 0.618
    R3 = P + Range * 1.000
    S1 = P - Range * 0.382
    S2 = P - Range * 0.618
    S3 = P - Range * 1.000
    """
    H, L, C = _ensure_scalar_values(high, low, close)
    P = (H + L + C) / 3.0
    rng = H - L
    R1 = P + rng * 0.382
    R2 = P + rng * 0.618
    R3 = P + rng * 1.0
    S1 = P - rng * 0.382
    S2 = P - rng * 0.618
    S3 = P - rng * 1.0
    return {"P": P, "R1": R1, "R2": R2, "R3": R3, "S1": S1, "S2": S2, "S3": S3}


def pivots_from_df(df: pd.DataFrame, method: str = "classic") -> pd.DataFrame:
    """
    Compute pivot levels for each row of an OHLCV DataFrame.

    Parameters
    ----------
    df : pd.DataFrame
      must contain columns ['high','low','close'] (case-insensitive)
    method : {"classic","fibonacci"}

    Returns
    -------
    pd.DataFrame
      columns: P, R1,R2,R3, S1,S2,S3 with same index as df.
    """
    if df is None or len(df) == 0:
        return pd.DataFrame(columns=["P", "R1", "R2", "R3", "S1", "S2", "S3"])

    # Normalize column names
    cols = {c.lower(): c for c in df.columns}
    if "high" not in cols or "low" not in cols or "close" not in cols:
        raise ValueError("DataFrame must include high, low, close columns")

    odf = df.copy()
    # compute P and range
    H = odf[cols["high"]].astype(float)
    L = odf[cols["low"]].astype(float)
    C = odf[cols["close"]].astype(float)

    P = (H + L + C) / 3.0
    rng = (H - L)

    if method == "classic":
        R1 = 2 * P - L
        S1 = 2 * P - H
        R2 = P + (H - L)
        S2 = P - (H - L)
        R3 = H + 2 * (P - L)
        S3 = L - 2 * (H - P)
    elif method == "fibonacci":
        R1 = P + rng * 0.382
        R2 = P + rng * 0.618
        R3 = P + rng * 1.0
        S1 = P - rng * 0.382
        S2 = P - rng * 0.618
        S3 = P - rng * 1.0
    else:
        raise ValueError("unknown method: choose 'classic' or 'fibonacci'")

    out = pd.DataFrame({
        "P": P,
        "R1": R1, "R2": R2, "R3": R3,
        "S1": S1, "S2": S2, "S3": S3
    }, index=df.index)

    return out
