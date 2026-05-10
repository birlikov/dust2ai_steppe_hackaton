-- Per-owner proactive-push cadence. NULL means "use env default
-- NOTIFIER_INTERVAL_S"; 0 means "off — keep loop alive but stay silent".
ALTER TABLE owner_identity ADD COLUMN notifier_interval_s INTEGER;
