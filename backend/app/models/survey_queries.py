"""SQL survei akhir pertandingan dan catatan metode bot. Transaksi diatur service."""

import json

from sqlalchemy import text
from sqlalchemy.orm import Session

KOLOM_PERTANYAAN = (
    "id, code, prompt, kind, scale_min, scale_max, label_min, label_max, options, required, "
    "active, position"
)


# QUERY SELECT: pertanyaan survei berurutan; pemain hanya menerima pertanyaan aktif.
def list_questions(database: Session, *, active_only: bool = True) -> list[dict]:
    syarat_aktif = "WHERE active = TRUE" if active_only else ""
    daftar_baris = database.execute(
        text(
            f"SELECT {KOLOM_PERTANYAAN} FROM survey_questions {syarat_aktif} ORDER BY position, id"
        )
    )
    daftar_pertanyaan = []
    for baris in daftar_baris:
        pertanyaan = dict(baris._mapping)
        # Kolom JSON options dinormalkan menjadi list.
        pilihan = pertanyaan.get("options")
        pertanyaan["options"] = json.loads(pilihan) if isinstance(pilihan, str) else (pilihan or [])
        pertanyaan["required"] = bool(pertanyaan["required"])
        pertanyaan["active"] = bool(pertanyaan["active"])
        daftar_pertanyaan.append(pertanyaan)
    return daftar_pertanyaan


# QUERY INSERT: pertanyaan baru dari panel; kode unik dijaga constraint database.
def insert_question(database: Session, pertanyaan: dict) -> int:
    parameter_sql = {
        **pertanyaan,
        "options": json.dumps(pertanyaan.get("options") or [], ensure_ascii=False),
    }
    hasil = database.execute(
        text("""
        INSERT INTO survey_questions
            (code, prompt, kind, scale_min, scale_max, label_min, label_max, options, required,
             active, position)
        VALUES (:code, :prompt, :kind, :scale_min, :scale_max, :label_min, :label_max, :options,
                :required, :active, :position)
    """),
        parameter_sql,
    )
    return int(hasil.lastrowid)


# QUERY UPDATE: ubah isi pertanyaan; jawaban lama tetap memakai salinan pertanyaan saat dijawab.
# Kolom position tidak disentuh: urutan hanya berubah lewat update_positions.
def update_question(database: Session, id_pertanyaan: int, pertanyaan: dict) -> int:
    parameter_sql = {
        **pertanyaan,
        "id": id_pertanyaan,
        "options": json.dumps(pertanyaan.get("options") or [], ensure_ascii=False),
    }
    return database.execute(
        text("""
        UPDATE survey_questions SET code=:code, prompt=:prompt, kind=:kind, scale_min=:scale_min,
            scale_max=:scale_max, label_min=:label_min, label_max=:label_max, options=:options,
            required=:required, active=:active
        WHERE id = :id
    """),
        parameter_sql,
    ).rowcount


# QUERY UPDATE: tulis posisi banyak pertanyaan sekaligus (executemany; transaksinya diatur service).
def update_positions(database: Session, daftar_posisi: list[dict]) -> None:
    database.execute(
        text("UPDATE survey_questions SET position = :position WHERE id = :id"), daftar_posisi
    )


# QUERY COUNT: apakah akun sudah mengirim survei untuk pertandingan ini.
def count_answers(database: Session, id_pertandingan: str, username: str) -> int:
    return int(
        database.execute(
            text("""
        SELECT COUNT(*) FROM survey_responses WHERE match_id = :match_id AND username = :username
    """),
            {"match_id": id_pertandingan, "username": username},
        ).scalar_one()
    )


# QUERY INSERT: satu jawaban beserta salinan pertanyaan dan konteks hasil pemain.
def insert_answer(database: Session, jawaban: dict) -> None:
    database.execute(
        text("""
        INSERT INTO survey_responses
            (match_id, room_code, username, question_id, question_snapshot, value_number,
             value_text, role, team, outcome)
        VALUES (:match_id, :room_code, :username, :question_id, :question_snapshot, :value_number,
                :value_text, :role, :team, :outcome)
    """),
        {
            **jawaban,
            "question_snapshot": json.dumps(jawaban["question_snapshot"], ensure_ascii=False),
        },
    )


# QUERY INSERT: metode dan persona bot sekali per pertandingan (untuk analisis per metode).
def record_match_bot(database: Session, bot: dict) -> None:
    database.execute(
        text("""
        INSERT IGNORE INTO match_bots (match_id, room_code, bot_name, method, persona, role)
        VALUES (:match_id, :room_code, :bot_name, :method, :persona, :role)
    """),
        bot,
    )


# Identitas bot pertandingan-pertandingan terakhir sebuah room, terbaru lebih dulu.
def latest_match_bots(database: Session, room_code: str):
    return database.execute(
        text("""
            SELECT match_id, bot_name, method, persona, role FROM match_bots
            WHERE room_code=:code ORDER BY created_at DESC, bot_name LIMIT 20
        """),
        {"code": room_code},
    ).mappings().all()  # fmt: skip


# QUERY DELETE: kosongkan jawaban beserta arsip peserta. Tanpa arsip ikut terhapus, pertandingan lama
# muncul lagi sebagai survei tertunda karena jawabannya sudah tidak ada (lihat pending_surveys).
def clear_responses(database: Session) -> int:
    jumlah_terhapus = database.execute(text("DELETE FROM survey_responses")).rowcount
    database.execute(text("DELETE FROM match_participants"))
    return jumlah_terhapus


# QUERY COUNT: jumlah jawaban satu pertanyaan.
def count_question_answers(database: Session, id_pertanyaan: int) -> int:
    return int(
        database.execute(
            text("SELECT COUNT(*) FROM survey_responses WHERE question_id = :id"),
            {"id": id_pertanyaan},
        ).scalar_one()
    )


# QUERY DELETE: hapus satu pertanyaan; service memastikan belum ada jawaban yang merujuknya.
def delete_question(database: Session, id_pertanyaan: int) -> None:
    database.execute(text("DELETE FROM survey_questions WHERE id = :id"), {"id": id_pertanyaan})


# QUERY RINGKASAN: jumlah, rata-rata, dan sebaran nilai per pertanyaan, serta rata-rata per metode bot.
# Setiap jawaban dihitung sekali: pertandingan yang semua botnya satu metode masuk ke metode itu,
# pertandingan dengan beberapa metode masuk kelompok "campuran" (tidak dibagi ke tiap metode).
def summary(database: Session) -> dict:
    distribusi = database.execute(text("""
        SELECT question_id, value_number, COUNT(*) AS n FROM survey_responses
        WHERE value_number IS NOT NULL GROUP BY question_id, value_number
    """)).all()
    per_metode = database.execute(text("""
        SELECT r.question_id, b.method, COUNT(*) AS n, AVG(r.value_number) AS rata
        FROM survey_responses r
        JOIN (
            SELECT match_id,
                   CASE WHEN COUNT(DISTINCT method) = 1 THEN MIN(method) ELSE 'campuran' END AS method
            FROM match_bots GROUP BY match_id
        ) b ON b.match_id = r.match_id
        WHERE r.value_number IS NOT NULL
        GROUP BY r.question_id, b.method
    """)).all()
    teks = database.execute(text("""
        SELECT question_id, COUNT(*) AS n FROM survey_responses
        WHERE value_text IS NOT NULL AND value_text <> '' GROUP BY question_id
    """)).all()
    return {
        "distribution": [dict(baris._mapping) for baris in distribusi],
        "per_method": [
            {**dict(baris._mapping), "rata": float(baris.rata) if baris.rata is not None else None}
            for baris in per_metode
        ],
        "text_answers": [dict(baris._mapping) for baris in teks],
    }


# QUERY EKSPOR: seluruh jawaban beserta metode bot di pertandingan yang sama. Satu kiriman
# (pertandingan + akun) tetap berkelompok menurut waktu kirimnya; di dalamnya jawaban mengikuti
# urutan pertanyaan sekarang.
def export_rows(database: Session) -> list[dict]:
    daftar_baris = database.execute(text("""
        SELECT r.created_at, r.match_id, r.room_code, r.username, r.role, r.team, r.outcome,
               q.code, r.question_snapshot, r.value_number, r.value_text,
               (SELECT GROUP_CONCAT(DISTINCT CONCAT(b.bot_name, ':', b.method, ':', b.persona)
                                    ORDER BY b.bot_name SEPARATOR ' | ')
                  FROM match_bots b WHERE b.match_id = r.match_id) AS bots
        FROM survey_responses r JOIN survey_questions q ON q.id = r.question_id
        ORDER BY MIN(r.created_at) OVER (PARTITION BY r.match_id, r.username), r.match_id,
                 r.username, q.position, q.id
    """))
    return [dict(baris._mapping) for baris in daftar_baris]


# QUERY INSERT: peserta manusia pertandingan yang selesai; dicatat sekali (INSERT IGNORE per match + username).
def record_participants(database: Session, daftar_peserta: list[dict]) -> None:
    for peserta in daftar_peserta:
        database.execute(
            text("""
            INSERT IGNORE INTO match_participants (match_id, room_code, username, role, team, outcome)
            VALUES (:match_id, :room_code, :username, :role, :team, :outcome)
        """),
            peserta,
        )


# QUERY SELECT: konteks survei satu akun dari arsip peserta (pertandingan tertentu atau yang terbaru di room).
def participant(
    database: Session, kode_room: str, username: str, id_pertandingan: str | None
) -> dict | None:
    baris = (
        database.execute(
            text("""
        SELECT match_id, room_code, role, team, outcome FROM match_participants
        WHERE room_code = :room_code AND username = :username
          AND (:match_id IS NULL OR match_id = :match_id)
        ORDER BY finished_at DESC LIMIT 1
    """),
            {"room_code": kode_room, "username": username, "match_id": id_pertandingan},
        )
        .mappings()
        .first()
    )
    return dict(baris) if baris else None


# QUERY SELECT: pertandingan selesai yang surveinya belum dijawab akun ini (terbaru dulu).
def pending_surveys(database: Session, username: str, limit: int = 20) -> list[dict]:
    daftar_baris = database.execute(
        text("""
        SELECT p.match_id, p.room_code, p.role, p.team, p.outcome, p.finished_at
        FROM match_participants p
        WHERE p.username = :username AND NOT EXISTS (
            SELECT 1 FROM survey_responses r WHERE r.match_id = p.match_id AND r.username = p.username
        )
        ORDER BY p.finished_at DESC LIMIT :limit
    """),
        {"username": username, "limit": limit},
    ).mappings()
    return [dict(baris) for baris in daftar_baris]
