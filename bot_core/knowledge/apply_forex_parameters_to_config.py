#!/usr/bin/env python3
"""
Apply numeric optimization parameters (SL/TP/fib tolerance) extracted from a Forex node PDF
into bot_core/config.yaml. Conservative: will only inject missing keys and will always
create a timestamped backup of config.yaml first.

Usage:
    source venv/scripts/activate
    python -m bot_core.knowledge.apply_forex_parameters_to_config
"""
from pathlib import Path
import yaml
import shutil
import sys
import time
import re

# Project / config paths
BASE_DIR = Path(__file__).resolve().parents[2]
CFG_PATH = BASE_DIR / "bot_core" / "config.yaml"

# Import loader helpers if available
try:
    from bot_core.knowledge.forex_node_loader import load_default_if_exists, parse_forex_node_pdf
except Exception:
    load_default_if_exists = None
    parse_forex_node_pdf = None

# --- helpers ---
def find_pdf_candidate() -> str | None:
    # Prefer loader candidate
    if load_default_if_exists:
        try:
            info = load_default_if_exists(str(BASE_DIR))
            path = info.get("path")
            if path:
                return path
        except Exception:
            pass
    # Fallback likely filenames
    for fname in ("Forex node1(1).pdf", "Forex node1.pdf", "forex_node.pdf"):
        p = BASE_DIR / fname
        if p.exists():
            return str(p)
    return None

def extract_numbers_from_text(text: str) -> dict:
    """Return dict with possible values: sl_pips, tp_pips, fib_tol (decimal)."""
    out = {"sl_pips": None, "tp_pips": None, "fib_tol": None}

    # normalize text
    t = text.replace("\n", " ").replace("\r", " ")
    t = re.sub(r"\s+", " ", t).lower()

    # 1) Look for explicit "SL X pips" or "Stop Loss X pips"
    m = re.search(r'(?:stop[- ]?loss|sl)[^\d]{0,6}([0-9]{1,4})\s*(?:pips|pts|points)?', t)
    if m:
        out["sl_pips"] = int(m.group(1))

    # 2) Look for explicit "TP X pips" or "Take Profit X pips"
    m = re.search(r'(?:take[- ]?profit|tp)[^\d]{0,6}([0-9]{1,4})\s*(?:pips|pts|points)?', t)
    if m:
        out["tp_pips"] = int(m.group(1))

    # 3) Look for combined "SL/TP X/Y" pattern
    m = re.search(r'(?:sl|stop[- ]?loss)[^\d]{0,6}([0-9]{1,4})\s*[/\\]\s*([0-9]{1,4})', t)
    if m:
        out["sl_pips"] = out["sl_pips"] or int(m.group(1))
        out["tp_pips"] = out["tp_pips"] or int(m.group(2))

    # 4) A more generic numeric pair pattern like "10/20 pips" preceded by "SL/TP" words
    m = re.search(r'(?:sl|tp|stop|take|stop[- ]loss).{0,20}?([0-9]{1,3})\s*[/]\s*([0-9]{1,3})\s*(?:pips|pts|points)?', t)
    if m:
        out["sl_pips"] = out["sl_pips"] or int(m.group(1))
        out["tp_pips"] = out["tp_pips"] or int(m.group(2))

    # 5) Fallback: any "X pips" occurrences — choose the two smallest reasonable numbers (SL small, TP larger)
    if not out["sl_pips"] or not out["tp_pips"]:
        all_pips = [int(x) for x in re.findall(r'([0-9]{1,4})\s*(?:pips|pts|points)', t)]
        all_pips = sorted(set([p for p in all_pips if 1 <= p <= 1000]))
        if all_pips:
            if out["sl_pips"] is None:
                out["sl_pips"] = all_pips[0]
            if out["tp_pips"] is None and len(all_pips) > 1:
                out["tp_pips"] = all_pips[1]

    # 6) Fibonacci tolerance: look for patterns like "fib tolerance 0.2%", "fib tol 0.001", or "0.382"
    m = re.search(r'fib(?:onacci)?(?:\s*(?:tol|tolerance)[:\s]*)?([0-9]*\.?[0-9]+)\s*%?', t)
    if m:
        val = float(m.group(1))
        # If > 1 it's probably percent
        if val > 1:
            out["fib_tol"] = val / 100.0
        else:
            out["fib_tol"] = val

    # Another common pattern: "tolerance 0.1%" or "tolerance 0.001"
    if out["fib_tol"] is None:
        m = re.search(r'(?:tolerance|tol)[^\d]{0,6}([0-9]*\.?[0-9]+)\s*%?', t)
        if m:
            val = float(m.group(1))
            out["fib_tol"] = val / 100.0 if val > 1 else val

    # Normalize reasonable defaults to None if unrealistic
    if out["fib_tol"] is not None and out["fib_tol"] > 1:
        out["fib_tol"] = None

    return out

def convert_pips_to_points(pips: int) -> dict:
    """Return dict form expected by your code (points used in your optimization config)."""
    # Your code converts points -> price units with /10000. We'll store sl_points/tp_points.
    return {"start": int(pips)}

def main():
    if not CFG_PATH.exists():
        print("config.yaml not found at", CFG_PATH)
        sys.exit(1)

    cfg = yaml.safe_load(CFG_PATH.read_text()) or {}

    # Check whether optimization already has relevant keys; if present, respect config and do nothing.
    opt = cfg.get("optimization", {})
    keys_present = any(k in opt for k in ("sl", "tp", "sl_points", "tp_points", "fib_tolerance", "fib_tol"))
    if keys_present:
        print("config.yaml's optimization section already contains SL/TP/fib settings. Nothing to do.")
        print("Existing optimization:", opt)
        return

    # Find PDF
    pdf = find_pdf_candidate()
    if not pdf:
        print("No forex PDF candidate found in project root. Nothing to update.")
        return

    print("Using PDF candidate:", pdf)

    # Parse PDF preview/fulltext
    text = ""
    parsed = {}
    if parse_forex_node_pdf:
        try:
            parsed = parse_forex_node_pdf(pdf)
            # parse_forex_node_pdf returns dict with keys like 'preview', 'symbols', 'strategies'
            text = (parsed.get("preview") or "") + " " + (parsed.get("text") or "")
        except Exception:
            text = ""
    else:
        print("parse_forex_node_pdf not available; cannot parse PDF. Aborting.")
        return

    if not text.strip():
        # As fallback use the preview if present
        text = parsed.get("preview", "")

    if not text.strip():
        print("No textual content could be extracted from PDF. Nothing to parse.")
        return

    found = extract_numbers_from_text(text)
    print("Parsed numeric candidates from PDF:", found)

    to_inject = {}
    if found["sl_pips"]:
        to_inject.setdefault("sl_points", convert_pips_to_points(found["sl_pips"]))
    if found["tp_pips"]:
        to_inject.setdefault("tp_points", convert_pips_to_points(found["tp_pips"]))
    if found["fib_tol"]:
        # your code expects a list for 'fib_tolerance' (e.g. [0.001])
        to_inject.setdefault("fib_tolerance", [float(found["fib_tol"])])

    if not to_inject:
        print("No SL/TP/fib numeric parameters detected. Nothing to inject.")
        return

    # Backup config.yaml
    ts = int(time.time())
    backup = CFG_PATH.with_suffix(f".yaml.bak.{ts}")
    shutil.copy2(CFG_PATH, backup)
    print("Backed up config.yaml to", backup)

    # Merge into optimization section
    new_opt = dict(opt)  # shallow copy
    # use keys consistent with existing expectations: sl_points, tp_points, fib_tolerance
    if "sl_points" in to_inject and "sl_points" not in new_opt:
        new_opt["sl_points"] = to_inject["sl_points"]
    if "tp_points" in to_inject and "tp_points" not in new_opt:
        new_opt["tp_points"] = to_inject["tp_points"]
    if "fib_tolerance" in to_inject and "fib_tolerance" not in new_opt:
        new_opt["fib_tolerance"] = to_inject["fib_tolerance"]

    cfg["optimization"] = new_opt

    # Write back
    CFG_PATH.write_text(yaml.safe_dump(cfg, sort_keys=False), encoding="utf-8")
    print("Updated config.yaml -> optimization keys injected:", to_inject)
    print("Done.")

if __name__ == "__main__":
    main()
