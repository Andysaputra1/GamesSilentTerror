"""Production administration, isolated from player authentication."""

import asyncio
import base64
import csv
import hashlib
import hmac
import io
import json
import re
import secrets
import socket
import ipaddress
from datetime import date, datetime, time, timedelta, timezone
from pathlib import Path
from typing import Literal
from urllib.parse import urlsplit
from tempfile import SpooledTemporaryFile
from time import perf_counter
from uuid import uuid4
from fastapi import APIRouter, Depends, HTTPException, Query, Response
from fastapi.responses import FileResponse, StreamingResponse, RedirectResponse
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from pydantic import BaseModel, Field, SecretStr
from sqlalchemy import text
from app.config.settings import settings
from app.module.password_service import verify_password
from app.module.persistence_service import PersistenceService, PersistenceError
from app.module.ai_runtime_service import ai_runtime, save_panel_configuration
from app.module.checker_service import checker_service
from app.module.npc_brain.runtime import POLA_MODEL_TAUTAN, brain_runtime
from app.module.activity_service import activity
from app.module.ai_diagnostics import capture_exchange, measure
from app.module.match_engine import Match
from app.module.npc_service import npc_context, decision_prompt, request_decision
from app.module.room_service import room_service
from app.controller.middleware.auth_limits import limit_auth
from app.module.ollama_client import generate_reply as local_reply
from app.module.openrouter_client import generate_reply as api_reply, failure_message
from app.controller.middleware.safe_validation import SafeValidationRoute

router = APIRouter(tags=["panel"], route_class=SafeValidationRoute)
ASSETS = Path(__file__).resolve().parents[3] / "public" / "panel"
bearer = HTTPBearer(auto_error=False)


# Jalankan transaksi panel dan ubah kegagalan penyimpanan menjadi HTTP 503.
def transaction(operation):
    try:
        return PersistenceService._run(operation)
    except PersistenceError as error:
        raise HTTPException(
            503, "Database panel belum siap. Periksa koneksi dan migrasi V5/V6."
        ) from error


# Buat sidik kredensial agar pergantian username/password membatalkan sesi lama.
def credential_version():
    raw = settings.panel_password_hash.get_secret_value() if settings.panel_password_hash else ""
    return hashlib.sha256((settings.panel_username + raw).encode()).hexdigest()


# Hash token panel sebelum pencarian atau penyimpanan di database.
def digest(token):
    return hashlib.sha256(token.encode()).hexdigest()


# Validasi hash token, kedaluwarsa, dan versi kredensial panel.
def require_panel(
    response: Response, credentials: HTTPAuthorizationCredentials | None = Depends(bearer)
):
    response.headers["Cache-Control"] = "no-store"
    if not credentials or not settings.panel_password_hash:
        raise HTTPException(401, "Login administrator diperlukan.")
    valid = transaction(
        lambda db: db.execute(
            text("""
        SELECT token_hash FROM panel_sessions WHERE token_hash=:token
        AND expires_at > UTC_TIMESTAMP() AND credential_version=:version
    """),
            {"token": digest(credentials.credentials), "version": credential_version()},
        ).scalar()
    )
    if not valid:
        raise HTTPException(401, "Sesi panel berakhir. Silakan login lagi.")
    return credentials.credentials


class Login(BaseModel):
    username: str = Field(min_length=1, max_length=100)
    password: str = Field(min_length=1, max_length=256)


# Periksa kredensial admin lalu simpan sesi panel berumur delapan jam.
@router.post("/api/panel/login", dependencies=[Depends(limit_auth)])
def login(body: Login, response: Response):
    response.headers["Cache-Control"] = "no-store"
    if not settings.panel_password_hash:
        raise HTTPException(503, "Password administrator belum disiapkan di server.")
    try:
        encoded = base64.b64decode(
            settings.panel_password_hash.get_secret_value(), validate=True
        ).decode()
    except (ValueError, UnicodeError):
        raise HTTPException(503, "Konfigurasi login panel tidak valid.")
    password_ok = verify_password(body.password, encoded)
    if (
        not hmac.compare_digest(body.username.encode(), settings.panel_username.encode())
        or not password_ok
    ):
        raise HTTPException(401, "Username atau password salah.")
    token = secrets.token_urlsafe(32)
    expires = datetime.now(timezone.utc).replace(tzinfo=None) + timedelta(hours=8)

    # Bersihkan sesi kedaluwarsa dan simpan hash sesi baru dalam satu transaksi.
    def save(db):
        db.execute(text("DELETE FROM panel_sessions WHERE expires_at <= UTC_TIMESTAMP()"))
        db.execute(
            text(
                "INSERT INTO panel_sessions(token_hash,expires_at,credential_version) VALUES(:token,:expires,:version)"
            ),
            {"token": digest(token), "expires": expires, "version": credential_version()},
        )

    transaction(save)
    return {"access_token": token, "username": settings.panel_username}


# Hapus sesi panel terautentikasi dari database.
@router.post("/api/panel/logout", status_code=204)
def logout(token=Depends(require_panel)):
    transaction(
        lambda db: db.execute(
            text("DELETE FROM panel_sessions WHERE token_hash=:token"), {"token": digest(token)}
        )
    )


# Pertahankan URL lama dengan mengarahkannya ke panel terpadu.
@router.get("/admin", include_in_schema=False)
@router.get("/history", include_in_schema=False)
def old_panel():
    return RedirectResponse("/panel", status_code=307)


# Sajikan halaman panel dengan kebijakan sumber konten dan tanpa cache.
@router.get("/panel", include_in_schema=False)
def page():
    return FileResponse(
        ASSETS / "index.html",
        headers={
            "Cache-Control": "no-store",
            "Content-Security-Policy": "default-src 'self'; script-src 'self'; style-src 'self'; frame-ancestors 'none'; base-uri 'none'; form-action 'self'",
            "X-Content-Type-Options": "nosniff",
        },
    )


# Sajikan JavaScript atau CSS panel dari daftar nama yang diizinkan.
@router.get("/panel/assets/{asset}", include_in_schema=False)
def assets(asset: Literal["panel.js", "panel.css"]):
    return FileResponse(ASSETS / asset, headers={"Cache-Control": "no-store"})


# Sajikan dokumen ERD/Proses AI/Arsitektur/Kode AI/Diagram Alir AI (HTML mandiri berskrip inline). Sandbox memberi origin terpisah sehingga
# skrip dokumen tidak bisa membaca data panel di origin yang sama.
@router.get("/panel/dokumen/{nama}", include_in_schema=False)
def dokumen(nama: Literal["erd", "proses-ai", "arsitektur", "kode-ai", "diagram-alir-ai"]):
    return FileResponse(
        ASSETS.parent / "dokumen" / f"{nama}.html",
        headers={
            "Cache-Control": "no-cache",
            "Content-Security-Policy": "sandbox allow-scripts; default-src 'none'; script-src 'unsafe-inline'; style-src 'unsafe-inline'; img-src data:; frame-ancestors 'none'; base-uri 'none'; form-action 'none'",
            "X-Content-Type-Options": "nosniff",
        },
    )


# Model yang disiapkan ai-docker (jalankan.bat): 4B cepat, 14B lebih pintar tetapi lebih lambat.
MODEL_LOKAL = ("qwen3:4b-instruct", "qwen3:14b")


# Susun konfigurasi publik dan status kunci tanpa membocorkan isi rahasia.
def config_view():
    config = ai_runtime.current()
    return {
        "provider": config.ai_provider,
        "endpoint": config.ollama_base_url,
        "model": (
            config.ollama_model if config.ai_provider == "docker" else config.openrouter_model
        ),
        "api_configured": bool(config.openrouter_api_key_value),
        "key_source": config.openrouter_key_source,
        "default_configured": bool(settings.openrouter_default or settings.openrouter_api_key),
        "custom_configured": config.openrouter_custom_configured,
        # Pilihan model lokal: model ai-docker, model di link saat tes terakhir, dan yang aktif.
        "local_model": config.ollama_model,
        "local_models": sorted(
            {*MODEL_LOKAL, *brain_runtime.model_tautan_tersedia, config.ollama_model}
        ),
        "token_source": (
            "panel"
            if ai_runtime.diatur_panel("ollama_tunnel_token")
            else "env" if settings.ollama_tunnel_token else "none"
        ),
        "persisted": bool(ai_runtime.override),
    }


# Kembalikan konfigurasi AI setelah autentikasi panel berhasil.
@router.get("/api/panel/config")
def config(token=Depends(require_panel)):
    return config_view()


class Configuration(BaseModel):
    provider: Literal["api", "docker"]
    endpoint: str = Field(default="", max_length=2048)
    api_key: SecretStr | None = None
    key_source: Literal["default", "custom"] | None = None
    tunnel_token: SecretStr | None = None
    clear_tunnel_token: bool = False
    model: str | None = Field(default=None, max_length=100)


# Terima hanya tunnel HTTPS publik tanpa kredensial atau parameter URL.
def validate_endpoint(endpoint):
    url = urlsplit(endpoint)
    if (
        url.scheme != "https"
        or not url.hostname
        or url.username
        or url.password
        or url.query
        or url.fragment
    ):
        raise HTTPException(422, "Masukkan URL tunnel HTTPS tanpa password, query, atau fragment.")
    try:
        addresses = socket.getaddrinfo(url.hostname, url.port or 443, type=socket.SOCK_STREAM)
        if not addresses or any(
            not ipaddress.ip_address(item[4][0]).is_global for item in addresses
        ):
            raise ValueError()
    except (OSError, ValueError):
        raise HTTPException(422, "Tunnel harus memiliki alamat publik yang dapat diakses.")
    return endpoint.rstrip("/")


# Validasi endpoint dan sumber kunci sebelum menyimpan konfigurasi AI.
@router.put("/api/panel/config")
def set_config(body: Configuration, token=Depends(require_panel)):
    api_key = body.api_key.get_secret_value().strip() if body.api_key else ""
    if api_key and (len(api_key) > 1024 or any(c.isspace() for c in api_key)):
        raise HTTPException(400, "Format API key tidak valid.")
    tunnel_token = body.tunnel_token.get_secret_value().strip() if body.tunnel_token else ""
    if tunnel_token and (len(tunnel_token) > 512 or any(c.isspace() for c in tunnel_token)):
        raise HTTPException(400, "Format token tunnel tidak valid.")
    model = (body.model or "").strip()
    if model and not POLA_MODEL_TAUTAN.fullmatch(model):
        raise HTTPException(400, "Nama model tidak valid (contoh: qwen3:4b-instruct).")
    endpoint = body.endpoint.strip()
    if endpoint:
        endpoint = validate_endpoint(endpoint)
    elif body.provider == "docker":
        raise HTTPException(422, "URL tunnel Ollama wajib diisi.")
    else:
        endpoint = ai_runtime.current().ollama_base_url
    try:
        save_panel_configuration(
            body.provider,
            endpoint,
            api_key=api_key or None,
            key_source=body.key_source,
            tunnel_token=tunnel_token or None,
            clear_tunnel_token=body.clear_tunnel_token,
            model=model or None,
        )
    except PersistenceError as error:
        raise HTTPException(503, "Konfigurasi gagal disimpan.") from error
    except ValueError as error:
        raise HTTPException(400, str(error)) from error
    # Key OpenRouter dan link LLM juga dipakai rantai penulis kalimat NPC: bangun ulang dan cek di latar.
    brain_runtime.segarkan_penulis()
    return config_view()


# Uji generasi singkat pada provider aktif dan laporkan kegagalan tanpa rahasia.
@router.post("/api/panel/check-ai", dependencies=[Depends(limit_auth)])
async def check_ai(token=Depends(require_panel)):
    import asyncio

    config = ai_runtime.current()
    try:
        if config.ai_provider == "docker":
            # Only a configured tunnel is accepted for the production panel probe.
            validate_endpoint(config.ollama_base_url)
            reply = await asyncio.wait_for(
                local_reply(
                    "Balas hanya OK.",
                    config=config.model_copy(update={"ollama_max_output_tokens": 16}),
                ),
                timeout=35,
            )
        else:
            reply = await asyncio.wait_for(
                api_reply("Balas hanya OK.", config=config, max_tokens=128), timeout=35
            )
        return {
            "active": True,
            "message": "AI aktif dan berhasil menghasilkan jawaban.",
            "reply": reply[:200],
        }
    except HTTPException:
        raise
    except Exception as error:
        return {
            "active": False,
            "message": failure_message(error),
            "error_type": type(error).__name__,
        }


# Gabungkan arsip ruangan berhalaman dengan penanda ruangan yang masih aktif.
class AIProbe(BaseModel):
    message: str = Field(
        default="Aku melihat Pemain_B menghindari pertanyaan. Apa alibimu?",
        min_length=1,
        max_length=1000,
    )
    scenario: Literal["discussion", "vote", "night"] = "discussion"


# Kirim satu pesan uji ke provider aktif dengan skenario diskusi/vote/malam, lalu kembalikan jawabannya.
@router.post("/api/panel/test-ai", dependencies=[Depends(limit_auth)])
async def test_ai(body: AIProbe, token=Depends(require_panel)):
    if not body.message.strip():
        raise HTTPException(422, "Teks skenario tidak boleh kosong.")
    return await run_probe(body.message.strip(), body.scenario)


# Daftar room yang pernah tercatat (cursor ID), jumlah pesan, dan tanda room yang masih hidup di memori.
@router.get("/api/panel/rooms")
def rooms(after_id: int = Query(0, ge=0), token=Depends(require_panel)):
    rows = transaction(
        lambda db: [
            dict(row)
            for row in db.execute(
                text("""
        SELECT s.id,s.room_code,s.created_at,COUNT(m.id) AS message_count,MAX(m.created_at) AS last_message_at
        FROM game_sessions s LEFT JOIN chat_messages m ON m.game_session_id=s.id
        WHERE s.id > :after GROUP BY s.id,s.room_code,s.created_at ORDER BY s.id LIMIT 201
    """),
                {"after": after_id},
            ).mappings()
        ]
    )
    with room_service.lock:
        live = {room.code for room in room_service.rooms.values()}
    for row in rows:
        row["live"] = row["room_code"] in live
    return {
        "rooms": rows[:200],
        "has_more": len(rows) > 200,
        "next_after_id": rows[min(len(rows), 200) - 1]["id"] if rows else after_id,
    }


# Gabungkan jejak tersimpan dan jejak aktif; cursor menjaga urutan halaman.
# Daftar tanpa `penjelasan` (bisa ~10 KB per jejak); detail diambil lewat endpoint jejak tunggal.
@router.get("/api/panel/checker/{code}")
def checker(
    code: str, before: str | None = Query(None, max_length=100), token=Depends(require_panel)
):
    if len(code) > 36:
        raise HTTPException(422, "Kode room terlalu panjang.")
    # Timestamp+ID cursor offers stable pages, including equal timestamps.
    params = {"code": code, "before": before or "9999"}
    rows = transaction(
        lambda db: db.execute(
            text("""
        SELECT id,JSON_REMOVE(trace,'$.penjelasan') AS trace,
        CONCAT(DATE_FORMAT(created_at,'%Y-%m-%d %H:%i:%s'), '|', id) AS trace_cursor
        FROM checker_traces WHERE room_code=:code
        AND CONCAT(DATE_FORMAT(created_at,'%Y-%m-%d %H:%i:%s'), '|', id) < :before
        ORDER BY created_at DESC,id DESC LIMIT 101
    """),
            params,
        )
        .mappings()
        .all()
    )
    archived = [
        json.loads(row["trace"]) if isinstance(row["trace"], str) else row["trace"]
        for row in rows[:100]
    ]
    live = checker_service.list(code) if before is None else []
    merged = {item["id"]: item for item in archived}
    merged.update({item["id"]: item for item in live})
    traces = sorted(merged.values(), key=lambda item: item["created_at"], reverse=True)
    return {
        "traces": traces,
        "events": activity.list(code) if before is None else [],
        # Ringkasan room hanya di halaman pertama: status, komposisi role, metode/persona bot.
        "room": checker_service.ringkasan_room(code, traces) if before is None else None,
        "has_more": len(rows) > 100,
        "next_before": rows[min(len(rows), 100) - 1]["trace_cursor"] if rows else None,
    }


# Satu jejak lengkap beserta penjelasan keputusan bot (parameter, penalaran metode, NLG).
@router.get("/api/panel/checker/{code}/jejak/{trace_id}")
def checker_trace(code: str, trace_id: str, token=Depends(require_panel)):
    if len(code) > 36 or len(trace_id) != 32 or any(c not in "0123456789abcdef" for c in trace_id):
        raise HTTPException(422, "Kode room atau ID jejak tidak valid.")
    live = checker_service.cari(code, trace_id)
    if live is not None:
        return live
    stored = transaction(
        lambda db: db.execute(
            text("SELECT trace FROM checker_traces WHERE id=:id AND room_code=:code"),
            {"id": trace_id, "code": code},
        ).scalar()
    )
    if stored is None:
        raise HTTPException(404, "Jejak tidak ditemukan.")
    return json.loads(stored) if isinstance(stored, str) else stored


# Bangun kondisi SQL berparameter; rentang tanggal WIB dikonversi ke UTC.
def history_filter(room_code, date_from, date_to, sender_kind="all"):
    if date_from == date.min:
        raise HTTPException(422, "Tanggal awal terlalu kecil.")
    if date_from and date_to and date_from > date_to:
        raise HTTPException(422, "Tanggal awal harus sebelum atau sama dengan tanggal akhir.")
    clauses = ["1=1"]
    params = {}
    if sender_kind != "all":
        clauses.append("m.sender_kind=:sender_kind")
        params["sender_kind"] = sender_kind
    if room_code:
        clauses.append("s.room_code=:room")
        params["room"] = room_code
    if date_from:
        clauses.append("m.created_at >= :start")
        params["start"] = datetime.combine(date_from, time()) - timedelta(hours=7)
    if date_to:
        if date_to == date.max:
            raise HTTPException(422, "Tanggal akhir terlalu besar.")
        clauses.append("m.created_at < :end")
        params["end"] = datetime.combine(date_to + timedelta(days=1), time()) - timedelta(hours=7)
    return " AND ".join(clauses), params


# Ambil halaman pesan sesuai filter tanpa memuat seluruh arsip.
@router.get("/api/panel/history")
def history(
    room_code: str | None = Query(None, max_length=36),
    date_from: date | None = None,
    date_to: date | None = None,
    after_id: int = Query(0, ge=0),
    before_id: int | None = Query(None, ge=1),
    urut: Literal["lama", "baru"] = "lama",
    sender_kind: Literal["all", "human", "bot", "legacy"] = "all",
    token=Depends(require_panel),
):
    where, params = history_filter(room_code, date_from, date_to, sender_kind)
    # Halaman berikutnya: "lama" melanjutkan sesudah after_id, "baru" (terbaru dulu) sebelum before_id.
    if urut == "baru":
        arah = "DESC"
        if before_id:
            where += " AND m.id<:before"
            params["before"] = before_id
    else:
        arah = "ASC"
        where += " AND m.id>:after"
        params["after"] = after_id
    rows = transaction(
        lambda db: [
            dict(row)
            for row in db.execute(
                text("""
        SELECT m.id,m.sender_name,m.sender_kind,m.message,m.nlu,m.created_at,m.match_id,m.round_number,m.phase,s.room_code
        FROM chat_messages m LEFT JOIN game_sessions s ON s.id=m.game_session_id
        WHERE """ + where + f" ORDER BY m.id {arah} LIMIT 201"),
                params,
            ).mappings()
        ]
    )
    for row in rows:  # bacaan IndoBERT saat game berjalan (JSON; kosong untuk pesan lama)
        if isinstance(row["nlu"], str):
            row["nlu"] = json.loads(row["nlu"])
    terakhir = rows[min(len(rows), 200) - 1]["id"] if rows else None
    return {
        "messages": rows[:200],
        "has_more": len(rows) > 200,
        # id pesan terakhir di halaman ini: lanjutkan dengan after_id (urut lama) atau before_id (urut baru).
        "next_after_id": terakhir if terakhir is not None else after_id,
    }


# Kolom CSV riwayat = format dataset NLU (sama dengan dataset latih IndoBERT), lalu info pesan. label_intent dan
# target adalah bacaan IndoBERT saat game berjalan, jadi perlu dicek manusia sebelum dipakai sebagai label.
KOLOM_CSV = ["pengirim", "teks_chat", "label_intent", "chat_sebelumnya", "daftar_pemain", "target",
             "session_id", "chat_id", "room_code", "confidence", "sender_kind", "waktu_utc"]  # fmt: skip


# Target bacaan → [{pemain, relasi}]. Bacaan baru menyimpan dict; konteks lama menyimpan teks "NOX: offend (0.88)".
def target_dataset(daftar):
    hasil = []
    for t in daftar or []:
        if isinstance(t, dict):
            hasil.append({"pemain": t["pemain"], "relasi": t["relasi"]})
        elif cocok := re.match(r"(.+): (offend|defend|neutral)\b", str(t)):
            hasil.append({"pemain": cocok[1], "relasi": cocok[2]})
    return hasil


# Satu pesan → satu baris dataset. Pesan tanpa bacaan IndoBERT (arsip lama) → kolom bacaan kosong.
def baris_dataset(chat_id, pengirim, jenis, teks, nlu, match_id, room_code, waktu):
    data = (json.loads(nlu) if isinstance(nlu, str) else nlu) or {}
    teks_json = lambda x: json.dumps(x, ensure_ascii=False)  # noqa: E731
    sebelum = [
        {"pengirim": c["pengirim"], "teks_chat": c["teks"], "label_intent": c.get("intent"),
         "target": target_dataset(c.get("target"))}
        for c in data.get("konteks") or []
    ]  # fmt: skip
    return [
        pengirim, teks, data.get("intent", ""),
        teks_json(sebelum) if data else "", teks_json(data.get("daftar_pemain") or []) if data else "",
        teks_json(target_dataset(data.get("target"))) if data else "",
        match_id or room_code or "", chat_id, room_code or "", data.get("confidence", ""), jenis,
        waktu.isoformat(sep=" ") if hasattr(waktu, "isoformat") else (waktu or ""),
    ]  # fmt: skip


# Ekspor snapshot riwayat menjadi CSV dengan pembacaan database per halaman.
@router.get("/api/panel/history.csv")
def download(
    date_from: date | None = None,
    date_to: date | None = None,
    room_code: str | None = Query(None, max_length=36),
    sender_kind: Literal["all", "human", "bot", "legacy"] = "all",
    urut: Literal["lama", "baru"] = "lama",
    token=Depends(require_panel),
):
    where, params = history_filter(room_code, date_from, date_to, sender_kind)
    # Build on disk beyond 1 MB; no giant in-memory transcript or long open DB transaction.
    output = SpooledTemporaryFile(max_size=1024 * 1024, mode="w+b")

    # Encode satu baris CSV sebagai UTF-8 ke berkas sementara ekspor.
    def write_row(values):
        buffer = io.StringIO(newline="")
        csv.writer(buffer).writerow(values)
        output.write(buffer.getvalue().encode("utf-8"))

    try:
        output.write(b"\xef\xbb\xbf")
        write_row(KOLOM_CSV)
        maximum = transaction(
            lambda db: db.execute(text("SELECT COALESCE(MAX(id),0) FROM chat_messages")).scalar()
        )
        # Snapshot sampai id maksimum saat ekspor dimulai; halaman berjalan naik ("lama") atau turun ("baru").
        baru = urut == "baru"
        batas = maximum + 1 if baru else 0
        syarat = " AND m.id<:batas" if baru else " AND m.id>:batas AND m.id<=:maximum"
        while True:
            page_params = {**params, "batas": batas, "maximum": maximum}
            rows = transaction(
                lambda db: db.execute(
                    text(
                        """
                SELECT m.id,m.sender_name,m.sender_kind,m.message,m.nlu,m.match_id,s.room_code,m.created_at
                FROM chat_messages m LEFT JOIN game_sessions s ON s.id=m.game_session_id
                WHERE """
                        + where
                        + syarat
                        + f" ORDER BY m.id {'DESC' if baru else 'ASC'} LIMIT 1000"
                    ),
                    page_params,
                ).all()
            )
            if not rows:
                break
            for row in rows:
                write_row(baris_dataset(*row))
            batas = rows[-1][0]
        output.seek(0)
    except BaseException:
        output.close()
        raise

    # Kirim potongan berkas ekspor dan tutup berkas saat streaming selesai.
    def chunks():
        try:
            while chunk := output.read(65536):
                yield chunk
        finally:
            output.close()

    return StreamingResponse(
        chunks(),
        media_type="text/csv; charset=utf-8",
        headers={
            "Content-Disposition": 'attachment; filename="riwayat-chat.csv"',
            "Cache-Control": "no-store",
        },
    )


# UJI AI: skenario permainan terisolasi dengan classifier/provider asli; pertandingan pemain tidak diubah.
async def run_probe(message, scenario):
    started = perf_counter()
    config = ai_runtime.current()
    trace = {
        "id": uuid4().hex,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "scenario": scenario,
        "message": message,
        "stage": "preparing",
        "active": False,
        "valid_decision": False,
        "timings": {},
        "provider": config.ai_provider,
        "model": (
            config.ollama_model if config.ai_provider == "docker" else config.openrouter_model
        ),
        "request": None,
        "response": None,
        "output": None,
        "note": "Skenario terisolasi; tidak mengirim chat atau menjalankan aksi di room pemain.",
    }
    try:
        with measure(trace, "prompt_ms"):
            match = Match(["Pemain_A", "Pemain_B", "Pemain_C", "Pemain_D", "Pemain_E"], ["NOX"])
            for name, role in zip(
                match.players, ["hitman", "stalker", "civilian", "civilian", "civilian", "spy"]
            ):
                match.players[name].role = role
            match.phase = {"discussion": "day", "vote": "tribunal", "night": "night"}[scenario]
            match.add_message("Pemain_A", message)
            context = npc_context(match, "NOX")
            trace["context"] = context
            trace["prompt"] = decision_prompt(context)
        trace["stage"] = "llm_pending"
        with capture_exchange(trace):
            decision = await asyncio.wait_for(request_decision(trace["prompt"], config), timeout=35)
        trace["active"] = True
        trace["output"] = decision.model_dump()
        with measure(trace, "validation_ms"):
            if decision.action == "wait":
                legal = decision.target is None
            else:
                legal = decision.target in context["legal_actions"].get(decision.action, [])
            legal = legal and (context["me"]["can_chat"] or not decision.message.strip())
            trace["valid_decision"] = legal
        trace["stage"] = "complete" if legal else "invalid_decision"
        trace["message_status"] = (
            "AI merespons dan keputusan valid."
            if legal
            else "AI merespons, tetapi keputusan tidak sesuai aturan skenario."
        )
    except Exception as error:
        response = trace.get("response") or {}
        trace["active"] = bool(response.get("body", {}).get("output"))
        trace["stage"] = "invalid_response" if trace["active"] else "failed"
        trace["error_type"] = type(error).__name__
        trace["message_status"] = (
            "Provider merespons, tetapi output bukan JSON keputusan yang valid."
            if trace["active"]
            else failure_message(error)
        )
    finally:
        trace["duration_ms"] = round((perf_counter() - started) * 1000, 2)
        response = trace.get("response") or {}
        trace["provider_reachable"] = 200 <= response.get("status_code", 0) < 300
        if not trace["active"] and trace["provider_reachable"]:
            trace["message_status"] = (
                "Provider terhubung, tetapi output kosong karena batas token tercapai."
                if response.get("body", {}).get("finish_reason") == "length"
                else "Provider terhubung, tetapi belum menghasilkan teks yang dapat digunakan."
            )
    return trace
