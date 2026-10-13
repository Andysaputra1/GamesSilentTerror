-- Avatar preference for user accounts. This mirrors the local skin migration
-- so Azure's isolated MySQL init directory has the column before backend startup.

ALTER TABLE user_accounts
  ADD COLUMN skin_id VARCHAR(20) NOT NULL DEFAULT 'dexter' AFTER display_name;

ALTER TABLE user_accounts
  ADD CONSTRAINT chk_user_accounts_skin_id
  CHECK (skin_id IN ('arthur', 'dexter', 'eloise', 'jenny', 'kiera', 'sadie'));

CREATE INDEX ix_user_accounts_skin_id ON user_accounts (skin_id);

INSERT INTO schema_migrations (version) VALUES ('V7__add_skin_preference');
