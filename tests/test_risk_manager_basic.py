# tests/test_risk_manager_basic.py
import pytest
from bot_core.risk_manager import RiskManager

def test_open_close_list():
    rm = RiskManager(initial_balance=1000.0, max_concurrent=2)
    assert rm.can_open_new() is True
    p = rm.open_position("p1", "long", 100.0, 1.0, size=1.0, strategy="s1")
    assert p.pid == "p1"
    assert rm.list_positions()["p1"]["status"] == "open"

    p2 = rm.open_position("p2", "long", 110.0, 1.0)
    assert rm.can_open_new() is False  # reached max_concurrent

    with pytest.raises(Exception):
        rm.open_position("p1", "long", 120.0, 1.0)  # duplicate pid

    rm.close_position("p1")
    assert rm.get_position("p1")["status"] == "closed"
    # Now we can open new one
    assert rm.can_open_new() is True
