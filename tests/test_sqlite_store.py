# tests/test_sqlite_store.py
import tempfile
import os
import time
from bot_core.storage.sqlite_store import SQLiteStore
from bot_core.risk_manager import RiskManager

def test_sqlite_store_persist_and_recover(tmp_path):
    db_path = str(tmp_path / "pos_test.sqlite")
    store = SQLiteStore(db_path)

    # create a RiskManager that uses the store.persist hook
    rm = RiskManager(initial_balance=1000.0, max_concurrent=10, persist_hook=store.persist)

    pid = "test-1"
    rm.open_position(pid, "long", 100.0, 1.5, size=1.5, strategy="s1")

    # ensure store contains it
    got = store.get_position(pid)
    assert got is not None
    assert got["pid"] == pid
    assert got["status"] in ("open", None)  # risk manager sets 'open'

    # close it and ensure store updated
    rm.close_position(pid)
    got2 = store.get_position(pid)
    assert got2 is not None
    assert got2["status"] == "closed"

    # list positions
    allp = store.list_positions()
    assert pid in allp
