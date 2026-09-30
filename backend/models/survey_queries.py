"""SQL survei akhir pertandingan dan catatan metode bot. Transaksi diatur service."""

import json

from sqlalchemy import text
from sqlalchemy.orm import Session

KOLOM_PERTANYAAN = (
    "id, code, prompt, kind, scale_min, scale_max, label_min, label_max, options, required, "
    "active, position"
)


# Ubah baris pertanyaan menjadi dict; kolom JSON options dinormalkan menjadi list.
def _question(row) -> dict:
    data = dict(row._mapping)
    options = data.get("options")
    data["options"] = json.loads(options) if isinstance(options, str) else (options or [])
    data["required"] = bool(data["required"])
    data["active"] = bool(data["active"])
    return data


# QUERY SELECT: pertanyaan survei berurutan; pemain hanya menerima pertanyaan aktif.
def list_questions(database: Session, *, active_only: bool = True) -> list[dict]:
    where = "WHERE active = TRUE" if active_only else ""
    rows = database.execute(
        text(f"SELECT {KOLOM_PERTANYAAN} FROM survey_questions {where} ORDER BY position, id")
    )
    return [_question(row) for row in rows]


# QUERY INSERT: pertanyaan baru dari panel; kode unik dijaga constraint database.
def insert_question(database: Session, data: dict) -> int:
    params = {**data, "options": json.dumps(data.get("options") or [], ensure_ascii=False)}
    result = database.execute(
        text("""
        INSERT INTO survey_questions
            (code, prompt, kind, scale_min, scale_max, label_min, label_max, options, required,
             active, position)
        VALUES (:code, :prompt, :kind, :scale_min, :scale_max, :label_min, :label_max, :options,
                :required, :active, :position)
    """),
        params,
    )
    return int(result.lastrowid)


# QUERY UPDATE: ubah pertanyaan; jawaban lama tetap memakai salinan pertanyaan saat dijawab.
def update_question(database: Session, question_id: int, data: dict) -> int:
    params = {
        **data,
        "id": question_id,
        "options": json.dumps(data.get("options") or [], ensure_ascii=False),
    }
    return database.execute(
        text("""
        UPDATE survey_questions SET code=:code, prompt=:prompt, kind=:kind, scale_min=:scale_min,
            scale_max=:scale_max, label_min=:label_min, label_max=:label_max, options=:options,
            required=:required, active=:active, position=:position
        WHERE id = :id
    """),
        params,
    ).rowcount


# QUERY COUNT: apakah akun sudah mengirim survei untuk pertandingan ini.
def count_answers(database: Session, match_id: str, username: str) -> int:
    return int(
        database.execute(
            text("""
        SELECT COUNT(*) FROM survey_responses WHERE match_id = :match_id AND username = :username
    """),
            {"match_id": match_id, "username": username},
        ).scalar_one()
    )


# QUERY INSERT: satu jawaban beserta salinan pertanyaan dan konteks hasil pemain.
def insert_answer(database: Session, row: dict) -> None:
    database.execute(
        text("""
        INSERT INTO survey_responses
            (match_id, room_code, username, question_id, question_snapshot, value_number,
             value_text, role, team, outcome)
        VALUES (:match_id, :room_code, :username, :question_id, :question_snapshot, :value_number,
                :value_text, :role, :team, :outcome)
    """),
        {**row, "question_snapshot": json.dumps(row["question_snapshot"], ensure_ascii=False)},
    )


# QUERY INSERT: metode dan persona bot sekali per pertandingan (untuk analisis per metode).
def record_match_bot(database: Session, row: dict) -> None:
    database.execute(
        text("""
        INSERT IGNORE INTO match_bots (match_id, room_code, bot_name, method, persona, role)
        VALUES (:match_id, :room_code, :bot_name, :method, :persona, :role)
    """),
        row,
    )


# QUERY RINGKASAN: jumlah, rata-rata, dan sebaran nilai per pertanyaan, serta rata-rata per metode bot.
def summary(database: Session) -> dict:
    distribusi = database.execute(text("""
        SELECT question_id, value_number, COUNT(*) AS n FROM survey_responses
        WHERE value_number IS NOT NULL GROUP BY question_id, value_number
    """)).all()
    per_metode = database.execute(text("""
        SELECT r.question_id, b.method, COUNT(*) AS n, AVG(r.value_number) AS rata
        FROM survey_responses r
        JOIN (SELECT DISTINCT match_id, method FROM match_bots) b ON b.match_id = r.match_id
        WHERE r.value_number IS NOT NULL
        GROUP BY r.question_id, b.method
    """)).all()
    teks = database.execute(text("""
        SELECT question_id, COUNT(*) AS n FROM survey_responses
        WHERE value_text IS NOT NULL AND value_text <> '' GROUP BY question_id
    """)).all()
    return {
        "distribution": [dict(row._mapping) for row in distribusi],
        "per_method": [
            {**dict(row._mapping), "rata": float(row.rata) if row.rata is not None else None}
            for row in per_metode
        ],
        "text_answers": [dict(row._mapping) for row in teks],
    }


# QUERY EKSPOR: seluruh jawaban beserta metode bot di pertandingan yang sama.
def export_rows(database: Session) -> list[dict]:
    rows = database.execute(text("""
        SELECT r.created_at, r.match_id, r.room_code, r.username, r.role, r.team, r.outcome,
               q.code, r.question_snapshot, r.value_number, r.value_text,
               (SELECT GROUP_CONCAT(DISTINCT CONCAT(b.bot_name, ':', b.method, ':', b.persona)
                                    ORDER BY b.bot_name SEPARATOR ' | ')
                  FROM match_bots b WHERE b.match_id = r.match_id) AS bots
        FROM survey_responses r JOIN survey_questions q ON q.id = r.question_id
        ORDER BY r.created_at, r.id
    """))
    return [dict(row._mapping) for row in rows]
