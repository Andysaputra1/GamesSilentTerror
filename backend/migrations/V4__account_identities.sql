-- Apply once to existing databases, after V3. No existing accounts are deleted.
USE shadow_heist;

CREATE TABLE IF NOT EXISTS account_identities (
  user_id BIGINT UNSIGNED NOT NULL,
  email VARCHAR(254) NOT NULL,
  google_subject VARCHAR(255) CHARACTER SET ascii COLLATE ascii_bin NULL,
  email_verified BOOLEAN NOT NULL DEFAULT FALSE,
  PRIMARY KEY (user_id),
  UNIQUE KEY uq_identity_email (email),
  UNIQUE KEY uq_identity_google_subject (google_subject),
  CONSTRAINT fk_identity_user FOREIGN KEY (user_id) REFERENCES user_accounts(id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

INSERT IGNORE INTO schema_migrations (version) VALUES ('V4__account_identities');
