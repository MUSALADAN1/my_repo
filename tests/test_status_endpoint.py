# tests/test_status_endpoint.py
import json
from backend import status_server
from backend.status_server import app
import pytest

def test_api_status_keys():
    client = app.test_client()
    rv = client.get("/api/status")
    assert rv.status_code == 200
    j = rv.get_json()
    assert set(["strategies", "zones", "metrics", "last_update"]).issubset(set(j.keys()))
