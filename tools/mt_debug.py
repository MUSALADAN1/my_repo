# tools/mt_debug.py
"""
Debug helper for multitimeframe resampling issues.

Run from project root as:
    python tools/mt_debug.py

This script ensures the project root is on sys.path so `bot_core` imports work,
then prints DataFrame/index/column diagnostics and results of resample_ohlcv()
and alignment so we can see why empty groups are created.
"""
import os
import sys
from pprint import pprint

# make sure project root (parent of tools/) is on sys.path
HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

import pandas as pd

# import the functions we want to inspect
from bot_core.multitimeframe import resample_ohlcv, align_multi_timeframes, MultiTimeframeWindow

# import the test helper to create the same df used by tests
try:
    from tests.test_multitimeframe import make_minute_df
except Exception as e:
    print("ERROR importing test helper from tests.test_multitimeframe:", e)
    print("List of files in project root for orientation:")
    pprint(sorted(os.listdir(ROOT)))
    raise

def print_sep(title=""):
    print("\n" + "="*30 + " " + title + " " + "="*30 + "\n")

def main():
    print("Python executable:", sys.executable)
    print("Python sys.path[0]:", sys.path[0])
    print("Pandas version:", pd.__version__)

    # make the minute df exactly like the tests do
    df = make_minute_df(n=30)
    print_sep("INPUT DF INFO")
    print("len(df):", len(df))
    print("columns:", df.columns.tolist())
    print("index type:", type(df.index))
    try:
        print("index tz:", getattr(df.index, "tz", None))
    except Exception:
        print("index tz: <error reading>")
    print("index dtype:", getattr(df.index, "dtype", None))
    print("index sample:")
    print(df.index[:10])
    print("head:")
    print(df.head(8))
    print("dtypes:")
    print(df.dtypes)

    # call resample_ohlcv
    print_sep("RESAMPLE 5T")
    try:
        r5 = resample_ohlcv(df, "5T")
        print("resample shape:", r5.shape)
        print(r5.head(12))
        print("any non-nan open/close?", (~(r5['open'].isna() & r5['close'].isna())).any())
    except Exception as e:
        print("resample_ohlcv raised:", repr(e))

    # alignment
    print_sep("ALIGN 1T -> [5T]")
    try:
        aligned = align_multi_timeframes(df, "1T", ["5T"])
        for k, v in aligned.items():
            print(f"TF {k} -> len {len(v)}")
            print(v.head(6))
    except Exception as e:
        print("align_multi_timeframes raised:", repr(e))

    # MultiTimeframeWindow snapshot
    print_sep("MULTITIMEFRAME WINDOW")
    try:
        mtw = MultiTimeframeWindow(df, base_tf="1T", target_tfs=["5T"], window=10)
        snap = None
        try:
            snap = mtw.snapshot(lookback=10)
        except Exception as e2:
            print("mtw.snapshot raised:", repr(e2))
            # show base resampled for info
            b = resample_ohlcv(df, "1T")
            print("base 1T length:", len(b))
            print(b.tail(12))
        if snap is not None:
            for k, v in snap.items():
                print("snapshot", k, "len", len(v))
                print(v.head(6))
    except Exception as e:
        print("MultiTimeframeWindow construction raised:", repr(e))

if __name__ == "__main__":
    main()
