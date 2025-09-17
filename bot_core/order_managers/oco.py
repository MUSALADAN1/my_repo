# bot_core/order_managers/oco.py
from typing import Dict, Any

class OCOManager:
    """
    Simple One-Cancels-the-Other manager.
    Tracks pairs and cancels opposite order when one fills.
    """

    def __init__(self, broker):
        self.broker = broker
        self._pairs = {}  # oco_id -> {"primary": id, "secondary": id}

    def place_oco(self, primary: Dict[str, Any], secondary: Dict[str, Any]) -> Dict[str, str]:
        p = self.broker.place_order(
            primary.get("symbol"),
            primary.get("side"),
            primary.get("amount"),
            price=primary.get("price"),
            order_type=primary.get("order_type", "limit")
        )
        s = self.broker.place_order(
            secondary.get("symbol"),
            secondary.get("side"),
            secondary.get("amount"),
            price=secondary.get("price"),
            order_type=secondary.get("order_type", "limit")
        )
        oco_id = f"oco-{len(self._pairs) + 1}"
        self._pairs[oco_id] = {"primary": p["id"], "secondary": s["id"]}
        return {"oco_id": oco_id, "primary_id": p["id"], "secondary_id": s["id"]}

    def reconcile_orders(self):
        to_remove = []
        for oco_id, pair in list(self._pairs.items()):
            p_id = pair["primary"]
            s_id = pair["secondary"]
            p = self.broker.fetch_order(p_id)
            s = self.broker.fetch_order(s_id)
            p_status = p.get("status") if p else None
            s_status = s.get("status") if s else None

            # if primary filled -> cancel secondary
            if p_status == "filled" and s_status != "cancelled":
                try:
                    self.broker.cancel_order(s_id)
                except Exception:
                    pass
                to_remove.append(oco_id)
                continue

            # if secondary filled -> cancel primary
            if s_status == "filled" and p_status != "cancelled":
                try:
                    self.broker.cancel_order(p_id)
                except Exception:
                    pass
                to_remove.append(oco_id)
                continue

            # if both final states, remove
            finals = ("filled", "cancelled", "rejected")
            if p_status in finals and s_status in finals:
                to_remove.append(oco_id)

        for oid in to_remove:
            self._pairs.pop(oid, None)
