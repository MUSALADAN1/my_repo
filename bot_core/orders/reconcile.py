# bot_core/orders/reconcile.py
from typing import Any, Dict, List
from bot_core.storage.order_store import OrderSQLiteStore
import json

def reconcile_orders(store: OrderSQLiteStore, broker: Any) -> List[Dict]:
    """
    Reconcile incomplete orders against broker. Returns list of updated records.

    Strategy:
      - Fetch orders with statuses that look 'open' / 'submitted' / 'new'
      - For each order:
         1) If broker.fetch_order(id) exists, call it and update local store with returned status/raw fields
         2) Else, call broker.fetch_open_orders(symbol) to see if our id exists among open orders; if missing, mark as 'unknown' or 'closed' (best-effort)
      - Be defensive: swallow exceptions and continue.
    """
    updated = []
    candidates = []
    for s in ("submitted", "new", "open", "created", "pending"):
        candidates.extend(store.list_orders(status=s))

    # dedupe by id
    seen = set()
    to_check = []
    for r in candidates:
        oid = r.get("id")
        if not oid or oid in seen:
            continue
        seen.add(oid)
        to_check.append(r)

    for rec in to_check:
        oid = rec.get("id")
        try:
            # prefer per-order fetch
            if hasattr(broker, "fetch_order"):
                try:
                    bro = broker.fetch_order(oid)
                    # normalize into raw dict
                    if bro is None:
                        # if broker returns None, skip
                        continue
                    # try to extract status if possible
                    status = None
                    if isinstance(bro, dict):
                        status = bro.get("status")
                        raw = bro
                    else:
                        # some fetchers return objects — convert via str
                        raw = {"result": str(bro)}
                    # update store
                    store.update_order(oid, status=status, raw=raw)
                    updated.append({"id": oid, "status": status or rec.get("status"), "raw": raw})
                    continue
                except Exception:
                    # fall through to open orders check
                    pass

            # fallback: fetch open orders and see if our id still exists
            if hasattr(broker, "fetch_open_orders"):
                try:
                    open_ = broker.fetch_open_orders(rec.get("symbol"))
                    # open_ expected iterable of orders with 'id' or similar
                    found = None
                    for o in (open_ or []):
                        # try common shapes
                        oid_key = None
                        if isinstance(o, dict):
                            if o.get("id") == oid or o.get("orderId") == oid or o.get("clientOrderId") == oid:
                                found = o
                                break
                        else:
                            # object-ish
                            if getattr(o, "id", None) == oid:
                                found = o
                                break
                    if found:
                        # still open — refresh raw
                        store.update_order(oid, raw=found)
                        updated.append({"id": oid, "status": rec.get("status"), "raw": found})
                    else:
                        # not found among open orders -> assume filled/closed -> mark 'closed'
                        store.update_order(oid, status="closed")
                        updated.append({"id": oid, "status": "closed", "raw": None})
                except Exception:
                    continue
        except Exception:
            continue

    return updated
