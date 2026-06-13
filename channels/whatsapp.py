"""channels/whatsapp.py — Twilio WhatsApp adapter (STRETCH, not implemented).

Sketch for whoever wires it up:
  Outbound: POST https://api.twilio.com/2010-04-01/Accounts/{SID}/Messages.json
            with From="whatsapp:<TWILIO_WHATSAPP_FROM>", To="whatsapp:<TWILIO_WHATSAPP_TO>",
            Body=text  (HTTP basic auth SID/AUTH_TOKEN; `twilio` SDK or plain requests).
  Inbound:  Twilio POSTs incoming WhatsApp messages to a webhook you host (Flask)
            at a public URL (e.g. ngrok). The webhook parks the reply text on a
            thread-safe queue; ask() sends, then blocks on queue.get(timeout=...).
  Needs:    pip install twilio flask, a Twilio WhatsApp sandbox, a public webhook URL.
            Same Channel contract as console/discord — drop-in once implemented.
"""
from __future__ import annotations

from typing import Optional

from .base import Channel


class WhatsAppChannel(Channel):
    name = "whatsapp"

    def __init__(self) -> None:
        raise NotImplementedError(
            "WhatsApp is a documented stretch adapter. Use --channel console or discord. "
            "See channels/whatsapp.py docstring and the README."
        )

    def send(self, text: str) -> None:  # pragma: no cover
        raise NotImplementedError

    def ask(self, text: str, timeout: Optional[float] = None) -> str:  # pragma: no cover
        raise NotImplementedError
