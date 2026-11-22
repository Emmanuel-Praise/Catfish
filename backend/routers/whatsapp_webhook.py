"""Meta Cloud API webhooks.

GET  /api/whatsapp/webhook  — verification handshake (configure in Meta console)
POST /api/whatsapp/webhook  — inbound messages; replies are sent back async
"""

import hashlib
import hmac
import logging
import random

from fastapi import APIRouter, BackgroundTasks, HTTPException, Query, Request

from ..chat_service import generate_reply, get_or_create_conversation
from ..config import settings
from ..database import get_db
from ..delivery import deliver

logger = logging.getLogger("kile.webhook")
router = APIRouter(prefix="/api/whatsapp", tags=["whatsapp"])

# If reply generation fails, Kile sends this instead of going silent —
# a real person would type "hold on", not vanish.
_BUSY_LINES = [
    "Hold on a sec, my network is bad",
    "One sec, I'm coming",
    "Sorry, my network is acting up. Say that again?",
]


@router.get("/webhook")
def verify(
    mode: str = Query(default="", alias="hub.mode"),
    token: str = Query(default="", alias="hub.verify_token"),
    challenge: str = Query(default="", alias="hub.challenge"),
):
    if mode == "subscribe" and token and hmac.compare_digest(token, settings.whatsapp_verify_token):
        return int(challenge) if challenge.isdigit() else challenge
    raise HTTPException(403, "Verification failed")


@router.post("/webhook")
async def inbound(request: Request, background_tasks: BackgroundTasks):
    payload = await request.json()

    if settings.whatsapp_app_secret:
        signature = request.headers.get("X-Hub-Signature-256", "")
        body = await request.body()
        expected = "sha256=" + hmac.new(
            settings.whatsapp_app_secret.encode(), body, hashlib.sha256
        ).hexdigest()
        if not hmac.compare_digest(signature, expected):
            raise HTTPException(401, "Invalid signature")

    for event in _extract_messages(payload):
        background_tasks.add_task(
            process_inbound_async, event["from"], event["text"], event.get("name")
        )
    return {"status": "received"}


def _extract_messages(payload: dict) -> list[dict]:
    events = []
    for entry in payload.get("entry", []):
        for change in entry.get("changes", []):
            value = change.get("value", {})
            contacts = {c.get("wa_id"): c.get("profile", {}).get("name") for c in value.get("contacts", [])}
            for msg in value.get("messages", []):
                if msg.get("type") != "text":
                    continue
                sender = msg.get("from", "")
                events.append(
                    {
                        "from": sender,
                        "text": msg.get("text", {}).get("body", ""),
                        "name": contacts.get(sender),
                    }
                )
    return events


async def process_inbound_async(sender: str, text: str, name: str | None) -> None:
    """Save inbound msg, pause like a real person, generate reply, deliver."""
    import asyncio

    from starlette.concurrency import run_in_threadpool

    from ..chat_service import (
        _save_message,
        compute_reply_delay,
        generate_reply,
        get_or_create_conversation,
    )
    from ..memory import extract_memories

    text = (text or "").strip()
    if not text:
        return

    def _receive():
        digits = "".join(ch for ch in sender if ch.isdigit())
        with get_db() as conn:
            participant = conn.execute(
                "SELECT * FROM participants WHERE replace(replace(contact_ref, '+', ''), ' ', '') LIKE ?",
                (f"%{digits}",),
            ).fetchone()
            if participant:
                participant = dict(participant)
            else:
                cursor = conn.execute(
                    """INSERT INTO participants (name, contact_ref, opted_in, notes)
                       VALUES (?, ?, 1, 'Auto-created from WhatsApp inbound')""",
                    (name or f"WhatsApp {sender}", digits),
                )
                pid = cursor.lastrowid
                participant = dict(
                    conn.execute("SELECT * FROM participants WHERE id = ?", (pid,)).fetchone()
                )

        conversation = get_or_create_conversation(participant["id"], channel="whatsapp")
        with get_db() as conn:
            conn.execute(
                "UPDATE conversations SET channel = 'whatsapp' WHERE id = ?",
                (conversation["id"],),
            )
        conversation["channel"] = "whatsapp"
        _save_message(conversation["id"], "user", text)
        return participant, conversation

    def _reply(payload):
        participant, conversation = payload
        reply = generate_reply(conversation["id"])
        extract_memories(participant["id"])
        return participant, conversation, reply

    try:
        participant, conversation = await run_in_threadpool(_receive)
    except Exception:
        logger.exception("Inbound save failed for %s", sender)
        return

    await asyncio.sleep(compute_reply_delay(text))

    try:
        participant, conversation, reply = await run_in_threadpool(_reply, (participant, conversation))
    except Exception:
        logger.exception("Inbound processing failed for %s", sender)
        try:
            filler = random.choice(_BUSY_LINES)
            await run_in_threadpool(_save_message, conversation["id"], "kile", filler)
            await deliver(participant, conversation, filler)
        except Exception:
            logger.exception("Filler delivery failed for %s", sender)
        return

    try:
        await deliver(participant, conversation, reply["content"])
    except Exception:
        logger.exception("Delivery failed for participant %s", participant["id"])


@router.get("/status")
def whatsapp_status():
    from ..channels import get_channel

    channel = get_channel("whatsapp")
    available = channel.is_available()
    return {
        "configured": available,
        "api_version": settings.whatsapp_api_version,
        "message_channel": settings.message_channel,
        "webhook_url": "/api/whatsapp/webhook",
    }
