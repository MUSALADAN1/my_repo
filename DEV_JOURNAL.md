2025-08-23T14:35:00Z - Replaced place_order with adapter-first implementation; added tests/test_adapter_order_smoke.py; pytest not installed yet (tests pending).
2025-08-23T14:59:00Z - tests/test_adapter_order_smoke.py updated to include type='market'; pytest passed with PYTHONPATH=. (adapter smoke test OK).
2025-08-23T15:12:00Z - Replaced top-level 'import MetaTrader5 as mt5' with guarded import in backend/bot_controller.py; py_compile OK.
