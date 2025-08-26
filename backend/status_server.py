#!/usr/bin/env python3
"""
Lightweight status server for the trading bot.

Endpoints:
  - GET  /api/status      -> returns current strategies, zones, metrics, last_update
  - GET  /api/config      -> returns a simple config stub or loads backend/config if available
  - POST /api/start       -> { "strategy": "<name>" }  - attempts to start strategy (dry-run if not available)
  - POST /api/stop        -> { "strategy": "<name>" }  - attempts to stop strategy

The implementation is defensive: it tries to reuse an existing StrategyManager instance
from backend.bot_controller (if your bot controller exposes one) or constructs a
light fallback that returns basic status. This keeps the endpoint usable during dev.
"""
from datetime import datetime, timezone
import json
from typing import Any, Dict, List
from flask import Flask, jsonify, request

app = Flask(__name__)

# Try to find a "live" StrategyManager instance in known places
_strategy_manager = None

def _locate_strategy_manager():
    """
    Try a few common import locations to find a running StrategyManager or broker/controller
    that exposes one. If not found, return None.
    """
    global _strategy_manager
    if _strategy_manager is not None:
        return _strategy_manager

    try:
        # If you have a bot controller that instantiates the manager, prefer it
        import backend.bot_controller as bc  # type: ignore
        if hasattr(bc, "strategy_manager"):
            _strategy_manager = getattr(bc, "strategy_manager")
            return _strategy_manager
    except Exception:
        pass

    try:
        # Some projects expose a module-level manager in backend.app or backend.status_server
        import backend.app as appmod  # type: ignore
        if hasattr(appmod, "strategy_manager"):
            _strategy_manager = getattr(appmod, "strategy_manager")
            return _strategy_manager
    except Exception:
        pass

    # last resort: import the class and make a minimal manager instance (no strategies).
    try:
        from bot_core.strategy_manager import StrategyManager  # type: ignore
        _strategy_manager = StrategyManager()
        return _strategy_manager
    except Exception:
        return None

def _status_from_manager(mgr) -> Dict[str, Any]:
    """
    Build a JSON-serializable status snapshot from a StrategyManager-like object.
    We attempt to be tolerant (some attributes may be missing).
    """
    now = datetime.now(timezone.utc).isoformat()
    out = {"strategies": [], "zones": [], "metrics": {}, "last_update": now}

    if mgr is None:
        # fallback: if a static status.json exists in project root, try to return it
        try:
            with open("status.json", "r", encoding="utf-8") as f:
                j = json.load(f)
                out.update({
                    "strategies": j.get("strategies", []),
                    "zones": j.get("zones", []),
                    "metrics": j.get("metrics", {}),
                    "last_update": j.get("last_update", now),
                })
                return out
        except Exception:
            return out

    # Strategies list
    try:
        for s in getattr(mgr, "strategies", []) or []:
            try:
                st = {
                    "name": getattr(s, "name", s.__class__.__name__),
                    "status": getattr(s, "status", "idle"),
                    "positions": int(getattr(s, "positions", 0) or 0),
                    "pnl": float(getattr(s, "pnl", 0.0) or 0.0),
                }
            except Exception:
                st = {"name": getattr(s, "name", s.__class__.__name__), "status": "unknown"}
            out["strategies"].append(st)
    except Exception:
        out["strategies"] = []

    # Try to get zones - StrategyManager might provide a helper or strategies themselves might expose zones
        # Try to get zones - StrategyManager might provide a helper or strategies themselves might expose zones
       # Try to get zones - StrategyManager might provide a helper or strategies themselves might expose zones
        # Try to get zones - StrategyManager might provide a helper or strategies themselves might expose zones
    try:
        # if StrategyManager has a snapshot/get_zones method
        if hasattr(mgr, "get_zones_snapshot"):
            out["zones"] = mgr.get_zones_snapshot() or []
        elif hasattr(mgr, "last_metrics") and isinstance(getattr(mgr, "last_metrics"), dict):
            out["zones"] = getattr(mgr, "last_metrics").get("zones", [])
        else:
            out["zones"] = []

        # If still empty, attempt to compute combined SR zones from available indicators
        if not out["zones"]:
            try:
                from bot_core import sr as sr_mod  # type: ignore
                import pandas as pd  # type: ignore

                # try common sources for an ohlcv snapshot
                df = None
                if hasattr(mgr, "get_last_ohlcv"):
                    try:
                        df = mgr.get_last_ohlcv()
                    except Exception:
                        df = None
                if df is None and hasattr(mgr, "last_ohlcv"):
                    try:
                        df = getattr(mgr, "last_ohlcv")
                    except Exception:
                        df = None
                lm = getattr(mgr, "last_metrics", None)
                if df is None and isinstance(lm, dict):
                    df = lm.get("last_ohlcv") or lm.get("ohlcv")
                # try strategies for recent data
                if df is None:
                    for s in getattr(mgr, "strategies", []) or []:
                        try:
                            if hasattr(s, "last_ohlcv"):
                                cand = getattr(s, "last_ohlcv")
                                if hasattr(cand, "columns") and "close" in cand.columns:
                                    df = cand
                                    break
                        except Exception:
                            continue

                if df is not None:
                    # normalize to DataFrame just in case
                    if not isinstance(df, pd.DataFrame):
                        df = None

                if df is not None:
                    out["zones"] = sr_mod.aggregate_zones_from_df(df) or []
            except Exception:
                # don't fail the endpoint if we can't compute zones
                out["zones"] = out.get("zones", [])
    except Exception:
        out["zones"] = []


    # Metrics - try common attributes and attach an 'elliott' snapshot when possible
        # Metrics - try common attributes (and attach pivots if possible)
    try:
        metrics = {}
        if hasattr(mgr, "get_metrics_snapshot"):
            metrics = mgr.get_metrics_snapshot() or {}
        elif hasattr(mgr, "last_metrics"):
            metrics = getattr(mgr, "last_metrics") or {}

        # If pivots are not present, try to compute from last_ohlcv
        # Accepts both list-of-dicts (API style) or a DataFrame-like object.
        if "pivots" not in (metrics or {}):
            try:
                # import here to avoid hard dependency if the module isn't available
                from bot_core.pivots import pivots_from_df  # defensive import
                import pandas as pd

                last_ohlcv = (metrics or {}).get("last_ohlcv")
                if last_ohlcv:
                    # last_ohlcv may be list of dicts (API-friendly) or a DataFrame already
                    if isinstance(last_ohlcv, list):
                        # build a tiny DataFrame; expect each dict to have a time field
                        df = pd.DataFrame(last_ohlcv)
                        # if 'time' column present, set as index
                        if "time" in df.columns:
                            df["time"] = pd.to_datetime(df["time"])
                            df = df.set_index("time")
                        # normalize expected OHLCV columns
                        # keep only open/high/low/close/volume if present
                        df = df[[c for c in ["open", "high", "low", "close", "volume"] if c in df.columns]]
                        # compute pivots (pivots_from_df should return a JSON-serializable dict)
                        piv = pivots_from_df(df)
                        if piv is not None:
                            metrics["pivots"] = piv
                    else:
                        # last_ohlcv may already be a DataFrame-like object; attempt to use it
                        try:
                            df = pd.DataFrame(last_ohlcv)
                            if "time" in df.columns:
                                df["time"] = pd.to_datetime(df["time"])
                                df = df.set_index("time")
                            df = df[[c for c in ["open", "high", "low", "close", "volume"] if c in df.columns]]
                            piv = pivots_from_df(df)
                            if piv is not None:
                                metrics["pivots"] = piv
                        except Exception:
                            # not a DataFrame-like structure we can use — skip
                            pass
            except Exception:
                # pivot computation failed (module missing or error) — ignore silently
                pass

        out["metrics"] = metrics
    except Exception:
        out["metrics"] = {}


        # compute lightweight Elliott snapshot (defensive)
        try:
            # local imports so missing optional deps don't break the whole endpoint
            import pandas as pd  # type: ignore
            from bot_core import elliott as elliott_mod  # type: ignore

            # helper to extract a close Series from various possible sources
            def _extract_last_close_series():
                # 1) common manager API
                if hasattr(mgr, "get_last_ohlcv"):
                    try:
                        df = mgr.get_last_ohlcv()
                        if isinstance(df, pd.DataFrame) and "close" in df.columns:
                            return df["close"]
                    except Exception:
                        pass
                # 2) manager attribute
                if hasattr(mgr, "last_ohlcv"):
                    try:
                        df = getattr(mgr, "last_ohlcv")
                        if isinstance(df, pd.DataFrame) and "close" in df.columns:
                            return df["close"]
                    except Exception:
                        pass
                # 3) last_metrics may include an ohlcv snapshot
                lm = getattr(mgr, "last_metrics", None)
                if isinstance(lm, dict):
                    df = lm.get("last_ohlcv") or lm.get("ohlcv")
                    if isinstance(df, pd.DataFrame) and "close" in df.columns:
                        return df["close"]
                # 4) try strategies for a recent ohlcv
                for s in getattr(mgr, "strategies", []) or []:
                    try:
                        if hasattr(s, "last_ohlcv"):
                            df = getattr(s, "last_ohlcv")
                            if isinstance(df, pd.DataFrame) and "close" in df.columns:
                                return df["close"]
                    except Exception:
                        continue
                return None

            close_series = _extract_last_close_series()
            if close_series is not None and len(close_series) > 0:
                # choose conservative detection params — tune later
                ell_snapshot = elliott_mod.detect_impulse(close_series, min_swings=5, left=1, right=1)
                # attach into metrics under a stable key
                metrics = metrics or {}
                metrics.setdefault("elliott", {})
                metrics["elliott"].update({
                    "snapshot": ell_snapshot,
                    "computed_from": "last_ohlcv",
                })
        except Exception:
            # any failure computing elliott should not break the status endpoint
            pass

        out["metrics"] = metrics
    except Exception:
        out["metrics"] = {}

    out["last_update"] = now
    return out


    # Pivots - try multiple fallbacks to produce a simple pivot snapshot (P, R1..S3)
    try:
        out["pivots"] = []  # default empty list

        # prefer a manager-provided pivots snapshot if available
        if hasattr(mgr, "get_pivots_snapshot"):
            p = mgr.get_pivots_snapshot() or []
            out["pivots"] = p if isinstance(p, list) else [p]
        else:
            # try to compute from metrics.last_ohlcv if present (list of dicts or single dict)
            last_ohlcv = None
            if isinstance(metrics, dict) and "last_ohlcv" in metrics:
                last_ohlcv = metrics.get("last_ohlcv")
            elif hasattr(mgr, "last_metrics") and isinstance(getattr(mgr, "last_metrics"), dict):
                last_ohlcv = getattr(mgr, "last_metrics").get("last_ohlcv")

            # normalize last_ohlcv to a DataFrame if possible
            import pandas as _pd
            from bot_core import pivots as _pivots

            if last_ohlcv:
                try:
                    # If it's a list of dicts or single dict, convert
                    if isinstance(last_ohlcv, dict):
                        last_ohlcv = [last_ohlcv]
                    odf = _pd.DataFrame(last_ohlcv)
                    # ensure required columns exist
                    if set(["high", "low", "close"]).issubset({c.lower() for c in odf.columns}):
                        # normalize column names to lowercase for pivots_from_df
                        odf.columns = [c.lower() for c in odf.columns]
                        piv_df = _pivots.pivots_from_df(odf, method="classic")
                        # attach the last row as a dict
                        if len(piv_df) > 0:
                            row = piv_df.iloc[-1].to_dict()
                            out["pivots"] = [row]
                except Exception:
                    # ignore; continue to other fallback
                    out["pivots"] = out.get("pivots", [])

            # fallback: if zones exist and have min/max/center, synthesize a single OHLC row
            if not out["pivots"]:
                try:
                    if out.get("zones"):
                        z = out["zones"][0]
                        if isinstance(z, dict) and "min_price" in z and "max_price" in z and "center" in z:
                            synth = _pd.DataFrame([{
                                "high": float(z.get("max_price")),
                                "low": float(z.get("min_price")),
                                "close": float(z.get("center"))
                            }])
                            piv_df = _pivots.pivots_from_df(synth, method="classic")
                            if len(piv_df) > 0:
                                out["pivots"] = [piv_df.iloc[-1].to_dict()]
                except Exception:
                    # best-effort - leave pivots as empty list
                    out["pivots"] = out.get("pivots", [])
    except Exception:
        out["pivots"] = []

    out["last_update"] = now
    return out


@app.route("/api/status", methods=["GET"])
def api_status():
    mgr = _locate_strategy_manager()
    status = _status_from_manager(mgr)
    return jsonify(status)

@app.route("/api/config", methods=["GET"])
def api_config():
    # Try to serve a lightweight config
    try:
        # if a backend config file exists in bot_core/config.yaml or backend/config.json, return it
        try:
            import yaml  # optional
            with open("bot_core/config.yaml", "r", encoding="utf-8") as f:
                cfg = yaml.safe_load(f)
                return jsonify({"ok": True, "config": cfg})
        except Exception:
            pass
        # fallback: minimal config
        return jsonify({"ok": True, "config": {"env": "dev", "version": "unknown"}})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500

@app.route("/api/start", methods=["POST"])
def api_start():
    data = request.get_json(silent=True) or {}
    name = data.get("strategy")
    mgr = _locate_strategy_manager()
    if mgr is None:
        # dry-run response
        return jsonify({"ok": True, "started": name, "note": "no live manager, dry-run"}), 200
    # try to call a start method on manager or strategy
    try:
        if hasattr(mgr, "start_strategy"):
            mgr.start_strategy(name)
            return jsonify({"ok": True, "started": name}), 200
        # try to find the strategy object and set a flag
        for s in getattr(mgr, "strategies", []) or []:
            if getattr(s, "name", "") == name or s.__class__.__name__ == name:
                # if plugin exposes start/stop, call it
                if hasattr(s, "start"):
                    s.start()
                else:
                    setattr(s, "status", "running")
                return jsonify({"ok": True, "started": name}), 200
        return jsonify({"ok": False, "error": "strategy not found"}), 404
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500

@app.route("/api/stop", methods=["POST"])
def api_stop():
    data = request.get_json(silent=True) or {}
    name = data.get("strategy")
    mgr = _locate_strategy_manager()
    if mgr is None:
        return jsonify({"ok": True, "stopped": name, "note": "no live manager, dry-run"}), 200
    try:
        if hasattr(mgr, "stop_strategy"):
            mgr.stop_strategy(name)
            return jsonify({"ok": True, "stopped": name}), 200
        for s in getattr(mgr, "strategies", []) or []:
            if getattr(s, "name", "") == name or s.__class__.__name__ == name:
                if hasattr(s, "stop"):
                    s.stop()
                else:
                    setattr(s, "status", "idle")
                return jsonify({"ok": True, "stopped": name}), 200
        return jsonify({"ok": False, "error": "strategy not found"}), 404
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500

@app.route("/", methods=["GET"])
def home():
    return jsonify({"ok": True, "service": "status_server", "time": datetime.now(timezone.utc).isoformat()})

if __name__ == "__main__":
    # Run the dev server (same style you used earlier)
    app.run(host="127.0.0.1", port=5000, debug=True)