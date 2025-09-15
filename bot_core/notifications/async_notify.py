# bot_core/notifications/async_notify.py
"""
AsyncNotifier — background queue + worker that sends notifications using NotificationManager.

Behavior:
 - queue.put_nowait() is used so producers never block; if queue is full a message is dropped.
 - worker thread flushes messages and calls NotificationManager.send.
 - atexit handler stops the worker on interpreter exit.
"""

from __future__ import annotations
import threading
import queue
import time
import atexit
from typing import Optional, Dict, Any, List, Tuple

from bot_core.notifications.notify import NotificationManager, NotificationError
import os

class AsyncNotifier:
    def __init__(self,
                 telegram_token: Optional[str] = None,
                 telegram_chat_id: Optional[str] = None,
                 slack_webhook: Optional[str] = None,
                 dry_run: bool = False,
                 max_queue: int = 1000,
                 swallow_exceptions: bool = True):
        self._mgr = NotificationManager(
            telegram_token=telegram_token,
            telegram_chat_id=telegram_chat_id,
            slack_webhook=slack_webhook,
            dry_run=dry_run
        )
        self._q: "queue.Queue[Tuple[str, List[str]]]" = queue.Queue(maxsize=max_queue)
        self._stop_event = threading.Event()
        self._thread = threading.Thread(target=self._worker, daemon=True, name="AsyncNotifierWorker")
        self._swallow = bool(swallow_exceptions)
        self._thread.start()
        # ensure we stop cleanly
        atexit.register(self.stop)

    def send_async(self, text: str, channels: Optional[List[str]] = None) -> bool:
        """
        Enqueue a message for background sending.
        Returns True if enqueued, False if dropped (queue full).
        """
        chan = channels or (["telegram"] if self._mgr.telegram_token and self._mgr.telegram_chat_id else [])
        item = (text, chan)
        try:
            self._q.put_nowait(item)
            return True
        except queue.Full:
            # drop message to avoid blocking main thread
            return False

    def _worker(self):
        while not self._stop_event.is_set():
            try:
                try:
                    text, chans = self._q.get(timeout=0.5)
                except queue.Empty:
                    continue
                try:
                    # call the synchronous NotificationManager send (it uses requests)
                    self._mgr.send(text, channels=chans)
                except Exception as e:
                    if not self._swallow:
                        raise
                    # otherwise ignore/send-on-failure
                finally:
                    try:
                        self._q.task_done()
                    except Exception:
                        pass
            except Exception:
                # guard against thread crashing
                time.sleep(0.2)
                continue

    def stop(self, timeout: float = 2.0) -> None:
        """
        Stop the worker thread (signal and join).
        """
        if self._stop_event.is_set():
            return
        self._stop_event.set()
        # wake thread if waiting
        try:
            # put a sentinel if thread is waiting (best-effort)
            self._q.put_nowait(("", []))
        except Exception:
            pass
        # join
        try:
            self._thread.join(timeout=timeout)
        except Exception:
            pass

    # convenience for users
    @classmethod
    def from_env(cls, dry_run_if_no_creds: bool = True, **kwargs) -> "AsyncNotifier":
        token = kwargs.get("telegram_token") or os.environ.get("TELEGRAM_BOT_TOKEN")
        chat = kwargs.get("telegram_chat_id") or os.environ.get("TELEGRAM_CHAT_ID")
        slack = kwargs.get("slack_webhook") or os.environ.get("SLACK_WEBHOOK_URL")
        dry = kwargs.get("dry_run", False)
        if dry_run_if_no_creds and not (token and chat) and not slack:
            dry = True
        return cls(telegram_token=token, telegram_chat_id=chat, slack_webhook=slack, dry_run=dry)
