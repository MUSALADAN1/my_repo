# bot_core/risk_manager.py
from typing import Dict, Optional
from dataclasses import dataclass, field
import threading
import time

@dataclass
class Position:
    pid: str
    side: str
    entry_price: float
    amount: float
    size: Optional[float] = None
    strategy: Optional[str] = None
    opened_at: float = field(default_factory=lambda: time.time())
    closed_at: Optional[float] = None
    status: str = "open"  # open/closed

class RiskManager:
    """
    Simple in-memory RiskManager with thread-safety and pluggable persistence hooks.

    API:
      - can_open_new() -> bool
      - open_position(pid, side, entry_price, amount, size=None, strategy=None) -> None
      - close_position(pid) -> None
      - get_position(pid) -> Optional[Position]
      - list_positions() -> Dict[pid, dict]
      - initial_balance (attribute, optional)
      - max_concurrent (attribute)
      - persist_hook (callable) optional function(pos_dict)
    """
    def __init__(self, initial_balance: float = 1000.0, max_concurrent: int = 5, persist_hook=None):
        self.initial_balance = float(initial_balance)
        self.max_concurrent = int(max_concurrent)
        self._positions: Dict[str, Position] = {}
        self._lock = threading.Lock()
        self.persist_hook = persist_hook

    def can_open_new(self) -> bool:
        with self._lock:
            open_count = sum(1 for p in self._positions.values() if p.status == "open")
            return open_count < self.max_concurrent

    def open_position(self, pid: str, side: str, entry_price: float, amount: float, size: Optional[float] = None, strategy: Optional[str] = None):
        with self._lock:
            if pid in self._positions:
                raise ValueError("pid already exists")
            pos = Position(pid=pid, side=side, entry_price=float(entry_price), amount=float(amount), size=size, strategy=strategy)
            self._positions[pid] = pos
            if self.persist_hook:
                try:
                    self.persist_hook("open", pos)
                except Exception:
                    pass
            return pos

    def close_position(self, pid: str):
        with self._lock:
            pos = self._positions.get(pid)
            if not pos:
                raise KeyError("position not found")
            pos.status = "closed"
            pos.closed_at = time.time()
            if self.persist_hook:
                try:
                    self.persist_hook("close", pos)
                except Exception:
                    pass
            return pos

    def list_positions(self) -> Dict[str, Dict]:
        with self._lock:
            return {pid: vars(p) for pid, p in self._positions.items()}

    def get_position(self, pid: str) -> Optional[Dict]:
        with self._lock:
            p = self._positions.get(pid)
            return vars(p) if p else None
