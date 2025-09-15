# backend/app.py
from flask import Flask
from flask_cors import CORS
from bot_controller import bot_api

app = Flask(__name__)
CORS(app)  # Allow React frontend to call our API

# Register the trading-bot blueprint
app.register_blueprint(bot_api, url_prefix='/api')

if __name__ == '__main__':
    # Run on port 5000, accessible from localhost
    app.run(host='0.0.0.0', port=5000, debug=True)
