-- Add skin preference to user accounts for avatar selection.
-- All 6 skins are available: arthur, dexter, eloise, jenny, kiera, sadie.

USE shadow_heist;

-- Add skinId column with default to 'dexter' (first character in alphabetical order for neutral default)
ALTER TABLE user_accounts
ADD COLUMN skin_id VARCHAR(20) NOT NULL DEFAULT 'dexter' AFTER display_name;

-- Add check constraint to ensure only valid skin values
ALTER TABLE user_accounts
ADD CONSTRAINT chk_user_accounts_skin_id
CHECK (skin_id IN ('arthur', 'dexter', 'eloise', 'jenny', 'kiera', 'sadie'));

-- Index for potential queries by skin preference
CREATE INDEX ix_user_accounts_skin_id ON user_accounts (skin_id);

INSERT INTO schema_migrations (version) VALUES ('V7__add_skin_preference');
