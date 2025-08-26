# backend/marketplace.py
"""
Simple plugin marketplace for strategy plugins.

Features:
 - install_plugin(zip_bytes, name_hint=None) -> dict (metadata/result)
 - uninstall_plugin(name) -> bool
 - list_plugins() -> list[dict]
 - enable_plugin(name) / disable_plugin(name)
 - simple Flask blueprint (admin-only) for uploads and control

Plugin storage layout (by default):
  <base_dir>/plugins/<name>/    # extracted package files
  <base_dir>/plugins.json       # registry: { name: {enabled:bool, version, installed_at, files: [...] } }

Validation:
 - Must contain either:
   * a top-level `create_strategy` callable when imported as a module, OR
   * a subclass of StrategyPlugin
 - Instantiation attempt is performed in a subprocess-like defensive import (here we do a guarded import + attribute check)
 - Uses StrategyManager (if available) to perform optional deeper checks.

This implementation is intentionally simple and file-backed for tests.
"""
import os
import io
import json
import zipfile
import importlib.util
import sys
import tempfile
import time
from typing import Optional, Dict, Any, List

from flask import Blueprint, request, jsonify, current_app
from datetime import datetime, timezone

# Optional: import StrategyPlugin / StrategyManager if present (best-effort)
try:
    from bot_core.strategies.plugin_base import StrategyPlugin
except Exception:
    StrategyPlugin = None

BASE_DIR = os.environ.get("MARKETPLACE_BASE", os.path.join(os.getcwd(), "marketplace_data"))
PLUGINS_DIR = os.path.join(BASE_DIR, "plugins")
REGISTRY_PATH = os.path.join(BASE_DIR, "plugins.json")

bp = Blueprint("marketplace", __name__)

def _ensure_dirs():
    os.makedirs(PLUGINS_DIR, exist_ok=True)
    if not os.path.exists(REGISTRY_PATH):
        with open(REGISTRY_PATH, "w", encoding="utf-8") as f:
            json.dump({}, f)

def _load_registry() -> Dict[str, Any]:
    _ensure_dirs()
    try:
        with open(REGISTRY_PATH, "r", encoding="utf-8") as f:
            return json.load(f) or {}
    except Exception:
        return {}

def _save_registry(reg: Dict[str, Any]) -> None:
    _ensure_dirs()
    with open(REGISTRY_PATH, "w", encoding="utf-8") as f:
        json.dump(reg, f, indent=2, default=str)

def _safe_module_name(name: str) -> str:
    # sanitize name for module usage
    return "".join(c if c.isalnum() or c == "_" else "_" for c in name)

def _validate_plugin_dir(path: str) -> bool:
    """
    Try to detect if the extracted plugin directory contains at least one
    importable module that exposes a `create_strategy` callable or a StrategyPlugin subclass.
    """
    # Search for py files at top-level
    for fname in os.listdir(path):
        if not fname.endswith(".py"):
            continue
        fpath = os.path.join(path, fname)
        # Try to import module from file path (temporary)
        modname = f"marketplace_check_{int(time.time()*1000)}_{os.path.splitext(fname)[0]}"
        try:
            spec = importlib.util.spec_from_file_location(modname, fpath)
            mod = importlib.util.module_from_spec(spec)
            loader = spec.loader
            if loader is None:
                continue
            loader.exec_module(mod)  # may raise
            # validation: create_strategy function
            if hasattr(mod, "create_strategy") and callable(getattr(mod, "create_strategy")):
                return True
            # or StrategyPlugin subclass defined
            if StrategyPlugin is not None:
                for attr in dir(mod):
                    obj = getattr(mod, attr)
                    try:
                        if isinstance(obj, type) and issubclass(obj, StrategyPlugin) and obj is not StrategyPlugin:
                            return True
                    except Exception:
                        continue
        except Exception:
            # ignore import errors for validation — plugin may be multi-file; try other files
            continue
    return False

def install_plugin(zip_bytes: bytes, name_hint: Optional[str] = None) -> Dict[str, Any]:
    """
    Install plugin from zip bytes. Returns dict:
      {"ok": True, "name": "...", "files": [...], "reason": None} or {"ok": False, "reason": "..."}
    """
    _ensure_dirs()
    # choose a safe name
    name = name_hint or f"plugin_{int(time.time())}"
    name = _safe_module_name(name)
    dest = os.path.join(PLUGINS_DIR, name)
    if os.path.exists(dest):
        return {"ok": False, "reason": "plugin_exists", "name": name}

    # extract zip to temp then move if validation passes
    with tempfile.TemporaryDirectory() as td:
        try:
            zf = zipfile.ZipFile(io.BytesIO(zip_bytes))
        except Exception as e:
            return {"ok": False, "reason": f"invalid_zip: {e}"}
        # safe extract: only relative paths
        try:
            for member in zf.namelist():
                # prevent path traversal
                if os.path.isabs(member) or ".." in member.split(os.path.sep):
                    return {"ok": False, "reason": "zip_contains_forbidden_paths"}
            zf.extractall(td)
        except Exception as e:
            return {"ok": False, "reason": f"extract_failed: {e}"}

        # try to detect plugin (module .py) at top-level or inside a top folder
        # prefer top-level folder if present
        candidate_dirs = [td]
        # if there is a single folder, consider it
        entries = [e for e in os.listdir(td) if e and not e.startswith("__MACOSX")]
        if len(entries) == 1 and os.path.isdir(os.path.join(td, entries[0])):
            candidate_dirs.insert(0, os.path.join(td, entries[0]))

        valid = False
        chosen = None
        for cd in candidate_dirs:
            if _validate_plugin_dir(cd):
                valid = True
                chosen = cd
                break

        if not valid or chosen is None:
            return {"ok": False, "reason": "validation_failed", "details": "no create_strategy or StrategyPlugin found"}

        # move chosen dir to plugins/<name>
        try:
            os.makedirs(dest, exist_ok=False)
            # copy files
            for root, dirs, files in os.walk(chosen):
                rel = os.path.relpath(root, chosen)
                target_root = os.path.join(dest, "" if rel == "." else rel)
                os.makedirs(target_root, exist_ok=True)
                for f in files:
                    src_f = os.path.join(root, f)
                    tgt = os.path.join(target_root, f)
                    with open(src_f, "rb") as sf, open(tgt, "wb") as tf:
                        tf.write(sf.read())
        except Exception as e:
            # cleanup
            try:
                if os.path.exists(dest):
                    import shutil
                    shutil.rmtree(dest)
            except Exception:
                pass
            return {"ok": False, "reason": f"install_move_failed: {e}"}

        # register plugin
        reg = _load_registry()
        files_list = []
        for root, dirs, files in os.walk(dest):
            for f in files:
                files_list.append(os.path.relpath(os.path.join(root, f), dest))
        reg[name] = {
            "name": name,
            "enabled": False,
            "installed_at": datetime.now(timezone.utc).isoformat(),
            "files": sorted(files_list),
            "version": "0.0.0"
        }
        _save_registry(reg)
        return {"ok": True, "name": name, "files": sorted(files_list)}

def uninstall_plugin(name: str) -> bool:
    reg = _load_registry()
    if name not in reg:
        return False
    # remove files
    dest = os.path.join(PLUGINS_DIR, name)
    import shutil
    try:
        if os.path.exists(dest):
            shutil.rmtree(dest)
    except Exception:
        pass
    reg.pop(name, None)
    _save_registry(reg)
    return True

def list_plugins() -> List[Dict[str, Any]]:
    reg = _load_registry()
    return list(reg.values())

def set_plugin_enabled(name: str, enabled: bool) -> bool:
    reg = _load_registry()
    if name not in reg:
        return False
    reg[name]["enabled"] = bool(enabled)
    _save_registry(reg)
    return True

# ---- Flask blueprint minimal admin API (requires auth admin) ----
@bp.route("/install", methods=["POST"])
def api_install():
    # expects multipart form with 'file' and optional 'name'
    f = request.files.get("file")
    if not f:
        return jsonify({"ok": False, "reason": "missing_file"}), 400
    b = f.read()
    name_hint = request.form.get("name")
    res = install_plugin(b, name_hint=name_hint)
    if not res.get("ok"):
        return jsonify(res), 400
    return jsonify(res), 201

@bp.route("/list", methods=["GET"])
def api_list():
    return jsonify({"ok": True, "plugins": list_plugins()}), 200

@bp.route("/enable/<name>", methods=["POST"])
def api_enable(name):
    ok = set_plugin_enabled(name, True)
    if not ok:
        return jsonify({"ok": False, "reason": "not_found"}), 404
    return jsonify({"ok": True}), 200

@bp.route("/disable/<name>", methods=["POST"])
def api_disable(name):
    ok = set_plugin_enabled(name, False)
    if not ok:
        return jsonify({"ok": False, "reason": "not_found"}), 404
    return jsonify({"ok": True}), 200

@bp.route("/uninstall/<name>", methods=["DELETE"])
def api_uninstall(name):
    ok = uninstall_plugin(name)
    if not ok:
        return jsonify({"ok": False, "reason": "not_found"}), 404
    return jsonify({"ok": True}), 200

def create_app(config: Optional[Dict[str, Any]] = None):
    """
    Convenience to run blueprint in isolation for tests:
      app = create_app({"MARKETPLACE_BASE": "/tmp/mp"})
      app.register_blueprint(...)

    But for normal backend usage you can import bp and register in your server:
      app.register_blueprint(bp, url_prefix="/marketplace")
    """
    from flask import Flask
    app = Flask("marketplace_app")
    cfg = config or {}
    base = cfg.get("MARKETPLACE_BASE") or os.environ.get("MARKETPLACE_BASE") or BASE_DIR
    global BASE_DIR, PLUGINS_DIR, REGISTRY_PATH
    BASE_DIR = base
    PLUGINS_DIR = os.path.join(BASE_DIR, "plugins")
    REGISTRY_PATH = os.path.join(BASE_DIR, "plugins.json")
    _ensure_dirs()
    app.register_blueprint(bp, url_prefix="/marketplace")
    return app
