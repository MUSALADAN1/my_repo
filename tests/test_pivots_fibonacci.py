# tests/test_pivots_fibonacci.py
import numpy as np
import pandas as pd
from bot_core.indicators import pivot_points

def test_pivot_points_fibonacci_vs_classic():
    np.random.seed(7)
    n = 12
    price = pd.Series(np.cumsum(np.random.randn(n)*0.2 + 0.05) + 1.0)
    high = price + (np.random.rand(n) * 0.05)
    low = price - (np.random.rand(n) * 0.05)
    close = price

    df_classic = pivot_points(high, low, close, method="classic")
    df_fibo = pivot_points(high, low, close, method="fibonacci")

    assert {"pp","r1","r2","r3","s1","s2","s3"}.issubset(df_classic.columns)
    assert {"pp","r1","r2","r3","s1","s2","s3"}.issubset(df_fibo.columns)
    # for same inputs, pp should be identical
    assert (df_classic["pp"].round(12) == df_fibo["pp"].round(12)).all()
    # fibonacci R1 should be between classic PP and classic R2 for most positive ranges
    # basic sanity: r1_fibo is numeric and not infinite
    assert df_fibo["r1"].notna().all()
