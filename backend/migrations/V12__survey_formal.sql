-- Survei penelitian versi formal (13 November 2026). Struktur tabel tidak berubah.
-- 1. Sebelas pertanyaan lama (V07 dan V11) tidak dipakai lagi. Yang belum punya jawaban dihapus. Yang sudah
--    punya jawaban hanya dinonaktifkan, karena foreign key survey_responses menjaga jawabannya tetap utuh.
-- 2. Sepuluh pertanyaan baru berbahasa formal, masuk paling bawah. Delapan pernyataan memakai skala
--    persetujuan 1 sampai 5 yang sama, sehingga rata-ratanya bisa dibandingkan. Setiap pernyataan mengukur satu
--    bagian bot: kemiripan dengan manusia, NLU (memahami pesan), NLG (bahasa), Fuzzy (keputusan dan peran),
--    tantangan, dan kecepatan. Ditambah satu pilihan ganda dan satu isian bebas, keduanya opsional.
-- 3. Pengingat survei hanya untuk pertandingan yang selesai mulai 13 November 2026 pukul 00.00 WIB
--    (12 November 17.00 UTC). Arsip peserta pertandingan sebelum itu dihapus. Arsip ini hanya dipakai survei
--    (pengingat di Main dan konteks pengiriman), jadi pertandingan lama tidak lagi bisa disurvei.
USE shadow_heist;

START TRANSACTION;

DELETE q FROM survey_questions q
WHERE q.code IN ('keseruan', 'bot_manusiawi', 'chat_bot_masuk_akal', 'keputusan_bot', 'kesulitan',
                 'komentar', 'pengalaman_bermain', 'saran_kesan_pesan', 'kesenangan_bersama_bot',
                 'harapan_bot_npc', 'kesenangan_individu')
  AND NOT EXISTS (SELECT 1 FROM survey_responses r WHERE r.question_id = q.id);

UPDATE survey_questions SET active = FALSE
WHERE code IN ('keseruan', 'bot_manusiawi', 'chat_bot_masuk_akal', 'keputusan_bot', 'kesulitan',
               'komentar', 'pengalaman_bermain', 'saran_kesan_pesan', 'kesenangan_bersama_bot',
               'harapan_bot_npc', 'kesenangan_individu');

SET @posisi_terakhir = (SELECT COALESCE(MAX(position), 0) FROM survey_questions);

INSERT IGNORE INTO survey_questions
  (code, prompt, kind, scale_min, scale_max, label_min, label_max, options, required, position)
VALUES
  ('kesenangan_bermain',
   'Bermain Silent Terror bersama Bot NPC merupakan pengalaman yang menyenangkan.',
   'scale', 1, 5, 'Sangat tidak setuju', 'Sangat setuju', NULL, TRUE, @posisi_terakhir + 10),
  ('kemiripan_manusia',
   'Bot NPC berperilaku layaknya pemain manusia.',
   'scale', 1, 5, 'Sangat tidak setuju', 'Sangat setuju', NULL, TRUE, @posisi_terakhir + 20),
  ('pemahaman_pesan',
   'Bot NPC memahami maksud pesan yang saya kirimkan dalam diskusi.',
   'scale', 1, 5, 'Sangat tidak setuju', 'Sangat setuju', NULL, TRUE, @posisi_terakhir + 30),
  ('kewajaran_bahasa',
   'Pesan yang ditulis Bot NPC menggunakan bahasa yang wajar dan sesuai dengan alur diskusi.',
   'scale', 1, 5, 'Sangat tidak setuju', 'Sangat setuju', NULL, TRUE, @posisi_terakhir + 40),
  ('ketepatan_keputusan',
   'Tuduhan, pembelaan, dan pilihan vote Bot NPC masuk akal berdasarkan kejadian dalam permainan.',
   'scale', 1, 5, 'Sangat tidak setuju', 'Sangat setuju', NULL, TRUE, @posisi_terakhir + 50),
  ('kesesuaian_peran',
   'Tindakan Bot NPC sesuai dengan peran yang dimainkannya.',
   'scale', 1, 5, 'Sangat tidak setuju', 'Sangat setuju', NULL, TRUE, @posisi_terakhir + 60),
  ('tingkat_tantangan',
   'Bot NPC memberikan tantangan yang sepadan, baik sebagai lawan maupun sebagai rekan satu tim.',
   'scale', 1, 5, 'Sangat tidak setuju', 'Sangat setuju', NULL, TRUE, @posisi_terakhir + 70),
  ('kecepatan_respons',
   'Bot NPC menanggapi pesan dan kejadian dalam permainan dengan cukup cepat.',
   'scale', 1, 5, 'Sangat tidak setuju', 'Sangat setuju', NULL, TRUE, @posisi_terakhir + 80),
  ('aspek_perbaikan',
   'Menurut Anda, aspek Bot NPC manakah yang paling perlu ditingkatkan?',
   'choice', 1, 6, NULL, NULL,
   JSON_ARRAY('Pemahaman terhadap pesan pemain', 'Kewajaran bahasa', 'Ketepatan keputusan',
              'Kecepatan menanggapi', 'Keaktifan dalam diskusi', 'Lainnya'),
   FALSE, @posisi_terakhir + 90),
  ('saran_masukan',
   'Silakan tuliskan kesan, saran, atau masukan Anda mengenai permainan ini dan Bot NPC.',
   'text', 1, 6, NULL, NULL, NULL, FALSE, @posisi_terakhir + 100);

SET time_zone = '+00:00';
DELETE FROM match_participants WHERE finished_at < '2026-11-12 17:00:00';

INSERT IGNORE INTO schema_migrations(version) VALUES ('V12__survey_formal');

COMMIT;
