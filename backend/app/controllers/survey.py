"""Endpoint survei akhir pertandingan (pemain) dan pengelolaan pertanyaan (panel)."""

import csv
import io
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from pydantic import BaseModel, Field

from app.controllers.panel import require_panel
from app.middleware.auth import require_authenticated_user
from app.middleware.safe_validation import SafeValidationRoute
from app.services.persistence_service import PersistenceError
from app.services.survey_service import SurveyAlreadySubmitted, survey_service

router = APIRouter(tags=["survey"], route_class=SafeValidationRoute)


class Answer(BaseModel):
    question_id: int = Field(ge=1)
    value: int | None = Field(default=None, ge=0, le=10)
    text: str | None = Field(default=None, max_length=1000)


class SurveySubmission(BaseModel):
    match_id: str = Field(min_length=1, max_length=40)
    answers: list[Answer] = Field(default_factory=list, max_length=50)


class Question(BaseModel):
    code: str = Field(min_length=2, max_length=40)
    prompt: str = Field(min_length=3, max_length=300)
    kind: Literal["stars", "scale", "choice", "text"] = "stars"
    scale_min: int = Field(default=1, ge=0, le=10)
    scale_max: int = Field(default=6, ge=1, le=10)
    label_min: str | None = Field(default=None, max_length=80)
    label_max: str | None = Field(default=None, max_length=80)
    options: list[str] = Field(default_factory=list, max_length=8)
    required: bool = True
    active: bool = True
    # Tidak ada kolom position: server yang menentukan posisi (baru = paling bawah, susunan ulang
    # lewat endpoint urutan). Panel lama yang masih mengirim position diabaikan, bukan ditolak.


# Semua id pertanyaan (termasuk yang nonaktif) dalam urutan baru; kelengkapannya diperiksa service.
class QuestionOrder(BaseModel):
    ids: list[int] = Field(min_length=1, max_length=1000)


# Terjemahkan kegagalan layanan survei menjadi status HTTP yang jelas tanpa detail internal.
def survey_call(operasi):
    try:
        return operasi()
    except SurveyAlreadySubmitted as error:
        raise HTTPException(409, str(error)) from error
    except LookupError as error:
        raise HTTPException(404, str(error)) from error
    except ValueError as error:
        raise HTTPException(400, str(error)) from error
    except PersistenceError as error:
        raise HTTPException(503, "Database survei belum siap. Jalankan migrasi V7.") from error


# PEMAIN: survei pertandingan selesai yang belum diisi, untuk pengingat di halaman Main.
@router.get("/api/survey/pending")
def pending(user=Depends(require_authenticated_user)):
    return {"surveys": survey_service.pending(user.username)}


@router.get("/api/rooms/{code}/survey")
# PEMAIN: pertanyaan aktif dan status pengiriman untuk pertandingan yang sudah selesai. match_id opsional
# (pengingat di Main): tanpa itu dipakai pertandingan terbaru akun ini di room tersebut.
def survey_status(
    code: str,
    match_id: str | None = Query(default=None, max_length=40),
    user=Depends(require_authenticated_user),
):
    return survey_call(lambda: survey_service.status(code, user.username, match_id))


@router.post("/api/rooms/{code}/survey")
# PEMAIN: kirim jawaban sekali per pertandingan; validasi skala mengikuti pertanyaan di database.
def survey_submit(code: str, body: SurveySubmission, user=Depends(require_authenticated_user)):
    daftar_jawaban = [jawaban.model_dump() for jawaban in body.answers]
    return survey_call(
        lambda: survey_service.submit(code, user.username, body.match_id, daftar_jawaban)
    )


@router.post("/api/panel/survey/questions", status_code=201)
# PANEL: tambah pertanyaan baru beserta jenis, skala, dan arti ujung skala.
def panel_create_question(body: Question, token=Depends(require_panel)):
    return survey_call(lambda: survey_service.create_question(body.model_dump()))


@router.put("/api/panel/survey/questions/order")
# PANEL: simpan urutan pertanyaan hasil seret atau tombol ▲▼. Harus didaftarkan sebelum rute
# /questions/{question_id}: rute itu juga cocok dengan "order" lalu menolaknya dengan 422.
def panel_reorder_questions(body: QuestionOrder, token=Depends(require_panel)):
    return survey_call(lambda: survey_service.reorder_questions(body.ids))


@router.put("/api/panel/survey/questions/{question_id}")
# PANEL: ubah pertanyaan atau nonaktifkan; posisinya tidak ikut berubah.
def panel_update_question(question_id: int, body: Question, token=Depends(require_panel)):
    return survey_call(lambda: survey_service.update_question(question_id, body.model_dump()))


@router.delete("/api/panel/survey/questions/{question_id}", status_code=204)
# PANEL: hapus pertanyaan yang belum punya jawaban.
def panel_delete_question(question_id: int, token=Depends(require_panel)):
    survey_call(lambda: survey_service.delete_question(question_id))


@router.delete("/api/panel/survey/responses")
# PANEL: hapus permanen semua jawaban dan pengingat survei pertandingan lama.
def panel_clear_responses(token=Depends(require_panel)):
    return survey_call(survey_service.clear_responses)


@router.get("/api/panel/survey/summary")
# PANEL: sebaran nilai per pertanyaan dan rata-rata per metode bot.
def panel_summary(token=Depends(require_panel)):
    return survey_call(survey_service.summary)


@router.get("/api/panel/survey/respondents")
# PANEL: jumlah pengisi dan isian setiap kiriman (satu akun di satu pertandingan), terbaru dulu.
def panel_respondents(token=Depends(require_panel)):
    return survey_call(survey_service.respondents)


@router.get("/api/panel/survey/responses.csv")
# PANEL: ekspor jawaban untuk analisis penelitian. Satu baris = satu kiriman (satu akun di satu pertandingan);
# setiap pertanyaan menjadi satu kolom berjudul "kode: teks pertanyaan" (urut posisi di panel) berisi jawabannya,
# angka untuk skala atau teks untuk pilihan dan isian. UTF-8 dengan BOM (dibaca benar oleh Excel). File ini dibuka
# di spreadsheet, jadi teks yang diawali = + - @ tab atau CR diberi awalan ' supaya tidak dijalankan sebagai formula
# (injeksi CSV). Angka tetap angka. CSV riwayat chat sengaja tidak diubah, karena dipakai sebagai dataset NLU.
# Alur: 1 ambil baris jawaban -> 2 kolom pertanyaan urut posisi -> 3 satu baris per kiriman, jawaban di kolom
#       pertanyaannya -> 4 amankan teks dari formula -> 5 tulis CSV ber-BOM
def panel_export(token=Depends(require_panel)):
    def aman_spreadsheet(nilai):
        if isinstance(nilai, str) and nilai[:1] in ("=", "+", "-", "@", "\t", "\r"):
            return "'" + nilai
        return nilai

    # 1 baris jawaban (berkelompok per kiriman)
    daftar_baris = survey_call(survey_service.export_rows)

    # 2 kolom pertanyaan: satu per pertanyaan yang punya jawaban, urut posisi sekarang
    judul_pertanyaan = {}
    for baris in sorted(daftar_baris, key=lambda b: (b["question_position"], b["question_id"])):
        judul_pertanyaan.setdefault(
            baris["question_id"], f'{baris["code"]}: {baris["question_prompt"]}'
        )
    kolom_kiriman = [
        "created_at", "match_id", "room_code", "username", "display_name", "role", "team", "outcome",
    ]  # fmt: skip
    kolom_csv = [*kolom_kiriman, *judul_pertanyaan.values(), "bots"]

    # 3 satu baris per kiriman; waktu kiriman = jawaban pertamanya
    kiriman = {}
    for baris in daftar_baris:
        satu = kiriman.setdefault(
            (baris["match_id"], baris["username"]),
            {**{kolom: baris.get(kolom) for kolom in kolom_kiriman}, "bots": baris.get("bots")},
        )
        satu["created_at"] = min(satu["created_at"], baris["created_at"])
        jawaban = (
            baris["value_number"] if baris["value_number"] is not None else baris["value_text"]
        )
        satu[judul_pertanyaan[baris["question_id"]]] = jawaban

    # 4-5 amankan dari formula lalu tulis
    penampung_csv = io.StringIO()
    penulis_csv = csv.writer(penampung_csv)
    penulis_csv.writerow([aman_spreadsheet(kolom) for kolom in kolom_csv])
    for satu in kiriman.values():
        penulis_csv.writerow([aman_spreadsheet(satu.get(kolom)) for kolom in kolom_csv])
    return Response(
        "﻿" + penampung_csv.getvalue(),
        media_type="text/csv; charset=utf-8",
        headers={
            "Content-Disposition": 'attachment; filename="survei_silent_terror.csv"',
            "Cache-Control": "no-store",
        },
    )
