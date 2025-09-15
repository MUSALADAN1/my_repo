#!/usr/bin/env python3
"""
scripts/run_webhook_executor.py

Usage:
  python scripts/run_webhook_executor.py [events_file] [processed_out_file]

Defaults:
  events_file: ./webhook_events.jsonl
  processed_out_file: ./webhook_events_processed.jsonl
"""
import sys
import os

# ensure project root on sys.path
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.abspath(os.path.join(SCRIPT_DIR, ".."))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from backend.webhook_executor import process_file
from bot_core.risk.risk_manager import RiskManager
from backend.exchanges import create_adapter
from backend.exchanges.broker import Broker

def main():
    events_path = sys.argv[1] if len(sys.argv) > 1 else os.path.join(os.getcwd(), "webhook_events.jsonl")
    processed_out = sys.argv[2] if len(sys.argv) > 2 else os.path.join(os.getcwd(), "webhook_events_processed.jsonl")

    # instantiate a mock adapter/broker for demo if none provided; in real use, pass a real adapter
    # For safety we will use a simple Mock-like adapter that uses Broker with a fake client if available.
    # Here we create a minimal adapter that supports place_order via Broker wrapper - using existing create_adapter factory:
    # If you have a ccxt adapter configured, you might call create_adapter('binance', config) instead.
    try:
        # for demo we use a MockClient that supports place_order via Broker.place_order
        client = type("MockClient", (), {"fetch_ohlcv": lambda *a, **k: []})()
        adapter = create_adapter("binance", {"client": client})
        broker = Broker(adapter_instance=adapter)
        broker.connect()
    except Exception:
        # fallback: create a simple stub broker that exposes place_order method
        class StubBroker:
            def __init__(self):
                self._orders = []
            def place_order(self, symbol, side, amount, price=None):
                o = {"id": f"stub-{len(self._orders)+1}", "symbol": symbol, "side": side, "amount": amount, "price": price, "status": "ok"}
                self._orders.append(o)
                return o
        broker = StubBroker()

    rm = RiskManager(max_concurrent_deals=2, trailing_stop_pct=0.03, drawdown_alert_pct=0.2)
    print(f"Processing events from: {events_path} -> {processed_out}")
    res = process_file(events_path, broker, rm, processed_path=processed_out)
    print(f"Processed {len(res)} events. Results written to {processed_out}")

if __name__ == "__main__":
    main()
