import pandas as pd
import glob
import os

# 1️⃣ Find all optimizer CSVs in this dir
files = glob.glob("opt_results_*.csv")

if not files:
    print("❌ No opt_results_*.csv files found in this folder.")
    exit(1)

# 2️⃣ Pick the one with the latest modification time
latest = max(files, key=os.path.getmtime)

print(f"🔍 Using file: {latest}\n")

# 3️⃣ Load it
df = pd.read_csv(latest)

# 4️⃣ Sort by win_rate then profit_factor (desc)
df_sorted = df.sort_values(["win_rate", "profit_factor"], ascending=False)

# 5️⃣ Pull out the very top row
best = df_sorted.iloc[0]

print("✅ Best parameters found:")
print(best.to_frame().T)   # display single‐row nicely
