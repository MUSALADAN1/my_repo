# tests/test_exchanges_adapter.py
from bot_core.exchanges.adapter import (
    ExchangeAdapter,
    OrderRequest,
    Order,
    OrderStatus,
)
import pytest


class DummyAdapter(ExchangeAdapter):
    """A tiny in-memory adapter used for unit testing the interface."""

    def __init__(self, config=None):
        super().__init__(config=config)
        self._orders = {}
        self._connected = False

    def connect(self):
        self._connected = True

    def disconnect(self):
        self._connected = False

    def fetch_ticker(self, symbol: str):
        return {"symbol": symbol, "last": 1.0}

    def fetch_ohlcv(self, symbol: str, timeframe: str, limit: int = 100):
        # return simple synthetic OHLCV tuples
        return [("t0", 1.0, 1.2, 0.9, 1.1, 10.0)]

    def fetch_balance(self):
        return {"USD": 1000.0}

    def create_order(self, req: OrderRequest) -> Order:
        oid = self._generate_id("test")
        order = Order(
            id=oid,
            symbol=req.symbol,
            side=req.side,
            amount=req.amount,
            price=req.price,
            filled=0.0,
            status=OrderStatus.OPEN,
        )
        self._orders[oid] = order
        return order

    def fetch_order(self, order_id: str):
        return self._orders.get(order_id)

    def fetch_open_orders(self, symbol: str = None):
        return [o for o in self._orders.values() if o.status == OrderStatus.OPEN and (symbol is None or o.symbol == symbol)]

    def cancel_order(self, order_id: str):
        o = self._orders.get(order_id)
        if not o:
            return False
        o.status = OrderStatus.CANCELED
        return True


def test_dummy_adapter_basic_flow():
    a = DummyAdapter()
    assert not a.is_connected()
    a.connect()
    assert a.is_connected()
    bal = a.fetch_balance()
    assert isinstance(bal, dict) and "USD" in bal

    req = OrderRequest(symbol="BTC/USDT", side="buy", amount=0.01, price=100.0)
    o = a.create_order(req)
    assert isinstance(o, Order)
    assert o.status == OrderStatus.OPEN

    open_orders = a.fetch_open_orders("BTC/USDT")
    assert len(open_orders) == 1

    ok = a.cancel_order(o.id)
    assert ok is True
    assert a.fetch_order(o.id).status == OrderStatus.CANCELED

    a.disconnect()
    assert not a.is_connected()
