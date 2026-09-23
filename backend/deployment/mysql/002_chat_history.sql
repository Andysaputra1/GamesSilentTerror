-- Additive migration: existing messages remain unchanged, with unknown legacy metadata.
ALTER TABLE chat_messages
    ADD COLUMN sender_kind ENUM('human','bot','legacy') NOT NULL DEFAULT 'legacy',
    ADD COLUMN match_id VARCHAR(36) NULL,
    ADD COLUMN round_number INT NULL,
    ADD COLUMN phase VARCHAR(32) NULL,
    ADD COLUMN reply_to_id BIGINT UNSIGNED NULL,
    ADD INDEX idx_chat_match_id (match_id, id);
INSERT INTO schema_migrations (version) VALUES ('V5__chat_history');
