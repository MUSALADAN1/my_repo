# scripts/test_webhook_executor_quick.py
import os
import sys

# Ensure repo root (one level up from scripts/) is on sys.path so `import backend` works
THIS_DIR = os.path.dirname(os.path.abspath(__file__))
REPO_ROOT = os.path.abspath(os.path.join(THIS_DIR, ".."))
if REPO_ROOT not in sys.path:
    sys.path.insert(0, REPO_ROOT)

import json
from backend import webhook_executor as we

# Minimal dummy broker & risk manager used in unit tests style
class DummyBroker:
    def place_order(self, symbol, side, amount, price=None):
        return {"id": f"ord-{symbol}-{side}", "status": "filled", "size": amount, "price": price}

class DummyRiskManager:
    def __init__(self):
        self._positions = {}
        self.initial_balance = 1000.0
    def can_open_new(self):
        return True
    def open_position(self, pid, side, entry_price, amount, size=None, strategy=None):
        self._positions[pid] = {"side": side, "entry_price": entry_price, "amount": amount, "size": size, "strategy": strategy}
    def list_positions(self):
        return self._positions.copy()
    def get_position(self, pid):
        return self._positions.get(pid)
    def close_position(self, pid):
        self._positions.pop(pid, None)

broker = DummyBroker()
rm = DummyRiskManager()

# buy event
evt_buy = {"signal": "buy", "symbol": "BTC/USDT", "amount": 0.01, "price": 30000.0, "strategy": "test-strat"}
res_buy = we.process_event(evt_buy, broker, rm)
print("BUY RESULT:", res_buy)
print("POSITIONS AFTER BUY:", rm.list_positions())

# sell event (should close the position)
evt_sell = {"signal": "sell", "symbol": "BTC/USDT", "strategy": "test-strat"}
res_sell = we.process_event(evt_sell, broker, rm)
print("SELL RESULT:", res_sell)
print("POSITIONS AFTER SELL:", rm.list_positions())

# process a small jsonlines file
tmp_path = "tmp_events.jsonl"
with open(tmp_path, "w", encoding="utf-8") as f:
    f.write(json.dumps(evt_buy) + "\n")
    f.write(json.dumps(evt_sell) + "\n")

res_list = we.process_file(tmp_path, broker, rm)
print("PROCESS_FILE RESULTS:", res_list)
