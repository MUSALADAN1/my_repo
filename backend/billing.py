# backend/billing.py
from flask import Blueprint, request, jsonify, current_app
import os

bp = Blueprint("billing", __name__)

# sensible public plans (example — use values you like)
PLANS = [
    {"id": "basic", "name": "Basic", "price": 1000, "currency": "USD",
     "description": "Paper trading + community support"},
    {"id": "pro", "name": "Pro", "price": 2500, "currency": "USD",
     "description": "Live trading, TWAP, webhook automations"},
    {"id": "team", "name": "Team", "price": 9900, "currency": "USD",
     "description": "Team seats, priority support"},
]

# try to import stripe; if unavailable we fall back to a dev stub
try:
    import stripe
    stripe.api_key = os.environ.get("STRIPE_SECRET_KEY", "")
except Exception:
    stripe = None

@bp.route("/plans", methods=["GET"])
def get_plans():
    return jsonify({"ok": True, "plans": PLANS}), 200

@bp.route("/checkout-session", methods=["POST"])
def checkout_session():
    data = request.get_json(silent=True) or {}
    plan_id = data.get("planId")
    plan = next((p for p in PLANS if p["id"] == plan_id), None)
    if not plan:
        return jsonify({"ok": False, "reason": "invalid_plan"}), 400

    domain = os.environ.get("STRIPE_DOMAIN", "http://localhost:3000")
    if stripe:
        # creates a checkout session using price_data inline (server-side)
        try:
            session = stripe.checkout.Session.create(
                payment_method_types=["card"],
                mode="subscription",
                line_items=[{
                    "price_data": {
                        "currency": plan["currency"].lower(),
                        "product_data": {"name": plan["name"], "description": plan.get("description", "")},
                        "unit_amount": plan["price"]
                    },
                    "quantity": 1
                }],
                success_url=f"{domain}/success?session_id={{CHECKOUT_SESSION_ID}}",
                cancel_url=f"{domain}/cancel",
            )
            return jsonify({"ok": True, "url": session.url}), 200
        except Exception as e:
            current_app.logger.exception("stripe checkout create failed")
            return jsonify({"ok": False, "reason": "stripe_error", "detail": str(e)}), 500

    # dev fallback when stripe isn't installed / configured
    return jsonify({"ok": True, "url": f"{domain}/fake-checkout?plan={plan_id}"}), 200

@bp.route("/portal-session", methods=["GET"])
def portal_session():
    domain = os.environ.get("STRIPE_DOMAIN", "http://localhost:3000")
    if stripe:
        try:
            # NOTE: in real code, you must supply a Stripe customer id mapped to your user
            # Here we return a 501 if not implemented
            return jsonify({"ok": False, "reason": "not_implemented", "detail": "Map users -> stripe customers first"}), 501
        except Exception as e:
            current_app.logger.exception("stripe portal create failed")
            return jsonify({"ok": False, "reason": "stripe_error", "detail": str(e)}), 500

    return jsonify({"ok": True, "url": f"{domain}/billing"}), 200
