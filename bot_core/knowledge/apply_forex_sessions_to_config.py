#!/usr/bin/env python3
"""
Apply session times extracted from a Forex node PDF into config.yaml.

Usage:
    python -m bot_core.knowledge.apply_forex_sessions_to_config
"""
from pathlib import Path
import yaml
import shutil
import sys
import time

BASE_DIR = Path(__file__).resolve().parents[2]  # project root
CFG_PATH = BASE_DIR / "bot_core" / "config.yaml"

# Try to import loader functions from the package
try:
    from bot_core.knowledge.forex_node_loader import load_default_if_exists, parse_session_times
except Exception:
    # If import fails, we still continue gracefully (script will no-op).
    load_default_if_exists = None
    parse_session_times = None

def norm_key(k: str) -> str:
    # Normalize common session name variants into the Title-like keys used by the bot
    k = k.strip().upper().replace("-", "").replace(" ", "")
    if k in ("NEWYORK","NEWYORKSESSION","NEWYORKS"):
        return "NewYork"
    if k == "SYDNEY":
        return "Sydney"
    if k == "TOKYO":
        return "Tokyo"
    if k in ("LONDON","LONDONSESSION"):
        return "London"
    # default: Title-case the token
    return k.title()

def main():
    if not CFG_PATH.exists():
        print("config.yaml not found at", CFG_PATH)
        sys.exit(1)

    # Load config
    cfg = yaml.safe_load(CFG_PATH.read_text()) or {}

    # If sessions already present, do nothing (safe default)
    if cfg.get("sessions"):
        print("config.yaml already contains 'sessions'. Nothing to do.")
        print("Existing sessions:", cfg.get("sessions"))
        return

    # Attempt to find PDF candidate via loader helper if available
    pdf_path = None
    if load_default_if_exists:
        try:
            info = load_default_if_exists(str(BASE_DIR))
            pdf_path = info.get("path")
            print("Found PDF candidate via loader:", pdf_path)
        except Exception:
            pdf_path = None

    # fall back to a likely filename in project root
    if pdf_path is None:
        candidate = BASE_DIR / "Forex node1(1).pdf"
        if candidate.exists():
            pdf_path = str(candidate)
            print("Found fallback PDF:", pdf_path)

    if pdf_path is None:
        print("No Forex node PDF found. Nothing to update.")
        return

    # Parse session times (function may handle many PDF formats)
    if not parse_session_times:
        print("parse_session_times function not available. Please ensure forex_node_loader.py is present.")
        return

    try:
        sess_map = parse_session_times(pdf_path)
    except Exception as e:
        print("parse_session_times raised:", e)
        sess_map = None

    if not sess_map:
        print("No session times parsed from PDF.")
        return

    # Normalize keys and ensure integer hour pairs
    normalized = {}
    for k, v in sess_map.items():
        try:
            # Expect v like [start_hour, end_hour] or (start,end)
            start, end = int(v[0]), int(v[1])
            normalized[norm_key(k)] = [start, end]
        except Exception:
            print(f"Skipping invalid session entry for {k}: {v}")

    if not normalized:
        print("No valid session entries found after normalization.")
        return

    # Backup config.yaml
    ts = int(time.time())
    backup_path = CFG_PATH.with_suffix(f".yaml.bak.{ts}")
    shutil.copy2(CFG_PATH, backup_path)
    print("Backed up config.yaml ->", backup_path)

    # Inject sessions into config and write back
    cfg["sessions"] = normalized
    CFG_PATH.write_text(yaml.safe_dump(cfg, sort_keys=False), encoding="utf-8")
    print("Updated config.yaml with sessions:", normalized)
    print("Done.")

if __name__ == "__main__":
    main()
