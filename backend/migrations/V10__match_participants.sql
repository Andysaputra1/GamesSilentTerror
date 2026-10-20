-- Peserta manusia setiap pertandingan yang sudah selesai, beserta role, kubu, dan hasilnya.
-- Dipakai survei akhir: pemain bisa mengisi survei kapan pun setelah pertandingan selesai (juga
-- setelah keluar room atau server dinyalakan ulang), dan Main menampilkan survei yang belum diisi.

CREATE TABLE IF NOT EXISTS match_participants (
  match_id CHAR(32) NOT NULL,
  room_code CHAR(36) NOT NULL,
  username VARCHAR(100) NOT NULL,
  role VARCHAR(20) NOT NULL,
  team VARCHAR(20) NOT NULL,
  outcome VARCHAR(10) NOT NULL,
  finished_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (match_id, username),
  KEY ix_match_participants_user (username, finished_at)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

INSERT IGNORE INTO schema_migrations(version) VALUES ('V10__match_participants');
