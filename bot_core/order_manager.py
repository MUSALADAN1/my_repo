# bot_core/order_manager.py
from __future__ import annotations
from dataclasses import dataclass, field
from enum import Enum
from typing import Dict, List, Optional
from datetime import datetime, timezone
import uuid


class OrderStatus(str, Enum):
    PENDING = "pending"     # waiting for trigger (e.g. pending/place-if-touch)
    OPEN = "open"           # placed on exchange (limit or market awaiting fill)
    FILLED = "filled"
    CANCELLED = "cancelled"


class OrderType(str, Enum):
    MARKET = "market"
    LIMIT = "limit"
    PENDING = "pending"


@dataclass
class Order:
    id: str
    symbol: str
    side: str  # 'buy' or 'sell'
    amount: float
    price: Optional[float] = None  # limit price or None for market
    order_type: OrderType = OrderType.LIMIT
    status: OrderStatus = OrderStatus.OPEN
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    filled_at: Optional[datetime] = None
    filled_price: Optional[float] = None
    oco_group: Optional[str] = None
    trigger_price: Optional[float] = None  # used for pending orders
    meta: Dict = field(default_factory=dict)


class OrderManager:
    """
    Simple in-memory order manager with:
      - place_order (market/limit/pending)
      - cancel_order
      - fill_order (simulate execution)
      - OCO grouping (create_oco or when placing with oco_group)
      - check_pending(current_price) to trigger pending orders
    """

    def __init__(self):
        self._orders: Dict[str, Order] = {}
        self._next = 1

    def _new_id(self) -> str:
        # use uuid to avoid collisions across restarts
        return str(uuid.uuid4())

    def place_order(
        self,
        symbol: str,
        side: str,
        amount: float,
        price: Optional[float] = None,
        order_type: OrderType = OrderType.LIMIT,
        trigger_price: Optional[float] = None,
        oco_group: Optional[str] = None,
        meta: Optional[Dict] = None,
    ) -> Order:
        """
        Place a new order. For order_type==PENDING, provide trigger_price.
        Returns the Order object (status will be PENDING for pending, OPEN otherwise).
        """
        if order_type == OrderType.PENDING and trigger_price is None:
            raise ValueError("pending orders require trigger_price")

        oid = self._new_id()
        status = OrderStatus.PENDING if order_type == OrderType.PENDING else OrderStatus.OPEN
        o = Order(
            id=oid,
            symbol=symbol,
            side=side,
            amount=amount,
            price=price,
            order_type=order_type,
            status=status,
            trigger_price=trigger_price,
            oco_group=oco_group,
            meta=meta or {},
        )
        self._orders[oid] = o
        return o

    def get_order(self, order_id: str) -> Optional[Order]:
        return self._orders.get(order_id)

    def get_open_orders(self, include_pending: bool = True) -> List[Order]:
        statuses = {OrderStatus.OPEN}
        if include_pending:
            statuses.add(OrderStatus.PENDING)
        return [o for o in self._orders.values() if o.status in statuses]

    def cancel_order(self, order_id: str) -> bool:
        o = self._orders.get(order_id)
        if not o or o.status in (OrderStatus.FILLED, OrderStatus.CANCELLED):
            return False
        o.status = OrderStatus.CANCELLED
        return True

    def fill_order(self, order_id: str, executed_price: Optional[float] = None) -> bool:
        """
        Mark an order as filled (simulate execution). If the order belongs to an OCO group,
        cancel the other orders in same group.
        """
        o = self._orders.get(order_id)
        if not o or o.status in (OrderStatus.FILLED, OrderStatus.CANCELLED):
            return False
        o.status = OrderStatus.FILLED
        o.filled_at = datetime.now(timezone.utc)
        o.filled_price = executed_price if executed_price is not None else o.price
        # Cancel OCO siblings
        if o.oco_group:
            for other in self._orders.values():
                if other.id != o.id and other.oco_group == o.oco_group and other.status not in (OrderStatus.FILLED, OrderStatus.CANCELLED):
                    other.status = OrderStatus.CANCELLED
        return True

    def create_oco(self, order_a_id: str, order_b_id: str) -> str:
        """
        Link two existing orders into an OCO group. Returns the group id.
        """
        o_a = self._orders.get(order_a_id)
        o_b = self._orders.get(order_b_id)
        if not o_a or not o_b:
            raise KeyError("one or both orders not found")
        gid = str(uuid.uuid4())
        o_a.oco_group = gid
        o_b.oco_group = gid
        return gid

    def check_pending(self, current_price: float) -> List[Order]:
        """
        Check pending orders and activate ones that meet trigger condition.
        For buy pending orders: trigger if current_price <= trigger_price
        For sell pending orders: trigger if current_price >= trigger_price

        When triggered, order_type becomes LIMIT, status becomes OPEN
        Returns list of activated orders.
        """
        activated: List[Order] = []
        for o in list(self._orders.values()):
            if o.status == OrderStatus.PENDING:
                if o.trigger_price is None:
                    continue
                if o.side.lower() == "buy" and current_price <= o.trigger_price:
                    o.status = OrderStatus.OPEN
                    o.order_type = OrderType.LIMIT
                    # if price not set, use trigger_price as the put-on-book limit
                    if o.price is None:
                        o.price = o.trigger_price
                    activated.append(o)
                elif o.side.lower() == "sell" and current_price >= o.trigger_price:
                    o.status = OrderStatus.OPEN
                    o.order_type = OrderType.LIMIT
                    if o.price is None:
                        o.price = o.trigger_price
                    activated.append(o)
        return activated

    def list_all(self) -> List[Order]:
        return list(self._orders.values())

    def reset(self):
        """Clear all orders (useful for tests)."""
        self._orders.clear()
