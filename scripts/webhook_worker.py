#!/usr/bin/env python3
"""
scripts/webhook_worker.py

Simple long-running worker that tails a jsonlines events file (e.g. webhook_events.jsonl)
and processes only new lines, writing a JSON-lines processed output.

Usage:
  python scripts/webhook_worker.py [events_file] [processed_out] [poll_seconds]

Defaults:
  events_file: ./webhook_events.jsonl
  processed_out: ./webhook_events_processed.jsonl
  poll_seconds: 2

Behavior:
 - Tracks byte offset in a companion file: <processed_out>.offset
 - On startup it resumes from stored offset (if any) to avoid re-processing old events.
 - Uses backend.webhook_executor.process_event for per-event processing.
 - Uses RiskManager + Broker (same fallback logic as run_webhook_executor).
 - Graceful shutdown on Ctrl+C (KeyboardInterrupt).
"""
import sys
import os
import time
import json
from pathlib import Path

# ensure project root on sys.path so imports work when running script directly
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.abspath(os.path.join(SCRIPT_DIR, ".."))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from backend.webhook_executor import process_event
from bot_core.risk.risk_manager import RiskManager
from backend.exchanges import create_adapter
from backend.exchanges.broker import Broker

def _make_broker_fallback():
    """Try to create a real Broker via create_adapter; otherwise return a simple stub broker."""
    try:
        # lightweight stub client to satisfy adapter factories that expect a client object
        client = type("MockClient", (), {"fetch_ohlcv": lambda *a, **k: []})()
        adapter = create_adapter("binance", {"client": client})
        broker = Broker(adapter_instance=adapter)
        broker.connect()
        return broker
    except Exception:
        class StubBroker:
            def __init__(self):
                self._orders = []
            def place_order(self, symbol, side, amount, price=None):
                o = {"id": f"stub-{len(self._orders)+1}", "symbol": symbol, "side": side, "amount": amount, "price": price, "status": "ok"}
                self._orders.append(o)
                return o
        return StubBroker()

def read_offset(offset_path: str) -> int:
    try:
        with open(offset_path, "r", encoding="utf-8") as f:
            return int(f.read().strip() or 0)
    except Exception:
        return 0

def write_offset(offset_path: str, offset: int) -> None:
    os.makedirs(os.path.dirname(offset_path) or ".", exist_ok=True)
    with open(offset_path, "w", encoding="utf-8") as f:
        f.write(str(int(offset)))

def process_new_lines(events_path: str, broker, rm, processed_out: str, offset_path: str) -> int:
    """
    Read from events_path starting at stored offset, process new lines, append results to processed_out.
    Returns new offset.
    """
    # ensure processed file exists
    os.makedirs(os.path.dirname(processed_out) or ".", exist_ok=True)
    open(processed_out, "a", encoding="utf-8").close()

    offset = read_offset(offset_path)
    # if events file does not exist yet, return same offset
    if not os.path.exists(events_path):
        return offset

    with open(events_path, "r", encoding="utf-8") as evf:
        evf.seek(offset)
        lines = evf.readlines()
        new_offset = evf.tell()

    if not lines:
        return offset  # nothing new

    results = []
    for line in lines:
        line = line.strip()
        if not line:
            continue
        try:
            event = json.loads(line)
        except Exception as e:
            res = {"status": "error", "reason": f"invalid json: {e}", "raw": line}
            results.append(res)
            continue

        try:
            r = process_event(event, broker, rm)
        except Exception as e:
            r = {"status": "error", "reason": f"executor exception: {e}", "event": event}
        results.append(r)

    # append results to processed_out
    with open(processed_out, "a", encoding="utf-8") as pf:
        for r in results:
            pf.write(json.dumps(r, default=str) + "\n")

    # persist new offset
    write_offset(offset_path, new_offset)
    return new_offset

def main():
    events_path = sys.argv[1] if len(sys.argv) > 1 else os.path.join(os.getcwd(), "webhook_events.jsonl")
    processed_out = sys.argv[2] if len(sys.argv) > 2 else os.path.join(os.getcwd(), "webhook_events_processed.jsonl")
    poll_seconds = float(sys.argv[3]) if len(sys.argv) > 3 else 2.0

    events_path = os.path.abspath(events_path)
    processed_out = os.path.abspath(processed_out)
    offset_path = processed_out + ".offset"

    print(f"Webhook worker starting: events={events_path}, processed_out={processed_out}, poll={poll_seconds}s")
    print("Initializing Broker and RiskManager...")

    broker = _make_broker_fallback()
    rm = RiskManager(max_concurrent_deals=2, trailing_stop_pct=0.03, drawdown_alert_pct=0.2)

    # show starting offset
    start_offset = read_offset(offset_path)
    print(f"Starting offset: {start_offset}")

    try:
        while True:
            new_offset = process_new_lines(events_path, broker, rm, processed_out, offset_path)
            if new_offset != start_offset:
                print(f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] processed up to byte offset {new_offset}")
                start_offset = new_offset
            time.sleep(poll_seconds)
    except KeyboardInterrupt:
        print("Worker interrupted by user. Shutting down.")
    except Exception as e:
        print(f"Worker encountered error: {e}")
    finally:
        print("Worker stopped.")

if __name__ == "__main__":
    main()
