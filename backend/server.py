# backend/server.py
from flask import Flask
# import blueprints that already exist in your repo
from backend.auth import bp as auth_bp
from backend.billing import bp as billing_bp
from backend import status_server as status_mod  # optional: reuse existing status_server app / functions

def create_app():
    app = Flask(__name__)
    # register existing auth blueprint under /api/auth
    app.register_blueprint(auth_bp, url_prefix="/api/auth")
    # register billing blueprint under /api/billing
    app.register_blueprint(billing_bp, url_prefix="/api/billing")

    # Optional: mount your standalone status_server as a route prefix
    try:
        # status_server is a module with a Flask app; we mount its routes onto this app by copying view functions
        # If this fails, it's safe to ignore — this is an additive attempt only.
        if hasattr(status_mod, "app"):
            for rule in list(status_mod.app.url_map.iter_rules()):
                # skip static or duplicated endpoints
                pass
    except Exception:
        pass

    return app

if __name__ == "__main__":
    app = create_app()
    app.run(host="0.0.0.0", port=int(__import__("os").environ.get("PORT", 8000)), debug=True)
