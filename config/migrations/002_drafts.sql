-- Drafts approval queue. Owner approves / edits / rejects via Telegram inline
-- keyboard before any public-facing post or paid-ads creative is published.

CREATE TABLE IF NOT EXISTS drafts (
    id TEXT PRIMARY KEY,                       -- uuid
    channel TEXT NOT NULL,                     -- instagram | google_business | marketing_ad
    kind TEXT NOT NULL,                        -- post | reply | ad_creative | campaign_plan
    payload TEXT NOT NULL,                     -- JSON blob: {caption, imageUrl, scheduledFor, ...}
    status TEXT NOT NULL,                      -- pending | approved | edited | rejected | published
    edit_text TEXT,                            -- owner's edit when status = edited
    reject_reason TEXT,
    external_id TEXT,                          -- e.g. instagram scheduledPostId once scheduled
    idempotency_key TEXT,                      -- for the publish-side write
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_drafts_status_created
    ON drafts(status, created_at);
CREATE INDEX IF NOT EXISTS idx_drafts_channel
    ON drafts(channel, status);

-- Owner identity capture: first /start writes the chat id here so we can route
-- escalations and approval prompts even after a process restart. Only one row
-- expected (single-tenant); kept as a table to avoid magic config.
CREATE TABLE IF NOT EXISTS owner_identity (
    id INTEGER PRIMARY KEY CHECK (id = 1),
    telegram_chat_id INTEGER NOT NULL,
    telegram_username TEXT,
    captured_at TEXT NOT NULL
);

-- Inbound leads from the website forms. Stored even if `marketing_report_to_owner`
-- fails so we never lose attribution.
CREATE TABLE IF NOT EXISTS leads (
    id TEXT PRIMARY KEY,                       -- uuid
    name TEXT NOT NULL,
    contact TEXT NOT NULL,                     -- phone or email
    intent TEXT NOT NULL,
    channel_preference TEXT,
    utm_source TEXT,
    utm_campaign TEXT,
    page TEXT,
    created_at TEXT NOT NULL,
    reported_to_owner_at TEXT
);
CREATE INDEX IF NOT EXISTS idx_leads_campaign
    ON leads(utm_campaign, created_at);
