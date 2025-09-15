#!/usr/bin/env python3
"""
Scan the repository for direct 'mt5.' (and related) usages and emit a JSON
report plus a concise console summary. Designed as a safe, read-only tool.
"""
import os
import re
import json
import argparse

# Patterns to detect direct references to MT5
PATTERNS = [
    r"\bmt5\.",            # direct attribute usage
    r"\bMetaTrader5\b",    # import or reference
    r"import\s+mt5\b",     # import mt5
]

def scan(root):
    results = {}
    total = 0
    for dirpath, dirnames, filenames in os.walk(root):
        # skip virtualenvs, git, caches
        if any(skip in dirpath for skip in ("venv", ".git", "__pycache__")):
            continue
        for fname in filenames:
            if not fname.endswith(".py"):
                continue
            path = os.path.join(dirpath, fname)
            try:
                txt = open(path, "r", encoding="utf-8", errors="ignore").read()
            except Exception:
                continue
            matches = []
            for i, line in enumerate(txt.splitlines(), start=1):
                for pat in PATTERNS:
                    if re.search(pat, line):
                        matches.append({"line": i, "text": line.strip()})
                        total += 1
                        break
            if matches:
                rel = os.path.relpath(path, root)
                results[rel] = matches
    return results, total

def main():
    parser = argparse.ArgumentParser(description="Scan repo for mt5 usages")
    parser.add_argument("--root", default=".", help="Repo root (default: .)")
    parser.add_argument("--out", default="mt5_usages.json", help="Output JSON file")
    args = parser.parse_args()

    root = os.path.abspath(args.root)
    results, total = scan(root)
    summary = {"total_matches": total, "files_with_matches": len(results)}
    out = {"summary": summary, "results": results}
    with open(args.out, "w", encoding="utf-8") as f:
        json.dump(out, f, indent=2)

    # Console summary (compact)
    print(f"Scanned root: {root}")
    print(f"Files with matches: {len(results)}; total matches: {total}")
    if len(results) <= 40:
        for fn, matches in sorted(results.items()):
            sample = matches[0]["text"] if matches else ""
            print(f" - {fn}: {len(matches)} match(es); sample (line {matches[0]['line']}): {sample[:200]}")
    else:
        print(" - Many files matched; see", args.out)
    print("Report written to", args.out)

if __name__ == "__main__":
    main()
