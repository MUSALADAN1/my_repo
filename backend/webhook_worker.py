# backend/webhook_worker.py
"""
Simple webhook worker that reads the JSON-lines events file and processes
unprocessed events via backend.webhook_executor.process_event.

Usage:
  # one-shot (process existing events and exit)
  python backend/webhook_worker.py --once --events ./webhook_events.jsonl --processed ./webhook_processed.jsonl

  # daemon (poll file for new lines)
  python backend/webhook_worker.py --daemon --events ./webhook_events.jsonl --processed ./webhook_processed.jsonl --interval 2.0

Design:
 - For testability the worker exposes a process_once(path, broker, risk_manager, processed_path)
 - process_once reads all lines from path, attempts to json.loads each, calls process_event,
   appends results to processed_path (optional) and returns list(results).
 - In daemon mode, the script will loop and process newly appended lines (best-effort tailing).
"""
import argparse
import json
import os
import time
from typing import Any, Dict, List, Optional

from backend import webhook_executor  # uses process_event
# Use bot_core's Broker and (a simple) RiskManager / fake if not present
try:
    from bot_core.exchanges.factory import create_adapter
    from bot_core.exchanges.broker import Broker
except Exception:
    Broker = None  # we will accept a fake broker in tests

# A minimal, test-friendly RiskManager implementation if none provided
class SimpleRiskManager:
    def __init__(self, initial_balance: float = 1000.0, max_positions: int = 5):
        self.initial_balance = float(initial_balance)
        self._positions = {}
        self._max = int(max_positions)

    def can_open_new(self) -> bool:
        return len(self._positions) < self._max

    def open_position(self, pid: str, side: str, entry_price: float, amount: float, size: Optional[float], strategy: Optional[str]):
        self._positions[pid] = {
            "pid": pid, "side": side, "entry_price": float(entry_price or 0.0),
            "amount": float(amount), "size": size, "strategy": strategy
        }

    def list_positions(self):
        return dict(self._positions)

    def get_position(self, pid: str):
        return self._positions.get(pid)

    def close_position(self, pid: str):
        return self._positions.pop(pid, None)

def _ensure_file_exists(path: str) -> None:
    if not os.path.exists(path):
        open(path, "a", encoding="utf-8").close()

def process_once(events_path: str, broker: Any, risk_manager: Any, processed_path: Optional[str] = None) -> List[Dict[str, Any]]:
    """
    Read all lines from events_path, process them via webhook_executor.process_event,
    append results to processed_path (if provided) and return list of results.
    """
    if not os.path.exists(events_path):
        raise FileNotFoundError(events_path)

    _ensure_file_exists(processed_path or "")

    results = []
    with open(events_path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                event = json.loads(line)
            except Exception as e:
                res = {"status": "error", "reason": f"parse_failed: {e}", "line": line}
                results.append(res)
                if processed_path:
                    with open(processed_path, "a", encoding="utf-8") as pf:
                        pf.write(json.dumps(res, default=str) + "\n")
                continue

            try:
                r = webhook_executor.process_event(event, broker, risk_manager)
            except Exception as e:
                r = {"status": "error", "reason": f"executor_exception: {e}", "event": event}

            results.append(r)
            if processed_path:
                with open(processed_path, "a", encoding="utf-8") as pf:
                    pf.write(json.dumps(r, default=str) + "\n")

    return results

def tail_and_process(events_path: str, broker: Any, risk_manager: Any, processed_path: Optional[str] = None, interval: float = 1.0):
    """
    Simple tail loop: track processed byte offset and process new appended lines.
    This is a best-effort implementation suitable for development.
    """
    _ensure_file_exists(events_path)
    offset = 0
    while True:
        try:
            size = os.path.getsize(events_path)
            if size < offset:
                # file truncated/rotated
                offset = 0
            if size > offset:
                with open(events_path, "r", encoding="utf-8") as f:
                    f.seek(offset)
                    for line in f:
                        line = line.strip()
                        if not line:
                            continue
                        try:
                            event = json.loads(line)
                        except Exception as e:
                            res = {"status": "error", "reason": f"parse_failed: {e}", "line": line}
                            if processed_path:
                                with open(processed_path, "a", encoding="utf-8") as pf:
                                    pf.write(json.dumps(res, default=str) + "\n")
                            continue
                        try:
                            r = webhook_executor.process_event(event, broker, risk_manager)
                        except Exception as e:
                            r = {"status": "error", "reason": f"executor_exception: {e}", "event": event}
                        if processed_path:
                            with open(processed_path, "a", encoding="utf-8") as pf:
                                pf.write(json.dumps(r, default=str) + "\n")
                    offset = f.tell()
        except Exception:
            # never stop on transient issues; log to stdout minimally
            print("webhook_worker: transient error, will retry", flush=True)
        time.sleep(interval)

def _build_default_broker():
    """
    Best-effort: create a Broker using default adapter name from env or fall back to None.
    This function is intentionally minimal — for production you should inject a configured Broker.
    """
    try:
        # attempt to create a local adapter via factory (bot_core.exchanges.factory)
        from bot_core.exchanges.factory import create_adapter
        from bot_core.exchanges.broker import Broker
        adapter, = create_adapter("binance", {})  # factory returns (cls-instance,) in some repo variants; adjust if needed
        br = Broker(adapter_instance=adapter)
        br.connect()
        return br
    except Exception:
        return None

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--events", default=os.environ.get("WEBHOOK_EVENTS_PATH", "webhook_events.jsonl"))
    parser.add_argument("--processed", default=os.environ.get("WEBHOOK_PROCESSED_PATH", "webhook_processed.jsonl"))
    parser.add_argument("--once", action="store_true")
    parser.add_argument("--daemon", action="store_true")
    parser.add_argument("--interval", type=float, default=2.0)
    args = parser.parse_args()

    # use a simple risk manager by default
    rm = SimpleRiskManager()
    # best-effort broker
    broker = _build_default_broker()

    if args.once:
        res = process_once(args.events, broker, rm, processed_path=args.processed)
        print(json.dumps({"processed": len(res), "results_sample": res[:2]}, default=str, indent=2))
        return

    if args.daemon:
        print("Starting webhook worker daemon (press CTRL+C to stop)")
        try:
            tail_and_process(args.events, broker, rm, processed_path=args.processed, interval=args.interval)
        except KeyboardInterrupt:
            print("Stopping daemon")
        return

    # default: one-shot behavior
    res = process_once(args.events, broker, rm, processed_path=args.processed)
    print(json.dumps({"processed": len(res)}, default=str))

if __name__ == "__main__":
    main()
