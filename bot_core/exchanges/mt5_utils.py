# my_trading_bot/bot_core/exchanges/mt5_utils.py
"""Small helpers for MT5 adapters: timeframe mapping and rates -> pandas.DataFrame.

This module intentionally avoids hard-dependencies at import time on MetaTrader5
so it can be imported in dry-run or test environments.
"""

from typing import Any, Dict, List, Optional, Union
import pandas as pd
import datetime
import numpy as np

def tf_to_mt5(timeframe: str) -> int:
    """
    Convert a timeframe string (e.g., '1m','5m','15m','30m','1h','4h','1d')
    into a safe integer constant for MT5. If MetaTrader5 package is installed,
    prefer mapping to the actual constants; otherwise return sensible defaults.

    Returns:
        int: numeric code (adapter will map to mt5.TIMEFRAME_* when available).
    """
    tf = (timeframe or "").strip().lower()
    mapping = {
        "1m": 1,
        "m1": 1,
        "5m": 5,
        "m5": 5,
        "15m": 15,
        "m15": 15,
        "30m": 30,
        "m30": 30,
        "1h": 60,
        "h1": 60,
        "4h": 240,
        "h4": 240,
        "1d": 1440,
        "d1": 1440,
    }
    return mapping.get(tf, 1)


def _recarray_to_list_of_dicts(recarray: Any) -> List[Dict[str, Any]]:
    """Convert an mt5 numpy recarray/c_struct array to a list of dicts if needed."""
    out = []
    try:
        # Try numpy structured array (common with mt5.copy_rates_* result)
        for r in recarray:
            # r typically supports indexing: r[0]=time, r[1]=open, r[2]=high...
            # But also exposes named fields sometimes: r['time'], r['open']...
            try:
                ts = int(r[0])
                o = float(r[1])
                h = float(r[2])
                l = float(r[3])
                c = float(r[4])
                v = float(r[5]) if len(r) > 5 else 0.0
            except Exception:
                # fallback to named fields if available
                ts = int(r['time']) if 'time' in r.dtype.names else int(r[0])
                o = float(r['open']) if 'open' in r.dtype.names else float(r[1])
                h = float(r['high']) if 'high' in r.dtype.names else float(r[2])
                l = float(r['low']) if 'low' in r.dtype.names else float(r[3])
                c = float(r['close']) if 'close' in r.dtype.names else float(r[4])
                v = float(r['tick_volume']) if 'tick_volume' in r.dtype.names else (float(r[5]) if len(r) > 5 else 0.0)
            out.append({"timestamp": int(ts * 1000), "open": o, "high": h, "low": l, "close": c, "volume": v})
    except Exception:
        # Not a recarray or unexpected structure; return empty list
        return []
    return out


def rates_to_dataframe(rates: Union[List[Dict[str, Any]], Any]) -> pd.DataFrame:
    """
    Convert rates to pandas.DataFrame with columns:
      ['timestamp', 'open', 'high', 'low', 'close', 'volume', 'datetime']

    Supported input types:
      - list of dicts where each dict contains keys: timestamp (ms) or time (s),
        open, high, low, close, volume.
      - numpy recarray returned by mt5.copy_rates_*.

    Returns:
      pd.DataFrame sorted by timestamp ascending. If input is empty returns empty DF.
    """
    if rates is None:
        return pd.DataFrame(columns=['timestamp', 'open', 'high', 'low', 'close', 'volume', 'datetime'])

    # If it's likely an mt5 recarray / numpy structured array
    if not isinstance(rates, list) and hasattr(rates, '__iter__') and hasattr(rates, 'dtype') and isinstance(getattr(rates, 'dtype'), np.dtype):
        try:
            list_rates = _recarray_to_list_of_dicts(rates)
        except Exception:
            list_rates = []
    else:
        # assume list-like
        list_rates = list(rates)

    # Normalize entries: convert keys and timestamp to ms
    normalized = []
    for entry in list_rates:
        if not isinstance(entry, dict):
            continue
        ts = None
        if 'timestamp' in entry:
            ts = int(entry['timestamp'])
        elif 'time' in entry:
            # mt5 copy_rates uses seconds since epoch often
            try:
                ts = int(entry['time']) * 1000
            except Exception:
                ts = None
        elif isinstance(entry.get(0, None), (int, float)):
            # numeric index based
            try:
                ts = int(entry[0]) * 1000
            except Exception:
                ts = None

        if ts is None:
            # skip malformed
            continue

        o = float(entry.get('open', entry.get('o', entry.get(1, 0.0))))
        h = float(entry.get('high', entry.get('h', entry.get(2, 0.0))))
        l = float(entry.get('low', entry.get('l', entry.get(3, 0.0))))
        c = float(entry.get('close', entry.get('c', entry.get(4, 0.0))))
        v = float(entry.get('volume', entry.get('v', entry.get('tick_volume', 0.0))))

        normalized.append({"timestamp": int(ts), "open": o, "high": h, "low": l, "close": c, "volume": v})

    if not normalized:
        return pd.DataFrame(columns=['timestamp', 'open', 'high', 'low', 'close', 'volume', 'datetime'])

    df = pd.DataFrame(normalized)
    # ensure correct dtypes and ordering
    df = df.sort_values('timestamp').reset_index(drop=True)
    df['datetime'] = pd.to_datetime(df['timestamp'], unit='ms', utc=True)
    # reorder columns
    df = df[['timestamp', 'datetime', 'open', 'high', 'low', 'close', 'volume']]
    return df
