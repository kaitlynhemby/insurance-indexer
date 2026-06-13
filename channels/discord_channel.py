"""channels/discord_channel.py — two-way Discord over the REST API via requests.

No discord.py / websocket gateway: the agent's flow is a synchronous
ask→wait-for-reply loop, so we send with POST and receive by polling
GET .../messages?after=<cursor>. Needs DISCORD_BOT_TOKEN + DISCORD_CHANNEL_ID
in .env, the bot in the guild with View Channel / Send Messages / Read Message
History, and the MESSAGE CONTENT INTENT enabled (else replies arrive blank).
"""
from __future__ import annotations

import os
import time
from typing import Optional

import requests

from .base import Channel

API = "https://discord.com/api/v10"


class DiscordChannel(Channel):
    name = "discord"

    def __init__(self) -> None:
        self.token = os.environ.get("DISCORD_BOT_TOKEN")
        self.channel_id = os.environ.get("DISCORD_CHANNEL_ID")
        if not self.token or not self.channel_id:
            raise RuntimeError("DISCORD_BOT_TOKEN and DISCORD_CHANNEL_ID must be set in .env")
        self.poll = float(os.environ.get("DISCORD_POLL_INTERVAL", "2"))
        self._headers = {"Authorization": f"Bot {self.token}", "Content-Type": "application/json"}
        self._bot_id = self._request("GET", "/users/@me")["id"]
        recent = self._request("GET", f"/channels/{self.channel_id}/messages", params={"limit": 1})
        self._cursor = recent[0]["id"] if recent else None  # ignore history before we start

    def _request(self, method: str, path: str, **kw):
        url = f"{API}{path}"
        for _ in range(4):
            r = requests.request(method, url, headers=self._headers, timeout=30, **kw)
            if r.status_code == 429:  # rate limited — honor Retry-After and retry
                time.sleep(float(r.headers.get("Retry-After", "1")) + 0.5)
                continue
            r.raise_for_status()
            return r.json()
        r.raise_for_status()
        return r.json()

    def send(self, text: str) -> None:
        msg = self._request(
            "POST", f"/channels/{self.channel_id}/messages", json={"content": text[:1900]}
        )
        self._cursor = msg["id"]  # don't treat our own message as a reply

    def ask(self, text: str, timeout: Optional[float] = None) -> str:
        self.send(text)
        deadline = None if timeout is None else time.time() + timeout
        empty_streak = 0
        while True:
            if deadline and time.time() > deadline:
                return ""
            time.sleep(self.poll)
            params = {"limit": 20}
            if self._cursor:
                params["after"] = self._cursor
            try:
                msgs = self._request("GET", f"/channels/{self.channel_id}/messages", params=params)
            except requests.RequestException as exc:
                raise RuntimeError(f"Discord poll failed: {exc}") from exc
            for m in reversed(msgs):  # API returns newest-first; process oldest-first
                self._cursor = m["id"]
                author = m.get("author", {})
                if author.get("bot") or author.get("id") == self._bot_id:
                    continue
                content = (m.get("content") or "").strip()
                if not content:
                    empty_streak += 1
                    if empty_streak >= 3:
                        raise RuntimeError(
                            "Discord replies have empty content — enable the MESSAGE CONTENT "
                            "INTENT for the bot in the Developer Portal."
                        )
                    continue
                return content
