# bot_core/knowledge/forex_node_loader.py
"""
Simple loader/parser for a "Forex node" PDF (e.g. 'Forex node1(1).pdf').
This module extracts text and returns a small structured summary (symbols,
sessions, strategy keywords, and a short text preview).
It is intentionally conservative and rule-of-thumb based (regex + keyword scan).
"""

from typing import Dict, List, Any
import re
from pathlib import Path

# We use PyPDF2 for PDF text extraction.
# Install with: python -m pip install PyPDF2
try:
    from PyPDF2 import PdfReader
except Exception as exc:
    PdfReader = None  # type: ignore

_SYMBOL_RE = re.compile(r'\b([A-Z]{3}[ /]?([A-Z]{3}m?)|[A-Z]{3}\/[A-Z]{3})\b')
# Accept forms like "EURUSD", "EURUSDm", "EUR/USD"
_SESSION_KEYWORDS = ["SYDNEY", "TOKYO", "LONDON", "FRANKFURT", "NEW YORK", "NEWYORK", "NEW-YORK"]
STRATEGY_KEYWORDS = [
    "NFP", "NON FARM", "NONFARM", "STRADDLE", "FADE", "FIBONACCI", "PIVOT", "ICHIMOKU",
    "SUPPLY", "DEMAND", "FRACTAL", "ZIGZAG", "BOLLINGER", "ELLIOTT", "RISK MANAGEMENT",
    "SCALP", "STRATEGY", "TRADING THE FADE", "STRADDLE STRATEGY"
]


def _extract_text_from_pdf(path: Path, max_pages: int = 50) -> str:
    if PdfReader is None:
        raise RuntimeError("PyPDF2 PdfReader not available. Install with: pip install PyPDF2")
    reader = PdfReader(str(path))
    texts = []
    for i, page in enumerate(reader.pages):
        if i >= max_pages:
            break
        try:
            texts.append(page.extract_text() or "")
        except Exception:
            # best-effort continue
            try:
                texts.append(page.extract_text() or "")
            except Exception:
                texts.append("")
    return "\n".join(texts)


def parse_forex_node_pdf(file_path: str) -> Dict[str, Any]:
    """
    Parse the provided PDF file and return a dictionary:
      {
        "path": str,
        "symbols": [ ... ],
        "sessions": [ ... ],
        "strategies": [ ... ],
        "preview": "first 500 chars",
        "full_text_length": int
      }
    """
    p = Path(file_path)
    if not p.exists():
        raise FileNotFoundError(f"File not found: {file_path}")

    text = _extract_text_from_pdf(p)

    # Normalize whitespace
    norm = re.sub(r"\s+", " ", text).upper()

    # Extract currency pairs (basic heuristics)
    raw_symbols = set()
    for m in _SYMBOL_RE.finditer(norm):
        candidate = m.group(0).replace("/", "").replace(" ", "")
        # normalize common "m" suffix (e.g., GBPUSDm -> GBPUSD)
        candidate = candidate.replace("M", "") if candidate.endswith("M") else candidate
        if len(candidate) >= 6 and candidate[:6].isalpha():
            sym = candidate[:6]
            raw_symbols.add(sym)

    symbols = sorted(raw_symbols)

    # Sessions
    sessions = [s for s in _SESSION_KEYWORDS if s in norm]
    # strategies: pick keywords present
    strategies = []
    for kw in STRATEGY_KEYWORDS:
        if kw.upper() in norm:
            strategies.append(kw.title())

    preview = (text[:1000] + "...") if len(text) > 1000 else text

    return {
        "path": str(p.resolve()),
        "symbols": symbols,
        "sessions": sessions,
        "strategies": strategies,
        "preview": preview,
        "full_text_length": len(text)
    }


# Convenience helper to load the uploaded default PDF if present
def load_default_if_exists(base_dir: str = ".", filename_patterns: List[str] = None) -> Dict[str, Any]:
    """Look for a likely forex node PDF in base_dir and parse it."""
    p = Path(base_dir)
    if filename_patterns is None:
        filename_patterns = ["forex node*.pdf", "forex*.pdf", "*.pdf"]
    # prefer exact match "Forex node1(1).pdf" if present
    candidates = []
    for pat in filename_patterns:
        candidates.extend(sorted(p.glob(pat)))
    # filter out unlikely matches (size > 1KB)
    candidates = [c for c in candidates if c.is_file() and c.stat().st_size > 1024]
    if not candidates:
        raise FileNotFoundError("No PDF candidates found in directory.")
    # pick first candidate (user can call parse_forex_node_pdf with exact path if they want a different file)
    chosen = candidates[0]
    return parse_forex_node_pdf(str(chosen))

# -----------------------
# Session-time extraction
# -----------------------
import math

_SESSION_NAMES = ["SYDNEY", "TOKYO", "LONDON", "FRANKFURT", "NEW YORK", "NEWYORK", "NEW-YORK"]

def extract_session_times_from_text(text: str) -> dict:
    """
    Conservative heuristics to find session time windows in textual PDF content.

    Returns dict mapping normalized session name -> (start_hour, end_hour) using 24-hour ints.
    Example: {'LONDON': (8,16), 'TOKYO': (0,8)}
    If nothing reliable is found, returns {}.
    """
    if not text:
        return {}
    norm = re.sub(r"\s+", " ", text).upper()

    # Patterns we attempt (order matters)
    # 1) London: 8 - 16  OR London 8-16 OR LONDON (8,16)
    pat1 = re.compile(r'\b(' + '|'.join([re.escape(n) for n in _SESSION_NAMES]) + r')\b[^0-9]{0,6}?([0-2]?\d)\s*(?:[:h]?)\s*(?:-|–|—|to)\s*([0-2]?\d)', re.IGNORECASE)
    # 2) London 8 16  OR London [8,16]
    pat2 = re.compile(r'\b(' + '|'.join([re.escape(n) for n in _SESSION_NAMES]) + r')\b[^0-9]{0,6}?\(?\s*([0-2]?\d)\s*[,;\s]\s*([0-2]?\d)\s*\)?', re.IGNORECASE)
    # 3) Fit "GMT" annotations e.g. "London (08:00 - 16:00 GMT)"
    pat3 = re.compile(r'\b(' + '|'.join([re.escape(n) for n in _SESSION_NAMES]) + r')\b[^0-9]{0,12}?([0-2]?\d)[:.]?([0-5]?\d)?\s*(?:-|to)\s*([0-2]?\d)[:.]?([0-5]?\d)?', re.IGNORECASE)

    found = {}

    for pat in (pat1, pat2, pat3):
        for m in pat.finditer(norm):
            name = m.group(1).upper().replace(" ", "").replace("-", "").replace("_", "")
            # pick the first two numeric groups we can convert to hours
            nums = []
            for g in m.groups()[1:]:
                if g is None:
                    continue
                try:
                    iv = int(g)
                except Exception:
                    continue
                # normalize to 0-23
                if iv >= 24:
                    iv = iv % 24
                nums.append(iv)
                if len(nums) >= 2:
                    break
            if len(nums) >= 2:
                start, end = nums[0], nums[1]
                # If end == start, treat as full-day (0-24) not useful — skip
                if start == end:
                    continue
                # store only sensible ranges (0-24)
                if 0 <= start <= 23 and 0 <= end <= 23:
                    found[name] = (start, end)
    return found


def parse_session_times(file_path: str) -> dict:
    """
    Parse PDF and try to extract session time windows.
    Returns mapping e.g. {'SYDNEY': (22,6), 'LONDON': (8,16)} or {} if none found.
    """
    p = Path(file_path)
    if not p.exists():
        # try default loader search
        try:
            info = load_default_if_exists(str(p.parent))
            # We don't have raw text here, so re-open the chosen PDF directly
            chosen = info.get("path")
            if chosen:
                text = _extract_text_from_pdf(Path(chosen))
            else:
                return {}
        except Exception:
            return {}
    else:
        try:
            text = _extract_text_from_pdf(p)
        except Exception:
            return {}

    return extract_session_times_from_text(text)


# Small CLI test when run directly
if __name__ == "__main__":
    import json, sys
    target = sys.argv[1] if len(sys.argv) > 1 else "Forex node1(1).pdf"
    try:
        out = parse_forex_node_pdf(target)
        print(json.dumps(out, indent=2))
    except Exception as e:
        print("ERROR:", e)
        raise
