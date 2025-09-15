# bot_core/storage/order_store.py
"""
OrderStore - simple SQLite-backed order lifecycle store.

Provides:
 - OrderStore(path=None) : path defaults to ./order_store.sqlite
 - OrderSQLiteStore : compatibility alias (tests expect this name)
 - persist_order(order_dict) -> stores initial record (compatibility alias)
 - record_new_order(order_dict) -> stores initial record
 - update_order_state(order_id, status, filled=None, price=None, raw=None)
 - get_order(order_id) -> dict or None
 - list_open_orders() -> dict mapping id->order
 - close() -> cleanup (not required)
"""

import os
import json
import sqlite3
import time
from typing import Optional, Dict, Any

DEFAULT_PATH = os.environ.get("ORDER_STORE_PATH", os.path.join(os.getcwd(), "order_store.sqlite"))


class OrderStore:
    def __init__(self, path: Optional[str] = None):
        self.path = path or DEFAULT_PATH
        os.makedirs(os.path.dirname(self.path) or ".", exist_ok=True)
        # allow cross-thread usage in simple apps/tests
        self._conn = sqlite3.connect(self.path, check_same_thread=False)
        try:
            self._conn.execute("PRAGMA journal_mode=WAL;")
        except Exception:
            pass
        self._ensure_table()

    def _ensure_table(self):
        cur = self._conn.cursor()
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS orders (
                id TEXT PRIMARY KEY,
                symbol TEXT,
                side TEXT,
                amount REAL,
                filled REAL,
                price REAL,
                status TEXT,
                created_ts REAL,
                updated_ts REAL,
                raw_json TEXT
            )
            """
        )
        cur.execute("CREATE INDEX IF NOT EXISTS idx_orders_status ON orders(status)")
        self._conn.commit()

    # Compatibility alias expected by tests
    # Compatibility alias expected by tests
    # Compatibility alias expected by tests
    def persist_order(self, order: Dict[str, Any]) -> str:
        """
        Compatibility method name. Delegates to record_new_order and returns the persisted id.
        """
        oid = self.record_new_order(order)
        return oid

    def record_new_order(self, order: Dict[str, Any]) -> str:
        """
        Insert a new order record. order must include: id, symbol, side, amount, status (optional).
        Returns inserted order id.
        """
        oid = str(order.get("id") or order.get("order_id") or order.get("orderId") or "")
        if not oid:
            raise ValueError("order must include an 'id' field")
        # ... existing logic unchanged ...
        cur = self._conn.cursor()
        cur.execute(
            """
            INSERT OR REPLACE INTO orders (id, symbol, side, amount, filled, price, status, created_ts, updated_ts, raw_json)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (oid, symbol, side, amount, filled, price, status, now, now, raw_json)
        )
        self._conn.commit()
        return oid

    # alias expected by some tests
    def update_order(self, order_id: str, status: str, filled: Optional[float] = None,
                     price: Optional[float] = None, raw: Optional[Dict[str, Any]] = None) -> None:
        """Compatibility wrapper name used by tests and older code."""
        return self.update_order_state(order_id, status, filled=filled, price=price, raw=raw)

    def list_orders(self, status: Optional[str] = None) -> list:
        """
        Return a list of orders (as dicts). If `status` provided, filter by status.
        This is used by reconcile_orders which expects list_orders(status=...).
        """
        cur = self._conn.cursor()
        if status:
            cur.execute("SELECT id FROM orders WHERE status = ?", (status,))
        else:
            cur.execute("SELECT id FROM orders")
        rows = cur.fetchall()
        out = []
        for (oid,) in rows:
            rec = self.get_order(oid)
            if rec:
                out.append(rec)
        return out



    def update_order_state(self, order_id: str, status: str, filled: Optional[float] = None,
                            price: Optional[float] = None, raw: Optional[Dict[str, Any]] = None) -> None:
        now = time.time()
        cur = self._conn.cursor()
        cur.execute("SELECT amount, filled, price, raw_json FROM orders WHERE id = ?", (order_id,))
        row = cur.fetchone()
        if row is None:
            base = {
                "id": order_id,
                "symbol": None,
                "side": None,
                "amount": None,
                "filled": filled or 0.0,
                "price": price,
                "status": status,
            }
            if raw:
                base.update({"raw": raw})
            self.record_new_order(base)
            return

        cur_amount, cur_filled, cur_price, cur_raw_json = row
        new_filled = float(filled) if filled is not None else (cur_filled if cur_filled is not None else 0.0)
        new_price = float(price) if price is not None else (cur_price if cur_price is not None else None)

        new_raw_json = cur_raw_json
        if raw is not None:
            try:
                new_raw_json = json.dumps(raw, default=str)
            except Exception:
                # preserve old raw if serialization fails
                pass

        cur.execute(
            """
            UPDATE orders
               SET filled = ?, price = ?, status = ?, updated_ts = ?, raw_json = ?
             WHERE id = ?
            """,
            (new_filled, new_price, status, now, new_raw_json, order_id)
        )
        self._conn.commit()

    def get_order(self, order_id: str) -> Optional[Dict[str, Any]]:
        cur = self._conn.cursor()
        cur.execute("SELECT id, symbol, side, amount, filled, price, status, created_ts, updated_ts, raw_json FROM orders WHERE id = ?", (order_id,))
        row = cur.fetchone()
        if row is None:
            return None
        oid, symbol, side, amount, filled, price, status, created_ts, updated_ts, raw_json = row
        try:
            raw = json.loads(raw_json) if raw_json else None
        except Exception:
            raw = raw_json
        return {
            "id": oid,
            "symbol": symbol,
            "side": side,
            "amount": amount,
            "filled": filled,
            "price": price,
            "status": status,
            "created_ts": created_ts,
            "updated_ts": updated_ts,
            "raw": raw
        }

    def list_open_orders(self) -> Dict[str, Dict[str, Any]]:
        """
        Returns open orders (status not in final states)
        Final states: filled, cancelled, rejected
        """
        cur = self._conn.cursor()
        cur.execute("SELECT id FROM orders WHERE status NOT IN ('filled','cancelled','rejected')")
        rows = cur.fetchall()
        out = {}
        for (oid,) in rows:
            rec = self.get_order(oid)
            if rec:
                out[oid] = rec
        return out

    def close(self):
        try:
            self._conn.commit()
        except Exception:
            pass
        try:
            self._conn.close()
        except Exception:
            pass


# Compatibility alias expected by tests
class OrderSQLiteStore(OrderStore):
    """Compatibility wrapper used by existing tests and code that import OrderSQLiteStore."""
    pass
