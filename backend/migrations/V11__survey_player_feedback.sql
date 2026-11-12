-- Tambahan pertanyaan pengalaman bermain Silent Terror dari formulir penelitian.
-- Pertanyaan lama tetap tersedia; kode unik mencegah duplikasi jika SQL dijalankan ulang.
-- Kelima pertanyaan masuk paling bawah (posisi terbesar + 10, 20, …), sama seperti pertanyaan baru dari
-- panel. Pada database baru (enam pertanyaan V07, posisi 10–60) hasilnya 70–110.
USE shadow_heist;

START TRANSACTION;

SET @posisi_terakhir = (SELECT COALESCE(MAX(position), 0) FROM survey_questions);

INSERT IGNORE INTO survey_questions
  (code, prompt, kind, scale_min, scale_max, label_min, label_max, options, required, position)
VALUES
  ('pengalaman_bermain',
   'Bagaimana pengalaman Anda dalam memainkan permainan Silent Terror ini?',
   'text', 1, 6, NULL, NULL, NULL, TRUE, @posisi_terakhir + 10),
  ('saran_kesan_pesan',
   'Adakah saran, kesan, dan pesan untuk permainan yang baru saja Anda mainkan?',
   'text', 1, 6, NULL, NULL, NULL, TRUE, @posisi_terakhir + 20),
  ('kesenangan_bersama_bot',
   'Seberapa menyenangkan pengalaman Anda bermain bersama Bot NPC yang ada di dalam permainan ini?',
   'scale', 1, 5, 'Sangat tidak menyenangkan', 'Sangat menyenangkan', NULL, TRUE,
   @posisi_terakhir + 30),
  ('harapan_bot_npc',
   'Hal apa yang Anda harapkan ke depannya untuk Bot NPC?',
   'choice', 1, 6, NULL, NULL, JSON_ARRAY('Lebih cepat', 'Lebih berempati', 'Lainnya'), FALSE,
   @posisi_terakhir + 40),
  ('kesenangan_individu',
   'Menurut Anda, seberapa menyenangkan permainan ini untuk dimainkan secara individu?',
   'scale', 1, 5, 'Sangat tidak menyenangkan', 'Sangat menyenangkan', NULL, TRUE,
   @posisi_terakhir + 50);

INSERT IGNORE INTO schema_migrations(version) VALUES ('V11__survey_player_feedback');

COMMIT;
