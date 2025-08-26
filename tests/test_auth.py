# tests/test_auth.py
import os
import tempfile
import json
from backend.auth import create_app
import pytest

def test_register_login_whoami_and_admin_users():
    # use a temp file for users
    fd, path = tempfile.mkstemp(suffix=".json")
    os.close(fd)
    os.unlink(path)  # ensure fresh

    # set an admin key to test admin registration
    admin_key = "adminkey123"

    app = create_app({
        "AUTH_USERS_PATH": path,
        "ADMIN_REG_KEY": admin_key,
        "AUTH_SECRET": "testsecret",
        "AUTH_TTL": 60
    })
    client = app.test_client()

    # register normal user
    r = client.post("/auth/register", json={"username": "alice", "password": "pw1"})
    assert r.status_code == 201
    assert r.get_json()["ok"] is True

    # register admin (with admin_key)
    r = client.post("/auth/register", json={"username": "boss", "password": "pw2", "role": "admin", "admin_key": admin_key})
    assert r.status_code == 201
    assert r.get_json()["ok"] is True

    # cannot register same user twice
    r = client.post("/auth/register", json={"username": "alice", "password": "pw1"})
    assert r.status_code == 400

    # login incorrect
    r = client.post("/auth/login", json={"username": "alice", "password": "bad"})
    assert r.status_code == 401

    # login correct -> get token
    r = client.post("/auth/login", json={"username": "alice", "password": "pw1"})
    assert r.status_code == 200
    token = r.get_json()["token"]
    assert token and isinstance(token, str)

    # whoami with token
    headers = {"Authorization": f"Bearer {token}"}
    r = client.get("/auth/whoami", headers=headers)
    assert r.status_code == 200
    j = r.get_json()
    assert j["user"]["username"] == "alice"
    assert j["user"]["role"] == "user"

    # admin login
    r = client.post("/auth/login", json={"username": "boss", "password": "pw2"})
    assert r.status_code == 200
    admin_token = r.get_json()["token"]
    # admin-only /users
    r = client.get("/auth/users", headers={"Authorization": f"Bearer {admin_token}"})
    assert r.status_code == 200
    users = r.get_json()["users"]
    # should include at least the two registered users
    assert any(u["username"] == "alice" for u in users)
    assert any(u["username"] == "boss" for u in users)

    # non-admin cannot access /users
    r = client.get("/auth/users", headers=headers)
    assert r.status_code == 403

    # cleanup temp file
    try:
        os.unlink(path)
    except Exception:
        pass
