# backend/bot_controller.py
from flask import Blueprint, request, jsonify
import yaml
import subprocess
import os
# Defensive MT5 import: do not fail at module import time if MetaTrader5 is absent.
# Defensive lazy MT5 loader: avoid importing/initializing MetaTrader5 at module import time.
mt5 = None

def ensure_mt5_local():
    """
    Lazy import of MetaTrader5. Prefer the centralized project helper if present.
    Returns the mt5 module or None if not available.
    """
    global mt5
    if mt5 is not None:
        return mt5
    try:
        from bot_core.exchanges.mt5_adapter import ensure_mt5 as _ensure_mt5
        mt5 = _ensure_mt5()
        return mt5
    except Exception:
        try:
            import MetaTrader5 as _m  # type: ignore
            mt5 = _m
            return mt5
        except Exception:
            mt5 = None
            return None

def ensure_and_init_mt5_local():
    """
    Ensure mt5 module is available and initialize terminal.
    Returns initialized mt5 module or None on failure.
    """
    m = ensure_mt5_local()
    if m is None:
        return None
    try:
        ok = m.initialize()
        if not ok:
            return None
        return m
    except Exception:
        return None

def guarded_mt5_shutdown():
    try:
        if 'mt5' in globals() and mt5 is not None and hasattr(mt5, "shutdown"):
            try:
                mt5.shutdown()
            except Exception:
                pass
    except Exception:
        pass


from flask import jsonify

bot_api = Blueprint('bot_api', __name__)
bot_process = None

# Paths to your core bot files
CONFIG_PATH = os.path.abspath(os.path.join(os.path.dirname(__file__),
                                            '..', 'bot_core', 'config.yaml'))
BOT_SCRIPT  = os.path.abspath(os.path.join(os.path.dirname(__file__),
                                            '..', 'bot_core', 'intraday_trading_bot.py'))

@bot_api.route('/start', methods=['POST'])
def start_bot():
    """
    Launches the trading bot as a subprocess.
    """
    global bot_process
    # If already running, reject
    if bot_process and bot_process.poll() is None:
        return jsonify({'status': 'already running'}), 400

    # Start the bot script
    bot_process = subprocess.Popen(['python', BOT_SCRIPT])
    return jsonify({'status': 'started'})

@bot_api.route('/stop', methods=['POST'])
def stop_bot():
    """
    Terminates the trading bot process if it's running.
    """
    global bot_process
    if not bot_process or bot_process.poll() is not None:
        return jsonify({'status': 'not running'}), 400

    bot_process.terminate()
    return jsonify({'status': 'stopped'})

@bot_api.route('/config', methods=['GET', 'POST'])
def config():
    """
    GET: Read the YAML config and return as JSON.
    POST: Overwrite the YAML config with the posted JSON.
    """
    if request.method == 'GET':
        with open(CONFIG_PATH, 'r') as f:
            cfg = yaml.safe_load(f)
        return jsonify(cfg)

    # POST
    new_cfg = request.get_json()
    with open(CONFIG_PATH, 'w') as f:
        yaml.safe_dump(new_cfg, f)
    return jsonify({'status': 'config updated'})
@bot_api.route('/status', methods=['GET'])
def status():
    """
    Returns current open positions and overall P/L.
    """
    try:
        positions = mt5.positions_get() or []
        total_pl = 0.0
        pos_list = []

        for pos in positions:
            pl = pos.profit
            total_pl += pl
            tick = mt5.symbol_info_tick(pos.symbol)
            current_price = (
                tick.bid if pos.type == mt5.ORDER_TYPE_BUY 
                else tick.ask
            )

            pos_list.append({
                'symbol': pos.symbol,
                'type': 'Buy' if pos.type == mt5.ORDER_TYPE_BUY else 'Sell',
                'volume': pos.volume,
                'price_open': pos.price_open,
                'current_price': round(current_price, 5),
                'profit': round(pl, 2)
            })

        return jsonify({
            'total_pl': round(total_pl, 2),
            'positions': pos_list
        })
    except Exception as e:
        return jsonify({'error': str(e)}), 500
