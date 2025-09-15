# backend/webhook_server.py
"""
Simple webhook receiver for TradingView / webhook alerts.

- POST /webhook  -> accepts JSON payload
- Optional header: X-Signature: 'sha256=<hex>' which is HMAC-SHA256(payload, WEBHOOK_SECRET)
- Events are appended to a jsonlines file defined by WEBHOOK_EVENTS_PATH env var (default ./webhook_events.jsonl)
- Use create_app() for testing.
"""

from flask import Flask, request, jsonify
import os
import hmac
import hashlib
import json
from datetime import datetime, timezone

WEBHOOK_SECRET = os.environ.get("WEBHOOK_SECRET", "")  # if empty, signature verification is skipped
WEBHOOK_EVENTS_PATH = os.environ.get("WEBHOOK_EVENTS_PATH", os.path.join(os.getcwd(), "webhook_events.jsonl"))

def verify_signature(payload_bytes: bytes, signature_header: str, secret: str) -> bool:
    """
    Verify HMAC-SHA256 signature header of form 'sha256=<hex>'.
    Returns True if header absent and secret empty (skips verification),
    otherwise returns hmac.compare_digest result.
    """
    if not secret:
        # no secret configured -> skip verification
        return True
    if not signature_header:
        return False
    try:
        scheme, hexsig = signature_header.split("=", 1)
    except Exception:
        return False
    if scheme.lower() != "sha256":
        return False
    expected = hmac.new(secret.encode("utf-8"), payload_bytes, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, hexsig)

def append_event_to_file(event: dict, path: str = WEBHOOK_EVENTS_PATH) -> None:
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    with open(path, "a", encoding="utf-8") as f:
        f.write(json.dumps(event, default=str) + "\n")

def create_app():
    app = Flask(__name__)

    @app.route("/health", methods=["GET"])
    def health():
        return jsonify({"status": "ok", "ts": datetime.now(timezone.utc).isoformat()}), 200

    @app.route("/webhook", methods=["POST"])
    def webhook():
        payload_bytes = request.get_data() or b""
        signature = request.headers.get("X-Signature", "") or request.headers.get("x-signature", "")

        # verify signature if secret configured
        secret = os.environ.get("WEBHOOK_SECRET", WEBHOOK_SECRET)
        ok = verify_signature(payload_bytes, signature, secret)
        if not ok:
            return jsonify({"status": "error", "reason": "invalid signature"}), 403

        # parse JSON safely
        try:
            payload = request.get_json(force=True)
        except Exception:
            try:
                payload = json.loads(payload_bytes.decode("utf-8") or "{}")
            except Exception:
                payload = {"raw": payload_bytes.decode("utf-8", errors="replace")}

        # create event record with metadata
        event = {
            "received_at": datetime.now(timezone.utc).isoformat(),
            "remote_addr": request.remote_addr,
            "headers": {k: v for k, v in request.headers.items()},
            "payload": payload
        }

        # append to file (path configurable via env)
        events_path = os.environ.get("WEBHOOK_EVENTS_PATH", WEBHOOK_EVENTS_PATH)
        try:
            append_event_to_file(event, events_path)
        except Exception as e:
            return jsonify({"status": "error", "reason": f"failed to save event: {e}"}), 500

        return jsonify({"status": "ok"}), 200

    return app

# convenience: if run directly, start dev server
if __name__ == "__main__":
    app = create_app()
    # debug reloader off by default in this script
    app.run(host="0.0.0.0", port=int(os.environ.get("WEBHOOK_PORT", "5005")), debug=False)
