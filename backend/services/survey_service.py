"""Survei akhir pertandingan: pertanyaan, skala, dan arti skala diatur dari database/panel."""

from __future__ import annotations

import re

from models import survey_queries as queries
from services.persistence_service import PersistenceService
from services.room_service import room_service

JENIS = {"stars", "scale", "choice", "text"}
NILAI_SKALA_MAKS = 10
PANJANG_TEKS = 1000
KOLOM_PUBLIK = (
    "id",
    "code",
    "prompt",
    "kind",
    "scale_min",
    "scale_max",
    "label_min",
    "label_max",
    "options",
    "required",
)


class SurveyAlreadySubmitted(ValueError):
    """Satu akun hanya mengirim survei sekali untuk satu pertandingan."""


# Bagian pertanyaan yang boleh dilihat pemain dan disalin ke setiap jawaban.
def public_question(question: dict) -> dict:
    return {key: question[key] for key in KOLOM_PUBLIK}


# VALIDASI PANEL: bentuk pertanyaan harus konsisten dengan jenis jawabannya.
def validate_question(data: dict) -> dict:
    code = str(data.get("code", "")).strip().lower()
    prompt = " ".join(str(data.get("prompt", "")).split())
    kind = data.get("kind")
    if not re.fullmatch(r"[a-z0-9_]{2,40}", code):
        raise ValueError("Kode pertanyaan 2–40 karakter: huruf kecil, angka, atau garis bawah.")
    if not 3 <= len(prompt) <= 300:
        raise ValueError("Teks pertanyaan harus 3–300 karakter.")
    if kind not in JENIS:
        raise ValueError("Jenis pertanyaan harus stars, scale, choice, atau text.")
    try:
        scale_min, scale_max = int(data.get("scale_min", 1)), int(data.get("scale_max", 6))
        position = int(data.get("position", 0))
    except (TypeError, ValueError) as error:
        raise ValueError("Skala dan urutan harus berupa angka bulat.") from error
    if kind == "stars" and scale_min != 1:
        raise ValueError("Pertanyaan bintang selalu dimulai dari 1.")
    if kind in {"stars", "scale"} and not 0 <= scale_min < scale_max <= NILAI_SKALA_MAKS:
        raise ValueError(f"Skala harus 0 ≤ minimum < maksimum ≤ {NILAI_SKALA_MAKS}.")
    labels = {}
    for key in ("label_min", "label_max"):
        value = data.get(key)
        value = " ".join(str(value).split()) if value not in (None, "") else None
        if value is not None and len(value) > 80:
            raise ValueError("Label arti skala maksimal 80 karakter.")
        labels[key] = value
    options = []
    if kind == "choice":
        options = [" ".join(str(item).split()) for item in (data.get("options") or [])]
        if not 2 <= len(options) <= 8 or len(set(options)) != len(options):
            raise ValueError("Pilihan ganda membutuhkan 2–8 pilihan berbeda.")
        if any(not 1 <= len(item) <= 80 for item in options):
            raise ValueError("Setiap pilihan 1–80 karakter.")
    if not -1000 <= position <= 1000:
        raise ValueError("Urutan harus antara -1000 dan 1000.")
    return {
        "code": code,
        "prompt": prompt,
        "kind": kind,
        "scale_min": scale_min if kind in {"stars", "scale"} else 1,
        "scale_max": scale_max if kind in {"stars", "scale"} else 6,
        **labels,
        "options": options,
        "required": bool(data.get("required", True)),
        "active": bool(data.get("active", True)),
        "position": position,
    }


# VALIDASI PEMAIN: setiap jawaban cocok dengan pertanyaan aktif; pertanyaan wajib harus dijawab.
def validate_answers(questions: dict[int, dict], answers: list[dict]) -> list[tuple]:
    by_id = {}
    for answer in answers:
        question_id = answer.get("question_id")
        if question_id not in questions:
            raise ValueError("Pertanyaan survei tidak dikenal atau sudah tidak aktif.")
        if question_id in by_id:
            raise ValueError("Setiap pertanyaan hanya boleh dijawab sekali.")
        by_id[question_id] = answer
    rows = []
    for question in questions.values():
        answer = by_id.get(question["id"], {})
        value, text = answer.get("value"), answer.get("text")
        if question["kind"] in {"stars", "scale"}:
            if value is None:
                if question["required"]:
                    raise ValueError(f"Jawab pertanyaan: {question['prompt']}")
                continue
            if isinstance(value, bool) or not isinstance(value, int):
                raise ValueError("Nilai skala harus berupa angka bulat.")
            if not question["scale_min"] <= value <= question["scale_max"]:
                raise ValueError(
                    f"Nilai untuk '{question['prompt']}' harus "
                    f"{question['scale_min']}–{question['scale_max']}."
                )
            rows.append((question, value, None))
        else:
            text = " ".join(str(text or "").split())
            if not text:
                if question["required"]:
                    raise ValueError(f"Jawab pertanyaan: {question['prompt']}")
                continue
            if question["kind"] == "choice" and text not in question["options"]:
                raise ValueError(f"Pilihan untuk '{question['prompt']}' tidak tersedia.")
            if len(text) > PANJANG_TEKS:
                raise ValueError(f"Jawaban teks maksimal {PANJANG_TEKS} karakter.")
            rows.append((question, None, text))
    return rows


class SurveyService:
    # KONTEKS: survei hanya untuk manusia peserta pertandingan yang sudah selesai.
    def _context(self, code, username, match_id=None):
        with room_service.lock:
            room = room_service.get(code, username)
            match = room.match
            if not match or not match.winner:
                raise ValueError("Survei tersedia setelah pertandingan selesai.")
            if match_id is not None and match.id != match_id:
                raise ValueError("Pertandingan sudah berganti. Perbarui halaman.")
            player = match.players.get(username)
            if not player or player.bot:
                raise ValueError("Survei hanya untuk pemain manusia di pertandingan ini.")
            result = match.result(username)
            return {
                "match_id": match.id,
                "room_code": room.code,
                "role": player.role,
                "team": result["team"],
                "outcome": result["outcome"],
            }

    # STATUS: pertanyaan aktif dan apakah akun sudah mengirim survei pertandingan ini.
    def status(self, code, username):
        context = self._context(code, username)

        def operation(database):
            return (
                queries.list_questions(database),
                queries.count_answers(database, context["match_id"], username),
            )

        questions, answered = PersistenceService._run(operation)
        return {
            "match_id": context["match_id"],
            "submitted": answered > 0,
            "questions": [public_question(question) for question in questions],
        }

    # KIRIM: validasi terhadap pertanyaan aktif, simpan semua jawaban dalam satu transaksi.
    def submit(self, code, username, match_id, answers):
        context = self._context(code, username, match_id)

        def operation(database):
            if queries.count_answers(database, context["match_id"], username):
                raise SurveyAlreadySubmitted(
                    "Survei untuk pertandingan ini sudah dikirim. Terima kasih!"
                )
            questions = {q["id"]: q for q in queries.list_questions(database)}
            rows = validate_answers(questions, answers)
            for question, value, text in rows:
                queries.insert_answer(
                    database,
                    {
                        **context,
                        "username": username,
                        "question_id": question["id"],
                        "question_snapshot": public_question(question),
                        "value_number": value,
                        "value_text": text,
                    },
                )
            return len(rows)

        return {"submitted": True, "answers": PersistenceService._run(operation)}

    # PANEL: semua pertanyaan, termasuk yang nonaktif.
    def all_questions(self):
        return PersistenceService._run(
            lambda database: queries.list_questions(database, active_only=False)
        )

    # PANEL: tambah pertanyaan; kode harus unik.
    def create_question(self, data):
        question = validate_question(data)

        def operation(database):
            existing = queries.list_questions(database, active_only=False)
            if any(item["code"] == question["code"] for item in existing):
                raise ValueError("Kode pertanyaan sudah dipakai.")
            return queries.insert_question(database, question)

        return {"id": PersistenceService._run(operation), **question}

    # PANEL: ubah pertanyaan; tidak ada penghapusan agar jawaban lama tetap utuh.
    def update_question(self, question_id, data):
        question = validate_question(data)

        def operation(database):
            existing = queries.list_questions(database, active_only=False)
            if not any(item["id"] == question_id for item in existing):
                raise LookupError("Pertanyaan tidak ditemukan.")
            if any(
                item["code"] == question["code"] and item["id"] != question_id for item in existing
            ):
                raise ValueError("Kode pertanyaan sudah dipakai.")
            queries.update_question(database, question_id, question)

        PersistenceService._run(operation)
        return {"id": question_id, **question}

    # PANEL: ringkasan jawaban per pertanyaan dan per metode bot.
    def summary(self):
        def operation(database):
            return queries.list_questions(database, active_only=False), queries.summary(database)

        questions, data = PersistenceService._run(operation)
        return {"questions": questions, **data}

    # PANEL: baris CSV untuk analisis penelitian.
    def export_rows(self):
        return PersistenceService._run(queries.export_rows)

    # NPC: catat metode dan persona bot pertandingan (gagal simpan tidak menghentikan game).
    def record_match_bots(self, rows):
        def operation(database):
            for row in rows:
                queries.record_match_bot(database, row)

        PersistenceService._run(operation)


survey_service = SurveyService()
