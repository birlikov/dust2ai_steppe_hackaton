-- Initial schema. Migration runner applies files in numeric order.

CREATE TABLE IF NOT EXISTS schema_version (
    version INTEGER PRIMARY KEY,
    applied_at TEXT NOT NULL
);

-- Conversation sessions (channel-agnostic)
CREATE TABLE IF NOT EXISTS sessions (
    id TEXT PRIMARY KEY,
    channel TEXT NOT NULL,                 -- telegram | whatsapp | instagram
    external_id TEXT NOT NULL,             -- platform chat/user id
    workflow_id TEXT,
    state TEXT NOT NULL DEFAULT '{}',      -- JSON blob
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_sessions_external
    ON sessions(channel, external_id);

-- aiogram FSM storage backing
CREATE TABLE IF NOT EXISTS fsm_state (
    bot_id INTEGER NOT NULL,
    chat_id INTEGER NOT NULL,
    user_id INTEGER NOT NULL,
    state TEXT,
    data TEXT NOT NULL DEFAULT '{}',       -- JSON blob
    PRIMARY KEY (bot_id, chat_id, user_id)
);

-- Idempotency cache for mutating tool calls
CREATE TABLE IF NOT EXISTS idempotency_keys (
    key TEXT PRIMARY KEY,
    scope TEXT NOT NULL,
    result TEXT NOT NULL,                  -- JSON blob
    created_at TEXT NOT NULL,
    expires_at TEXT
);
CREATE INDEX IF NOT EXISTS idx_idempotency_scope
    ON idempotency_keys(scope, created_at);

-- Append-only audit log (every tool call, message, error)
CREATE TABLE IF NOT EXISTS audit_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ts TEXT NOT NULL,
    session_id TEXT,
    workflow_id TEXT,
    actor TEXT NOT NULL,                   -- user | agent | tool | system
    event_type TEXT NOT NULL,              -- inbound | tool_call | tool_result | outbound | error
    payload TEXT NOT NULL DEFAULT '{}'     -- JSON blob
);
CREATE INDEX IF NOT EXISTS idx_audit_session
    ON audit_log(session_id, ts);
CREATE INDEX IF NOT EXISTS idx_audit_workflow
    ON audit_log(workflow_id, ts);
