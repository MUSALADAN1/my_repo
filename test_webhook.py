# test_webhook.py
import os
import hmac
import hashlib
import json
from backend.webhook_server import create_app
import tempfile
import pathlib

def sign_payload(secret: str, payload_bytes: bytes) -> str:
    sig = hmac.new(secret.encode("utf-8"), payload_bytes, hashlib.sha256).hexdigest()
    return f"sha256={sig}"

def test_webhook_accepts_and_saves_event(tmp_path, monkeypatch):
    # prepare test event file path
    events_file = str(tmp_path / "events.jsonl")
    monkeypatch.setenv("WEBHOOK_EVENTS_PATH", events_file)

    # configure secret and set env
    secret = "testsecret123"
    monkeypatch.setenv("WEBHOOK_SECRET", secret)

    app = create_app()
    client = app.test_client()

    payload = {"strategy": "ma_crossover", "signal": "long", "symbol": "BTC/USDT"}
    payload_bytes = json.dumps(payload).encode("utf-8")
    signature = sign_payload(secret, payload_bytes)

    resp = client.post("/webhook", data=payload_bytes, headers={"Content-Type": "application/json", "X-Signature": signature})
    assert resp.status_code == 200
    assert resp.get_json().get("status") == "ok"

    # ensure events file exists and contains the payload
    with open(events_file, "r", encoding="utf-8") as f:
        lines = [json.loads(l) for l in f.readlines() if l.strip()]
    assert len(lines) == 1
    assert lines[0]["payload"]["strategy"] == "ma_crossover"
    assert lines[0]["payload"]["signal"] == "long"

def test_webhook_rejects_invalid_signature(tmp_path, monkeypatch):
    events_file = str(tmp_path / "events2.jsonl")
    monkeypatch.setenv("WEBHOOK_EVENTS_PATH", events_file)
    secret = "anothersecret"
    monkeypatch.setenv("WEBHOOK_SECRET", secret)

    app = create_app()
    client = app.test_client()

    payload = {"strategy": "test", "signal": "sell"}
    payload_bytes = json.dumps(payload).encode("utf-8")
    # create wrong signature (using different secret)
    wrong_sig = hmac.new(b"badsecret", payload_bytes, hashlib.sha256).hexdigest()
    header = f"sha256={wrong_sig}"

    resp = client.post("/webhook", data=payload_bytes, headers={"Content-Type": "application/json", "X-Signature": header})
    assert resp.status_code == 403
    assert "invalid signature" in resp.get_json().get("reason", "")
    # events file should not exist or be empty
    if os.path.exists(events_file):
        with open(events_file, "r", encoding="utf-8") as f:
            content = f.read().strip()
        assert content == "" or content is None
