from fastapi import APIRouter, BackgroundTasks, HTTPException
from pydantic import BaseModel, Field

from ..chat_service import (
    generate_reply,
    get_or_create_conversation,
    handle_user_message,
)
from ..database import get_db, rows_to_dicts
from ..memory import extract_memories, get_memories

router = APIRouter(prefix="/api", tags=["chat"])


class MessageIn(BaseModel):
    content: str = Field(min_length=1, max_length=4000)


@router.get("/participants/{participant_id}/conversation")
def get_conversation(participant_id: int):
    with get_db() as conn:
        row = conn.execute(
            "SELECT id FROM participants WHERE id = ?", (participant_id,)
        ).fetchone()
    if not row:
        raise HTTPException(404, "Participant not found")
    return get_or_create_conversation(participant_id)


@router.get("/conversations/{conversation_id}/messages")
def list_messages(conversation_id: int, after_id: int = 0):
    with get_db() as conn:
        exists = conn.execute(
            "SELECT id FROM conversations WHERE id = ?", (conversation_id,)
        ).fetchone()
        if not exists:
            raise HTTPException(404, "Conversation not found")
        rows = conn.execute(
            """SELECT id, role, content, created_at FROM messages
               WHERE conversation_id = ? AND id > ?
               ORDER BY id ASC""",
            (conversation_id, after_id),
        ).fetchall()
    return rows_to_dicts(rows)


@router.post("/conversations/{conversation_id}/messages")
async def send_message(conversation_id: int, body: MessageIn, background_tasks: BackgroundTasks):
    try:
        reply = await handle_user_message(conversation_id, body.content)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(503, str(exc)) from exc

    with get_db() as conn:
        row = conn.execute(
            """SELECT c.id AS conv_id, c.channel, c.participant_id,
                      p.name, p.contact_ref, p.opted_in, p.notes, p.timezone
               FROM conversations c
               JOIN participants p ON p.id = c.participant_id
               WHERE c.id = ?""",
            (conversation_id,),
        ).fetchone()
    if row:
        participant = {
            "id": row["participant_id"],
            "name": row["name"],
            "contact_ref": row["contact_ref"],
            "opted_in": row["opted_in"],
            "notes": row["notes"],
            "timezone": row["timezone"],
        }
        conversation = {"id": row["conv_id"], "channel": row["channel"]}
        from ..delivery import deliver

        delivery = await deliver(participant, conversation, reply["content"])
        reply["delivery"] = delivery
        background_tasks.add_task(extract_memories, row["participant_id"])

    return {"user_saved": True, "kile_reply": reply}


@router.post("/conversations/{conversation_id}/regenerate")
def regenerate(conversation_id: int):
    with get_db() as conn:
        row = conn.execute(
            """SELECT id FROM messages
               WHERE conversation_id = ? AND role = 'kile'
               ORDER BY id DESC LIMIT 1""",
            (conversation_id,),
        ).fetchone()
        if row:
            conn.execute("DELETE FROM messages WHERE id = ?", (row["id"],))
    try:
        reply = generate_reply(conversation_id)
    except RuntimeError as exc:
        raise HTTPException(503, str(exc)) from exc
    return reply


@router.get("/participants/{participant_id}/memories")
def list_memories(participant_id: int):
    return get_memories(participant_id, limit=50)
