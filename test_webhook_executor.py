# test_webhook_executor.py
import json
from pathlib import Path
from backend.webhook_executor import process_file
from bot_core.risk.risk_manager import RiskManager

class MockBroker:
    def __init__(self):
        self.orders = []
    def place_order(self, symbol, side, amount, price=None):
        o = {"id": f"mock-{len(self.orders)+1}", "symbol": symbol, "side": side, "amount": amount, "price": price, "status": "ok"}
        self.orders.append(o)
        return o

def test_process_file_buy_and_sell(tmp_path):
    events_file = tmp_path / "events.jsonl"
    processed = tmp_path / "processed.jsonl"

    # buy event then sell event
    buy_event = {"strategy": "ma_crossover", "signal": "buy", "symbol": "BTC/USDT", "amount": 0.5}
    sell_event = {"strategy": "ma_crossover", "signal": "sell", "symbol": "BTC/USDT"}

    with open(events_file, "w", encoding="utf-8") as f:
        f.write(json.dumps(buy_event) + "\n")
        f.write(json.dumps(sell_event) + "\n")

    broker = MockBroker()
    rm = RiskManager(max_concurrent_deals=2, trailing_stop_pct=0.03, drawdown_alert_pct=0.2)
    results = process_file(str(events_file), broker, rm, processed_path=str(processed))

    # Expect two results
    assert len(results) == 2
    # first should be buy ok
    assert results[0]["status"] == "ok" and results[0]["action"] == "buy"
    # second should be ok sell (closing the buy we opened)
    assert results[1]["status"] == "ok" and results[1]["action"] == "sell"

    # broker should have recorded two orders
    assert len(broker.orders) >= 2
