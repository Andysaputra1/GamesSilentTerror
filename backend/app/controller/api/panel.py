"""Production administration, isolated from player authentication."""

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
from fastapi import APIRouter, Depends, HTTPException, Query, Response
from fastapi.responses import FileResponse, StreamingResponse
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
from app.module.room_service import room_service
from app.controller.middleware.auth_limits import limit_auth
from app.controller.middleware.safe_validation import SafeValidationRoute

router = APIRouter(tags=["panel"], route_class=SafeValidationRoute)
ASSETS = Path(__file__).resolve().parents[3] / "public" / "panel"
bearer = HTTPBearer(auto_error=False)


# Jalankan transaksi panel dan ubah kegagalan penyimpanan menjadi HTTP 503.
def transaction(operasi):
    try:
        return PersistenceService._run(operasi)
    except PersistenceError as error:
        raise HTTPException(
            503, "Database panel belum siap. Periksa koneksi dan migrasi V5/V6."
        ) from error


# Buat sidik kredensial agar pergantian username/password membatalkan sesi lama.
def credential_version():
    hash_password = (
        settings.panel_password_hash.get_secret_value() if settings.panel_password_hash else ""
    )
    return hashlib.sha256((settings.panel_username + hash_password).encode()).hexdigest()


# Hash token panel sebelum pencarian atau penyimpanan di database.
def digest(token):
    return hashlib.sha256(token.encode()).hexdigest()


# Kolom JSON dari database bisa berupa teks atau sudah menjadi objek.
def _baca_kolom_json(nilai):
    return json.loads(nilai) if isinstance(nilai, str) else nilai


# Validasi hash token, kedaluwarsa, dan versi kredensial panel.
def require_panel(
    response: Response, credentials: HTTPAuthorizationCredentials | None = Depends(bearer)
):
    response.headers["Cache-Control"] = "no-store"
    if not credentials or not settings.panel_password_hash:
        raise HTTPException(401, "Login administrator diperlukan.")
    sesi_berlaku = transaction(
        lambda database: database.execute(
            text("""
        SELECT token_hash FROM panel_sessions WHERE token_hash=:token
        AND expires_at > UTC_TIMESTAMP() AND credential_version=:version
    """),
            {"token": digest(credentials.credentials), "version": credential_version()},
        ).scalar()
    )
    if not sesi_berlaku:
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
        hash_password = base64.b64decode(
            settings.panel_password_hash.get_secret_value(), validate=True
        ).decode()
    except (ValueError, UnicodeError):
        raise HTTPException(503, "Konfigurasi login panel tidak valid.")
    # Password selalu dihitung lebih dulu agar lama proses tidak membocorkan benar-salahnya username.
    password_cocok = verify_password(body.password, hash_password)
    if (
        not hmac.compare_digest(body.username.encode(), settings.panel_username.encode())
        or not password_cocok
    ):
        raise HTTPException(401, "Username atau password salah.")
    token_sesi = secrets.token_urlsafe(32)
    waktu_kedaluwarsa = datetime.now(timezone.utc).replace(tzinfo=None) + timedelta(hours=8)

    # Bersihkan sesi kedaluwarsa dan simpan hash sesi baru dalam satu transaksi.
    def simpan_sesi(database):
        database.execute(text("DELETE FROM panel_sessions WHERE expires_at <= UTC_TIMESTAMP()"))
        database.execute(
            text(
                "INSERT INTO panel_sessions(token_hash,expires_at,credential_version) VALUES(:token,:expires,:version)"
            ),
            {
                "token": digest(token_sesi),
                "expires": waktu_kedaluwarsa,
                "version": credential_version(),
            },
        )

    transaction(simpan_sesi)
    return {"access_token": token_sesi}


# Hapus sesi panel terautentikasi dari database.
@router.post("/api/panel/logout", status_code=204)
def logout(token=Depends(require_panel)):
    transaction(
        lambda database: database.execute(
            text("DELETE FROM panel_sessions WHERE token_hash=:token"), {"token": digest(token)}
        )
    )


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


# Sajikan dokumen ERD/Proses AI/Arsitektur/Kode dan Diagram Alir Fuzzy + NLU (HTML mandiri berskrip inline). Sandbox memberi origin terpisah sehingga
# skrip dokumen tidak bisa membaca data panel di origin yang sama.
@router.get("/panel/dokumen/{nama}", include_in_schema=False)
def dokumen(
    nama: Literal[
        "erd", "proses-ai", "arsitektur",
        "kode-fuzzy", "diagram-alir-fuzzy",
        "kode-nlu-intent", "kode-nlu-target", "diagram-alir-nlu",
    ],
):  # fmt: skip
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


# Daftar room yang pernah tercatat (cursor ID), jumlah pesan, dan tanda room yang masih hidup di memori.
@router.get("/api/panel/rooms")
def rooms(after_id: int = Query(0, ge=0), token=Depends(require_panel)):
    # LIMIT 201 = satu baris lebih dari isi halaman, untuk tahu masih ada halaman berikutnya.
    daftar_baris = transaction(
        lambda database: [
            dict(baris)
            for baris in database.execute(
                text("""
        SELECT s.id,s.room_code,s.created_at,COUNT(m.id) AS message_count
        FROM game_sessions s LEFT JOIN chat_messages m ON m.game_session_id=s.id
        WHERE s.id > :after GROUP BY s.id,s.room_code,s.created_at ORDER BY s.id LIMIT 201
    """),
                {"after": after_id},
            ).mappings()
        ]
    )
    with room_service.lock:
        kode_room_hidup = {room.code for room in room_service.rooms.values()}
    for baris in daftar_baris:
        baris["live"] = baris["room_code"] in kode_room_hidup
    isi_halaman = daftar_baris[:200]
    return {
        "rooms": isi_halaman,
        "has_more": len(daftar_baris) > 200,
        "next_after_id": isi_halaman[-1]["id"] if isi_halaman else after_id,
    }


# Gabungkan jejak tersimpan dan jejak aktif; cursor menjaga urutan halaman.
# Daftar tanpa `penjelasan` (bisa ~10 KB per jejak); detail diambil lewat endpoint jejak tunggal.
@router.get("/api/panel/checker/{code}")
def checker(
    code: str, before: str | None = Query(None, max_length=100), token=Depends(require_panel)
):
    if len(code) > 36:
        raise HTTPException(422, "Kode room terlalu panjang.")
    # Cursor waktu+ID membuat halaman stabil walau ada waktu yang sama. LIMIT 101 = satu baris lebih
    # dari isi halaman, untuk tahu masih ada halaman berikutnya.
    daftar_baris = transaction(
        lambda database: database.execute(
            text("""
        SELECT JSON_REMOVE(trace,'$.penjelasan') AS trace,
        CONCAT(DATE_FORMAT(created_at,'%Y-%m-%d %H:%i:%s'), '|', id) AS trace_cursor
        FROM checker_traces WHERE room_code=:code
        AND CONCAT(DATE_FORMAT(created_at,'%Y-%m-%d %H:%i:%s'), '|', id) < :before
        ORDER BY created_at DESC,id DESC LIMIT 101
    """),
            {"code": code, "before": before or "9999"},
        )
        .mappings()
        .all()
    )
    isi_halaman = daftar_baris[:100]
    # Jejak di memori menimpa arsip ber-ID sama; halaman lanjutan hanya berisi arsip.
    jejak_arsip = [_baca_kolom_json(baris["trace"]) for baris in isi_halaman]
    jejak_aktif = checker_service.list(code) if before is None else []
    jejak_per_id = {jejak["id"]: jejak for jejak in jejak_arsip}
    jejak_per_id.update({jejak["id"]: jejak for jejak in jejak_aktif})
    jejak_terbaru_dulu = sorted(
        jejak_per_id.values(), key=lambda jejak: jejak["created_at"], reverse=True
    )
    return {
        "traces": jejak_terbaru_dulu,
        "events": activity.list(code) if before is None else [],
        # Ringkasan room hanya di halaman pertama: status, komposisi role, metode/persona bot.
        "room": (
            checker_service.ringkasan_room(code, jejak_terbaru_dulu) if before is None else None
        ),
        "has_more": len(daftar_baris) > 100,
        "next_before": isi_halaman[-1]["trace_cursor"] if isi_halaman else None,
    }


# Satu jejak lengkap beserta penjelasan keputusan bot (parameter, penalaran metode, NLG).
@router.get("/api/panel/checker/{code}/jejak/{trace_id}")
def checker_trace(code: str, trace_id: str, token=Depends(require_panel)):
    if (
        len(code) > 36
        or len(trace_id) != 32
        or any(karakter not in "0123456789abcdef" for karakter in trace_id)
    ):
        raise HTTPException(422, "Kode room atau ID jejak tidak valid.")
    jejak_aktif = checker_service.cari(code, trace_id)
    if jejak_aktif is not None:
        return jejak_aktif
    jejak_arsip = transaction(
        lambda database: database.execute(
            text("SELECT trace FROM checker_traces WHERE id=:id AND room_code=:code"),
            {"id": trace_id, "code": code},
        ).scalar()
    )
    if jejak_arsip is None:
        raise HTTPException(404, "Jejak tidak ditemukan.")
    return _baca_kolom_json(jejak_arsip)


# Bangun kondisi SQL berparameter; rentang tanggal WIB dikonversi ke UTC.
def history_filter(room_code, date_from, date_to, sender_kind="all"):
    if date_from == date.min:
        raise HTTPException(422, "Tanggal awal terlalu kecil.")
    if date_from and date_to and date_from > date_to:
        raise HTTPException(422, "Tanggal awal harus sebelum atau sama dengan tanggal akhir.")
    selisih_wib = timedelta(hours=7)
    daftar_syarat = ["1=1"]
    parameter_sql = {}
    if sender_kind != "all":
        daftar_syarat.append("m.sender_kind=:sender_kind")
        parameter_sql["sender_kind"] = sender_kind
    if room_code:
        daftar_syarat.append("s.room_code=:room")
        parameter_sql["room"] = room_code
    if date_from:
        daftar_syarat.append("m.created_at >= :start")
        parameter_sql["start"] = datetime.combine(date_from, time()) - selisih_wib
    if date_to:
        if date_to == date.max:
            raise HTTPException(422, "Tanggal akhir terlalu besar.")
        daftar_syarat.append("m.created_at < :end")
        parameter_sql["end"] = datetime.combine(date_to + timedelta(days=1), time()) - selisih_wib
    return " AND ".join(daftar_syarat), parameter_sql


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
    syarat_sql, parameter_sql = history_filter(room_code, date_from, date_to, sender_kind)
    # Halaman berikutnya: "lama" melanjutkan sesudah after_id, "baru" (terbaru dulu) sebelum before_id.
    if urut == "baru":
        arah = "DESC"
        if before_id:
            syarat_sql += " AND m.id<:before"
            parameter_sql["before"] = before_id
    else:
        arah = "ASC"
        syarat_sql += " AND m.id>:after"
        parameter_sql["after"] = after_id
    # LIMIT 201 = satu baris lebih dari isi halaman, untuk tahu masih ada halaman berikutnya.
    daftar_baris = transaction(
        lambda database: [
            dict(baris)
            for baris in database.execute(
                text("""
        SELECT m.id,m.sender_name,m.sender_kind,m.message,m.nlu,m.created_at,m.round_number,m.phase,s.room_code
        FROM chat_messages m LEFT JOIN game_sessions s ON s.id=m.game_session_id
        WHERE """ + syarat_sql + f" ORDER BY m.id {arah} LIMIT 201"),
                parameter_sql,
            ).mappings()
        ]
    )
    for baris in daftar_baris:  # bacaan IndoBERT saat game berjalan (JSON; kosong untuk pesan lama)
        baris["nlu"] = _baca_kolom_json(baris["nlu"])
    isi_halaman = daftar_baris[:200]
    return {
        "messages": isi_halaman,
        "has_more": len(daftar_baris) > 200,
        # id pesan terakhir di halaman ini: lanjutkan dengan after_id (urut lama) atau before_id (urut baru).
        "next_after_id": isi_halaman[-1]["id"] if isi_halaman else after_id,
    }


# Kolom CSV riwayat = format dataset NLU (sama dengan dataset latih IndoBERT), lalu info pesan. label_intent dan
# target adalah bacaan IndoBERT saat game berjalan, jadi perlu dicek manusia sebelum dipakai sebagai label.
KOLOM_CSV = ["pengirim", "teks_chat", "label_intent", "chat_sebelumnya", "daftar_pemain", "target",
             "session_id", "chat_id", "room_code", "confidence", "sender_kind", "waktu_utc"]  # fmt: skip


# Target bacaan → [{pemain, relasi}]. Bacaan baru menyimpan dict; konteks lama menyimpan teks "NOX: offend (0.88)".
def target_dataset(daftar_target):
    hasil = []
    for target in daftar_target or []:
        if isinstance(target, dict):
            hasil.append({"pemain": target["pemain"], "relasi": target["relasi"]})
        elif cocok := re.match(r"(.+): (offend|defend|neutral)\b", str(target)):
            hasil.append({"pemain": cocok[1], "relasi": cocok[2]})
    return hasil


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
    # INPUT: filter yang sama dengan daftar riwayat
    syarat_sql, parameter_sql = history_filter(room_code, date_from, date_to, sender_kind)

    # PROSES: CSV ditulis ke berkas sementara. Lewat 1 MB berkas pindah ke disk, jadi transkrip besar
    # tidak menumpuk di memori dan transaksi database tidak terbuka lama.
    berkas_csv = SpooledTemporaryFile(max_size=1024 * 1024, mode="w+b")

    # Encode satu baris CSV sebagai UTF-8 ke berkas sementara ekspor.
    def tulis_baris_csv(nilai_kolom):
        penampung = io.StringIO(newline="")
        csv.writer(penampung).writerow(nilai_kolom)
        berkas_csv.write(penampung.getvalue().encode("utf-8"))

    def teks_json(nilai):
        return json.dumps(nilai, ensure_ascii=False)

    try:
        berkas_csv.write(b"\xef\xbb\xbf")
        tulis_baris_csv(KOLOM_CSV)
        id_maksimum = transaction(
            lambda database: database.execute(
                text("SELECT COALESCE(MAX(id),0) FROM chat_messages")
            ).scalar()
        )
        # Snapshot sampai id maksimum saat ekspor dimulai; halaman berjalan naik ("lama") atau turun ("baru").
        urut_baru = urut == "baru"
        batas = id_maksimum + 1 if urut_baru else 0
        syarat_halaman = " AND m.id<:batas" if urut_baru else " AND m.id>:batas AND m.id<=:maximum"
        while True:
            parameter_halaman = {**parameter_sql, "batas": batas, "maximum": id_maksimum}
            daftar_baris = transaction(
                lambda database: database.execute(
                    text(
                        """
                SELECT m.id,m.sender_name,m.sender_kind,m.message,m.nlu,m.match_id,s.room_code,m.created_at
                FROM chat_messages m LEFT JOIN game_sessions s ON s.id=m.game_session_id
                WHERE """
                        + syarat_sql
                        + syarat_halaman
                        + f" ORDER BY m.id {'DESC' if urut_baru else 'ASC'} LIMIT 1000"
                    ),
                    parameter_halaman,
                ).all()
            )
            if not daftar_baris:
                break
            for id_chat, pengirim, jenis, teks, nlu, id_match, kode_room, waktu in daftar_baris:
                # Satu pesan → satu baris dataset, urutannya mengikuti KOLOM_CSV.
                # Pesan tanpa bacaan IndoBERT (arsip lama) → kolom bacaan kosong.
                bacaan = _baca_kolom_json(nlu) or {}
                chat_sebelumnya = [
                    {
                        "pengirim": pesan["pengirim"],
                        "teks_chat": pesan["teks"],
                        "label_intent": pesan.get("intent"),
                        "target": target_dataset(pesan.get("target")),
                    }
                    for pesan in bacaan.get("konteks") or []
                ]
                tulis_baris_csv(
                    [
                        pengirim,
                        teks,
                        bacaan.get("intent", ""),
                        teks_json(chat_sebelumnya) if bacaan else "",
                        teks_json(bacaan.get("daftar_pemain") or []) if bacaan else "",
                        teks_json(target_dataset(bacaan.get("target"))) if bacaan else "",
                        id_match or kode_room or "",
                        id_chat,
                        kode_room or "",
                        bacaan.get("confidence", ""),
                        jenis,
                        waktu.isoformat(sep=" ") if hasattr(waktu, "isoformat") else (waktu or ""),
                    ]
                )
            batas = daftar_baris[-1][0]
        berkas_csv.seek(0)
    except BaseException:
        berkas_csv.close()
        raise

    # Kirim potongan berkas ekspor dan tutup berkas saat streaming selesai.
    def kirim_potongan_berkas():
        try:
            while potongan := berkas_csv.read(65536):
                yield potongan
        finally:
            berkas_csv.close()

    # OUTPUT: berkas dialirkan ke browser sedikit demi sedikit
    return StreamingResponse(
        kirim_potongan_berkas(),
        media_type="text/csv; charset=utf-8",
        headers={
            "Content-Disposition": 'attachment; filename="riwayat-chat.csv"',
            "Cache-Control": "no-store",
        },
    )
