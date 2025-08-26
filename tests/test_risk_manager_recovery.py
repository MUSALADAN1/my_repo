# tests/test_risk_manager_recovery.py
from bot_core.storage.sqlite_store import SQLiteStore
from bot_core.risk_manager import RiskManager
from bot_core.risk_manager_utils import load_positions_from_store

def test_recover_positions_from_store(tmp_path):
    db_path = str(tmp_path / "recover.sqlite")
    store = SQLiteStore(db_path)

    # create first RM with persist hook so it writes into sqlite
    rm_src = RiskManager(initial_balance=1000.0, max_concurrent=5, persist_hook=store.persist)

    pid = "recover-1"
    rm_src.open_position(pid, "long", 123.45, 2.0, size=2.0, strategy="s1")

    # now create a new risk manager (fresh) and recover from store
    rm_new = RiskManager(initial_balance=1000.0, max_concurrent=5)

    # ensure fresh has no positions
    assert pid not in rm_new.list_positions()

    # load positions
    load_positions_from_store(store, rm_new)

    # now rm_new should have the recovered position
    assert pid in rm_new.list_positions()
    pos = rm_new.get_position(pid)
    assert pos is not None
    assert float(pos.get("entry_price", 0.0)) == 123.45
    # verify strategy recorded
    assert pos.get("strategy") == "s1"
