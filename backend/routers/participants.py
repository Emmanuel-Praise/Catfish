from datetime import datetime
from typing import Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from ..chat_service import get_or_create_conversation
from ..database import get_db, rows_to_dicts

router = APIRouter(prefix="/api/participants", tags=["participants"])


class ParticipantIn(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    contact_ref: Optional[str] = Field(default=None, max_length=200)
    opted_in: bool = True
    notes: str = Field(default="", max_length=2000)
    timezone: str = Field(default="UTC", max_length=60)


class ParticipantPatch(BaseModel):
    name: Optional[str] = Field(default=None, min_length=1, max_length=120)
    contact_ref: Optional[str] = Field(default=None, max_length=200)
    opted_in: Optional[bool] = None
    notes: Optional[str] = Field(default=None, max_length=2000)
    timezone: Optional[str] = Field(default=None, max_length=60)


class BulkIn(BaseModel):
    text: str = Field(min_length=1, max_length=20000)


@router.post("/bulk", status_code=201)
def bulk_create_participants(body: BulkIn):
    """Add many contacts at once — numbers separated by newlines, commas, or spaces."""
    import re

    tokens = re.split(r"[\s,;]+", body.text.strip())
    created: list[dict] = []
    skipped: list[dict] = []

    with get_db() as conn:
        existing = set()
        for row in conn.execute(
            "SELECT contact_ref FROM participants WHERE contact_ref IS NOT NULL"
        ):
            digits = "".join(ch for ch in (row["contact_ref"] or "") if ch.isdigit())
            if digits:
                existing.add(digits)

        for token in tokens:
            raw = token.strip()
            if not raw:
                continue
            digits = "".join(ch for ch in raw if ch.isdigit())
            if len(digits) < 8:
                skipped.append({"value": raw, "reason": "not a valid number"})
                continue
            if digits in existing:
                skipped.append({"value": raw, "reason": "duplicate"})
                continue
            contact = "+" + digits
            cursor = conn.execute(
                """INSERT INTO participants (name, contact_ref, opted_in, notes)
                   VALUES (?, ?, 1, 'Added in bulk')""",
                (contact, contact),
            )
            row = conn.execute(
                "SELECT * FROM participants WHERE id = ?", (cursor.lastrowid,)
            ).fetchone()
            created.append(dict(row))
            existing.add(digits)

    return {"created": created, "skipped": skipped}


@router.get("")
def list_participants():
    with get_db() as conn:
        rows = conn.execute(
            """SELECT p.*,
                      (SELECT COUNT(*) FROM conversations c WHERE c.participant_id = p.id)
                          AS conversation_count,
                      (SELECT COUNT(*) FROM memories m WHERE m.participant_id = p.id)
                          AS memory_count
               FROM participants p
               ORDER BY COALESCE(p.last_active_at, p.created_at) DESC"""
        ).fetchall()
    return rows_to_dicts(rows)


@router.post("", status_code=201)
def create_participant(body: ParticipantIn):
    with get_db() as conn:
        cursor = conn.execute(
            """INSERT INTO participants (name, contact_ref, opted_in, notes, timezone)
               VALUES (?, ?, ?, ?, ?)""",
            (body.name.strip(), body.contact_ref, int(body.opted_in), body.notes, body.timezone),
        )
        participant_id = cursor.lastrowid
        row = conn.execute(
            "SELECT * FROM participants WHERE id = ?", (participant_id,)
        ).fetchone()
    conversation = get_or_create_conversation(participant_id)
    data = dict(row)
    data["conversation_id"] = conversation["id"]
    return data


@router.get("/{participant_id}")
def get_participant(participant_id: int):
    with get_db() as conn:
        row = conn.execute(
            "SELECT * FROM participants WHERE id = ?", (participant_id,)
        ).fetchone()
    if not row:
        raise HTTPException(404, "Participant not found")
    return dict(row)


@router.patch("/{participant_id}")
def update_participant(participant_id: int, body: ParticipantPatch):
    fields = body.model_dump(exclude_unset=True)
    if not fields:
        raise HTTPException(400, "No fields to update")
    with get_db() as conn:
        existing = conn.execute(
            "SELECT id FROM participants WHERE id = ?", (participant_id,)
        ).fetchone()
        if not existing:
            raise HTTPException(404, "Participant not found")
        sets = ", ".join(f"{k} = ?" for k in fields)
        values = [int(v) if k == "opted_in" and isinstance(v, bool) else v for k, v in fields.items()]
        conn.execute(
            f"UPDATE participants SET {sets} WHERE id = ?",
            (*values, participant_id),
        )
        row = conn.execute(
            "SELECT * FROM participants WHERE id = ?", (participant_id,)
        ).fetchone()
    return dict(row)


@router.delete("/{participant_id}", status_code=204)
def delete_participant(participant_id: int):
    with get_db() as conn:
        cursor = conn.execute("DELETE FROM participants WHERE id = ?", (participant_id,))
        if cursor.rowcount == 0:
            raise HTTPException(404, "Participant not found")
