"""Outbound delivery: routes Kile's replies to the right channel."""

import logging

from .channels import get_channel
from .config import settings

logger = logging.getLogger("kile.delivery")


def should_deliver_whatsapp(participant: dict, conversation: dict) -> bool:
    # MESSAGE_CHANNEL=log is a hard kill-switch (simulator mode) — never hit
    # the real Graph API, regardless of which channel the conversation is on.
    if settings.message_channel != "whatsapp":
        return False
    return bool(participant.get("contact_ref"))


async def deliver(participant: dict, conversation: dict, text: str) -> dict:
    """Send `text` to the participant if their channel requires it.

    Never raises — delivery failures are logged, not propagated.
    """
    if not should_deliver_whatsapp(participant, conversation):
        channel = get_channel("web")
        return await channel.send(participant, text)

    channel = get_channel("whatsapp")
    result = await channel.send(participant, text)
    if result.get("status") != "sent":
        logger.warning(
            "WhatsApp delivery failed for participant %s: %s",
            participant.get("id"),
            result.get("error"),
        )
    return result
