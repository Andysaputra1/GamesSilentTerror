-- Development only: janice / user132 and kimberly / user132.
-- INSERT IGNORE preserves existing accounts; this does not reset passwords.
USE shadow_heist;

INSERT IGNORE INTO user_accounts (username, display_name, password_hash)
VALUES
('janice', 'Janice', 'pbkdf2_sha256$600000$ae3168581be547d69d9ad4ba590672ac$209d9cd9ed15918c3b1fe7593dbdd51973c67fa640986a2489c3ecc5fe431e66'),
('kimberly', 'Kimberly', 'pbkdf2_sha256$600000$ae3168581be547d69d9ad4ba590672ac$209d9cd9ed15918c3b1fe7593dbdd51973c67fa640986a2489c3ecc5fe431e66');

INSERT IGNORE INTO schema_migrations (version) VALUES ('V3__add_demo_players');
