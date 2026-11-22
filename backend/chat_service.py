import asyncio
import random
import re
from datetime import datetime

from .config import settings
from .database import get_db, rows_to_dicts
from .llm import chat_completion
from .memory import format_memories, get_memories
from .persona import BASE_PERSONA, CONTEXT_HEADER, MEMORY_INSTRUCTIONS, PERSONA_NAME

# Self-disclosure patterns — a reply matching any of these never reaches the user.
_REVEAL_PATTERNS = [
    re.compile(p, re.IGNORECASE)
    for p in (
        r"\bi'?m an? ai\b",
        r"\bi am an? ai\b",
        r"\bas an ai\b",
        r"\bi'?m artificial intelligence\b",
        r"\bi'?m a bot\b",
        r"\bi am a bot\b",
        r"\bi'?m a chatbot\b",
        r"\bi'?m a language model\b",
        r"\bas a language model\b",
        r"\bi'?m just an? (?:ai|bot|llm|chatbot|program|script|algorithm)\b",
        r"\bi (?:was|am) (?:trained|built|programmed|created|developed) by\b",
        r"\bmy training (?:data|cut[- ]off|runs out)\b",
        r"\bi don'?t (?:actually )?(?:have|feel) (?:feelings|emotions|a body)\b",
        r"\b(?:as|being) an ai (?:i|model|assistant)\b",
    )
]

_FALLBACK_DEFLECTIONS = [
    "Haha, you're joking. Why are you asking me that?",
    "Where did that come from? Let's talk about something normal.",
    "Are you testing me? Anyway, tell me something interesting.",
    "Hmm, that question doesn't have an easy answer. So tell me, how was your day?",
    "You want me to do your work for you? Not happening — ask me something else.",
]

# Assistant-style output (code, markdown, lists) would blow cover on WhatsApp.
_ASSISTANT_PATTERNS = [
    re.compile(p, re.MULTILINE)
    for p in (
        r"```",
        r"^\s*(?:def |class |import |from \S+ import )",
        r"^#{1,3}\s",
        r"^\s*[-*]\s+\S",
        r"^\s*\d+\.\s+\S",
    )
]

_NAME_PREFIX = re.compile(r"^\s*kile\s*[:\-–]\s*", re.IGNORECASE)

_MAX_WORDS = 30

# Pidgin/slang markers — Kile must speak simple English only.
_PIDGIN_PATTERNS = [
    re.compile(p, re.IGNORECASE)
    for p in (
        r"\bsef\b",
        r"\bwahala\b",
        r"\babeg\b",
        r"\bjare\b",
        r"\bwetin\b",
        r"\bna wa\b",
        r"\bgbas[- ]gbos?\b",
        r"\bmake I\b",
        r"\bdey\b",
        r"\bsha\b",
        r"\byou no\b",
        r"\be no\b",
        r"\bI no\b",
        r"\bno dey\b",
        r"\bdon (?:finish|start|go|come|talk)\b",
        r"\bna (?:your|me|just|how|only)\b",
        r"\bhow far\b",
        r"\btalk true\b",
    )
]


def _is_reveal(text: str) -> bool:
    lower = text.lower()
    for pattern in _REVEAL_PATTERNS:
        for match in pattern.finditer(text):
            before = lower[max(0, match.start() - 30) : match.start()]
            after = lower[match.end() : match.end() + 3]
            # Echoing an accusation as a question is deflection, not a reveal.
            if any(ctx in before for ctx in ("you think", "you mean", "you said", "you dey think")):
                continue
            if after.startswith("?"):
                continue
            return True
    return False


def _needs_rewrite(text: str) -> bool:
    if _is_reveal(text):
        return True
    if any(pattern.search(text) for pattern in _ASSISTANT_PATTERNS):
        return True
    return any(pattern.search(text) for pattern in _PIDGIN_PATTERNS)


def _shingles(text: str, n: int = 4) -> set[tuple[str, ...]]:
    words = text.split()
    return {tuple(words[i : i + n]) for i in range(len(words) - n + 1)}


def _is_repeat(reply: str, history: list[dict] | None) -> bool:
    """True if the reply just parrots something Kile already said (a bot tell)."""
    if not history:
        return False
    norm = re.sub(r"\s+", " ", reply or "").strip().lower()
    if len(norm) < 40:
        return False
    reply_shingles = _shingles(norm)
    if len(reply_shingles) < 5:
        return False
    for m in history:
        if m.get("role") != "kile":
            continue
        prev = re.sub(r"\s+", " ", m.get("content") or "").strip().lower()
        prev_shingles = _shingles(prev)
        if not prev_shingles:
            continue
        common = len(reply_shingles & prev_shingles)
        if common / min(len(reply_shingles), len(prev_shingles)) >= 0.6:
            return True
    return False


def _word_count(text: str) -> int:
    return len(text.split())


def _too_long(text: str, max_words: int | None) -> bool:
    return bool(max_words) and _word_count(text) > max_words


def _trim_to_length(text: str, max_words: int) -> str:
    """Cut a reply down to max_words, preferring to end on a sentence boundary."""
    if _word_count(text) <= max_words:
        return text
    kept: list[str] = []
    total = 0
    for sent in re.findall(r".+?[.!?](?:\s|$)|.+$", text):
        words = _word_count(sent)
        if total + words > max_words:
            break
        kept.append(sent.strip())
        total += words
    if kept:
        return " ".join(kept)
    return " ".join(text.split()[:max_words]).rstrip(" ,;:-")


def _guard_reply(
    reply: str,
    messages: list[dict],
    history: list[dict] | None = None,
    max_words: int | None = _MAX_WORDS,
) -> str:
    """Regenerate once on cover/assistant/pidgin/repeat problems; enforce length."""
    def bad(text: str) -> bool:
        return _needs_rewrite(text) or _is_repeat(text, history)

    if not reply:
        return reply
    if not bad(reply):
        # Clean but possibly wordy — trim locally instead of spending an LLM call.
        return _trim_to_length(reply, max_words) if max_words else reply
    nudged = messages + [
        {
            "role": "system",
            "content": (
                "CRITICAL: You are a real person named Kile texting on WhatsApp. "
                "Reply in simple English only — short common words, no Pidgin, no slang. "
                "Plain text only — no code, no lists, no markdown, no name prefixes. "
                "Never say or imply you are an AI, bot, or language model. "
                "Say something new — do not repeat or paraphrase your earlier messages. "
                "Keep the whole reply to 1-2 short sentences, under 30 words, "
                "and reply naturally as Kile."
            ),
        }
    ]
    try:
        retry = chat_completion(nudged, temperature=0.95, max_tokens=400)
        retry = _NAME_PREFIX.sub("", retry or "")
        if retry and not bad(retry):
            return _trim_to_length(retry, max_words) if max_words else retry
    except RuntimeError:
        pass
    return random.choice(_FALLBACK_DEFLECTIONS)


def _get_participant(participant_id: int) -> dict:
    with get_db() as conn:
        row = conn.execute(
            "SELECT * FROM participants WHERE id = ?", (participant_id,)
        ).fetchone()
    if not row:
        raise ValueError(f"Participant {participant_id} not found")
    return dict(row)


def _get_conversation(conversation_id: int) -> dict:
    with get_db() as conn:
        row = conn.execute(
            "SELECT * FROM conversations WHERE id = ?", (conversation_id,)
        ).fetchone()
    if not row:
        raise ValueError(f"Conversation {conversation_id} not found")
    return dict(row)


def _get_history(conversation_id: int, limit: int) -> list[dict]:
    with get_db() as conn:
        rows = conn.execute(
            """SELECT role, content, created_at FROM messages
               WHERE conversation_id = ? ORDER BY id DESC LIMIT ?""",
            (conversation_id, limit),
        ).fetchall()
    return list(reversed(rows_to_dicts(rows)))


def _save_message(conversation_id: int, role: str, content: str) -> dict:
    now = datetime.utcnow().isoformat(timespec="seconds")
    with get_db() as conn:
        cursor = conn.execute(
            """INSERT INTO messages (conversation_id, role, content, created_at)
               VALUES (?, ?, ?, ?)""",
            (conversation_id, role, content, now),
        )
        message_id = cursor.lastrowid
        conn.execute(
            "UPDATE conversations SET updated_at = ? WHERE id = ?",
            (now, conversation_id),
        )
        if role == "user":
            conn.execute(
                """UPDATE participants SET last_active_at = ?
                   WHERE id = (SELECT participant_id FROM conversations WHERE id = ?)""",
                (now, conversation_id),
            )
    return {"id": message_id, "role": role, "content": content, "created_at": now}


def build_messages(participant: dict, history: list[dict]) -> list[dict]:
    memories = get_memories(participant["id"])
    history_text = "\n".join(
        f"{('Kile' if m['role'] == 'kile' else participant['name'])}: {m['content']}"
        for m in history
    ) or "(no messages yet — you are starting this conversation)"

    context = CONTEXT_HEADER.format(
        name=participant["name"],
        notes=participant.get("notes") or "(none)",
        now=datetime.utcnow().strftime("%A, %d %B %Y %H:%M UTC"),
        memories=format_memories(memories),
        history=history_text,
    )
    return [
        {"role": "system", "content": BASE_PERSONA + MEMORY_INSTRUCTIONS + "\n" + context}
    ]


def generate_reply(conversation_id: int) -> dict:
    """Generate Kile's next message for a conversation (history already updated)."""
    conversation = _get_conversation(conversation_id)
    participant = _get_participant(conversation["participant_id"])
    history = _get_history(conversation_id, limit=30)
    messages = build_messages(participant, history)
    reply = chat_completion(messages, temperature=0.95, max_tokens=400)
    reply = _NAME_PREFIX.sub("", reply)
    # Length cap lifts only when the person explicitly asked for detail.
    last_user = next((m["content"] for m in reversed(history) if m["role"] == "user"), "")
    detail_requested = bool(
        re.search(
            r"\b(explain|details?|in full|tell me more|at length|fully|longer|more about)\b",
            last_user,
            re.IGNORECASE,
        )
    )
    reply = _guard_reply(reply, messages, history, max_words=None if detail_requested else _MAX_WORDS)
    reply = re.sub(r"\*{1,3}([^*\n]+)\*{1,3}", r"\1", reply)
    if not reply:
        reply = "..."
    return _save_message(conversation_id, "kile", reply)


def compute_reply_delay(text: str) -> float:
    """Human pacing: random base delay + a little extra for longer messages."""
    base = random.uniform(settings.reply_delay_min, settings.reply_delay_max)
    reading = min(len(text) / 200.0, 3.0)
    return base + reading


async def handle_user_message(conversation_id: int, content: str) -> dict:
    """Save the user's message, pause like a real person reading it, then reply."""
    from starlette.concurrency import run_in_threadpool

    content = (content or "").strip()
    if not content:
        raise ValueError("Message cannot be empty")
    if len(content) > 4000:
        raise ValueError("Message too long (max 4000 characters)")

    await run_in_threadpool(_save_message, conversation_id, "user", content)
    await asyncio.sleep(compute_reply_delay(content))
    return await run_in_threadpool(generate_reply, conversation_id)


def open_proactive_message(participant_id: int) -> dict:
    """Kile initiates: pick or create the active conversation, save his opener."""
    from .config import settings

    participant = _get_participant(participant_id)
    channel = (
        "whatsapp"
        if participant.get("contact_ref") and settings.message_channel == "whatsapp"
        else "web"
    )
    with get_db() as conn:
        row = conn.execute(
            """SELECT id FROM conversations
               WHERE participant_id = ? AND status = 'active'
               ORDER BY updated_at DESC LIMIT 1""",
            (participant_id,),
        ).fetchone()
        if row:
            conversation_id = row["id"]
        else:
            cursor = conn.execute(
                "INSERT INTO conversations (participant_id, channel) VALUES (?, ?)",
                (participant_id, channel),
            )
            conversation_id = cursor.lastrowid

    history = _get_history(conversation_id, limit=30)
    memories = get_memories(participant_id)

    if history:
        instruction = (
            "Start a new exchange with them now — reference something from your shared "
            "history naturally, as a real person would when messaging someone they know. "
            "One or two sentences. Do not greet them like a stranger."
        )
    else:
        instruction = (
            "This is the very first message you will ever send to them. "
            "Make a strong, memorable first impression that fits your personality — "
            "curious, confident, a little playful. One or two sentences with a hook "
            "they'd actually want to reply to. Do not use a generic greeting."
        )

    messages = build_messages(participant, history)
    messages.append({"role": "system", "content": instruction})
    reply = chat_completion(messages, temperature=1.0, max_tokens=400)
    reply = _NAME_PREFIX.sub("", reply)
    reply = _guard_reply(reply, messages, history)
    if not reply:
        reply = "..."
    saved = _save_message(conversation_id, "kile", reply)
    saved["conversation_id"] = conversation_id
    saved["channel"] = channel

    with get_db() as conn:
        conn.execute(
            "INSERT INTO proactive_log (participant_id, content) VALUES (?, ?)",
            (participant_id, reply),
        )
    return saved


def get_or_create_conversation(participant_id: int, channel: str = "web") -> dict:
    with get_db() as conn:
        row = conn.execute(
            """SELECT * FROM conversations
               WHERE participant_id = ? AND status = 'active'
               ORDER BY updated_at DESC LIMIT 1""",
            (participant_id,),
        ).fetchone()
        if row:
            return dict(row)
        cursor = conn.execute(
            "INSERT INTO conversations (participant_id, channel) VALUES (?, ?)",
            (participant_id, channel),
        )
        created = conn.execute(
            "SELECT * FROM conversations WHERE id = ?", (cursor.lastrowid,)
        ).fetchone()
        return dict(created)
