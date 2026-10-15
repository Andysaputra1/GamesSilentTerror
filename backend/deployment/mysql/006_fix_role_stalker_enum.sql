-- Role 'stalker' untuk tabel players. Baseline Azure masih memakai 'detective', sehingga arsip
-- peserta Stalker gagal disimpan. Salinan migration lokal V8__fix_role_stalker_enum.sql.

ALTER TABLE players
  MODIFY COLUMN role ENUM('civilian', 'hitman', 'spy', 'stalker') NULL DEFAULT NULL;

INSERT INTO schema_migrations (version) VALUES ('V8__fix_role_stalker_enum');
