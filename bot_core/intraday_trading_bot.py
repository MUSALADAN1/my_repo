    # Lazy MT5 loader: avoid importing MetaTrader5 at module import time.
# Use ensure_mt5_local() at runtime to obtain the mt5 module (or None).
mt5 = None

def ensure_mt5_local():
    """
    Initialize and return the MetaTrader5 module if available.
    This delegates to bot_core.exchanges.mt5_adapter.ensure_mt5().
    It sets the module-level `mt5` variable when successful so subsequent
    code can reference the global `mt5`.
    Always returns the mt5 module or None on failure.
    """
    global mt5
    if mt5 is not None:
        return mt5
    try:
        from bot_core.exchanges.mt5_adapter import ensure_mt5 as _ensure_mt5
        mt5 = _ensure_mt5()
        return mt5
    except Exception:
        mt5 = None
        return None

import pandas as pd
import numpy as np
from datetime import datetime, timedelta, timezone
import requests
import time
import openpyxl
import os
BASE_DIR = os.path.dirname(__file__)
# lazy, safe TwelveData client initialization (no network at import)
try:
    from twelvedata import TDClient  # may perform imports but shouldn't call network
except Exception:
    TDClient = None

td = None  # will be initialized lazily

def init_td_client():
    """Initialize and return a TwelveData client instance, or None on failure.
    This is safe to call at runtime; it will not raise on network errors — it returns None.
    """
    global td
    if td is not None:
        return td
    if TDClient is None:
        td = None
        return None
    try:
        td = TDClient(apikey=cfg.get("td_api_key", "f96a350e2c7d4f9cbf0db0078117df7b"))
        return td
    except Exception:
        # swallow network/import errors — caller will handle missing client
        td = None
        return None

import yaml
from bot_core import auto_optimize
# Adapter manager for exchange abstraction
from bot_core.exchanges.adapter_manager import init_adapter, get_adapter_instance, close_adapter
def get_equity_from_adapter(adapter):
    """
    Normalize different adapter.fetch_balance() return shapes and return a numeric equity/balance
    or None when unknown.

    Supported shapes (examples):
    - MT5Adapter dry-run: {'account': {'balance': 10000.0, 'equity': 10000.0, ...}}
    - CCXT-like: {'total': {'USDT': 123.4, 'USD': 123.4}, 'free': {...}, 'used': {...}}
    - {'balance': 1234.0} or {'equity': 1234.0}
    """
    try:
        acc = adapter.fetch_balance()
        if acc is None:
            return None

        # most MT5 adapter returns nested dict under 'account'
        if isinstance(acc, dict):
            # first: account.balance or account.equity
            if 'account' in acc and isinstance(acc['account'], dict):
                b = acc['account'].get('balance') or acc['account'].get('equity')
                if isinstance(b, (int, float)):
                    return float(b)

            # ccxt style total dict
            if 'total' in acc:
                total = acc['total']
                if isinstance(total, dict):
                    # prefer USD / USDT / EUR keys if present
                    for k in ('USD', 'USDT', 'EUR', 'BTC'):
                        if k in total and isinstance(total[k], (int, float)):
                            return float(total[k])
                    # otherwise return first numeric value
                    for v in total.values():
                        if isinstance(v, (int, float)):
                            return float(v)
                elif isinstance(total, (int, float)):
                    return float(total)

            # simple balance/equity keys
            for k in ('balance', 'equity'):
                if k in acc and isinstance(acc[k], (int, float)):
                    return float(acc[k])

        # unknown shape
        return None
    except Exception:
        return None

from bot_core.indicators import SMA, RSI
# add near other imports in intraday_trading_bot.py
from bot_core.knowledge.forex_node_loader import load_default_if_exists
import re
# new import for session parsing
from bot_core.knowledge.forex_node_loader import parse_session_times




# === Initialize persistent globals ===
TRADE_MEMORY = {}
_high_watermark = None
_last_report_date = None

# === Load external config.yaml ===
# === Load external config.yaml ===
cfg_path = os.path.join(BASE_DIR, "config.yaml")
with open(cfg_path, "r") as f:
    cfg = yaml.safe_load(f)
    opt_per_symbol = cfg.get("optimization_per_symbol", {})


BASE_RISK_PCT       = cfg.get("risk_pct", 1.0)
_DEFAULT_SYMBOLS = ['GBPUSDm', 'USDJPYm', 'XAUUSDm', 'BTCUSDm', 'USDCADm', 'GBPJPYm']

# Prefer explicit symbols in config.yaml first
cfg_symbols = cfg.get("symbols")
if cfg_symbols:
    SYMBOLS = cfg_symbols
else:
    # Try to extract symbols from the uploaded Forex node PDF
    try:
        info = load_default_if_exists(BASE_DIR)
        extracted = info.get("symbols", [])
        # Keep only 6-letter alpha tokens (e.g. EURUSD, USDJPY) detected by the loader
        filtered = [s for s in extracted if re.fullmatch(r'[A-Z]{6}', s)]
        # If your project uses the trailing 'm' suffix (e.g. EURUSDm), detect and preserve that style
        use_suffix_m = any(sym.endswith('m') for sym in _DEFAULT_SYMBOLS)
        if use_suffix_m:
            filtered = [f"{s}m" for s in filtered]
        SYMBOLS = filtered if filtered else _DEFAULT_SYMBOLS
    except Exception:
        # If anything fails, fall back to defaults
        SYMBOLS = _DEFAULT_SYMBOLS
TELEGRAM_TOKEN      = cfg.get("telegram", {}).get("token", "7753112854:AAFA0Y-IFH8SB1rxRiG6vNDZqM_pjRUZP7c")
TELEGRAM_CHAT_ID    = cfg.get("telegram", {}).get("chat_id", "6577914440")
LOG_FILE            = cfg.get("log_file", "trade_log.xlsx")
SPREAD_LIMIT        = cfg.get("spread_limit", 30)
_DAILY_REPORT_HOUR  = cfg.get("daily_report_hour", 0)
MAX_DRAWDOWN_PCT    = cfg.get("max_drawdown_pct", 10.0)
TRADE_COOLDOWN      = timedelta(minutes=cfg.get("trade_cooldown_minutes", 10))
# --- TRADING SESSIONS: prefer config.yaml -> PDF-extracted -> built-in defaults ---
_cfg_sessions = cfg.get("sessions")
if _cfg_sessions:
    TRADING_SESSIONS = {k: tuple(v) for k, v in _cfg_sessions.items()}
else:
    # Try to extract session times from the uploaded Forex node PDF
        # Try to extract session times from the uploaded Forex node PDF (robust to filename)
    try:
        # Prefer loader discovery (works even if filename changed)
        pdf_candidate = None
        try:
            info = load_default_if_exists(BASE_DIR)
            pdf_candidate = info.get("path")
        except Exception:
            pdf_candidate = None

        if pdf_candidate:
            try:
                sess_map = parse_session_times(pdf_candidate)
            except Exception:
                sess_map = {}
        else:
            sess_map = {}

        # normalize keys to the same form used in the code (Title case)
        if sess_map:
            def norm_key(k):
                k = k.replace("NEWYORK", "NewYork").replace("NEW-YORK", "NewYork").replace("NEW YORK", "NewYork")
                return k.title() if k not in ("NewYork",) else "NewYork"
            TRADING_SESSIONS = {norm_key(k): tuple(v) for k, v in sess_map.items()}
        else:
            # built-in fallback
            TRADING_SESSIONS = {k: tuple(v) for k,v in cfg.get("sessions", {'Sydney': [22, 6], 'Tokyo': [0, 8], 'London': [8, 16], 'NewYork': [13, 21]}).items()}
    except Exception:
        TRADING_SESSIONS = {k: tuple(v) for k,v in cfg.get("sessions", {'Sydney': [22, 6], 'Tokyo': [0, 8], 'London': [8, 16], 'NewYork': [13, 21]}).items()}



# === Load optimized parameters ===
opt_cfg = cfg.get("optimization", {})
# if you ran pick_best.py and injected sl/tp/fib into config.yaml, use:
OPT_SL      = opt_cfg.get("sl", None)
OPT_TP      = opt_cfg.get("tp", None)
OPT_FIB_TOL = opt_cfg.get("fib_tol", None)
# otherwise fall back to the first point in the pips ranges:
if OPT_SL is None:
    sl_pts = opt_cfg.get("sl_points", {})
    OPT_SL = sl_pts.get("start", 10) / 10000.0
if OPT_TP is None:
    tp_pts = opt_cfg.get("tp_points", {})
    OPT_TP = tp_pts.get("start", 20) / 10000.0
if OPT_FIB_TOL is None:
    fibs = opt_cfg.get("fib_tolerance", [0.001])
    OPT_FIB_TOL = fibs[0]


def in_session(now):
    for start, end in TRADING_SESSIONS.values():
        if start < end:
            if start <= now.hour < end:
                return True
        else:
            if now.hour >= start or now.hour < end:
                return True
    return False

# === Telegram & Logging ===
def send_telegram(msg: str):
    try:
        requests.post(
            f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage",
            data={'chat_id': TELEGRAM_CHAT_ID, 'text': msg}
        )
    except Exception:
        pass

def log_to_excel(data: dict):
    from openpyxl import load_workbook
    if os.path.exists(LOG_FILE):
        with pd.ExcelWriter(LOG_FILE, engine='openpyxl', mode='a', if_sheet_exists='overlay') as writer:
            pd.DataFrame([data]).to_excel(writer, index=False, sheet_name='Trades', header=False, startrow=writer.sheets['Trades'].max_row)
    else:
        pd.DataFrame([data]).to_excel(LOG_FILE, index=False, sheet_name='Trades')

def is_near_fib_retracement(df, current_price, side, tol=0.001):
    high = df['high'].max()
    low  = df['low'].min()
    diff = high - low
    level = (high - 0.382 * diff) if side=='buy' else (low + 0.382 * diff)
    return abs(current_price - level) < tol
# adjust threshold if needed


def fetch_data(sym, tf, bars):
    """
    Adapter-first fetch. Attempts to retrieve OHLCV via adapter.fetch_ohlcv(..., as_dataframe=True).
    Falls back to direct mt5 calls if adapter not available or returns empty and mt5 is present.
    """
    # Try adapter first (preferred)
    try:
        from bot_core.exchanges.adapter_manager import get_adapter_instance
        adapter = get_adapter_instance()
        df = adapter.fetch_ohlcv(sym, tf, since=None, limit=bars, as_dataframe=True)
        if df is not None and hasattr(df, "empty") and not df.empty:
            return df
    except Exception:
        df = None

        # MT5 fallback (only if mt5 is available)
            # MT5 fallback (only if mt5 is available)
    # Lazy-load mt5 at runtime via the adapter helper to avoid import-time side effects.
    try:
        from bot_core.exchanges.mt5_adapter import ensure_mt5
        mt5 = ensure_mt5()
    except Exception:
        mt5 = None

    if mt5 is not None:
        try:
            # initialize once (raise if failed)
            if not mt5.initialize():
                raise RuntimeError("MT5 initialization failed")
        except Exception:
            return pd.DataFrame()

        # ensure symbol is selected in the terminal
        try:
            if not mt5.symbol_select(sym, True):
                return pd.DataFrame()
        except Exception:
            return pd.DataFrame()

        tf_map = {
            '1d': getattr(mt5, "TIMEFRAME_D1", None),
            '4h': getattr(mt5, "TIMEFRAME_H4", None),
            '1h': getattr(mt5, "TIMEFRAME_H1", None),
            '30m': getattr(mt5, "TIMEFRAME_M30", None),
            '15m': getattr(mt5, "TIMEFRAME_M15", None),
            '5m': getattr(mt5, "TIMEFRAME_M5", None),
        }

        try:
            # use mt5.copy_rates_from; if it raises or returns None -> empty
            rates = mt5.copy_rates_from(sym, tf_map.get(tf), datetime.now(timezone.utc), int(bars))
        except Exception:
            rates = None

        if not rates:
            return pd.DataFrame()

        df2 = pd.DataFrame(rates)
        if 'time' in df2.columns:
            df2['time'] = pd.to_datetime(df2['time'], unit='s')
        return df2

    return pd.DataFrame()


    return pd.DataFrame()

def daily_trend(df_daily):
    """Return 'up' if close > pivot, 'down' otherwise."""
    piv = compute_pivots(df_daily)
    last = df_daily['close'].iloc[-1]
    return 'up' if last > piv['pivot'].iloc[-1] else 'down'

def weekly_trend(df_weekly):
    """Return 'up' if close > pivot, 'down' otherwise."""
    piv = compute_pivots(df_weekly)
    last_close = df_weekly["close"].iloc[-1]
    last_pivot = piv["pivot"].iloc[-1]
    return "up" if last_close > last_pivot else "down"

# === Intraday Signals === 
def intraday_signals(equity, risk_pct):
    signals = []
    for sym in SYMBOLS:
        # ─── Inject per‑symbol overrides ────────────────────────
        p       = opt_per_symbol.get(sym, {})
        sl_dist = p.get("sl",      OPT_SL)
        tp_dist = p.get("tp",      OPT_TP)
        fib_tol = p.get("fib_tol", OPT_FIB_TOL)

        # Weekly Trend Filter (only trade if weekly is up)
        df_w = fetch_data(sym, '1d', 84)
        if df_w.empty or weekly_trend(df_w) != "up":
            continue

        # 15m data
        df = fetch_data(sym, '15m', 100)
        if df.empty:
            continue

        # === Indicator Filters: SMA(50) & RSI(14) ===
        df['sma50'] = SMA(df['close'], window=50)
        df['rsi14'] = RSI(df['close'], window=14)
        # Current candle
        c0 = df.iloc[-1]
        # Only proceed if price > SMA50 and RSI between 30–70
        if not (c0['close'] > df['sma50'].iloc[-1] and 30 < df['rsi14'].iloc[-1] < 70):
            continue

        # Daily Trend (only trade if daily is up)
        df1d = fetch_data(sym, '1d', 50)
        if df1d.empty or daily_trend(df1d) != 'up':
            continue

        # Major supply/demand zones on 4H
        df4h = fetch_data(sym, '4h', 100)
        if df4h.empty:
            continue
        major_demand, major_supply = detect_supply_demand_zones(df4h, lookback=40, threshold=0.0015)

        # Session Filter
        now_utc = datetime.utcnow()
        if not in_session(now_utc):
            continue

        # Fibonacci (1h)
        df1h = fetch_data(sym, '1h', 100)
        if df1h.empty:
            continue

        # Recent Candles pattern
        c0, c1 = df.iloc[-1], df.iloc[-2]
        bullish = c1['close'] < c1['open'] and c0['close'] > c0['open'] and c0['close'] > c1['open']
        bearish = c1['close'] > c1['open'] and c0['close'] < c0['open'] and c0['close'] < c1['open']
        if not (bullish or bearish):
            continue

        current_price = c0['close']
        # ─── Use direction, not undefined side ───────────────────
        direction = 'buy' if bullish else 'sell'
        if not is_near_fib_retracement(df1h, current_price, direction, tol=fib_tol):
            continue

        # Micro supply/demand zones (30m)
        df30 = fetch_data(sym, '30m', 60)
        demand_zones, supply_zones = detect_supply_demand_zones(df30, lookback=20, threshold=0.0008)

        # Filter trades away from major 4H zones
        if bullish and not any(abs(c0['low'] - dz) < 0.002 for dz in major_demand):
            continue
        if bearish and not any(abs(c0['high'] - sz) < 0.002 for sz in major_supply):
            continue

        # Fetch tick via adapter (preferred) with MT5 fallback
                    # adapter fallback already tried and set tick=None if failed
        if not tick and 'mt5' in globals() and mt5 is not None:
                try:
                    tinfo = mt5.symbol_info_tick(sym)
                    if tinfo is not None:
                        tick = {
                            "symbol": sym,
                            "bid": float(getattr(tinfo, "bid", 0.0)),
                            "ask": float(getattr(tinfo, "ask", 0.0)),
                            "last": float(getattr(tinfo, "last", getattr(tinfo, "bid", 0.0))),
                            "timestamp": int(time.time() * 1000)
                        }
                except Exception:
                    tick = None


        # If we couldn't obtain a tick, skip this symbol
        if not tick:
            continue

        # Spread Filter (works with adapter dict or fallback dict)
        spread = (tick['ask'] - tick['bid']) * (100000 if 'JPY' not in sym else 100)
        if spread > SPREAD_LIMIT:
            continue

        # Pivot Points on last two candles
        pivots_raw = compute_pivots(df.iloc[-2:])
        pivots = {k: (v.iloc[-1] if isinstance(v, pd.Series) else v) for k, v in pivots_raw.items()}

        # Decision Logic for trade entry
        if bullish and c0['low'] < pivots['s1']:
            side = 'buy'
        elif bearish and c0['high'] > pivots['r1']:
            side = 'sell'
        elif bullish and any(abs(c0['low'] - dz) < 0.0008 for dz in demand_zones):
            side = 'buy'
        elif bearish and any(abs(c0['high'] - sz) < 0.0008 for sz in supply_zones):
            side = 'sell'
        else:
            continue

        # Real-time backtest validation (uses per‑symbol SL/TP)
        stats = backtest(sym, '15m', sl_dist, tp_dist)
        if stats['win_rate'] < 0.5 or stats['walk_forward'] < 0.4:
            continue

        # Entry, SL, TP using per‑symbol distances
        entry    = tick['ask'] if side == 'buy' else tick['bid']
        sl_price = entry - sl_dist if side == 'buy' else entry + sl_dist
        tp_price = entry + tp_dist if side == 'buy' else entry - tp_dist

        # Position sizing
        vol = round((equity * risk_pct / abs(entry - sl_price)) * 0.0001, 2)

        signals.append({
            'symbol':     sym,
            'side':       side,
            'volume':     vol,
            'entry':      round(entry,5),
            'stop_loss':  round(sl_price,5),
            'take_profit':round(tp_price,5)
        })
        send_telegram(f"📈 {sym} {side.upper()} @ {entry:.5f}")

    return signals


# === Pivot Points ===
def compute_pivots(df):
    H, L, C = df['high'], df['low'], df['close']
    pivot = (H + L + C) / 3
    return {
        'pivot': pivot,
        'r1': 2*pivot - L,
        's1': 2*pivot - H,
        'r2': pivot + (H - L),
        's2': pivot - (H - L)
    }

def detect_supply_demand_zones(df, lookback=30, threshold=0.0015):
    demand_zones = []
    supply_zones = []
    for i in range(2, len(df)-2):
        low = df['low'].iloc[i]
        high = df['high'].iloc[i]
        # Demand: local minimum
        if all(df['low'].iloc[i] < df['low'].iloc[i+j] for j in [-2, -1, 1, 2]):
            demand_zones.append(low)
        # Supply: local maximum
        if all(df['high'].iloc[i] > df['high'].iloc[i+j] for j in [-2, -1, 1, 2]):
            supply_zones.append(high)
    return demand_zones[-3:], supply_zones[-3:]

def detect_fractals(df):
    df['fractal_high'] = df['high'][
        (df['high'].shift(2) < df['high'].shift(1)) & (df['high'].shift(1) > df['high'])
    ]
    df['fractal_low'] = df['low'][
        (df['low'].shift(2) > df['low'].shift(1)) & (df['low'].shift(1) < df['low'])
    ]
    return df

def compute_zigzag(df, pct=5):
    pivots, trend = [], None
    last = df['close'].iloc[0]
    for price in df['close']:
        change = (price - last)/last*100
        if trend in (None, 'down') and change >= pct:
            pivots.append(('low', last))
            last, trend = price, 'up'
        elif trend in (None, 'up') and change <= -pct:
            pivots.append(('high', last))
            last, trend = price, 'down'
    return pivots

def detect_double_top_bottom(df, window=50, tol=0.002):
    patterns = []
    tops = df['high'].rolling(window).max().shift() == df['high']
    highs = df[tops]['high']
    for i in range(len(highs)-1):
        if abs(highs.iloc[i]-highs.iloc[i+1])<=tol*highs.iloc[i]:
            patterns.append(('double_top', highs.index[i]))
    bottoms = df['low'].rolling(window).min().shift() == df['low']
    lows = df[bottoms]['low']
    for i in range(len(lows)-1):
        if abs(lows.iloc[i]-lows.iloc[i+1])<=tol*lows.iloc[i]:
            patterns.append(('double_bottom', lows.index[i]))
    return patterns

def manage_trailing_stop():
    """
    Adapter-first trailing stop manager.
    - Tries adapter.fetch_positions() and adapter.fetch_ticker() to compute trailing SL.
    - If adapter exposes a modification method (common names checked), it will call it.
    - Otherwise falls back to MT5 order_send SL/TP update (existing behavior).
    """
    # Try adapter first
    adapter = None
    try:
        adapter = get_adapter_instance()
    except Exception:
        adapter = None

    # Helper to compute new SL given position dict-like and tick price
    def _compute_new_sl(pos, price):
        # pos expected shape: {'ticket'/'id', 'symbol', 'volume', 'price_open'/'price', 'type', 'sl', 'tp'}
        entry = float(pos.get('price_open', pos.get('price', 0.0)))
        sl = pos.get('sl', None)
        try:
            side_type = int(pos.get('type', 0))
        except Exception:
            # fallback: guess side 0=buy,1=sell
            side_type = 0
        mult = 100 if 'JPY' in pos.get('symbol', '') else 10000
        # calculate pips in the same way as original
        if side_type == 0:
            pips = (price - entry) * mult
        else:
            pips = (entry - price) * mult

        new_sl = None
        if pips >= 50:
            new_sl = entry + 0.003 if side_type == 0 else entry - 0.003
        elif pips >= 30:
            new_sl = entry + 0.0015 if side_type == 0 else entry - 0.0015
        elif pips >= 15:
            new_sl = entry
        return new_sl, sl, side_type

    # Adapter path
    if adapter:
        try:
            positions = []
            try:
                positions = adapter.fetch_positions() or []
            except Exception:
                positions = []

            # If adapter returns positions as objects, normalize to dicts
            normalized = []
            for p in positions:
                if isinstance(p, dict):
                    normalized.append(p)
                else:
                    # try to extract common attributes
                    normalized.append({
                        'ticket': getattr(p, 'ticket', getattr(p, 'id', None)),
                        'symbol': getattr(p, 'symbol', getattr(p, 'symbol_name', None)),
                        'volume': getattr(p, 'volume', None),
                        'price_open': getattr(p, 'price_open', getattr(p, 'entry', None)),
                        'sl': getattr(p, 'sl', None),
                        'tp': getattr(p, 'tp', None),
                        'type': getattr(p, 'type', None)
                    })

            for pos in normalized:
                sym = pos.get('symbol')
                if not sym:
                    continue
                # fetch tick via adapter if possible, else try mt5 fallback below
                tick = None
                try:
                    tick = adapter.fetch_ticker(sym)
                except Exception:
                    tick = None

                # fallback to mt5 tick if needed
                if not tick and 'mt5' in globals() and mt5 is not None:
                    try:
                        tinfo = mt5.symbol_info_tick(sym)
                        if tinfo is not None:
                            tick = {
                                'bid': float(getattr(tinfo, 'bid', 0.0)),
                                'ask': float(getattr(tinfo, 'ask', 0.0))
                            }
                    except Exception:
                        tick = None

                if not tick:
                    continue

                price = tick['bid'] if int(pos.get('type', 0)) == 0 else tick['ask']
                new_sl, old_sl, side_type = _compute_new_sl(pos, price)
                if new_sl is None:
                    continue

                # Only update if new_sl improves the stop (same logic as before)
                if (side_type == 0 and new_sl > (old_sl or 0)) or (side_type == 1 and new_sl < (old_sl or 0)):
                    # Try adapter-provided modification APIs (common names checked)
                    modified = False
                    try:
                        # Prefer a modern generic API first (modify_position(ticket, sl=..., tp=...))
                        if hasattr(adapter, "modify_position"):
                            # try to pass both SL and TP when available
                            try:
                                adapter.modify_position(pos.get('ticket') or pos.get('id'), sl=new_sl, tp=pos.get('tp'))
                            except TypeError:
                                # some adapters may accept (ticket, sl, tp) positional args
                                adapter.modify_position(pos.get('ticket') or pos.get('id'), new_sl, pos.get('tp'))
                            modified = True

                        # Backwards-compatible methods (older adapters)
                        elif hasattr(adapter, "modify_position_sl"):
                            adapter.modify_position_sl(pos.get('ticket') or pos.get('id'), new_sl)
                            modified = True
                        elif hasattr(adapter, "set_position_sl"):
                            adapter.set_position_sl(pos.get('ticket') or pos.get('id'), new_sl)
                            modified = True
                        elif hasattr(adapter, "update_position"):
                            # generic update_position(ticket, { 'sl': new_sl })
                            adapter.update_position(pos.get('ticket') or pos.get('id'), {'sl': new_sl})
                            modified = True
                    except Exception as e:
                        # adapter modification failed — we'll fallback to MT5 if available
                        send_telegram(f"⚠️ Adapter SL update failed for {sym}: {e}")
                        modified = False


                    if modified:
                        send_telegram(f"🔁 {sym} SL moved to {round(new_sl,5)} (adapter)")
                        continue  # next position

            # adapter path done
            return
        except Exception as e:
            # adapter path raised unexpected error; fall back to MT5 below
            send_telegram(f"⚠️ manage_trailing_stop adapter path error: {e}")

    # MT5 fallback (original behavior)
    try:
        for pos in mt5.positions_get() or []:
            sym, entry, sl, ticket = pos.symbol, pos.price_open, pos.sl, pos.ticket
            try:
                tick = mt5.symbol_info_tick(sym)
            except Exception:
                tick = None
            if not tick:
                continue
            price = tick.bid if pos.type == 0 else tick.ask
            mult = 100 if 'JPY' in sym else 10000
            pips = (price - entry) * mult if pos.type == 0 else (entry - price) * mult
            new_sl = None
            if pips >= 50:
                new_sl = entry + 0.003 if pos.type == 0 else entry - 0.003
            elif pips >= 30:
                new_sl = entry + 0.0015 if pos.type == 0 else entry - 0.0015
            elif pips >= 15:
                new_sl = entry
            if new_sl and ((pos.type == 0 and new_sl > sl) or (pos.type == 1 and new_sl < sl)):
                mt5.order_send({
                    'action': mt5.TRADE_ACTION_SLTP,
                    'position': ticket,
                    'sl': round(new_sl, 5),
                    'tp': pos.tp,
                    'symbol': sym,
                    'type_time': mt5.ORDER_TIME_GTC,
                    'type_filling': mt5.ORDER_FILLING_IOC
                })
                send_telegram(f"🔁 {sym} SL moved to {new_sl:.5f}")
    except Exception as e:
        send_telegram(f"🚨 manage_trailing_stop MT5 fallback error: {e}")


def check_drawdown(equity):
    global _high_watermark
    if _high_watermark is None or equity>_high_watermark:
        _high_watermark = equity
    dd = (_high_watermark-equity)/_high_watermark*100
    if dd>=MAX_DRAWDOWN_PCT:
        send_telegram(f"⚠️ Drawdown {dd:.2f}%")
        _high_watermark = equity

def daily_equity_report(equity):
    global _last_report_date
    now = datetime.now(timezone.utc)
    if _last_report_date is None:
        _last_report_date = now.date()
    if now.date()!=_last_report_date and now.hour==_DAILY_REPORT_HOUR:
        send_telegram(f"📊 Equity: {equity:.2f}, High: {_high_watermark:.2f}")
        _last_report_date = now.date()

def backtest(symbol, tf, sl_pt=0.002, tp_pt=0.004):
    """
    symbol: e.g. 'GBPUSDm'
    tf: timeframe string, e.g. '15m'
    sl_pt: stop‑loss distance in price units
    tp_pt: take‑profit distance in price units
    """
    df = fetch_data(symbol, tf, 300)
    if df.empty or len(df) < 100:
        return {'win_rate': 0.0, 'profit_factor': 0.0, 'walk_forward': 0.0}

    wins = losses = 0
    profit = loss = 0.0

    # iterate through candles and simulate SL/TP hits
    for i in range(20, len(df)-2):
        c1, c0 = df.iloc[i-1], df.iloc[i]
        bullish = c1['close'] < c1['open'] and c0['close'] > c0['open'] and c0['close'] > c1['open']
        bearish = c1['close'] > c1['open'] and c0['close'] < c0['open'] and c0['close'] < c1['open']
        if not (bullish or bearish):
            continue

        entry = c0['close']
        sl = entry - sl_pt if bullish else entry + sl_pt
        tp = entry + tp_pt if bullish else entry - tp_pt

        future = df.iloc[i+1:i+10]
        hit_tp = (future['high'] > tp).any() if bullish else (future['low'] < tp).any()
        hit_sl = (future['low'] < sl).any() if bullish else (future['high'] > sl).any()

        if hit_tp and not hit_sl:
            wins += 1
            profit += abs(tp - entry)
        elif hit_sl and not hit_tp:
            losses += 1
            loss += abs(entry - sl)
        elif hit_tp and hit_sl:
            # if both, count as loss
            losses += 1
            loss += abs(entry - sl)

    total = wins + losses
    if total == 0:
        return {'win_rate': 0.0, 'profit_factor': 0.0, 'walk_forward': 0.0}

    win_rate = wins / total
    profit_factor = profit / loss if loss else float('inf')
    wf_score = walk_forward(df)

    return {
        'win_rate': round(win_rate, 2),
        'profit_factor': round(profit_factor, 2),
        'walk_forward': round(wf_score, 2)
    }


def walk_forward(df, window=100, test_size=20):
    results = []
    for i in range(0, len(df) - window - test_size, test_size):
        train = df.iloc[i:i+window]
        test = df.iloc[i+window:i+window+test_size]
        wins = 0
        losses = 0
        for j in range(1, len(test)):
            c1, c0 = test.iloc[j-1], test.iloc[j]
            bullish = c1['close'] < c1['open'] and c0['close'] > c0['open'] and c0['close'] > c1['open']
            bearish = c1['close'] > c1['open'] and c0['close'] < c0['open'] and c0['close'] < c1['open']
            if not (bullish or bearish):
                continue

            entry = c0['close']
            sl = entry - 0.002 if bullish else entry + 0.002
            tp = entry + 0.004 if bullish else entry - 0.004

            future = test.iloc[j+1:j+5]
            hit_tp = (future['high'] > tp).any() if bullish else (future['low'] < tp).any()
            hit_sl = (future['low'] < sl).any() if bullish else (future['high'] > sl).any()

            if hit_tp and not hit_sl:
                wins += 1
            elif hit_sl and not hit_tp:
                losses += 1

        total = wins + losses
        win_rate = wins / total if total else 0
        results.append(win_rate)
    return np.mean(results) if results else 0

def is_trade_allowed(symbol, side):
    key = f"{symbol}_{side}"
    last_time = TRADE_MEMORY.get(key)
    now = datetime.now()
    if last_time is None or now - last_time > TRADE_COOLDOWN:
        TRADE_MEMORY[key] = now
        return True
    return False

def scalp_signals(equity, risk_pct):
    signals = []
    for sym in SYMBOLS:
        # ─── Inject per-symbol overrides ────────────────────────
        p       = opt_per_symbol.get(sym, {})
        sl_dist = p.get("sl",      OPT_SL)
        tp_dist = p.get("tp",      OPT_TP)
        fib_tol = p.get("fib_tol", OPT_FIB_TOL)

        df = fetch_data(sym, '5m', 100)
        if df.empty:
            continue

        # --- Obtain tick via adapter (preferred), MT5 fallback otherwise ---
        tick = None
        try:
            adapter = get_adapter_instance()
            tick = adapter.fetch_ticker(sym)
        except Exception:
            tick = None

        if not tick and 'mt5' in globals() and mt5 is not None:
            try:
                tinfo = mt5.symbol_info_tick(sym)
                if tinfo is not None:
                    tick = {
                        "symbol": sym,
                        "bid": float(getattr(tinfo, "bid", 0.0)),
                        "ask": float(getattr(tinfo, "ask", 0.0)),
                        "last": float(getattr(tinfo, "last", getattr(tinfo, "bid", 0.0))),
                        "timestamp": int(time.time() * 1000)
                    }
            except Exception:
                tick = None

        # If we couldn't obtain a tick, skip this symbol
        if not tick:
            continue

        # Spread Filter (works with adapter dict or fallback dict)
        spread = (tick['ask'] - tick['bid']) * (100000 if 'JPY' not in sym else 100)
        if spread > SPREAD_LIMIT:
            continue

        c0, c1, c2 = df.iloc[-1], df.iloc[-2], df.iloc[-3]
        bullish = c2['low'] > c1['low'] < c0['low'] and c0['close'] > c0['open']
        bearish = c2['high'] < c1['high'] > c0['high'] and c0['close'] < c0['open']
        if not (bullish or bearish):
            continue

        side = 'buy' if bullish else 'sell'
        entry = tick.ask if side == 'buy' else tick.bid

        # ─── Use per‑symbol SL/TP ───────────────────────────────
        sl_price = entry - sl_dist if side == 'buy' else entry + sl_dist
        tp_price = entry + tp_dist if side == 'buy' else entry - tp_dist

        vol = round((equity * risk_pct / abs(entry - sl_price)) * 0.0001, 2)

        signals.append({
            'symbol':     sym,
            'side':       side,
            'volume':     vol,
            'entry':      round(entry,5),
            'stop_loss':  round(sl_price,5),
            'take_profit':round(tp_price,5)
        })
        send_telegram(f"⚡ {sym.upper()} {side.upper()} SCALP @ {entry:.5f}")

    return signals


def is_high_impact_news():
    """
    Return True if there is a nearby high-impact event detected.
    This function initializes the TwelveData client lazily and is robust:
    - if the client is unavailable or network calls fail, it returns False.
    - it tolerates different client method names and wraps errors.
    """
    try:
        client = init_td_client()
        if client is None:
            # No client available (import/network disabled). Treat as no-news.
            return False

        # Try a couple of likely method names; TwelveData wrappers vary by version.
        calendar = None
        if hasattr(client, "get_economic_calendar"):
            calendar = client.get_economic_calendar(country='US,EU,GB', importance='3')
        elif hasattr(client, "economic_calendar"):
            calendar = client.economic_calendar(country='US,EU,GB', importance='3')
        else:
            # Unknown client API — bail out safely
            return False

        # calendar might be an object with as_json() or already a list/dict
        if hasattr(calendar, "as_json"):
            events = calendar.as_json()
        else:
            events = calendar

        now = datetime.utcnow()
        for ev in (events or []):
            # tolerant timestamp extraction
            ts_str = ev.get('timestamp') if isinstance(ev, dict) else None
            if not ts_str:
                ts_str = ev.get('date') if isinstance(ev, dict) else None
            if not ts_str:
                continue
            try:
                ts = datetime.strptime(ts_str, '%Y-%m-%d %H:%M:%S')
            except Exception:
                continue
            if abs((ts - now).total_seconds()) < 3600:  # within 1 hour
                return True
    except Exception as e:
        # Print for debug, but never raise on import/runtime network issues
        print("News API error:", e)
    return False


# === Signal Generation ===
def generate_signals(equity):
    signals = []
    now = datetime.now(timezone.utc)
    if not in_session(now):
        send_telegram("⏳ Not in trading session — skipping signal generation.")
        return []
    for sym in SYMBOLS:
        # --- Weekly Trend Filter ---
        df_w = fetch_data(sym, '1d', 7*12)  # ~7 weekly bars on 1d TF
        if df_w.empty or weekly_trend(df_w) != "up":
            continue

    # Check for high-impact news
    if is_high_impact_news():
        send_telegram("📰 High-impact news nearby — skipping trades.")
        return []

    # Drawdown and daily report
    check_drawdown(equity)
    daily_equity_report(equity)
    manage_trailing_stop()

    intraday_sigs = intraday_signals(equity, BASE_RISK_PCT)
    scalp_sigs = scalp_signals(equity, BASE_RISK_PCT)

    # Chart patterns or fractals (1h)
    for sym in SYMBOLS:
        df1h = fetch_data(sym, '1h', 200)
        if df1h.empty:
            continue
        piv = compute_pivots(df1h)
        fr = detect_fractals(df1h)
        zz = compute_zigzag(df1h)
        cp = detect_double_top_bottom(df1h)
        if cp or zz:
            send_telegram(f"Pattern for {sym}: {cp or zz}")

    signals = intraday_sigs + scalp_sigs
    filtered = []
    for sig in signals:
        if is_trade_allowed(sig['symbol'], sig['side']):
            filtered.append(sig)
        else:
            send_telegram(f"⏳ Skipping {sig['symbol']} {sig['side']} - recent trade placed")
    return filtered

# === Place Order & Main Loop ===
def place_order(sig):
    """
    Adapter-first order execution. Attempts:
    1) adapter.create_order(...) via adapter (preferred)
    2) fallback to MT5 if adapter missing / fails and mt5 is available
    Returns: dict with shape {"executor": "adapter"|"mt5"|"error", "raw": <raw-response> }
    """
    # Normalize fields
    symbol = sig.get("symbol")
    side = sig.get("side")
    amount = float(sig.get("volume", 0.0) or 0.0)
    entry_price = sig.get("entry", None)
    sl = sig.get("stop_loss", None)
    tp = sig.get("take_profit", None)
    params = {"stop_loss": sl, "take_profit": tp}

    # Determine dry_run flag safely
    dry_run = True
    try:
        if "cfg" in globals() and isinstance(cfg, dict):
            dry_run = cfg.get("dry_run", True)
    except Exception:
        dry_run = True

    # Standardized return helper
    def _make_err(msg):
        send_telegram(f"🚨 {msg}")
        return {"error": msg, "executor": "error"}

    # --- 1) Try adapter path (preferred) ---
    adapter_obj = globals().get("adapter", None)
    if adapter_obj is None:
        # Try adapter manager fallback
        try:
            from bot_core.exchanges import adapter_manager
            adapter_obj = adapter_manager.get_adapter()
        except Exception:
            adapter_obj = None

    if adapter_obj is not None:
        try:
            # Use the adapter's create_order interface. Pass params dict; adapter may accept dry_run.
            adapter_res = adapter_obj.create_order(
                symbol=symbol,
                side=side,
                type="market",
                amount=amount,
                price=entry_price,
                params=params,
                dry_run=dry_run,
            )
            send_telegram(f"✅ Adapter order for {symbol} {side} -> {getattr(adapter_res,'get', lambda k, d=None: getattr(adapter_res,k,d))('id','ok')}")
            return {"executor": "adapter", "raw": adapter_res}
        except Exception as e:
            # Adapter failed — log and fall back to MT5
            send_telegram(f"🚨 Adapter order exception for {symbol} {side}: {e}")

    # --- 2) MT5 fallback (only if adapter not available or failed) ---
    # Lazy-load mt5 via mt5_adapter.ensure_mt5() for runtime safety (no import-time side effects).\n    try:\n        from bot_core.exchanges.mt5_adapter import ensure_mt5\n        mt5 = ensure_mt5()\n    except Exception:\n        mt5 = None\n\n    if mt5 is not None:
        try:
            # Build a conservative MT5-style request similar to mt5_adapter.create_order
            order_type = getattr(mt5, "ORDER_TYPE_BUY", 0) if side and side.lower() == "buy" else getattr(mt5, "ORDER_TYPE_SELL", 1)
            action = getattr(mt5, "TRADE_ACTION_DEAL", 0)
            request = {
                "action": action,
                "symbol": symbol,
                "volume": float(amount),
                "type": order_type,
                "price": float(entry_price) if entry_price is not None else 0.0,
                "sl": float(sl) if sl is not None else 0.0,
                "tp": float(tp) if tp is not None else 0.0,
                "deviation": 20,
                "magic": 0,
                "comment": "fallback-mt5",
            }
            result = mt5.order_send(request)
            # result may be a struct: check retcode/order
            retcode = getattr(result, "retcode", None)
            if retcode is None:
                # best-effort: return raw result
                send_telegram(f"⚠️ MT5 order_send returned nonstandard result for {symbol} {side}")
                return {"executor": "mt5", "raw": result}
            # Accept trade retcodes that indicate success
            success_codes = {getattr(mt5, "TRADE_RETCODE_DONE", 10009), getattr(mt5, "TRADE_RETCODE_DONE_REMAINS", -1)}
            if retcode in success_codes or retcode == getattr(mt5, "TRADE_RETCODE_DONE", retcode):
                send_telegram(f"✅ MT5 order placed for {symbol} {side} (retcode={retcode})")
                return {"executor": "mt5", "raw": result}
            else:
                send_telegram(f"⚠️ MT5 order result for {symbol} {side} retcode={retcode}")
                return {"executor": "mt5", "raw": result}
        except Exception as e:
            send_telegram(f"🚨 MT5 order exception for {symbol} {side}: {e}")
            return {"error": str(e), "executor": "mt5-failed"}

    # --- 3) No executor available ---
    return _make_err(f"No adapter or MT5 available to place order for {symbol} {side}")



if __name__ == '__main__':
    # Initialize adapter via adapter_manager (safe dry-run default).
    adapter_cfg = {
        # Keep dry_run True by default for safety. Set to False and supply MT5 credentials
        # only when you are ready to go live.
        "dry_run": cfg.get("dry_run", True),
        # optional MT5 settings (used when dry_run=False)
        "terminal": cfg.get("mt5_terminal"),
        "login": cfg.get("mt5_login"),
        "password": cfg.get("mt5_password"),
        "server": cfg.get("mt5_server"),
        "health_symbol": cfg.get("health_symbol", "EURUSD"),
    }

    print("🔧 Initializing exchange adapter (dry_run={})…".format(adapter_cfg["dry_run"]))
    init_adapter("mt5", adapter_cfg)
    adapter = get_adapter_instance()

    # Optionally run a light health check (won't connect in dry_run)
    try:
        adapter.health_check()
    except Exception as e:
        print("Adapter health check warning:", e)

    # Run the auto optimizer (unchanged)
    print("🔧 Running auto-optimizer…")
    auto_optimize.main()

    # Start trading loop (adapter is used indirectly for now; existing mt5.* calls still present)
    print("✅ Starting trading loop…")

    try:
        while True:
            print(f"⏱  {datetime.now(timezone.utc).isoformat()} – Checking for trades…")
            # NOTE: currently the rest of the code still uses mt5.* calls.
            # We will replace those usages one at a time later.
            # For now, calling mt5.account_info() will still work if mt5 is available,
            # or you can switch to adapter: adapter.fetch_balance()
            try:
                # prefer adapter balance when possible
                                # prefer adapter balance when possible (adapter-only)
                equity = get_equity_from_adapter(adapter)
                if equity is None:
                    # safe fallback to a nominal equity for dry-run / unknown adapters
                    equity = 10000.0
                signals = generate_signals(equity)

                for sig in signals:
                    place_order(sig)
            except Exception as ex:
                print("Error in trading loop iteration:", ex)

            time.sleep(60)  # wait a minute, then re-optimize on next restart
    except KeyboardInterrupt:
        print("\n🛑 Interrupted by user. Exiting cleanly.")
    finally:
        # ensure adapter is closed cleanly
        try:
            close_adapter()
        except Exception:
            pass
        # Also attempt to shutdown mt5 if present
        try:
            if 'mt5' in globals() and hasattr(mt5, "shutdown"):
                mt5.shutdown()
        except Exception:
            pass

