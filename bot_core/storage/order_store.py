# bot_core/storage/order_store.py
import sqlite3
import json
from typing import Any, Dict, List, Optional
from datetime import datetime, timezone
import os

DEFAULT_SCHEMA = """
CREATE TABLE IF NOT EXISTS orders (
    id TEXT PRIMARY KEY,
    status TEXT,
    symbol TEXT,
    side TEXT,
    amount REAL,
    price REAL,
    order_type TEXT,
    strategy TEXT,
    raw TEXT,
    created_at TEXT,
    updated_at TEXT
);
CREATE INDEX IF NOT EXISTS idx_orders_status ON orders(status);
"""

def _now_iso():
    return datetime.now(timezone.utc).isoformat()

class OrderSQLiteStore:
    """
    Simple SQLite-backed order persistence.

    Methods:
      - persist_order(order: dict) -> str (id)
      - update_order(order_id: str, **fields) -> None
      - get_order(order_id) -> dict | None
      - list_orders(status: Optional[str] = None) -> List[dict]
      - close()
    """
    def __init__(self, path: str):
        self.path = path or ":memory:"
        os.makedirs(os.path.dirname(self.path) or ".", exist_ok=True)
        self.conn = sqlite3.connect(self.path, check_same_thread=False)
        self.conn.row_factory = sqlite3.Row
        self._ensure_schema()

    def _ensure_schema(self):
        cur = self.conn.cursor()
        cur.executescript(DEFAULT_SCHEMA)
        self.conn.commit()

    def persist_order(self, order: Dict[str, Any]) -> str:
        """
        Insert or replace order record.
        Expects 'id' key in order. If missing, raises ValueError.
        """
        if not order or "id" not in order:
            raise ValueError("order must contain 'id'")

        oid = str(order["id"])
        now = _now_iso()
        raw = json.dumps(order, default=str)

        # try insert, if exists replace certain fields
        cur = self.conn.cursor()
        cur.execute(
            "INSERT OR REPLACE INTO orders (id,status,symbol,side,amount,price,order_type,strategy,raw,created_at,updated_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, COALESCE((SELECT created_at FROM orders WHERE id = ?), ?), ?)",
            (
                oid,
                order.get("status"),
                order.get("symbol"),
                order.get("side"),
                order.get("amount"),
                order.get("price"),
                order.get("order_type"),
                order.get("strategy"),
                raw,
                oid,
                now,
                now,
            ),
        )
        self.conn.commit()
        return oid

    def update_order(self, order_id: str, **fields) -> None:
        """
        Update arbitrary named fields and raw JSON if provided.
        """
        if not order_id:
            return
        set_parts = []
        params: List[Any] = []
        raw = None
        for k, v in fields.items():
            if k == "raw":
                raw = json.dumps(v, default=str)
                set_parts.append("raw = ?")
                params.append(raw)
            else:
                set_parts.append(f"{k} = ?")
                params.append(v)
        # always update updated_at
        set_parts.append("updated_at = ?")
        params.append(_now_iso())

        if not set_parts:
            return
        params.append(order_id)
        sql = f"UPDATE orders SET {', '.join(set_parts)} WHERE id = ?"
        cur = self.conn.cursor()
        cur.execute(sql, params)
        self.conn.commit()

    def get_order(self, order_id: str) -> Optional[Dict[str, Any]]:
        cur = self.conn.cursor()
        cur.execute("SELECT * FROM orders WHERE id = ?", (order_id,))
        row = cur.fetchone()
        if not row:
            return None
        d = dict(row)
        try:
            d["raw"] = json.loads(d.get("raw") or "{}")
        except Exception:
            d["raw"] = d.get("raw")
        return d

    def list_orders(self, status: Optional[str] = None) -> List[Dict[str, Any]]:
        cur = self.conn.cursor()
        if status is None:
            cur.execute("SELECT * FROM orders ORDER BY created_at ASC")
            rows = cur.fetchall()
        else:
            cur.execute("SELECT * FROM orders WHERE status = ? ORDER BY created_at ASC", (status,))
            rows = cur.fetchall()
        out = []
        for r in rows:
            d = dict(r)
            try:
                d["raw"] = json.loads(d.get("raw") or "{}")
            except Exception:
                d["raw"] = d.get("raw")
            out.append(d)
        return out

    def close(self):
        try:
            self.conn.close()
        except Exception:
            pass
