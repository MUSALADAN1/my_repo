# tests/test_trailing_atr.py
import pytest
from bot_core.risk.risk_manager import RiskManager

def test_atr_trailing_stop_moves_and_triggers():
    rm = RiskManager(max_concurrent_deals=3, trailing_stop_pct=0.02,
                     trailing_stop_mode="atr", atr_period=14, atr_multiplier=2.0)

    pid = "pos-1"
    side = "long"
    entry_price = 100.0
    amount = 1000.0
    initial_atr = 1.5  # initial ATR at open

    pos = rm.open_position(pid, side, entry_price, amount, atr=initial_atr)
    # initial stop should be entry - k*atr = 100 - 2*1.5 = 97.0
    assert abs(pos["stop"] - 97.0) < 1e-6

    # price moves up strongly; ATR updates (simulate a slightly lower ATR)
    new_price = 106.0
    new_atr = 1.3
    new_stop = rm.update_price(pid, new_price, atr=new_atr)
    # expected new_stop = max(97.0, 106 - 2*1.3 = 103.4) => 103.4
    assert abs(new_stop - 103.4) < 1e-6

    # now price falls to 103.0, which is below current stop 103.4 -> should_close should be True
    assert rm.should_close(pid, 103.0) is True
