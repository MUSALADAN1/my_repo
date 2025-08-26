# tests/test_marketplace.py
import os
import io
import zipfile
import tempfile
import shutil
from backend.marketplace import install_plugin, uninstall_plugin, list_plugins, set_plugin_enabled, create_app, PLUGINS_DIR, REGISTRY_PATH

def make_simple_strategy_zip(mod_name="sample_uploaded"):
    """
    Create a zip in memory with a single python module that defines create_strategy.
    Uses a minimal function similar to your existing sample_strategy.
    """
    buf = io.BytesIO()
    zf = zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED)
    code = """
from bot_core.strategies.plugin_base import StrategyPlugin
class UploadedStrategy(StrategyPlugin):
    def __init__(self, name="uploaded", params=None):
        super().__init__(name, params or {})
    def on_bar(self, df):
        return None

def create_strategy(params=None):
    return UploadedStrategy("uploaded", params or {})
"""
    zf.writestr(f"{mod_name}.py", code)
    zf.close()
    buf.seek(0)
    return buf.getvalue()

def test_install_list_enable_uninstall(tmp_path, monkeypatch):
    # use isolated marketplace base
    base = tmp_path / "mpbase"
    os.environ["MARKETPLACE_BASE"] = str(base)

    # ensure fresh
    if base.exists():
        shutil.rmtree(str(base))

    zip_bytes = make_simple_strategy_zip("uploaded_mod")
    res = install_plugin(zip_bytes, name_hint="uploaded_mod")
    assert res.get("ok") is True
    name = res["name"]

    # list should show plugin
    plugins = list_plugins()
    assert any(p["name"] == name for p in plugins)

    # enable plugin
    assert set_plugin_enabled(name, True) is True
    reg = json_registry = None
    # registry file exists
    assert os.path.exists(REGISTRY_PATH)
    # uninstall
    assert uninstall_plugin(name) is True
    assert not os.path.exists(os.path.join(PLUGINS_DIR, name))

def test_blueprint_endpoints(tmp_path):
    # create a test Flask app and register blueprint
    base = tmp_path / "mpbase2"
    os.environ["MARKETPLACE_BASE"] = str(base)
    app = create_app({"MARKETPLACE_BASE": str(base)})
    client = app.test_client()

    # upload via endpoint
    zip_bytes = make_simple_strategy_zip("uploaded_ep")
    data = {
        "file": (io.BytesIO(zip_bytes), "p.zip"),
        "name": "uploaded_ep"
    }
    r = client.post("/marketplace/install", data=data, content_type="multipart/form-data")
    assert r.status_code == 201
    j = r.get_json()
    assert j["ok"] is True
    pname = j["name"]

    # list
    r = client.get("/marketplace/list")
    assert r.status_code == 200
    assert any(p["name"] == pname for p in r.get_json()["plugins"])

    # enable
    r = client.post(f"/marketplace/enable/{pname}")
    assert r.status_code == 200

    # disable
    r = client.post(f"/marketplace/disable/{pname}")
    assert r.status_code == 200

    # uninstall
    r = client.delete(f"/marketplace/uninstall/{pname}")
    assert r.status_code == 200
