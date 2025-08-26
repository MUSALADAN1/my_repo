# bot_core/storage/sqlite_store.py
import sqlite3
from typing import Optional, Dict, Any
import time
import os
from contextlib import closing

class SQLiteStore:
    """
    Minimal SQLite-backed store for RiskManager positions.
    Usage:
      store = SQLiteStore(path="positions.db")
      rm.persist_hook = store.persist
    The persist hook accepts (action, pos) where action in ("open","close")
    and pos is either a dataclass-like object with attributes or a dict.
    """

    def __init__(self, path: str = "positions.sqlite"):
        # ensure directory exists
        dirp = os.path.dirname(path) or "."
        os.makedirs(dirp, exist_ok=True)
        self.path = path
        self._init_schema()

    def _conn(self):
        # By default sqlite3 returns rows as tuples; we'll convert as needed.
        return sqlite3.connect(self.path, timeout=5, check_same_thread=False)

    def _init_schema(self):
        with closing(self._conn()) as conn:
            cur = conn.cursor()
            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS positions (
                    pid TEXT PRIMARY KEY,
                    side TEXT,
                    entry_price REAL,
                    amount REAL,
                    size REAL,
                    strategy TEXT,
                    opened_at REAL,
                    closed_at REAL,
                    status TEXT
                )
                """
            )
            conn.commit()

    def _normalize(self, pos: Any) -> Dict[str, Any]:
        """
        Accept either dict or object with attributes (like dataclass Position).
        """
        if pos is None:
            return {}
        if isinstance(pos, dict):
            d = pos.copy()
        else:
            # dataclass/object: pull attributes
            d = {
                "pid": getattr(pos, "pid", None),
                "side": getattr(pos, "side", None),
                "entry_price": getattr(pos, "entry_price", None),
                "amount": getattr(pos, "amount", None),
                "size": getattr(pos, "size", None),
                "strategy": getattr(pos, "strategy", None),
                "opened_at": getattr(pos, "opened_at", None),
                "closed_at": getattr(pos, "closed_at", None),
                "status": getattr(pos, "status", None),
            }
        # ensure keys exist
        for k in ["pid","side","entry_price","amount","size","strategy","opened_at","closed_at","status"]:
            d.setdefault(k, None)
        return d

    def persist(self, action: str, pos: Any):
        """
        Action: 'open' or 'close'
        pos: dataclass/object or dict representing position
        """
        d = self._normalize(pos)
        if not d.get("pid"):
            raise ValueError("position must have pid")

        with closing(self._conn()) as conn:
            cur = conn.cursor()
            if action == "open":
                cur.execute(
                    """
                    INSERT OR REPLACE INTO positions
                    (pid, side, entry_price, amount, size, strategy, opened_at, closed_at, status)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        d["pid"],
                        d["side"],
                        d["entry_price"],
                        d["amount"],
                        d["size"],
                        d["strategy"],
                        float(d["opened_at"]) if d["opened_at"] is not None else time.time(),
                        d["closed_at"],
                        d.get("status", "open"),
                    ),
                )
            elif action == "close":
                cur.execute(
                    "UPDATE positions SET status = ?, closed_at = ? WHERE pid = ?",
                    (d.get("status", "closed"), float(d.get("closed_at") or time.time()), d["pid"]),
                )
            else:
                raise ValueError("unknown action")
            conn.commit()

    def get_position(self, pid: str) -> Optional[Dict[str, Any]]:
        with closing(self._conn()) as conn:
            cur = conn.cursor()
            cur.execute("SELECT pid, side, entry_price, amount, size, strategy, opened_at, closed_at, status FROM positions WHERE pid = ?", (pid,))
            row = cur.fetchone()
            if not row:
                return None
            keys = ["pid","side","entry_price","amount","size","strategy","opened_at","closed_at","status"]
            return {k: row[i] for i,k in enumerate(keys)}

    def list_positions(self) -> Dict[str, Dict[str, Any]]:
        with closing(self._conn()) as conn:
            cur = conn.cursor()
            cur.execute("SELECT pid, side, entry_price, amount, size, strategy, opened_at, closed_at, status FROM positions")
            rows = cur.fetchall()
            keys = ["pid","side","entry_price","amount","size","strategy","opened_at","closed_at","status"]
            return {r[0]: {k: r[i] for i,k in enumerate(keys)} for r in rows}
