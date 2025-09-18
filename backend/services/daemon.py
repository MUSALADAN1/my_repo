# backend/services/daemon.py
import threading
import time
import logging
from typing import Optional, Any

_log = logging.getLogger("services.daemon")


class ServiceRunner:
    """
    Simple threaded service runner that:
      - periodically calls oco_manager.reconcile_orders() if provided
      - starts/stops a twap_executor if provided
    Intended for simple local/test usage (not a production process manager).
    """

    def __init__(
        self,
        broker: Any = None,
        oco_manager: Optional[Any] = None,
        twap_executor: Optional[Any] = None,
        reconcile_interval: float = 5.0,
    ):
        self.broker = broker
        self.oco_manager = oco_manager
        self.twap_executor = twap_executor
        self.reconcile_interval = float(reconcile_interval)
        self._stop_event = threading.Event()
        self._thread: Optional[threading.Thread] = None

    def _loop(self) -> None:
        _log.info("ServiceRunner loop started (interval=%s)", self.reconcile_interval)
        while not self._stop_event.wait(self.reconcile_interval):
            # OCO reconciliation
            if self.oco_manager is not None:
                try:
                    self.oco_manager.reconcile_orders()
                except Exception as e:
                    _log.exception("OCO reconcile failed: %s", e)

            # optional periodic TWAP housekeeping (if implemented)
            if self.twap_executor is not None:
                # Some executors may expose light maintenance methods; call if present
                try:
                    if hasattr(self.twap_executor, "periodic_maintenance"):
                        self.twap_executor.periodic_maintenance()
                except Exception as e:
                    _log.exception("TWAP periodic maintenance failed: %s", e)

        _log.info("ServiceRunner loop exiting")

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            _log.debug("ServiceRunner already running")
            return

        _log.info("Starting ServiceRunner")
        self._stop_event.clear()
        self._thread = threading.Thread(target=self._loop, daemon=True, name="service-runner")
        self._thread.start()

        # start the TWAP executor if it provides a start() method
        if self.twap_executor is not None and hasattr(self.twap_executor, "start"):
            try:
                self.twap_executor.start()
            except Exception as e:
                _log.exception("failed to start twap_executor: %s", e)

    def stop(self, timeout: float = 5.0) -> None:
        _log.info("Stopping ServiceRunner")
        self._stop_event.set()

        if self._thread is not None:
            self._thread.join(timeout)

        # try stopping twap executor if it provides a stop() method
        if self.twap_executor is not None and hasattr(self.twap_executor, "stop"):
            try:
                self.twap_executor.stop()
            except Exception as e:
                _log.exception("failed to stop twap_executor: %s", e)
