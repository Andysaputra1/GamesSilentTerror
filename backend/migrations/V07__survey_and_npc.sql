-- Survei akhir pertandingan dan catatan otak NPC per bot.
-- Pertanyaan, jenis jawaban, skala, dan arti ujung skala diatur dari database/panel,
-- bukan dari frontend. Jawaban menyimpan salinan pertanyaan saat dijawab supaya
-- perubahan pertanyaan di kemudian hari tidak mengubah arti data lama.

USE shadow_heist;

CREATE TABLE IF NOT EXISTS survey_questions (
  id INT UNSIGNED NOT NULL AUTO_INCREMENT,
  code VARCHAR(40) NOT NULL,
  prompt VARCHAR(300) NOT NULL,
  kind ENUM('stars', 'scale', 'choice', 'text') NOT NULL DEFAULT 'stars',
  scale_min TINYINT UNSIGNED NOT NULL DEFAULT 1,
  scale_max TINYINT UNSIGNED NOT NULL DEFAULT 6,
  label_min VARCHAR(80) NULL,
  label_max VARCHAR(80) NULL,
  options JSON NULL,
  required BOOLEAN NOT NULL DEFAULT TRUE,
  active BOOLEAN NOT NULL DEFAULT TRUE,
  position SMALLINT NOT NULL DEFAULT 0,
  created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
  updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  PRIMARY KEY (id),
  UNIQUE KEY uq_survey_questions_code (code),
  KEY ix_survey_questions_active (active, position)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS survey_responses (
  id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
  match_id CHAR(32) NOT NULL,
  room_code CHAR(36) NOT NULL,
  username VARCHAR(100) NOT NULL,
  question_id INT UNSIGNED NOT NULL,
  question_snapshot JSON NOT NULL,
  value_number SMALLINT NULL,
  value_text VARCHAR(1000) NULL,
  role VARCHAR(20) NULL,
  team VARCHAR(20) NULL,
  outcome VARCHAR(10) NULL,
  created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (id),
  UNIQUE KEY uq_survey_answer (match_id, username, question_id),
  KEY ix_survey_responses_question (question_id, created_at),
  CONSTRAINT fk_survey_responses_question
    FOREIGN KEY (question_id) REFERENCES survey_questions(id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- Metode penalaran dan persona setiap bot, agar jawaban survei bisa dianalisis per metode.
CREATE TABLE IF NOT EXISTS match_bots (
  match_id CHAR(32) NOT NULL,
  room_code CHAR(36) NOT NULL,
  bot_name VARCHAR(100) NOT NULL,
  method VARCHAR(20) NOT NULL,
  persona VARCHAR(20) NOT NULL,
  role VARCHAR(20) NOT NULL,
  created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (match_id, bot_name)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- Pertanyaan awal; dapat diubah atau dinonaktifkan dari panel.
INSERT IGNORE INTO survey_questions
  (code, prompt, kind, scale_min, scale_max, label_min, label_max, required, position)
VALUES
  ('keseruan', 'Seberapa seru pertandingan ini?', 'stars', 1, 6,
   'Sangat membosankan', 'Sangat seru', TRUE, 10),
  ('bot_manusiawi', 'Seberapa mirip bot dengan pemain manusia?', 'stars', 1, 6,
   'Jelas seperti bot', 'Tidak bisa dibedakan dari manusia', TRUE, 20),
  ('chat_bot_masuk_akal', 'Seberapa masuk akal chat yang ditulis bot?', 'stars', 1, 6,
   'Tidak masuk akal', 'Sangat masuk akal', TRUE, 30),
  ('keputusan_bot', 'Seberapa tepat keputusan bot (tuduhan dan vote)?', 'stars', 1, 6,
   'Asal-asalan', 'Sangat tepat', TRUE, 40),
  ('kesulitan', 'Seberapa sulit menebak siapa Hitman?', 'scale', 1, 6,
   'Sangat mudah', 'Sangat sulit', TRUE, 50),
  ('komentar', 'Saran atau komentar untuk permainan ini (opsional)', 'text', 1, 6,
   NULL, NULL, FALSE, 60);

INSERT IGNORE INTO schema_migrations(version) VALUES ('V7__survey_and_npc');
