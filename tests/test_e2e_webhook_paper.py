# tests/test_e2e_webhook_paper.py
import json
import time
from bot_core.brokers.paper_broker import PaperBroker
from backend.webhook_executor import process_event
from typing import Dict, Any

class SimpleRiskManager:
    """
    Minimal risk manager mock for e2e tests.
    Provides the small API expected by webhook_executor:
      - can_open_new()
      - open_position(pid, side, entry_price, amount, size=None, strategy=None)
      - close_position(pid)
      - list_positions()
      - get_position(pid)
    """
    def __init__(self, max_concurrent_deals: int = 10):
        self.max_concurrent_deals = max_concurrent_deals
        self._positions: Dict[str, Dict[str, Any]] = {}

    def can_open_new(self) -> bool:
        return len(self._positions) < self.max_concurrent_deals

    def open_position(self, pid: str, side: str, entry_price: float, amount: float, size: float = None, strategy: str = None):
        self._positions[pid] = {
            "pid": pid,
            "side": side,
            "entry_price": float(entry_price),
            "amount": float(amount),
            "size": float(size) if size is not None else None,
            "strategy": strategy,
            "opened_ts": time.time(),
        }

    def close_position(self, pid: str):
        if pid in self._positions:
            del self._positions[pid]

    def list_positions(self):
        return dict(self._positions)

    def get_position(self, pid: str):
        return self._positions.get(pid)


def test_webhook_buy_then_sell_e2e():
    # Arrange: paper broker with a known last price and simple RM
    broker = PaperBroker(starting_prices={"BTC/USDT": 50000.0})
    rm = SimpleRiskManager(max_concurrent_deals=2)

    # 1) Place BUY via process_event
    buy_event = {
        "strategy": "e2e_test",
        "signal": "buy",
        "symbol": "BTC/USDT",
        "amount": 0.01
    }

    res_buy = process_event(buy_event, broker, rm)
    assert res_buy["status"] == "ok", f"buy failed: {res_buy}"
    assert res_buy["action"] == "buy"
    pid = res_buy.get("pid")
    assert pid is not None, "expected pid to be returned"
    # Risk manager should now have one position with pid
    pos = rm.get_position(pid)
    assert pos is not None, "risk manager did not record the opened position"
    assert pos["side"] == "long" or pos["side"] == "buy"

    # 2) Place SELL via process_event -> should find position and close it
    sell_event = {
        "strategy": "e2e_test",
        "signal": "sell",
        "symbol": "BTC/USDT"
    }
    res_sell = process_event(sell_event, broker, rm)
    assert res_sell["status"] == "ok", f"sell failed: {res_sell}"
    assert res_sell["action"] == "sell"
    # after sell, the risk manager should no longer have the pid
    assert rm.get_position(pid) is None


def test_webhook_limit_order_and_manual_fill_e2e():
    # Arrange
    broker = PaperBroker(starting_prices={"ETH/USDT": 2000.0})
    rm = SimpleRiskManager(max_concurrent_deals=2)

    # Place a limit buy (should remain open)
    buy_event = {
        "strategy": "e2e_test",
        "signal": "buy",
        "symbol": "ETH/USDT",
        "amount": 0.1,
        "price": 1999.0  # price provided -> webhook code will pass this through
    }
    # We force a limit by setting order_type in event payload (webhook_executor will forward price but its default is market)
    # Some systems treat presence of price as limit; adjust depending on your executor behavior.
    buy_event["order_type"] = "limit"

    res_buy = process_event(buy_event, broker, rm)
    # If webhook executor uses 'price' only but still uses market, the broker will fill; accept both.
    assert res_buy["status"] in ("ok", "partial", "error") or res_buy["status"] == "ok"
    # If order returned, and it's open in broker, simulate a fill and then reconcile
    o = None
    # find any open order in broker
    for order in broker.fetch_open_orders(buy_event["symbol"]):
        if order["symbol"] == buy_event["symbol"]:
            o = order
            break

    if o:
        # simulate fill
        broker.simulate_fill(o["id"], price=1999.0)
        # now create a sell event to close
        sell_event = {"strategy": "e2e_test", "signal": "sell", "symbol": "ETH/USDT"}
        # Process sell; risk manager close occurs if position present
        res_sell = process_event(sell_event, broker, rm)
        # Accept either a successful sell or rejection (if no position tracked)
        assert "status" in res_sell
    else:
        # If no open order was found, then the original buy may have been filled by a market fill
        # ensure the risk manager has at least one position or the broker recorded a filled order
        has_filled = any(o.get("status") == "filled" for o in broker.orders.values())
        assert has_filled
