"""channels/base.py — the messaging-channel contract the config agent uses.

The agent only needs one primitive: ask(question) -> the insurer's reply. Each
adapter (console, Discord, WhatsApp) hides its transport behind this so the
agent's confirm-then-apply loop stays synchronous and channel-agnostic.
"""
from __future__ import annotations

import abc
from typing import Optional


class Channel(abc.ABC):
    name = "base"

    @abc.abstractmethod
    def send(self, text: str) -> None:
        """Deliver a one-way message to the insurer."""

    @abc.abstractmethod
    def ask(self, text: str, timeout: Optional[float] = None) -> str:
        """Send `text` and block until the insurer replies; return the reply
        (empty string on timeout)."""

    def close(self) -> None:  # optional cleanup
        pass
