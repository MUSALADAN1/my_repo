# test_notifications.py
import json
from bot_core.notifications.notify import NotificationManager, NotificationError
import builtins

def test_send_telegram_monkeypatched(monkeypatch):
    # monkeypatch env vars
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "fake-token")
    monkeypatch.setenv("TELEGRAM_CHAT_ID", "12345")

    recorded = {}
    # fake requests.post
    def fake_post(url, data=None, json=None, timeout=None):
        # record call and return a fake response-like object
        recorded['url'] = url
        recorded['data'] = data
        class Resp:
            def __init__(self):
                self.status_code = 200
            def json(self):
                return {"ok": True, "result": {"message_id": 1}}
            @property
            def text(self):
                return '{"ok": true}'
        return Resp()

    monkeypatch.setattr("requests.post", fake_post)

    nm = NotificationManager()  # will pick token/chat from env
    res = nm.send_telegram("Hello test")
    assert isinstance(res, dict)
    assert recorded['url'].startswith("https://api.telegram.org/botfake-token/sendMessage")
    assert recorded['data']["chat_id"] == "12345"
    assert "Hello test" in recorded['data']["text"]

def test_send_telegram_missing_config():
    # ensure missing env triggers NotificationError
    nm = NotificationManager(telegram_token=None, telegram_chat_id=None, dry_run=True)
    try:
        nm.send_telegram("hi")
        # should not reach here
        assert False, "expected NotificationError when telegram not configured"
    except NotificationError:
        pass
