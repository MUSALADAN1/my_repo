# test_fetch.py
from bot_core.intraday_trading_bot import fetch_data

# pick a known symbol/timeframe
df = fetch_data("GBPUSDm", "15m", 50)
print("Columns:", df.columns.tolist())
print(df.head())
