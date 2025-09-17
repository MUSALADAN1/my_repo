# bot_core/order_managers/reconciler.py
import threading
import time
from typing import Optional

class BackgroundReconciler:
    """
    Tiny background reconciler that periodically calls oco_mgr.reconcile_orders().
    Start/stop friendly for tests.
    """
    def __init__(self, oco_mgr, interval: float = 1.0):
        self.oco_mgr = oco_mgr
        self.interval = float(interval)
        self._stop = threading.Event()
        self._thread: Optional[threading.Thread] = None

    def _loop(self):
        while not self._stop.wait(self.interval):
            try:
                self.oco_mgr.reconcile_orders()
            except Exception:
                # ignore exceptions in background to keep loop alive
                pass

    def start(self):
        if self._thread and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._loop, daemon=True)
        self._thread.start()

    def stop(self, join: bool = True, timeout: float = 2.0):
        self._stop.set()
        if join and self._thread:
            self._thread.join(timeout=timeout)
