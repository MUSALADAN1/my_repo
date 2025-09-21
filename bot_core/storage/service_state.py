# bot_core/storage/service_state.py
"""
Simple SQLite-backed state store for persistent runtime objects:
- TWAP jobs
- OCO pairs

API is intentionally minimal and synchronous.
"""

import sqlite3
import json
import threading
from typing import Dict, Any, List, Optional

DEFAULT_DB = "service_state.sqlite"

_lock = threading.RLock()

class ServiceStateStore:
    def __init__(self, db_path: str = DEFAULT_DB):
        self.db_path = db_path
        self._conn = sqlite3.connect(self.db_path, check_same_thread=False)
        self._ensure_schema()

    def _ensure_schema(self):
        with _lock:
            cur = self._conn.cursor()
            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS twap_jobs (
                    job_id TEXT PRIMARY KEY,
                    payload_json TEXT NOT NULL,
                    progress_json TEXT,
                    status TEXT NOT NULL,
                    created_ts REAL,
                    updated_ts REAL
                );
                """
            )
            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS oco_pairs (
                    pair_id TEXT PRIMARY KEY,
                    event_id TEXT,
                    primary_id TEXT,
                    secondary_id TEXT,
                    pair_json TEXT NOT NULL,
                    status TEXT NOT NULL,
                    created_ts REAL,
                    updated_ts REAL
                );
                """
            )
            self._conn.commit()

    # ----- TWAP jobs -----
    def save_twap_job(self, job_id: str, payload: Dict[str, Any], status: str = "running",
                      progress: Optional[Dict[str, Any]] = None, ts: float = None):
        payload_json = json.dumps(payload)
        progress_json = json.dumps(progress or {})
        ts = ts or __import__("time").time()
        with _lock:
            cur = self._conn.cursor()
            cur.execute(
                """
                INSERT OR REPLACE INTO twap_jobs (job_id, payload_json, progress_json, status, created_ts, updated_ts)
                VALUES (?, ?, ?, ?, COALESCE((SELECT created_ts FROM twap_jobs WHERE job_id = ?), ?), ?)
                """,
                (job_id, payload_json, progress_json, status, job_id, ts, ts),
            )
            self._conn.commit()

    def update_twap_progress(self, job_id: str, progress: Dict[str, Any], status: Optional[str]=None, ts: float=None):
        progress_json = json.dumps(progress or {})
        ts = ts or __import__("time").time()
        with _lock:
            cur = self._conn.cursor()
            if status:
                cur.execute("UPDATE twap_jobs SET progress_json = ?, status = ?, updated_ts = ? WHERE job_id = ?",
                            (progress_json, status, ts, job_id))
            else:
                cur.execute("UPDATE twap_jobs SET progress_json = ?, updated_ts = ? WHERE job_id = ?",
                            (progress_json, ts, job_id))
            self._conn.commit()

    def delete_twap_job(self, job_id: str):
        with _lock:
            cur = self._conn.cursor()
            cur.execute("DELETE FROM twap_jobs WHERE job_id = ?", (job_id,))
            self._conn.commit()

    def list_active_twap_jobs(self) -> List[Dict[str, Any]]:
        with _lock:
            cur = self._conn.cursor()
            cur.execute("SELECT job_id, payload_json, progress_json, status, created_ts, updated_ts FROM twap_jobs WHERE status IN ('running','paused')")
            rows = cur.fetchall()
        res = []
        for r in rows:
            res.append({
                "job_id": r[0],
                "payload": json.loads(r[1]),
                "progress": json.loads(r[2] or "{}"),
                "status": r[3],
                "created_ts": r[4],
                "updated_ts": r[5],
            })
        return res

    # ----- OCO pairs -----
    def save_oco_pair(self, pair_id: str, data: Dict[str, Any], status: str = "open", ts: float = None):
        pair_json = json.dumps(data)
        ts = ts or __import__("time").time()
        with _lock:
            cur = self._conn.cursor()
            cur.execute(
                """
                INSERT OR REPLACE INTO oco_pairs (pair_id, event_id, primary_id, secondary_id, pair_json, status, created_ts, updated_ts)
                VALUES (?, ?, ?, ?, ?, ?, COALESCE((SELECT created_ts FROM oco_pairs WHERE pair_id = ?), ?), ?)
                """,
                (pair_id, data.get("event_id"), data.get("primary_id"), data.get("secondary_id"), pair_json, status, pair_id, ts, ts),
            )
            self._conn.commit()

    def update_oco_pair_status(self, pair_id: str, status: str, ts: float = None):
        ts = ts or __import__("time").time()
        with _lock:
            cur = self._conn.cursor()
            cur.execute("UPDATE oco_pairs SET status = ?, updated_ts = ? WHERE pair_id = ?", (status, ts, pair_id))
            self._conn.commit()

    def delete_oco_pair(self, pair_id: str):
        with _lock:
            cur = self._conn.cursor()
            cur.execute("DELETE FROM oco_pairs WHERE pair_id = ?", (pair_id,))
            self._conn.commit()

    def list_active_oco_pairs(self) -> List[Dict[str, Any]]:
        with _lock:
            cur = self._conn.cursor()
            cur.execute("SELECT pair_id, pair_json, status, created_ts, updated_ts FROM oco_pairs WHERE status = 'open'")
            rows = cur.fetchall()
        res = []
        for r in rows:
            res.append({
                "pair_id": r[0],
                "data": json.loads(r[1]),
                "status": r[2],
                "created_ts": r[3],
                "updated_ts": r[4],
            })
        return res

# Convenience singleton
_default_store = None

def get_default_store(db_path: Optional[str] = None) -> ServiceStateStore:
    global _default_store
    if _default_store is None:
        _default_store = ServiceStateStore(db_path or DEFAULT_DB)
    return _default_store
