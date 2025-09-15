# bot_core/inspect_symbol.py
# Safe MT5 usage: avoid importing/initializing MetaTrader5 at module import time.
# Use ensure_and_init_mt5() at runtime to obtain an initialized mt5 module (or None).

mt5 = None

def ensure_mt5_local():
    """
    Lazy import of MetaTrader5. Prefer the project's mt5_adapter helper if available.
    Returns the mt5 module or None if not available.
    """
    global mt5
    if mt5 is not None:
        return mt5
    try:
        # prefer centralized helper if present in project
        from bot_core.exchanges.mt5_adapter import ensure_mt5 as _ensure_mt5
        mt5 = _ensure_mt5()
        return mt5
    except Exception:
        # fallback: try direct import (still lazy)
        try:
            import MetaTrader5 as _m  # type: ignore
            mt5 = _m
            return mt5
        except Exception:
            mt5 = None
            return None

def ensure_and_init_mt5():
    """
    Ensure the mt5 module is available and that mt5.initialize() succeeds.
    Returns the initialized mt5 module, or None if unavailable / failed to initialize.
    """
    m = ensure_mt5_local()
    if m is None:
        return None
    try:
        ok = m.initialize()
        # Some runtimes return True/False, some return a struct — treat falsy as failure.
        if not ok:
            return None
        return m
    except Exception:
        return None

def guarded_shutdown():
    """Call mt5.shutdown() if possible — swallow errors."""
    try:
        if 'mt5' in globals() and mt5 is not None and hasattr(mt5, "shutdown"):
            try:
                mt5.shutdown()
            except Exception:
                pass
    except Exception:
        pass

def inspect_symbol(symbol: str = "GBPUSDm"):
    """
    Inspect a symbol via MT5. Returns a dict with info or raises/returns None on failure.
    This function is safe to call in environments where MT5 is not installed.
    """
    m = ensure_and_init_mt5()
    if m is None:
        print("MT5 not available or failed to initialize (safe fallback).")
        return None

    try:
        info = m.symbol_info(symbol)
    except Exception as e:
        print(f"MT5 symbol_info() call failed: {e}")
        guarded_shutdown()
        return None

    if info is None:
        print(f"Symbol {symbol} not found or not visible in the terminal.")
        guarded_shutdown()
        return None

    # Normalize some common fields into a plain dict for easier use
    try:
        out = {
            "symbol": symbol,
            "trade_mode": getattr(info, "trade_mode", None),
            "filling_mode": getattr(info, "filling_mode", None),
            "trade_fill_flags": getattr(info, "trade_fill_flags", None),
            "description": getattr(info, "description", None),
            "visible": getattr(info, "visible", None),
            "path": getattr(info, "path", None),
        }
    except Exception:
        out = {"symbol": symbol, "raw": info}

    # Print a short summary (useful when run as script)
    print(f"\n--- Symbol Info: {symbol} ---")
    print(f"Trade Mode       : {out.get('trade_mode')}")
    print(f"Filling Mode     : {out.get('filling_mode')}")
    print(f"Allowed Fillings : {out.get('trade_fill_flags')}")
    guarded_shutdown()
    return out

if __name__ == "__main__":
    # CLI usage: python bot_core/inspect_symbol.py
    import sys
    sym = "GBPUSDm"
    if len(sys.argv) > 1:
        sym = sys.argv[1]
    inspect_symbol(sym)
