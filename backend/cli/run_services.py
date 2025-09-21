# backend/cli/run_services.py
"""
Small CLI to run the ServiceRunner locally.

Usage examples:
  python -m backend.cli.run_services --broker-class bot_core.brokers.paper.PaperBroker
  python -m backend.cli.run_services --broker-class bot_core.brokers.paper.PaperBroker --reconcile-interval 2.0

You can pass broker constructor args as JSON (no spaces or escaped quotes) with --broker-args:
  python -m backend.cli.run_services \
    --broker-class bot_core.brokers.paper.PaperBroker \
    --broker-args '{"starting_balance": 1000}'
"""
import argparse
import importlib
import json
import logging
import time
from typing import Any

from backend.services.daemon import ServiceRunner

_log = logging.getLogger("run_services")
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")


def import_class(path: str):
    module_name, class_name = path.rsplit(".", 1)
    module = importlib.import_module(module_name)
    return getattr(module, class_name)


def try_import(path: str):
    try:
        return import_class(path)
    except Exception as e:
        _log.warning("failed to import %s: %s", path, e)
        return None


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--broker-class", type=str, help="Fully-qualified broker class path (e.g. bot_core.brokers.paper.PaperBroker)")
    p.add_argument("--broker-args", type=str, default="{}", help="JSON string of kwargs for broker constructor")
    p.add_argument("--reconcile-interval", type=float, default=5.0, help="Seconds between OCO reconcile runs")
    p.add_argument("--no-twap", action="store_true", help="Do not attempt to start a BackgroundTWAPExecutor")
    args = p.parse_args()

    broker = None
    if args.broker_class:
        cls = try_import(args.broker_class)
        if cls is None:
            _log.error("broker class import failed; exiting")
            return 2
        try:
            broker_kwargs = json.loads(args.broker_args or "{}")
        except Exception as e:
            _log.error("broker-args JSON parse failed: %s", e)
            return 3
        broker = cls(**broker_kwargs) if broker_kwargs else cls()
        _log.info("constructed broker: %s", type(broker))

    # optional imports
    oco_manager = None
    try:
        from bot_core.order_managers.oco import OCOManager  # type: ignore
        if broker is not None:
            try:
                oco_manager = OCOManager(broker)
                _log.info("OCOManager instantiated")
            except Exception as e:
                _log.warning("failed to instantiate OCOManager: %s", e)
    except Exception:
        _log.info("OCOManager not available (skipping)")

    twap_executor = None
    if not args.no_twap:
        try:
            mod = importlib.import_module("bot_core.execution.twap_bg")
            TWAPCls = getattr(mod, "BackgroundTWAPExecutor", None)
            if TWAPCls and broker is not None:
                twap_executor = TWAPCls(broker)
                _log.info("BackgroundTWAPExecutor instantiated")
        except Exception as e:
            _log.info("BackgroundTWAPExecutor not available or failed to instantiate: %s", e)

    runner = ServiceRunner(broker=broker, oco_manager=oco_manager, twap_executor=twap_executor, reconcile_interval=args.reconcile_interval)

    try:
        runner.start()
        _log.info("ServiceRunner started. Ctrl-C to stop.")
        while True:
            time.sleep(1.0)
    except KeyboardInterrupt:
        _log.info("Keyboard interrupt received, stopping runner...")
    finally:
        runner.stop()
        _log.info("ServiceRunner stopped")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
