# backend/server.py
from flask import Flask
# import blueprints that already exist in your repo
from backend.auth import bp as auth_bp
from backend.billing import bp as billing_bp
from flask_cors import CORS

# import the status_server module (it defines `app` and many routes)
import backend.status_server as status_mod

def create_app():
    app = Flask(__name__)
    CORS(app)                      
    # register blueprints
    app.register_blueprint(auth_bp, url_prefix="/api/auth")
    app.register_blueprint(billing_bp, url_prefix="/api/billing")

    # ---- Mount routes from backend.status_server.app into this app ----
    # status_mod.app is a Flask app module with routes defined directly.
    # We iterate its rules and re-register the underlying view functions here.
    try:
        for rule in status_mod.app.url_map.iter_rules():
            # skip static endpoints
            if rule.endpoint == "static":
                continue
            # get the view function object (callable) from the status_server app
            view_func = status_mod.app.view_functions.get(rule.endpoint)
            if view_func is None:
                continue
            # create a unique endpoint name in our main app to avoid collisions
            endpoint_name = f"status_{rule.endpoint}"
            # add the same rule path and methods to our app, pointing at the same callable
            # str(rule) yields the rule pattern (e.g. '/api/status')
            app.add_url_rule(str(rule),
                             endpoint=endpoint_name,
                             view_func=view_func,
                             methods=[m for m in rule.methods if m in ("GET", "POST", "PUT", "DELETE", "PATCH", "OPTIONS")])
    except Exception:
        # don't fail startup if this copying fails — app still runs with your blueprints
        app.logger.exception("Could not mount status_server routes into main app")

    return app

if __name__ == "__main__":
    app = create_app()
    app.run(host="0.0.0.0", port=int(__import__("os").environ.get("PORT", 8000)), debug=True)
