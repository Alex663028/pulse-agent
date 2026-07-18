"""Telegram gateway — polling-based Bot API bridge.

Requires ``TELEGRAM_BOT_TOKEN`` in ``~/.pulse/.env`` or envar.
Uses only the stdlib + ``requests`` (no heavy framework).
"""

from __future__ import annotations

import json
import logging
import time
import urllib.request
import urllib.error

from pulse.cli.runtime import Runtime
from pulse.gateways.base import Gateway

logger = logging.getLogger(__name__)

API = "https://api.telegram.org/bot{token}/{method}"


def _post(url: str, data: dict) -> dict:
    req = urllib.request.Request(
        url,
        data=json.dumps(data).encode(),
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=10) as resp:
        return json.loads(resp.read())


def _get(url: str) -> dict:
    with urllib.request.urlopen(url, timeout=15) as resp:
        return json.loads(resp.read())


class TelegramGateway(Gateway):
    """Polls the Telegram Bot API long-poll endpoint and routes messages through the orchestrator."""

    name = "telegram"

    def __init__(self, token: str = ""):
        self._token = token
        self._active = False
        self._offset = 0

    def _call(self, method: str, data: dict | None = None) -> dict:
        """Invoke a Telegram Bot API ``method`` with optional JSON payload and return the parsed response."""
        return _post(API.format(token=self._token, method=method), data or {})

    def start(self, runtime: Runtime) -> None:
        """Resolve the bot token, then run a long-poll loop dispatching messages through ``runtime``."""
        if not self._token:
            # try env
            import os

            self._token = os.environ.get("TELEGRAM_BOT_TOKEN", "")
        if not self._token:
            # try .env
            from pulse.config.settings import load_env

            env = load_env(runtime.settings)
            self._token = env.get("TELEGRAM_BOT_TOKEN", "")
        if not self._token:
            logger.warning("[telegram] no TELEGRAM_BOT_TOKEN — gateway disabled")
            return
        me = self._call("getMe")
        logger.info(
            "[telegram] connected as @%s", me.get("result", {}).get("username", "?")
        )

        self._active = True
        while self._active:
            try:
                updates = self._call(
                    "getUpdates", {"offset": self._offset, "timeout": 30}
                )
            except (urllib.error.URLError, OSError, KeyError, ValueError):
                time.sleep(3)
                continue
            for upd in updates.get("result", []):
                self._offset = max(self._offset, upd["update_id"] + 1)
                msg = upd.get("message") or upd.get("channel_post")
                if not msg:
                    continue
                chat_id = msg["chat"]["id"]
                text = (msg.get("text") or "").strip()
                if not text:
                    continue
                self._call("sendChatAction", {"chat_id": chat_id, "action": "typing"})
                try:
                    res = runtime.orchestrator.run(text, session_id=f"tg:{chat_id}")
                except (RuntimeError, OSError, ValueError) as e:
                    self._send(chat_id, f"error: {e}")
                    continue
                if res.success:
                    self._send(chat_id, res.answer or "(empty)")
                    if res.candidate_skill:
                        self._send(
                            chat_id,
                            f"↳ proposed skill: {res.candidate_skill} (eval: pulse skills eval {res.candidate_skill})",
                        )
                else:
                    self._send(chat_id, f"error: {res.error or 'failed'}")
            time.sleep(0.5)

    def _send(self, chat_id: int, text: str) -> None:
        for chunk in self._chunks(text, 4000):
            try:
                self._call("sendMessage", {"chat_id": chat_id, "text": chunk})
            except (urllib.error.URLError, OSError):
                pass

    @staticmethod
    def _chunks(text: str, size: int) -> list[str]:
        if len(text) <= size:
            return [text]
        paras = text.split("\n\n")
        out, buf = [], ""
        for p in paras:
            # if a single paragraph exceeds size, split it further
            while len(p) > size:
                if buf:
                    out.append(buf)
                    buf = ""
                out.append(p[:size])
                p = p[size:]
            if not p:
                continue
            if len(buf) + len(p) + 2 <= size:
                buf = (buf + "\n\n" + p).strip()
            else:
                if buf:
                    out.append(buf)
                buf = p
        if buf:
            out.append(buf)
        return out or [text[:size]]

    def stop(self) -> None:
        """Signal the polling loop to exit."""
        self._active = False
