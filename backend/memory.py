import json
from datetime import datetime

from .database import get_db, rows_to_dicts
from .llm import extract_json_prompt


def get_memories(participant_id: int, limit: int = 8) -> list[dict]:
    with get_db() as conn:
        rows = conn.execute(
            """SELECT id, kind, content, importance, created_at
               FROM memories WHERE participant_id = ?
               ORDER BY importance DESC, updated_at DESC LIMIT ?""",
            (participant_id, limit),
        ).fetchall()
    return rows_to_dicts(rows)


def format_memories(memories: list[dict]) -> str:
    if not memories:
        return "Memories: (none yet — this may be your first conversation with them)."
    lines = [f"- ({m['kind']}) {m['content']}" for m in memories]
    return "Your memories about them:\n" + "\n".join(lines)


def _upsert_memory(conn, participant_id: int, kind: str, content: str, importance: int) -> None:
    existing = conn.execute(
        """SELECT id FROM memories
           WHERE participant_id = ? AND kind = ? AND lower(content) = lower(?)""",
        (participant_id, kind, content),
    ).fetchone()
    now = datetime.utcnow().isoformat(timespec="seconds")
    if existing:
        conn.execute(
            "UPDATE memories SET importance = ?, updated_at = ? WHERE id = ?",
            (max(importance, 1), now, existing["id"]),
        )
    else:
        conn.execute(
            """INSERT INTO memories (participant_id, kind, content, importance, created_at, updated_at)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (participant_id, kind, content, importance, now, now),
        )


def extract_memories(participant_id: int) -> list[str]:
    """Ask the LLM to pull lasting facts from recent chats; store what matters."""
    with get_db() as conn:
        rows = conn.execute(
            """SELECT m.role, m.content FROM messages m
               JOIN conversations c ON c.id = m.conversation_id
               WHERE c.participant_id = ?
               ORDER BY m.id DESC LIMIT 40""",
            (participant_id,),
        ).fetchall()
        existing = conn.execute(
            "SELECT kind, content FROM memories WHERE participant_id = ?",
            (participant_id,),
        ).fetchall()

    messages = list(reversed([dict(r) for r in rows]))
    if len(messages) < 4:
        return []

    transcript = "\n".join(f"{m['role']}: {m['content']}" for m in messages)
    known = "\n".join(f"- ({r['kind']}) {r['content']}" for r in existing) or "(none)"

    prompt = f"""Extract lasting, personal memories worth remembering across future conversations.

Known memories (do not duplicate):
{known}

Transcript:
{transcript}

Return a JSON array. Each item: {{"kind": "fact"|"preference"|"summary"|"event", "content": "...", "importance": 1-5}}.
Only include genuinely useful details (names, preferences, life events, recurring topics, opinions, relationship context).
Max 4 items. If nothing worth keeping, return []."""

    try:
        raw = extract_json_prompt(prompt)
        start, end = raw.find("["), raw.rfind("]")
        if start == -1 or end == -1:
            return []
        items = json.loads(raw[start : end + 1])
    except Exception:
        return []

    saved = []
    valid_kinds = {"fact", "preference", "summary", "event"}
    with get_db() as conn:
        for item in items[:4]:
            if not isinstance(item, dict):
                continue
            kind = str(item.get("kind", "fact")).lower()
            content = str(item.get("content", "")).strip()
            if kind not in valid_kinds or not content or len(content) > 400:
                continue
            try:
                importance = max(1, min(5, int(item.get("importance", 3))))
            except (TypeError, ValueError):
                importance = 3
            _upsert_memory(conn, participant_id, kind, content, importance)
            saved.append(content)
    return saved
