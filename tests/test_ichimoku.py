# tests/test_ichimoku.py
import numpy as np
import pandas as pd
import numpy as _np
from bot_core.indicators import ichimoku

def test_ichimoku_basic_runs():
    np.random.seed(2)
    n = 80
    price = pd.Series(np.cumsum(np.random.randn(n)*0.3 + 0.05) + 50)
    high = price + (np.random.rand(n) * 0.2)
    low = price - (np.random.rand(n) * 0.2)
    close = price
    out = ichimoku(high, low, close)

    # Basic structural checks
    assert {"tenkan","kijun","senkou_a","senkou_b","chikou"}.issubset(set(out.columns))
    assert len(out) == n

    # No infinite values in numeric columns
    num = out.select_dtypes(include=[float, int])
    assert not _np.isinf(num.to_numpy()).any()

    # The shifted spans will have NaNs at the edges; ensure they contain some valid values
    assert out["senkou_a"].notna().any(), "senkou_a is all NaN"
    assert out["senkou_b"].notna().any(), "senkou_b is all NaN"
    assert out["chikou"].notna().any(), "chikou is all NaN"

    # Tenkan and Kijun should have many non-NaN values (shorter windows)
    assert out["tenkan"].notna().sum() >= int(n * 0.5)
    assert out["kijun"].notna().sum() >= int(n * 0.3)
