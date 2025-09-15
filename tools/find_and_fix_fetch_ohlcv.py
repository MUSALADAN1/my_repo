#!/usr/bin/env python3
"""
Find 'def fetch_ohlcv' occurrences and @abstractmethod decorators near them.
Optionally patch to remove @abstractmethod and ensure function raises NotImplementedError.

Usage:
  python tools/find_and_fix_fetch_ohlcv.py        # dry-run: prints matches only
  python tools/find_and_fix_fetch_ohlcv.py --apply   # apply changes (backups created)
"""

import re
import argparse
from pathlib import Path
from textwrap import dedent

parser = argparse.ArgumentParser()
parser.add_argument("--apply", action="store_true", help="apply changes (create .bak backups)")
parser.add_argument("--preview", action="store_true", help="show file diffs before applying")
args = parser.parse_args()

root = Path(".")
py_files = [p for p in root.rglob("*.py") if not any(x in p.parts for x in (".git", "venv", "node_modules", "__pycache__"))]

fetch_re = re.compile(r"def\s+fetch_ohlcv\s*\(", re.MULTILINE)
abstract_re = re.compile(r"@abstractmethod\s*\n\s*def\s+fetch_ohlcv\s*\(", re.MULTILINE)

patched_files = []
for p in sorted(py_files):
    s = p.read_text(encoding="utf-8", errors="replace")
    if fetch_re.search(s):
        print(f"\n== {p} ==")
        # show small context: lines around def
        idx = fetch_re.search(s).start()
        start = max(0, s.rfind("\n", 0, idx-300))
        end = min(len(s), s.find("\n", idx+200))
        snippet = s[start:end]
        print(snippet)
        if abstract_re.search(s):
            print("-> Found @abstractmethod preceding fetch_ohlcv")
            if args.apply:
                # remove the decorator only in the specific decorator+def pattern
                s2 = abstract_re.sub("def fetch_ohlcv(", s, count=1)
                # ensure function body has NotImplementedError
                # locate def line start
                m = re.search(r"def\s+fetch_ohlcv\s*\([^\)]*\)\s*:\s*\n", s2)
                if m:
                    insert_pos = m.end()
                    following = s2[insert_pos:insert_pos+200]
                    if "NotImplementedError" not in following:
                        # determine indentation (use 4 spaces)
                        indent = "    "
                        insert = indent + "raise NotImplementedError('fetch_ohlcv is not implemented for this adapter')\n"
                        s2 = s2[:insert_pos] + insert + s2[insert_pos:]
                # write backup then new file
                bak = p.with_suffix(p.suffix + ".bak")
                bak.write_text(s, encoding="utf-8")
                p.write_text(s2, encoding="utf-8")
                patched_files.append(str(p))
                print("Patched:", p)
        else:
            print("-> No @abstractmethod decorator found for this function (ok).")

if not args.apply:
    print("\nDry-run complete. Re-run with --apply to make changes.")
else:
    print("\nApplied changes to files:", patched_files)
