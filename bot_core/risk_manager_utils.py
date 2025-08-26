# bot_core/risk_manager_utils.py
from typing import Any, Dict

def load_positions_from_store(store: Any, risk_manager: Any) -> None:
    """
    Load open positions from the provided store into the risk_manager.

    - store must implement list_positions() -> Dict[pid, record]
    - risk_manager must implement list_positions() and open_position(...)

    Behavior:
      - For each stored position with status == "open" (or missing status),
        if it is not already present in risk_manager.list_positions(), call
        risk_manager.open_position(...) to recreate it.
      - Defensive: ignores positions that cannot be opened, and tolerates
        different open_position signatures (tries named args then positional).
    """
    if store is None or risk_manager is None:
        return

    try:
        stored: Dict[str, Dict] = store.list_positions() or {}
    except Exception:
        # if store doesn't support it or fails, nothing to load
        return

    try:
        existing = risk_manager.list_positions() or {}
    except Exception:
        existing = {}

    for pid, rec in stored.items():
        # only consider open positions
        status = (rec.get("status") or "").lower() if isinstance(rec.get("status"), str) else rec.get("status")
        if status not in (None, "", "open"):
            continue

        if pid in existing:
            # already known to risk_manager
            continue

        # extract fields with fallbacks
        side = rec.get("side", "long")
        entry_price = rec.get("entry_price", rec.get("entry", 0.0)) or 0.0
        amount = rec.get("amount", rec.get("size", 0.0)) or 0.0
        size = rec.get("size", None)
        strategy = rec.get("strategy", None)

        # attempt to call open_position defensively
        try:
            # preferred: named args (most modern RiskManager implementations)
            risk_manager.open_position(
                pid=pid,
                side=side,
                entry_price=float(entry_price),
                amount=float(amount),
                size=size,
                strategy=strategy
            )
        except TypeError:
            # fallback to older positional signature if any: (pid, side, entry_price, amount, size, strategy)
            try:
                risk_manager.open_position(pid, side, float(entry_price), float(amount), size, strategy)
            except Exception:
                # give up on this position
                continue
        except Exception:
            # ignore and continue
            continue
