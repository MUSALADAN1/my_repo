# bot_core/notifications/notify.py
"""
NotificationManager

Currently supports:
 - Telegram (via Bot API): send_message(text)
 - Slack (basic webhook support via send_slack)

Usage:
  from bot_core.notifications.notify import NotificationManager
  nm = NotificationManager()
  nm.send_telegram("Hello world")
  
Environment variables (recommended):
  TELEGRAM_BOT_TOKEN  - Bot token (like 123456:ABC-DEF...)
  TELEGRAM_CHAT_ID    - chat id (user or group)
  SLACK_WEBHOOK_URL   - optional Slack incoming webhook url
"""

import os
from typing import Optional
import requests

class NotificationError(Exception):
    pass

class NotificationManager:
    def __init__(self,
                 telegram_token: Optional[str] = None,
                 telegram_chat_id: Optional[str] = None,
                 slack_webhook: Optional[str] = None,
                 dry_run: bool = False):
        # prefer explicit args, else environment
        self.telegram_token = telegram_token or os.environ.get("TELEGRAM_BOT_TOKEN")
        self.telegram_chat_id = telegram_chat_id or os.environ.get("TELEGRAM_CHAT_ID")
        self.slack_webhook = slack_webhook or os.environ.get("SLACK_WEBHOOK_URL")
        self.dry_run = bool(dry_run)

    # ---------- Telegram ----------
    def send_telegram(self, text: str, parse_mode: str = "Markdown") -> dict:
        """
        Send a message to configured Telegram chat. Returns response JSON on success.
        Raises NotificationError on misconfig or HTTP failure.
        """
        if not self.telegram_token or not self.telegram_chat_id:
            raise NotificationError("Telegram token or chat id not configured")

        if self.dry_run:
            return {"status": "dry_run", "text": text}

        url = f"https://api.telegram.org/bot{self.telegram_token}/sendMessage"
        payload = {
            "chat_id": str(self.telegram_chat_id),
            "text": text,
            "parse_mode": parse_mode
        }
        try:
            resp = requests.post(url, data=payload, timeout=10)
        except Exception as e:
            raise NotificationError(f"failed to send telegram message: {e}")

        if resp.status_code not in (200, 201):
            raise NotificationError(f"telegram API returned {resp.status_code}: {resp.text}")

        try:
            return resp.json()
        except Exception:
            return {"status_code": resp.status_code, "text": resp.text}

    # ---------- Slack ----------
    def send_slack(self, text: str) -> dict:
        """
        Send a simple text message to Slack incoming webhook.
        """
        if not self.slack_webhook:
            raise NotificationError("Slack webhook not configured")

        if self.dry_run:
            return {"status": "dry_run", "text": text}

        try:
            resp = requests.post(self.slack_webhook, json={"text": text}, timeout=10)
        except Exception as e:
            raise NotificationError(f"failed to send slack message: {e}")

        if resp.status_code not in (200, 201):
            raise NotificationError(f"slack webhook returned {resp.status_code}: {resp.text}")

        try:
            return resp.json()
        except Exception:
            return {"status_code": resp.status_code, "text": resp.text}

    # ---------- convenience ----------
    def send(self, text: str, channels: Optional[list] = None) -> dict:
        """
        Send to multiple channels. channels = ['telegram','slack']. Returns dict of results.
        """
        results = {}
        chans = channels or (["telegram"] if self.telegram_token and self.telegram_chat_id else [])
        for c in chans:
            try:
                if c == "telegram":
                    results["telegram"] = self.send_telegram(text)
                elif c == "slack":
                    results["slack"] = self.send_slack(text)
                else:
                    results[c] = {"status": "skipped", "reason": "unknown channel"}
            except NotificationError as e:
                results[c] = {"status": "error", "reason": str(e)}
        return results
