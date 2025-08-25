# backend/exchanges/__init__.py
"""
Adapter factory and auto-discovery for exchange adapters.

Discover adapter classes in backend.exchanges.*, construct instances via
create_adapter(name, config) and ensure returned instances expose a stable
order API (create_order, modify_position, cancel_order, fetch_order, fetch_open_orders).
"""
from typing import Any, Dict, Optional, Type
import pkgutil
import importlib
import inspect
import re

_registry: Dict[str, Type] = {}
_aliases: Dict[str, Type] = {}

def _safe_register_module(module_name: str) -> None:
    try:
        mod = importlib.import_module(module_name)
    except Exception:
        return
    for _name, cls in inspect.getmembers(mod, inspect.isclass):
        if getattr(cls, "__module__", None) != mod.__name__:
            continue
        if not _name.endswith("Adapter"):
            continue
        key = _name.lower()
        _registry[key] = cls
        alias = _name[:-7]
        alias_key = alias.lower()
        _aliases[alias_key] = cls
        tokens = re.findall(r"[A-Z][a-z]*|[a-z]+", alias)
        for t in tokens:
            tkey = t.lower()
            if tkey and tkey not in _aliases:
                _aliases[tkey] = cls

package_name = __name__  # "backend.exchanges"
for finder, modname, ispkg in pkgutil.iter_modules(__path__):
    if modname.startswith("_"):
        continue
    fullname = f"{package_name}.{modname}"
    _safe_register_module(fullname)

def list_adapters() -> Dict[str, Type]:
    return dict(_registry)

def list_aliases() -> Dict[str, Type]:
    return dict(_aliases)

def _try_construct(cls: Type, config: Optional[Dict[str, Any]] = None):
    config = config or {}
    try:
        return cls(config)
    except TypeError:
        pass
    if isinstance(config, dict):
        try:
            return cls(**config)
        except TypeError:
            pass
    try:
        return cls()
    except Exception:
        raise

# Wrappers to normalize possible method signatures
def _wrap_create_order(method):
    """
    Compatibility wrapper for create_order variants.

    Accepts both `order_type` and `type` keywords from callers and will attempt
    multiple common adapter signatures (Wilder/MT5 style, CCXT style, etc.)
    """
    def _w(symbol, side, order_type=None, amount=None, price=None, params=None, **kwargs):
        # Allow callers to pass `type` (common) or `order_type`
        if order_type is None:
            if "type" in kwargs:
                order_type = kwargs.pop("type")
            elif "order_type" in kwargs:
                order_type = kwargs.pop("order_type")

        # 1) try canonical signature: (symbol, side, order_type, amount, price=..., params=...)
        try:
            return method(symbol, side, order_type, amount, price=price, params=params)
        except TypeError:
            pass
        # 2) CCXT-like signature: (symbol, side, amount, price=None, params=None)
        try:
            return method(symbol, side, amount, price=price, params=params)
        except TypeError:
            pass
        # 3) positional 4-arg: (symbol, side, amount, price)
        try:
            return method(symbol, side, amount, price)
        except TypeError:
            pass
        # 4) minimal: (symbol, side, amount)
        try:
            return method(symbol, side, amount)
        except Exception:
            # re-raise last exception to provide a useful traceback
            raise
    return _w


def _wrap_modify_position(method):
    def _w(ticket, sl=None, tp=None, is_order=False, params=None):
        try:
            return method(ticket, sl=sl, tp=tp, is_order=is_order)
        except TypeError:
            pass
        try:
            return method(ticket, sl, tp, is_order)
        except TypeError:
            pass
        try:
            return method(ticket, {"sl": sl, "tp": tp})
        except TypeError:
            pass
        return method(ticket, sl, tp)
    return _w

def _wrap_cancel_order(method):
    def _w(order_id, symbol=None):
        try:
            return method(order_id=order_id, symbol=symbol)
        except TypeError:
            pass
        try:
            return method(order_id)
        except TypeError:
            pass
        return method(order_id, symbol)
    return _w

def _wrap_fetch_order(method):
    def _w(order_id, symbol=None):
        try:
            return method(order_id=order_id, symbol=symbol)
        except TypeError:
            pass
        return method(order_id)
    return _w

def _wrap_fetch_open_orders(method):
    def _w(symbol=None):
        try:
            return method(symbol=symbol)
        except TypeError:
            pass
        return method()
    return _w

def _attach_stub(name, inst):
    def _stub(*args, **kwargs):
        raise NotImplementedError(f"{inst.__class__.__name__} does not implement {name}")
    setattr(inst, name, _stub)

def _ensure_order_api(inst: Any):
    candidates = {
        "create_order": ["create_order", "place_order", "create", "order_send", "order_create", "createOrder"],
        "modify_position": ["modify_position", "modify", "modify_order", "edit_order", "modifyPosition", "update_position"],
        "cancel_order": ["cancel_order", "cancel", "order_cancel", "cancelOrder"],
        "fetch_order": ["fetch_order", "get_order", "order_info", "getOrder"],
        "fetch_open_orders": ["fetch_open_orders", "open_orders", "get_open_orders", "list_open_orders"]
    }

    # create_order
    if not hasattr(inst, "create_order"):
        for alt in candidates["create_order"]:
            if hasattr(inst, alt) and callable(getattr(inst, alt)):
                setattr(inst, "create_order", _wrap_create_order(getattr(inst, alt)))
                break
        else:
            _attach_stub("create_order", inst)

    # modify_position
    if not hasattr(inst, "modify_position"):
        for alt in candidates["modify_position"]:
            if hasattr(inst, alt) and callable(getattr(inst, alt)):
                setattr(inst, "modify_position", _wrap_modify_position(getattr(inst, alt)))
                break
        else:
            _attach_stub("modify_position", inst)

    # cancel_order
    if not hasattr(inst, "cancel_order"):
        for alt in candidates["cancel_order"]:
            if hasattr(inst, alt) and callable(getattr(inst, alt)):
                setattr(inst, "cancel_order", _wrap_cancel_order(getattr(inst, alt)))
                break
        else:
            _attach_stub("cancel_order", inst)

    # fetch_order
    if not hasattr(inst, "fetch_order"):
        for alt in candidates["fetch_order"]:
            if hasattr(inst, alt) and callable(getattr(inst, alt)):
                setattr(inst, "fetch_order", _wrap_fetch_order(getattr(inst, alt)))
                break
        else:
            _attach_stub("fetch_order", inst)

    # fetch_open_orders
    if not hasattr(inst, "fetch_open_orders"):
        for alt in candidates["fetch_open_orders"]:
            if hasattr(inst, alt) and callable(getattr(inst, alt)):
                setattr(inst, "fetch_open_orders", _wrap_fetch_open_orders(getattr(inst, alt)))
                break
        else:
            _attach_stub("fetch_open_orders", inst)

    return inst

def create_adapter(name: str, config: Optional[Dict[str, Any]] = None):
    if not name:
        raise ValueError("Adapter name required")
    key = name.strip().lower()
    if key in _registry:
        cls = _registry[key]
        inst = _try_construct(cls, config)
        return _ensure_order_api(inst)
    if key in _aliases:
        cls = _aliases[key]
        inst = _try_construct(cls, config)
        return _ensure_order_api(inst)
    for alias_key, cls in _aliases.items():
        if alias_key in key:
            inst = _try_construct(cls, config)
            return _ensure_order_api(inst)
    raise ValueError(f"Unknown adapter name: {name}. Available: {sorted(list(_aliases.keys()))}")

__all__ = ["create_adapter", "list_adapters", "list_aliases"]
