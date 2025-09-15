# test_indicators.py
import pandas as pd
from bot_core.indicators import SMA, RSI

# Generate a simple increasing series
data = pd.Series(range(1, 101))

# Compute SMA and RSI
sma10 = SMA(data, window=10)
rsi14 = RSI(data, window=14)

print("Last 5 values of SMA(10):")
print(sma10.tail())
print("\nLast 5 values of RSI(14):")
print(rsi14.tail())

# --- Stochastic taste test (append this) ---
def test_stochastic_oscillator():
    import pandas as pd
    from bot_core.indicators import stochastic

    # Small sample candles (same scale used by your other tests)
    data = {
        'high':  [10,12,11,13,14,15,16,17,18,19,20,21,22,23,24],
        'low':   [ 5, 6, 7, 6, 8, 9,10,11,12,13,14,15,16,17,18],
        'close': [ 7,11, 9,12,13,14,15,16,17,18,19,20,21,22,23],
    }
    df = pd.DataFrame(data)

    stoch = stochastic(df['high'], df['low'], df['close'])
    print("\n🧪 Stochastic Output (last 5 rows):")
    print(stoch.tail(5))

# Ensure the test runs when executing the file directly
if __name__ == "__main__":
    # If you already have other tests printing, the existing prints will run first.
    # Call the stochastic test after them:
    try:
        test_stochastic_oscillator()
    except Exception as e:
        print("Stochastic test failed:", e)

# --- MACD taste test (append this) ---
def test_macd():
    import pandas as pd
    from bot_core.indicators import macd

    # simple increasing close prices to get stable MACD values
    close = pd.Series([i + 1 for i in range(60)])  # 60 points for EMA warm-up

    m = macd(close)
    print("\n🧪 MACD Output (last 5 rows):")
    print(m.tail(5))

if __name__ == "__main__":
    # If the file already prints other tests, this will run after them.
    try:
        test_macd()
    except Exception as e:
        print("MACD test failed:", e)

# --- Bollinger Bands taste test (append this) ---
def test_bollinger():
    import pandas as pd
    from bot_core.indicators import bollinger_bands

    # Create a synthetic close price series with 50+ points
    close = pd.Series([100 + (i * 0.5) + ((-1)**i) for i in range(60)])  # trending with small noise
    bb = bollinger_bands(close, window=20, num_std=2.0)
    print("\n🧪 Bollinger Bands (last 5 rows):")
    print(bb.tail(5))

if __name__ == "__main__":
    # If already calling other tests, ensure this runs too.
    try:
        test_bollinger()
    except Exception as e:
        print("Bollinger test failed:", e)

# --- ATR taste test (append this) ---
def test_atr():
    import pandas as pd
    from bot_core.indicators import atr

    # Make synthetic OHLC data (60 rows) — a little variability
    high = pd.Series([100 + (i * 0.5) + (i % 5) for i in range(60)])
    low  = pd.Series([ 98 + (i * 0.5) - (i % 3) for i in range(60)])
    close= pd.Series([ 99 + (i * 0.5) + ((-1)**i) for i in range(60)])

    atr_sma = atr(high, low, close, window=14, method="sma")
    atr_wilder = atr(high, low, close, window=14, method="wilder")

    print("\n🧪 ATR (SMA) last 5 rows:")
    print(atr_sma.tail(5))
    print("\n🧪 ATR (Wilder) last 5 rows:")
    print(atr_wilder.tail(5))

# Ensure it runs
if __name__ == "__main__":
    try:
        test_atr()
    except Exception as e:
        print("ATR test failed:", e)

# --- Parabolic SAR taste test (append this) ---
def test_parabolic_sar():
    import pandas as pd
    from bot_core.indicators import parabolic_sar

    # Synthetic high/low series with a clear uptrend then slight pullback
    highs = [100 + i*0.5 + (i%5)*0.2 for i in range(60)]
    lows  = [99  + i*0.5 - (i%5)*0.2 for i in range(60)]

    high = pd.Series(highs)
    low = pd.Series(lows)

    sar = parabolic_sar(high, low)
    print("\n🧪 Parabolic SAR (last 10 rows):")
    print(sar.tail(10))

# Ensure it runs with other tests
if __name__ == "__main__":
    try:
        test_parabolic_sar()
    except Exception as e:
        print("Parabolic SAR test failed:", e)
