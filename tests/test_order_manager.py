# tests/test_order_manager.py
import pytest
from bot_core.order_manager import OrderManager, OrderType, OrderStatus

def test_place_and_cancel_order():
    om = OrderManager()
    o = om.place_order("BTC/USD", "buy", 0.1, price=100.0, order_type=OrderType.LIMIT)
    assert o.id is not None
    assert o.status == OrderStatus.OPEN
    open_orders = om.get_open_orders()
    assert len(open_orders) == 1
    cancelled = om.cancel_order(o.id)
    assert cancelled is True
    assert om.get_order(o.id).status == OrderStatus.CANCELLED
    assert len(om.get_open_orders()) == 0

def test_oco_group_and_fill_cancels_sibling():
    om = OrderManager()
    a = om.place_order("BTC/USD", "sell", 0.1, price=200.0, order_type=OrderType.LIMIT)
    b = om.place_order("BTC/USD", "sell", 0.1, price=210.0, order_type=OrderType.LIMIT)
    gid = om.create_oco(a.id, b.id)
    assert om.get_order(a.id).oco_group == gid
    assert om.get_order(b.id).oco_group == gid

    filled = om.fill_order(a.id, executed_price=200.0)
    assert filled is True
    assert om.get_order(a.id).status == OrderStatus.FILLED
    # sibling should be cancelled
    assert om.get_order(b.id).status == OrderStatus.CANCELLED

def test_pending_order_trigger_and_fill():
    om = OrderManager()
    # create a pending buy that triggers at 50.0
    p = om.place_order("ABC/USD", "buy", 1.0, order_type=OrderType.PENDING, trigger_price=50.0)
    assert p.status == OrderStatus.PENDING
    # price not reached yet
    activated = om.check_pending(51.0)
    assert activated == []
    assert om.get_order(p.id).status == OrderStatus.PENDING

    # price drops and triggers pending order
    activated = om.check_pending(50.0)
    assert len(activated) == 1
    o2 = om.get_order(p.id)
    assert o2.status == OrderStatus.OPEN
    assert o2.order_type == OrderType.LIMIT
    assert o2.price == 50.0

    # simulate fill
    done = om.fill_order(p.id, executed_price=49.9)
    assert done is True
    assert om.get_order(p.id).status == OrderStatus.FILLED
    assert om.get_order(p.id).filled_price == 49.9
