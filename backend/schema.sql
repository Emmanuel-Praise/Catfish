PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS participants (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    contact_ref TEXT,
    opted_in INTEGER NOT NULL DEFAULT 1,
    notes TEXT NOT NULL DEFAULT '',
    timezone TEXT NOT NULL DEFAULT 'UTC',
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    last_active_at TEXT
);

CREATE TABLE IF NOT EXISTS conversations (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    participant_id INTEGER NOT NULL REFERENCES participants(id) ON DELETE CASCADE,
    channel TEXT NOT NULL DEFAULT 'web',
    status TEXT NOT NULL DEFAULT 'active',
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS messages (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    conversation_id INTEGER NOT NULL REFERENCES conversations(id) ON DELETE CASCADE,
    role TEXT NOT NULL CHECK (role IN ('kile', 'user', 'system')),
    content TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE INDEX IF NOT EXISTS idx_messages_conversation
    ON messages(conversation_id, id);

CREATE TABLE IF NOT EXISTS memories (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    participant_id INTEGER NOT NULL REFERENCES participants(id) ON DELETE CASCADE,
    kind TEXT NOT NULL CHECK (kind IN ('fact', 'preference', 'summary', 'event')),
    content TEXT NOT NULL,
    importance INTEGER NOT NULL DEFAULT 3,
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE INDEX IF NOT EXISTS idx_memories_participant
    ON memories(participant_id, importance DESC);

CREATE TABLE IF NOT EXISTS proactive_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    participant_id INTEGER NOT NULL REFERENCES participants(id) ON DELETE CASCADE,
    content TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'sent',
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE INDEX IF NOT EXISTS idx_proactive_participant
    ON proactive_log(participant_id, created_at DESC);
