-- Bacaan NLU IndoBERT tiap pesan saat game berjalan (intent, confidence, target) untuk riwayat chat panel.

ALTER TABLE chat_messages
  ADD COLUMN nlu JSON NULL;

INSERT INTO schema_migrations (version) VALUES ('V9__chat_nlu');
