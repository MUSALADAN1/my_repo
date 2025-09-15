# tests/test_webhook_signature.py
import os
import json
import hmac
import hashlib
from datetime import datetime, timezone

import pytest
from backend.webhook_server import create_app, verify_signature

def make_sha256_header(secret: str, payload_bytes: bytes) -> str:
    sig = hmac.new(secret.encode("utf-8"), payload_bytes, hashlib.sha256).hexdigest()
    return f"sha256={sig}"

def test_verify_signature_accepts_valid_and_rejects_invalid(tmp_path, monkeypatch):
    secret = "super-secret-for-tests"
    payload = {"signal": "buy", "symbol": "BTC/USDT"}
    payload_bytes = json.dumps(payload).encode("utf-8")

    # valid header
    valid_header = make_sha256_header(secret, payload_bytes)
    assert verify_signature(payload_bytes, valid_header, secret) is True

    # invalid header (bad scheme)
    assert verify_signature(payload_bytes, "md5=deadbeef", secret) is False

    # missing header when secret configured -> reject
    assert verify_signature(payload_bytes, "", secret) is False

    # missing secret -> verification is skipped (True)
    assert verify_signature(payload_bytes, "", "") is True

def test_webhook_endpoint_with_and_without_signature(monkeypatch):
    secret = "endpoint-secret"
    monkeypatch.setenv("WEBHOOK_SECRET", secret)

    app = create_app()
    client = app.test_client()

    payload = {"signal": "buy", "symbol": "BTC/USDT", "amount": 0.01}
    payload_bytes = json.dumps(payload).encode("utf-8")
    header = make_sha256_header(secret, payload_bytes)

    # valid signature should return 200
    resp = client.post("/webhook", data=payload_bytes, headers={"Content-Type": "application/json", "X-Signature": header})
    assert resp.status_code == 200
    assert resp.json.get("status") == "ok"

    # invalid signature should return 403
    bad_header = "sha256=" + "0"*64
    resp2 = client.post("/webhook", data=payload_bytes, headers={"Content-Type": "application/json", "X-Signature": bad_header})
    assert resp2.status_code == 403
    assert resp2.json.get("status") == "error"

def test_webhook_endpoint_skip_verification_when_no_secret(monkeypatch):
    # ensure no secret in env -> verification skipped
    monkeypatch.delenv("WEBHOOK_SECRET", raising=False)

    app = create_app()
    client = app.test_client()

    payload = {"signal": "buy", "symbol": "BTC/USDT"}
    resp = client.post("/webhook", json=payload)
    assert resp.status_code == 200
    assert resp.json.get("status") == "ok"
