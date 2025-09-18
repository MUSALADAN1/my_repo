# tests/test_paper_broker.py
import time
from bot_core.brokers.paper_broker import PaperBroker

def test_market_order_fills_immediately():
    b = PaperBroker(starting_prices={"BTC/USDT": 50000.0})
    o = b.place_order("BTC/USDT", "buy", 0.01, order_type="market")
    assert o["status"] == "filled"
    assert "filled_price" in o and float(o["filled_price"]) == 50000.0

def test_limit_order_stays_open_and_can_be_filled():
    b = PaperBroker()
    o = b.place_order("ETH/USDT", "buy", 0.1, price=2000.0, order_type="limit")
    assert o["status"] == "open"
    open_orders = b.fetch_open_orders("ETH/USDT")
    assert any(x["id"] == o["id"] for x in open_orders)
    # simulate fill
    filled = b.simulate_fill(o["id"], price=1999.0)
    assert filled["status"] == "filled"
    assert float(filled["filled_price"]) == 1999.0

def test_cancel_open_order():
    b = PaperBroker()
    o = b.place_order("XRP/USDT", "sell", 10.0, price=0.5, order_type="limit")
    assert o["status"] == "open"
    canceled = b.cancel_order(o["id"])
    assert canceled["status"] == "canceled"
    # cancel again is idempotent (returns same record)
    canceled2 = b.cancel_order(o["id"])
    assert canceled2["status"] == "canceled"

def test_fetch_order_returns_copy():
    b = PaperBroker()
    o = b.place_order("ADA/USDT", "buy", 5.0, order_type="market", price=1.2)
    fetched = b.fetch_order(o["id"])
    assert fetched is not o
    assert fetched["id"] == o["id"]
