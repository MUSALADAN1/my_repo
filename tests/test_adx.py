# tests/test_adx.py
import pandas as pd
import numpy as np
from bot_core.indicators import adx

def test_adx_basic_runs():
    np.random.seed(1)
    n = 60
    price = pd.Series(np.cumsum(np.random.randn(n) * 0.3 + 0.05) + 50)
    high = price + (np.random.rand(n) * 0.2)
    low = price - (np.random.rand(n) * 0.2)
    close = price
    out = adx(high, low, close, period=14)
    assert "adx" in out.columns
    assert "plus_di" in out.columns
    assert "minus_di" in out.columns
    # ensure no infinite values
    assert out.replace([float('inf'), -float('inf')], pd.NA).notna().all().all()
