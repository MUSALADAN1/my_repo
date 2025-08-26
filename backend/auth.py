# backend/auth.py
"""
Lightweight auth module (file-backed users + HMAC token).
Provides a Flask blueprint with routes:
 - POST /register  -> {"ok": True}
 - POST /login     -> {"ok": True, "token": "..."}
 - GET  /whoami    -> requires Authorization: Bearer <token>
 - GET  /users     -> admin-only, list users (no passwords)
Designed for tests and simple single-node deployments. Replace backing store
with a real DB in production.
"""
import os
import json
import time
import hmac
import hashlib
import secrets
from functools import wraps
from typing import Optional, Dict, Any
from datetime import datetime, timezone

from flask import Flask, Blueprint, request, jsonify, current_app

# Config using env vars, but blueprint accepts app.config overrides
DEFAULT_USERS_PATH = os.environ.get("AUTH_USERS_PATH", os.path.join(os.getcwd(), "auth_users.json"))
DEFAULT_SECRET = os.environ.get("AUTH_SECRET", "")  # If empty, tokens still work but are signed with generated secret at runtime (tests can set)
ADMIN_REG_KEY = os.environ.get("ADMIN_REG_KEY", "")  # optional secret to allow role=admin on registration

bp = Blueprint("auth", __name__)

# ---- helpers: password hashing ----
def _hash_password(password: str, salt: Optional[bytes] = None) -> Dict[str, Any]:
    if salt is None:
        salt = secrets.token_bytes(16)
    # PBKDF2-HMAC-SHA256
    dk = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, 100_000)
    return {"salt": salt.hex(), "hash": dk.hex()}

def _verify_password(password: str, salt_hex: str, hash_hex: str) -> bool:
    try:
        salt = bytes.fromhex(salt_hex)
        expected = bytes.fromhex(hash_hex)
        dk = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, 100_000)
        return hmac.compare_digest(dk, expected)
    except Exception:
        return False

# ---- token helpers (HMAC signed compact token) ----
def _sign_token(payload: str, secret: str) -> str:
    mac = hmac.new(secret.encode("utf-8"), payload.encode("utf-8"), hashlib.sha256).hexdigest()
    return f"{payload}:{mac}"

def _verify_signed_token(token: str, secret: str) -> Optional[str]:
    """
    token format: "<username>|<expiry_ts>|<nonce>:<mac>"
    returns payload (username|expiry|nonce) if valid and not expired, else None
    """
    try:
        payload, mac = token.rsplit(":", 1)
    except Exception:
        return None
    expected = hmac.new(secret.encode("utf-8"), payload.encode("utf-8"), hashlib.sha256).hexdigest()
    if not hmac.compare_digest(expected, mac):
        return None
    parts = payload.split("|")
    if len(parts) != 3:
        return None
    username, expiry_s, nonce = parts
    try:
        expiry = int(expiry_s)
    except Exception:
        return None
    now = int(time.time())
    if expiry < now:
        return None
    return payload  # caller can parse username if needed

def create_token_for_user(username: str, secret: str, ttl_seconds: int = 3600) -> str:
    expiry = int(time.time()) + int(ttl_seconds)
    nonce = secrets.token_hex(8)
    payload = f"{username}|{expiry}|{nonce}"
    return _sign_token(payload, secret)

def parse_token_get_user(token: str, secret: str) -> Optional[Dict[str, Any]]:
    payload = _verify_signed_token(token, secret)
    if not payload:
        return None
    username, expiry_s, nonce = payload.split("|")
    return {"username": username, "expiry": int(expiry_s), "nonce": nonce}

# ---- users storage helpers ----
def _load_users(path: str) -> Dict[str, Any]:
    try:
        if not os.path.exists(path):
            return {}
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f) or {}
            return data
    except Exception:
        return {}

def _save_users(path: str, users: Dict[str, Any]) -> None:
    d = os.path.dirname(path) or "."
    os.makedirs(d, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(users, f, indent=2)

def _user_public_safe(rec: Dict[str, Any]) -> Dict[str, Any]:
    return {"username": rec.get("username"), "role": rec.get("role", "user"), "created_at": rec.get("created_at")}

# ---- decorators for route protection ----
def require_auth(role: Optional[str] = None):
    def decorator(f):
        @wraps(f)
        def wrapped(*args, **kwargs):
            auth = request.headers.get("Authorization", "") or request.headers.get("authorization", "")
            if not auth or not auth.lower().startswith("bearer "):
                return jsonify({"ok": False, "reason": "missing_authorization"}), 401
            token = auth.split(" ", 1)[1].strip()
            secret = current_app.config.get("AUTH_SECRET") or DEFAULT_SECRET
            userinfo = parse_token_get_user(token, secret)
            if not userinfo:
                return jsonify({"ok": False, "reason": "invalid_or_expired_token"}), 401
            # load user and check role
            users_path = current_app.config.get("AUTH_USERS_PATH") or DEFAULT_USERS_PATH
            users = _load_users(users_path)
            rec = users.get(userinfo["username"])
            if not rec:
                return jsonify({"ok": False, "reason": "user_not_found"}), 401
            user_role = rec.get("role", "user")
            if role and user_role != role:
                return jsonify({"ok": False, "reason": "insufficient_role"}), 403
            # inject user into request context via request._auth_user (simple)
            request._auth_user = {"username": rec["username"], "role": user_role}
            return f(*args, **kwargs)
        return wrapped
    return decorator

# ---- Flask blueprint endpoints ----
@bp.route("/register", methods=["POST"])
def register():
    body = request.get_json(force=True, silent=True) or {}
    username = body.get("username")
    password = body.get("password")
    role = (body.get("role") or "user").lower()

    if not username or not password:
        return jsonify({"ok": False, "reason": "missing_username_or_password"}), 400

    users_path = current_app.config.get("AUTH_USERS_PATH") or DEFAULT_USERS_PATH
    users = _load_users(users_path)

    if username in users:
        return jsonify({"ok": False, "reason": "user_exists"}), 400

    # role elevation only if ADMIN_REG_KEY configured and matches provided admin_key
    admin_key = body.get("admin_key") or ""
    if role == "admin":
        cfg_admin_key = current_app.config.get("ADMIN_REG_KEY") or ADMIN_REG_KEY
        if not cfg_admin_key or admin_key != cfg_admin_key:
            # reject silently as normal user registration
            role = "user"

    hashed = _hash_password(password)
    users[username] = {
        "username": username,
        "password": {"salt": hashed["salt"], "hash": hashed["hash"]},
        "role": role,
        "created_at": datetime.now(timezone.utc).isoformat()
    }
    _save_users(users_path, users)
    return jsonify({"ok": True}), 201

@bp.route("/login", methods=["POST"])
def login():
    body = request.get_json(force=True, silent=True) or {}
    username = body.get("username")
    password = body.get("password")
    if not username or not password:
        return jsonify({"ok": False, "reason": "missing_username_or_password"}), 400

    users_path = current_app.config.get("AUTH_USERS_PATH") or DEFAULT_USERS_PATH
    users = _load_users(users_path)
    rec = users.get(username)
    if not rec:
        return jsonify({"ok": False, "reason": "invalid_credentials"}), 401

    pw = rec.get("password", {})
    if not _verify_password(password, pw.get("salt", ""), pw.get("hash", "")):
        return jsonify({"ok": False, "reason": "invalid_credentials"}), 401

    secret = current_app.config.get("AUTH_SECRET") or DEFAULT_SECRET
    if not secret:
        # if no secret configured, generate a runtime secret (non-persistent) to still issue tokens
        secret = secrets.token_hex(32)
        current_app.config["AUTH_SECRET"] = secret

    ttl = int(current_app.config.get("AUTH_TTL", 3600))
    token = create_token_for_user(username, secret, ttl_seconds=ttl)
    return jsonify({"ok": True, "token": token}), 200

@bp.route("/whoami", methods=["GET"])
@require_auth()
def whoami():
    u = getattr(request, "_auth_user", None)
    return jsonify({"ok": True, "user": u}), 200

@bp.route("/users", methods=["GET"])
@require_auth(role="admin")
def list_users():
    users_path = current_app.config.get("AUTH_USERS_PATH") or DEFAULT_USERS_PATH
    users = _load_users(users_path)
    return jsonify({"ok": True, "users": [ _user_public_safe(rec) for rec in users.values() ]}), 200

# ---- helper to create a testing Flask app ----
def create_app(config: Optional[Dict[str, Any]] = None) -> Flask:
    app = Flask("auth_app")
    cfg = config or {}
    app.config["AUTH_USERS_PATH"] = cfg.get("AUTH_USERS_PATH") or cfg.get("USERS_PATH") or DEFAULT_USERS_PATH
    app.config["AUTH_SECRET"] = cfg.get("AUTH_SECRET") or os.environ.get("AUTH_SECRET", "")
    app.config["ADMIN_REG_KEY"] = cfg.get("ADMIN_REG_KEY") or os.environ.get("ADMIN_REG_KEY", "")
    app.config["AUTH_TTL"] = int(cfg.get("AUTH_TTL", 3600))
    app.register_blueprint(bp, url_prefix="/auth")
    return app
