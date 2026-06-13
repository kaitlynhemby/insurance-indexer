"""channels/console.py — local stdin/stdout channel. Always works offline; the
default, and the channel the tests/demo drive."""
from __future__ import annotations

from typing import Optional

from .base import Channel


class ConsoleChannel(Channel):
    name = "console"

    def send(self, text: str) -> None:
        print(f"\n[agent → insurer] {text}")

    def ask(self, text: str, timeout: Optional[float] = None) -> str:
        self.send(text)
        try:
            return input("[insurer reply] > ").strip()
        except EOFError:
            return ""
