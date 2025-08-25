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
    try:
        # if StrategyManager has a snapshot/get_zones method
        if hasattr(mgr, "get_zones_snapshot"):
            out["zones"] = mgr.get_zones_snapshot() or []
        elif hasattr(mgr, "last_metrics") and isinstance(getattr(mgr, "last_metrics"), dict):
            out["zones"] = getattr(mgr, "last_metrics").get("zones", [])
        else:
            # attempt to call sr_zones_from_series on the first strategy's recent window, if available
            out["zones"] = []
    except Exception:
        out["zones"] = []

    # Metrics - try common attributes
    try:
        metrics = {}
        if hasattr(mgr, "get_metrics_snapshot"):
            metrics = mgr.get_metrics_snapshot() or {}
        elif hasattr(mgr, "last_metrics"):
            metrics = getattr(mgr, "last_metrics") or {}
        out["metrics"] = metrics
    except Exception:
        out["metrics"] = {}

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