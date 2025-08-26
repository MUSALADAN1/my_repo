# tests/test_webhook_worker_process_once.py
import json
import os
import tempfile
from backend import webhook_worker
from backend import webhook_executor

class FakeBroker:
    def __init__(self):
        self.calls = []
    def place_order(self, symbol, side, amount, price=None, **kw):
        self.calls.append({"symbol": symbol, "side": side, "amount": amount, "price": price})
        return {"id": "fake-ord-1", "status": "filled"}

class FakeRiskManager:
    def __init__(self):
        self.opened = {}
        self.initial_balance = 1000.0
    def can_open_new(self):
        return True
    def open_position(self, pid, side, entry_price, amount, size, strategy):
        self.opened[pid] = dict(pid=pid, side=side, entry_price=entry_price, amount=amount, size=size, strategy=strategy)
    def list_positions(self):
        return dict(self.opened)
    def get_position(self, pid):
        return self.opened.get(pid)
    def close_position(self, pid):
        return self.opened.pop(pid, None)

def test_process_once_creates_processed_file(tmp_path):
    events_file = tmp_path / "events.jsonl"
    processed_file = tmp_path / "processed.jsonl"

    # write a single buy event
    ev = {"signal": "buy", "symbol": "BTC/USDT", "amount": 0.1, "strategy": "test"}
    events_file.write_text(json.dumps(ev) + "\n")

    broker = FakeBroker()
    rm = FakeRiskManager()

    res = webhook_worker.process_once(str(events_file), broker, rm, processed_path=str(processed_file))
    assert isinstance(res, list)
    assert len(res) == 1
    r = res[0]
    # order should be attached in ok result
    assert r.get("status") in ("ok", "partial") or "order" in r
    # processed file should exist and contain at least one JSON line
    assert processed_file.exists()
    txt = processed_file.read_text().strip()
    assert txt != ""
    # broker was called
    assert len(broker.calls) >= 1
    call = broker.calls[0]
    assert call["symbol"] == "BTC/USDT"
    assert call["side"] == "buy"
