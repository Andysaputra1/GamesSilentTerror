"""Endpoint survei akhir pertandingan (pemain) dan pengelolaan pertanyaan (panel)."""

import csv
import io
import json
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Response
from pydantic import BaseModel, Field

from controller.api.panel import require_panel
from controller.middleware.auth import require_authenticated_user
from controller.middleware.safe_validation import SafeValidationRoute
from services.persistence_service import PersistenceError
from services.survey_service import SurveyAlreadySubmitted, survey_service

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
    position: int = Field(default=0, ge=-1000, le=1000)


# Terjemahkan kegagalan layanan survei menjadi status HTTP yang jelas tanpa detail internal.
def survey_call(operation):
    try:
        return operation()
    except SurveyAlreadySubmitted as error:
        raise HTTPException(409, str(error)) from error
    except LookupError as error:
        raise HTTPException(404, str(error)) from error
    except ValueError as error:
        raise HTTPException(400, str(error)) from error
    except PersistenceError as error:
        raise HTTPException(503, "Database survei belum siap. Jalankan migrasi V7.") from error


@router.get("/api/rooms/{code}/survey")
# PEMAIN: pertanyaan aktif dan status pengiriman untuk pertandingan yang sudah selesai.
def survey_status(code: str, user=Depends(require_authenticated_user)):
    return survey_call(lambda: survey_service.status(code, user.username))


@router.post("/api/rooms/{code}/survey")
# PEMAIN: kirim jawaban sekali per pertandingan; validasi skala mengikuti pertanyaan di database.
def survey_submit(code: str, body: SurveySubmission, user=Depends(require_authenticated_user)):
    answers = [answer.model_dump() for answer in body.answers]
    return survey_call(lambda: survey_service.submit(code, user.username, body.match_id, answers))


@router.get("/api/panel/survey/questions")
# PANEL: semua pertanyaan, termasuk yang dinonaktifkan.
def panel_questions(token=Depends(require_panel)):
    return {"questions": survey_call(survey_service.all_questions)}


@router.post("/api/panel/survey/questions", status_code=201)
# PANEL: tambah pertanyaan baru beserta jenis, skala, dan arti ujung skala.
def panel_create_question(body: Question, token=Depends(require_panel)):
    return survey_call(lambda: survey_service.create_question(body.model_dump()))


@router.put("/api/panel/survey/questions/{question_id}")
# PANEL: ubah pertanyaan atau nonaktifkan (tidak ada hapus agar data lama tetap utuh).
def panel_update_question(question_id: int, body: Question, token=Depends(require_panel)):
    return survey_call(lambda: survey_service.update_question(question_id, body.model_dump()))


@router.get("/api/panel/survey/summary")
# PANEL: sebaran nilai per pertanyaan dan rata-rata per metode bot.
def panel_summary(token=Depends(require_panel)):
    return survey_call(survey_service.summary)


@router.get("/api/panel/survey/responses.csv")
# PANEL: ekspor seluruh jawaban untuk analisis penelitian. UTF-8 dengan BOM (dibaca benar oleh Excel).
# Nilai disimpan persis demi data penelitian, sama seperti CSV riwayat chat: teks bebas pemain tidak
# di-escape, jadi saat membuka di spreadsheet impor kolom teks sebagai teks (bukan formula).
def panel_export(token=Depends(require_panel)):
    rows = survey_call(survey_service.export_rows)
    buffer = io.StringIO()
    columns = [
        "created_at", "match_id", "room_code", "username", "role", "team", "outcome", "code",
        "prompt", "value_number", "value_text", "bots",
    ]  # fmt: skip
    writer = csv.DictWriter(buffer, fieldnames=columns, extrasaction="ignore")
    writer.writeheader()
    for row in rows:
        snapshot = row.get("question_snapshot")
        snapshot = json.loads(snapshot) if isinstance(snapshot, str) else (snapshot or {})
        writer.writerow({**row, "prompt": snapshot.get("prompt", "")})
    return Response(
        "﻿" + buffer.getvalue(),
        media_type="text/csv; charset=utf-8",
        headers={
            "Content-Disposition": 'attachment; filename="survei_silent_terror.csv"',
            "Cache-Control": "no-store",
        },
    )
