# bot_core/knowledge/apply_forex_node_to_config.py
"""
Apply PDF-extracted forex node symbols into config.yaml automatically.

Behavior:
- Loads BASE_DIR/config.yaml
- If config.yaml contains no 'symbols' key or it's empty, it will attempt to
  parse the local Forex node PDF (via forex_node_loader.load_default_if_exists)
  and write a filtered list of symbols into config.yaml.
- Creates a backup of config.yaml as config.yaml.bak.TIMESTAMP
- Does nothing if config.yaml already contains non-empty 'symbols'.

Run from repo root with: python -m bot_core.knowledge.apply_forex_node_to_config
"""

from pathlib import Path
import yaml
from datetime import datetime
import re
import sys

# local loader
from bot_core.knowledge.forex_node_loader import load_default_if_exists, parse_forex_node_pdf

BASE_DIR = Path(__file__).resolve().parents[2]  # points to repo root /my_trading_bot
CFG_PATH = BASE_DIR / "bot_core" / "config.yaml"

SYMBOL_RE = re.compile(r'^[A-Z]{6}$')  # matches EURUSD, USDJPY, etc.


def read_config(path: Path):
    if not path.exists():
        return {}
    with path.open("r", encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


def write_config(path: Path, cfg: dict):
    with path.open("w", encoding="utf-8") as f:
        yaml.safe_dump(cfg, f, sort_keys=False)


def backup_file(path: Path):
    stamp = datetime.utcnow().strftime("%Y%m%dT%H%M%SZ")
    bak = path.with_suffix(path.suffix + f".bak.{stamp}")
    path.replace(bak)
    return bak


def normalize_and_filter(symbols):
    out = []
    for s in symbols:
        s2 = s.strip().upper().replace("/", "").replace(" ", "")
        # remove trailing 'M' that loader may have removed earlier; we will re-add suffix later if needed
        if s2.endswith("M"):
            s2 = s2[:-1]
        if SYMBOL_RE.match(s2):
            out.append(s2)
    # preserve order, unique
    seen = set()
    filtered = []
    for s in out:
        if s not in seen:
            filtered.append(s)
            seen.add(s)
    return filtered


def main():
    print("Applying Forex node symbols to config.yaml (if needed)...")
    cfg_path = CFG_PATH
    if not cfg_path.exists():
        print("config.yaml not found at:", cfg_path)
        sys.exit(1)

    cfg = read_config(cfg_path)
    have_symbols = bool(cfg.get("symbols"))
    if have_symbols:
        print("config.yaml already contains 'symbols'. Nothing to do.")
        print("Existing symbols:", cfg.get("symbols"))
        return

    # Try to load PDF candidate from BASE_DIR/bot_core (the loader searches repo root by default)
    try:
        info = load_default_if_exists(str(BASE_DIR))
        extracted = info.get("symbols", [])
        print("Extracted symbols from PDF (raw):", extracted[:30])
    except Exception as e:
        print("Failed to find/parse PDF candidate:", e)
        # try to check a common filename inside repo root as fallback
        fallback = BASE_DIR / "Forex node1(1).pdf"
        if fallback.exists():
            info = parse_forex_node_pdf(str(fallback))
            extracted = info.get("symbols", [])
            print("Extracted symbols from fallback filename:", extracted[:30])
        else:
            print("No PDF found to extract symbols. Aborting.")
            return

    filtered = normalize_and_filter(extracted)
    if not filtered:
        print("No valid 6-letter currency symbols were found in the PDF. Aborting.")
        return

    # Decide whether to add 'm' suffix to match existing default convention.
    # Heuristic: if any default in our repo has trailing 'm', we re-add it.
    default_has_m = False
    # Check common places: bot_core/config.yaml may have defaults elsewhere; fallback to a heuristic
    # If repo naming (e.g., intraday_trading_bot) uses 'EURUSDm' style, use suffix
    # We'll check a tiny set of known filenames for evidence:
    candidate_files = [
        BASE_DIR / "bot_core" / "intraday_trading_bot.py",
        BASE_DIR / "bot_core" / "exchanges" / "mt5_adapter.py",
    ]
    for cf in candidate_files:
        try:
            text = cf.read_text(encoding="utf-8")
            if re.search(r"[A-Z]{6}m", text):
                default_has_m = True
                break
        except Exception:
            continue

    final_symbols = [s + "m" for s in filtered] if default_has_m else filtered

    # Backup config.yaml and write new one
    bak_path = cfg_path.with_suffix(cfg_path.suffix + ".bak." + datetime.utcnow().strftime("%Y%m%dT%H%M%SZ"))
    cfg_path.replace(bak_path)  # atomic move; keeps original as backup
    print("Backup of config.yaml created:", bak_path)

    cfg["symbols"] = final_symbols
    write_config(cfg_path, cfg)
    print("Wrote updated config.yaml with symbols:", final_symbols)
    print("Done.")


if __name__ == "__main__":
    main()
