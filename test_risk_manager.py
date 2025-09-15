# test_risk_manager.py
import pytest
from bot_core.risk.risk_manager import RiskManager, RiskManagerError

def test_trailing_stop_moves_and_triggers_close():
    rm = RiskManager(max_concurrent_deals=3, trailing_stop_pct=0.05)
    pos = rm.open_position(pid="p1", side="long", entry_price=100.0, amount=100.0)
    assert pos["stop"] == pytest.approx(95.0)

    # price moves up -> peak increases and stop moves up accordingly
    new_stop = rm.update_price("p1", 110.0)
    # expected new stop = max(old_stop, 110*(1-0.05)=104.5) -> 104.5
    assert new_stop == pytest.approx(104.5)

    # price falls below stop -> should close
    assert rm.should_close("p1", 103.0) is True

    # close removes position
    removed = rm.close_position("p1")
    assert removed is not None
    assert "p1" not in rm.list_positions()

def test_max_concurrent_enforced():
    rm = RiskManager(max_concurrent_deals=2, trailing_stop_pct=0.03)
    rm.open_position(pid="a", side="long", entry_price=50.0, amount=50.0)
    rm.open_position(pid="b", side="short", entry_price=200.0, amount=200.0)
    assert rm.can_open_new() is False
    with pytest.raises(RiskManagerError):
        rm.open_position(pid="c", side="long", entry_price=60.0, amount=60.0)

    # close one and ensure we can open more
    rm.close_position("a")
    assert rm.can_open_new() is True
    p = rm.open_position(pid="c", side="long", entry_price=60.0, amount=60.0)
    assert p["pid"] == "c"

def test_drawdown_alert_logic():
    rm = RiskManager(max_concurrent_deals=3, trailing_stop_pct=0.02, drawdown_alert_pct=0.10)  # alert at 10%
    dd, alert = rm.record_equity(10000.0)
    assert dd == pytest.approx(0.0) and alert is False

    # equity rises
    dd, alert = rm.record_equity(11000.0)
    assert dd == pytest.approx(0.0) and alert is False

    # equity falls but not enough for alert
    dd, alert = rm.record_equity(10500.0)
    assert dd < 0 and alert is False

    # equity drops below 10% from peak (11000 -> 9800 is ~ -0.109) -> alert True
    dd, alert = rm.record_equity(9800.0)
    assert alert is True
    assert dd <= -0.089  # roughly -10% or worse
