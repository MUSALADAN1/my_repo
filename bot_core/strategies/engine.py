# bot_core/strategies/engine.py
"""
Plugin-aware StrategyManager.

Backward-compatible with the small Strategy abstract that existed previously,
but primarily targets the project's StrategyPlugin API defined in plugin_base.py.

Features:
 - register Strategy or StrategyPlugin instances
 - optional StrategyContext to be provided (manager.set_context)
 - discovery: prefers module.create_strategy() factory function if present,
   otherwise instantiates StrategyPlugin subclasses found in the module.
"""

from abc import ABC, abstractmethod
from typing import Any, Dict, Optional, List
import importlib
import inspect
import logging

logger = logging.getLogger(__name__)

# Backwards compatible minimal class (keeps older tests working)
class Strategy(ABC):
    def __init__(self, name: Optional[str] = None, config: Optional[Dict] = None):
        self.name = name or self.__class__.__name__
        self.config = config or {}
        self.enabled = False

    @abstractmethod
    def on_bar(self, ohlcv: Any) -> Optional[Dict[str, Any]]:
        raise NotImplementedError


# Try to import the project's plugin_base StrategyPlugin and StrategyContext if available.
# This allows the manager to work with the concrete plugins in bot_core/strategies/.
try:
    from bot_core.strategies.plugin_base import StrategyPlugin, StrategyContext  # type: ignore
except Exception:
    StrategyPlugin = None  # type: ignore
    StrategyContext = None  # type: ignore


class StrategyManager:
    """
    Manage registered strategies (both lightweight Strategy and project StrategyPlugin).

    Use set_context(context) to provide a StrategyContext (broker + config).
    """

    def __init__(self, context: Optional["StrategyContext"] = None):
        self._strategies: Dict[str, Any] = {}
        self.context = context

    # Context helpers
    def set_context(self, context: "StrategyContext") -> None:
        """Attach a StrategyContext (e.g. broker, config). Newly-registered plugin instances
        will be initialized immediately if context is present."""
        self.context = context
        # initialize already registered plugin instances with the context
        if StrategyPlugin is not None:
            for s in list(self._strategies.values()):
                if isinstance(s, StrategyPlugin):
                    try:
                        s.initialize(self.context)
                    except Exception:
                        logger.exception("Error initializing strategy '%s' with new context", getattr(s, "name", "?"))

    # Registration
    def register(self, strategy: Any, initialize: bool = True) -> None:
        """
        Register a strategy instance.
        Acceptable types:
          - an instance of Strategy (backcompat)
          - an instance of StrategyPlugin (preferred)
        If `initialize` is True and the manager has a context and the strategy exposes initialize(),
        it will be called.
        """
        name = getattr(strategy, "name", None) or strategy.__class__.__name__
        if not name:
            raise TypeError("Strategy instance must have a 'name' attribute")

        if name in self._strategies:
            logger.warning("Overwriting existing strategy registration '%s'", name)

        self._strategies[name] = strategy
        logger.debug("Registered strategy '%s' (%s)", name, type(strategy).__name__)

        # initialize plugin instance if appropriate
        if initialize and self.context is not None:
            if StrategyPlugin is not None and isinstance(strategy, StrategyPlugin):
                try:
                    strategy.initialize(self.context)
                    logger.debug("Initialized StrategyPlugin '%s' with context", name)
                except Exception:
                    logger.exception("Failed to initialize strategy '%s'", name)
            else:
                # Some back-compat or simple Strategy objects may expose initialize; call if present.
                init_fn = getattr(strategy, "initialize", None)
                if callable(init_fn):
                    try:
                        init_fn(self.context)
                    except Exception:
                        logger.exception("Failed to call initialize() on strategy '%s'", name)

    def unregister(self, name: str) -> None:
        s = self._strategies.pop(name, None)
        if s:
            # try to call on_exit if present
            exit_fn = getattr(s, "on_exit", None)
            if callable(exit_fn):
                try:
                    exit_fn()
                except Exception:
                    logger.exception("Error during strategy '%s' on_exit()", name)
        logger.debug("Unregistered strategy '%s'", name)

    def get(self, name: str) -> Optional[Any]:
        return self._strategies.get(name)

    def list(self) -> List[str]:
        return list(self._strategies.keys())

    # Enable / disable -- plugin instances may not have 'enabled' attribute; we set it if missing.
    def enable(self, name: str) -> bool:
        s = self._strategies.get(name)
        if s is None:
            return False
        if not hasattr(s, "enabled"):
            try:
                setattr(s, "enabled", True)
            except Exception:
                pass
        else:
            try:
                s.enabled = True
            except Exception:
                setattr(s, "enabled", True)
        logger.debug("Enabled strategy '%s'", name)
        return True

    def disable(self, name: str) -> bool:
        s = self._strategies.get(name)
        if s is None:
            return False
        if hasattr(s, "enabled"):
            try:
                s.enabled = False
            except Exception:
                setattr(s, "enabled", False)
        logger.debug("Disabled strategy '%s'", name)
        return True

    # Running strategies
    def run_on_bar(self, ohlcv: Any) -> Dict[str, Any]:
        """
        Run through all registered strategies that are enabled (or always-run if they do not support enable flag).
        For StrategyPlugin instances we do not require an 'enabled' flag, but we still respect it if present.
        """
        results: Dict[str, Any] = {}
        for name, strat in list(self._strategies.items()):
            enabled_flag = getattr(strat, "enabled", True)  # default to True if not specified
            if not enabled_flag:
                continue
            try:
                sig = strat.on_bar(ohlcv)
                # If the plugin returns a structure that marks zone-skip, just include it
                if sig is not None:
                    results[name] = sig
                    # If plugin exposes on_signal hook, call it (best-effort)
                    on_signal = getattr(strat, "on_signal", None)
                    if callable(on_signal):
                        try:
                            on_signal(sig)
                        except Exception:
                            logger.exception("on_signal() failed for '%s'", name)
                    logger.debug("Strategy '%s' produced: %s", name, sig)
            except Exception:
                logger.exception("Error running strategy '%s'", name)
        return results

    # Discovery helpers
    def discover_from_module(self, module, params: Optional[Dict] = None) -> List[Any]:
        """
        Discover StrategyPlugin instances from an imported module.

        Discovery order:
          1) If module has callable create_strategy(params) -> prefer that.
             - call create_strategy(params or {}) and accept:
               * a StrategyPlugin instance
               * a tuple (instance, ...) -> take first element if instance-like
          2) Otherwise, find classes in module that subclass StrategyPlugin and instantiate them (no args).
        """
        found: List[Any] = []
        params = params or {}
        # 1) factory function
        create_fn = getattr(module, "create_strategy", None)
        if callable(create_fn):
            try:
                inst = create_fn(params)
                # some factories return (instance, something else)
                if isinstance(inst, tuple) or isinstance(inst, list):
                    candidate = inst[0] if inst else None
                else:
                    candidate = inst
                if candidate is not None:
                    self.register(candidate)
                    found.append(candidate)
                return found
            except Exception:
                logger.exception("create_strategy() failed in module %s", getattr(module, "__name__", "?"))

        # 2) class scanning for StrategyPlugin subclasses
        if StrategyPlugin is not None:
            for _, obj in inspect.getmembers(module, inspect.isclass):
                if inspect.isclass(obj) and issubclass(obj, StrategyPlugin) and obj is not StrategyPlugin and obj.__module__ == module.__name__:
                    try:
                        inst = obj()  # default ctor expected by plugin implementations
                        self.register(inst)
                        found.append(inst)
                    except Exception:
                        logger.exception("Failed to instantiate StrategyPlugin class %s", obj)
        else:
            # fallback: look for our lightweight Strategy classes
            for _, obj in inspect.getmembers(module, inspect.isclass):
                if issubclass(obj, Strategy) and obj is not Strategy and obj.__module__ == module.__name__:
                    try:
                        inst = obj()
                        self.register(inst)
                        found.append(inst)
                    except Exception:
                        logger.exception("Failed to instantiate Strategy class %s", obj)

        return found

    def load_module_from_path(self, module_path: str, params: Optional[Dict] = None) -> List[Any]:
        """
        Import module by path and discover strategies in it (prefers factory).
        """
        try:
            module = importlib.import_module(module_path)
            return self.discover_from_module(module, params=params)
        except Exception:
            logger.exception("Failed to import strategy module '%s'", module_path)
            return []
