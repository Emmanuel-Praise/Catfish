from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from ..chat_service import open_proactive_message
from ..config import settings
from ..database import get_db, rows_to_dicts

router = APIRouter(prefix="/api/proactive", tags=["proactive"])


class ProactiveIn(BaseModel):
    participant_id: int


def _in_quiet_hours(now: datetime) -> bool:
    hour = now.hour
    start, end = settings.proactive_quiet_start, settings.proactive_quiet_end
    if start == end:
        return False
    if start > end:
        return hour >= start or hour < end
    return start <= hour < end


def _cooldown_active(participant_id: int) -> bool:
    cutoff = (datetime.utcnow() - timedelta(hours=settings.proactive_cooldown_hours)).isoformat(
        timespec="seconds"
    )
    with get_db() as conn:
        row = conn.execute(
            """SELECT 1 FROM proactive_log
               WHERE participant_id = ? AND created_at >= ? LIMIT 1""",
            (participant_id, cutoff),
        ).fetchone()
    return row is not None


@router.post("/trigger")
async def trigger_proactive(body: ProactiveIn):
    with get_db() as conn:
        participant = conn.execute(
            "SELECT * FROM participants WHERE id = ?", (body.participant_id,)
        ).fetchone()
    if not participant:
        raise HTTPException(404, "Participant not found")
    if not participant["opted_in"]:
        raise HTTPException(403, "Participant has not opted in")

    now = datetime.now(timezone.utc).astimezone().replace(tzinfo=None)
    if _in_quiet_hours(now):
        raise HTTPException(429, "Quiet hours — not sending proactive messages now")
    if _cooldown_active(body.participant_id):
        raise HTTPException(429, "Cooldown active — already messaged recently")

    # WhatsApp only allows free-form messages within 24h of the person's last
    # inbound message — outside that window a proactive send risks a ban.
    if participant["contact_ref"] and settings.message_channel == "whatsapp":
        last_active = participant["last_active_at"]
        if not last_active:
            raise HTTPException(
                429,
                "WhatsApp 24-hour window: this person has never messaged Kile first — "
                "wait for their inbound message before initiating",
            )
        try:
            last = datetime.fromisoformat(last_active)
        except ValueError:
            last = None
        if last is None or now - last > timedelta(hours=24):
            raise HTTPException(
                429,
                "WhatsApp 24-hour window: their last message was over 24h ago — "
                "free-form proactive is not allowed until they message again",
            )

    try:
        message = open_proactive_message(body.participant_id)
    except RuntimeError as exc:
        raise HTTPException(503, str(exc)) from exc

    from ..delivery import deliver

    conversation = {"id": message["conversation_id"], "channel": message.get("channel", "web")}
    delivery = await deliver(dict(participant), conversation, message["content"])
    message["delivery"] = delivery
    return message


@router.get("/log")
def proactive_log(limit: int = 50):
    with get_db() as conn:
        rows = conn.execute(
            """SELECT pl.*, p.name AS participant_name
               FROM proactive_log pl
               JOIN participants p ON p.id = pl.participant_id
               ORDER BY pl.id DESC LIMIT ?""",
            (min(limit, 200),),
        ).fetchall()
    return rows_to_dicts(rows)
