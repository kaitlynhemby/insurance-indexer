"""channels — pluggable messaging adapters for the config agent.

get_channel(name) returns a Channel. Unknown names or missing credentials fall
back to the console adapter (with a printed warning) so a demo never hard-fails.
Channel selection: explicit name > $INDEXER_CHANNEL > "console".
"""
from __future__ import annotations

import os
from typing import Optional

from .base import Channel
from .console import ConsoleChannel


def get_channel(name: Optional[str] = None) -> Channel:
    name = (name or os.environ.get("INDEXER_CHANNEL") or "console").lower()
    if name == "console":
        return ConsoleChannel()
    if name == "discord":
        try:
            from .discord_channel import DiscordChannel
            return DiscordChannel()
        except Exception as exc:
            print(f"[channel] Discord unavailable ({exc}); falling back to console.")
            return ConsoleChannel()
    if name == "whatsapp":
        try:
            from .whatsapp import WhatsAppChannel
            return WhatsAppChannel()
        except Exception as exc:
            print(f"[channel] WhatsApp unavailable ({exc}); falling back to console.")
            return ConsoleChannel()
    print(f"[channel] unknown channel {name!r}; using console.")
    return ConsoleChannel()
