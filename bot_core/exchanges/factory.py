# bot_core/exchanges/factory.py
from typing import Dict, Optional, Tuple

from .binance_adapter import BinanceAdapter
from .bybit_adapter import BybitAdapter
from .kucoin_adapter import KuCoinAdapter
from .mt5_adapter import MT5Adapter
from .ccxt_adapter import CCXTAdapter

# canonical adapters by short name
_ADAPTERS = {
    "binance": BinanceAdapter,
    "bybit": BybitAdapter,
    "kucoin": KuCoinAdapter,
    "mt5": MT5Adapter,
    # keep this mapping for direct ccxt wrapper alias
    "ccxt": CCXTAdapter,
}

def create_adapter(name: str, config: Optional[Dict] = None):
    """
    Factory helper to instantiate an adapter by short name.

    Special support:
      - name may be "ccxt" -> returns CCXTAdapter(config)
      - or "ccxt:binance" -> returns CCXTAdapter(config_with_exchange_name)
      - or plain "binance" -> returns BinanceAdapter
    """
    config = config or {}
    if not name:
        raise ValueError("Adapter name required")

    # support colon syntax: "ccxt:binance" or "ccxt:bybit"
    if ":" in name:
        base, sub = name.split(":", 1)
        base = base.lower().strip()
        sub = sub.strip()
        if base == "ccxt":
            # inject exchange hint into config
            cfg = dict(config)
            if "exchange" not in cfg:
                cfg["exchange"] = sub
            return CCXTAdapter(cfg)
        # otherwise fall through to normal resolution

    key = name.lower().strip()
    cls = _ADAPTERS.get(key)
    if not cls:
        raise ValueError(f"No adapter registered for '{name}'. Available: {list(_ADAPTERS.keys())}")
    return cls(config or {})
