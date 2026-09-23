"""Production administration, isolated from player authentication."""
import base64
import csv
import hashlib
import hmac
import io
import json
import secrets
import socket
import ipaddress
from datetime import date, datetime, time, timedelta, timezone
from pathlib import Path
from typing import Literal
from urllib.parse import urlsplit
from tempfile import SpooledTemporaryFile
from fastapi import APIRouter, Depends, HTTPException, Query, Response
from fastapi.responses import FileResponse, StreamingResponse, RedirectResponse
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from pydantic import BaseModel, Field, SecretStr
from sqlalchemy import text
from config.settings import settings
from services.password_service import verify_password
from services.persistence_service import PersistenceService, PersistenceError
from services.ai_runtime_service import ai_runtime, save_panel_configuration
from services.checker_service import checker_service
from services.activity_service import activity
from services.room_service import room_service
from controller.middleware.auth_limits import limit_auth
from module.ollama_client import generate_reply as local_reply
from module.openrouter_client import generate_reply as api_reply, failure_message

router = APIRouter(tags=["panel"])
ASSETS = Path(__file__).resolve().parents[2] / "public" / "panel"
bearer = HTTPBearer(auto_error=False)


def transaction(operation):
    try:
        return PersistenceService._run(operation)
    except PersistenceError as error:
        raise HTTPException(503, "Database panel belum siap. Periksa koneksi dan migrasi V5/V6.") from error


def credential_version():
    raw = settings.panel_password_hash.get_secret_value() if settings.panel_password_hash else ""
    return hashlib.sha256((settings.panel_username + raw).encode()).hexdigest()


def digest(token):
    return hashlib.sha256(token.encode()).hexdigest()


def require_panel(response: Response, credentials: HTTPAuthorizationCredentials | None = Depends(bearer)):
    response.headers["Cache-Control"] = "no-store"
    if not credentials or not settings.panel_password_hash:
        raise HTTPException(401, "Login administrator diperlukan.")
    valid = transaction(lambda db: db.execute(text("""
        SELECT token_hash FROM panel_sessions WHERE token_hash=:token
        AND expires_at > UTC_TIMESTAMP() AND credential_version=:version
    """), {"token": digest(credentials.credentials), "version": credential_version()}).scalar())
    if not valid:
        raise HTTPException(401, "Sesi panel berakhir. Silakan login lagi.")
    return credentials.credentials


class Login(BaseModel):
    username: str = Field(min_length=1, max_length=100)
    password: str = Field(min_length=1, max_length=256)


@router.post("/api/panel/login", dependencies=[Depends(limit_auth)])
def login(body: Login, response: Response):
    response.headers["Cache-Control"] = "no-store"
    if not settings.panel_password_hash:
        raise HTTPException(503, "Password administrator belum disiapkan di server.")
    try:
        encoded = base64.b64decode(settings.panel_password_hash.get_secret_value(), validate=True).decode()
    except (ValueError, UnicodeError):
        raise HTTPException(503, "Konfigurasi login panel tidak valid.")
    password_ok = verify_password(body.password, encoded)
    if not hmac.compare_digest(body.username.encode(), settings.panel_username.encode()) or not password_ok:
        raise HTTPException(401, "Username atau password salah.")
    token = secrets.token_urlsafe(32)
    expires = datetime.now(timezone.utc).replace(tzinfo=None) + timedelta(hours=8)
    def save(db):
        db.execute(text("DELETE FROM panel_sessions WHERE expires_at <= UTC_TIMESTAMP()"))
        db.execute(text("INSERT INTO panel_sessions(token_hash,expires_at,credential_version) VALUES(:token,:expires,:version)"),
                   {"token": digest(token), "expires": expires, "version": credential_version()})
    transaction(save)
    return {"access_token": token, "username": settings.panel_username}


@router.post("/api/panel/logout", status_code=204)
def logout(token=Depends(require_panel)):
    transaction(lambda db: db.execute(text("DELETE FROM panel_sessions WHERE token_hash=:token"), {"token": digest(token)}))


@router.get("/admin", include_in_schema=False)
@router.get("/history", include_in_schema=False)
def old_panel():
    return RedirectResponse("/panel", status_code=307)


@router.get("/panel", include_in_schema=False)
def page():
    return FileResponse(ASSETS / "index.html", headers={"Cache-Control": "no-store",
        "Content-Security-Policy": "default-src 'self'; script-src 'self'; style-src 'self'; frame-ancestors 'none'; base-uri 'none'; form-action 'self'",
        "X-Content-Type-Options": "nosniff"})


@router.get("/panel/assets/{asset}", include_in_schema=False)
def assets(asset: Literal["panel.js", "panel.css"]):
    return FileResponse(ASSETS / asset, headers={"Cache-Control": "no-store"})


def config_view():
    config = ai_runtime.current()
    return {"provider": config.ai_provider, "endpoint": config.ollama_base_url,
            "model": "qwen/qwen3-14b" if config.ai_provider == "api" else "qwen3:14b",
            "api_configured": bool(config.openrouter_api_key_value),
            "key_source": config.openrouter_key_source,
            "default_configured": bool(settings.openrouter_default or settings.openrouter_api_key),
            "custom_configured": config.openrouter_custom_configured, "persisted": bool(ai_runtime.override)}


@router.get("/api/panel/config")
def config(token=Depends(require_panel)):
    return config_view()


class Configuration(BaseModel):
    provider: Literal["api", "docker"]
    endpoint: str = Field(default="", max_length=2048)
    api_key: SecretStr | None = None
    key_source: Literal["default", "custom"] | None = None


def validate_endpoint(endpoint):
    url = urlsplit(endpoint)
    if url.scheme != "https" or not url.hostname or url.username or url.password or url.query or url.fragment:
        raise HTTPException(422, "Masukkan URL tunnel HTTPS tanpa password, query, atau fragment.")
    try:
        addresses = socket.getaddrinfo(url.hostname, url.port or 443, type=socket.SOCK_STREAM)
        if not addresses or any(not ipaddress.ip_address(item[4][0]).is_global for item in addresses):
            raise ValueError()
    except (OSError, ValueError):
        raise HTTPException(422, "Tunnel harus memiliki alamat publik yang dapat diakses.")
    return endpoint.rstrip("/")


@router.put("/api/panel/config")
def set_config(body: Configuration, token=Depends(require_panel)):
    api_key = body.api_key.get_secret_value().strip() if body.api_key else ""
    if api_key and (len(api_key) > 1024 or any(c.isspace() for c in api_key)):
        raise HTTPException(400, "Format API key tidak valid.")
    endpoint = body.endpoint.strip()
    if endpoint:
        endpoint = validate_endpoint(endpoint)
    elif body.provider == "docker":
        raise HTTPException(422, "URL tunnel Ollama wajib diisi.")
    else:
        endpoint = ai_runtime.current().ollama_base_url
    try:
        save_panel_configuration(body.provider, endpoint, api_key=api_key or None, key_source=body.key_source)
    except PersistenceError as error:
        raise HTTPException(503, "Konfigurasi gagal disimpan.") from error
    except ValueError as error:
        raise HTTPException(400, str(error)) from error
    return config_view()


@router.post("/api/panel/check-ai", dependencies=[Depends(limit_auth)])
async def check_ai(token=Depends(require_panel)):
    import asyncio
    config = ai_runtime.current().model_copy(update={"api_backend": "openrouter", "ollama_model": "qwen3:14b"})
    try:
        if config.ai_provider == "docker":
            # Only a configured tunnel is accepted for the production panel probe.
            validate_endpoint(config.ollama_base_url)
            reply = await asyncio.wait_for(local_reply("Balas hanya OK.", config=config.model_copy(update={"ollama_max_output_tokens": 16})), timeout=35)
        else:
            reply = await asyncio.wait_for(api_reply("Balas hanya OK.", config=config, max_tokens=128), timeout=35)
        return {"active": True, "message": "AI aktif dan berhasil menghasilkan jawaban.", "reply": reply[:200]}
    except HTTPException:
        raise
    except Exception as error:
        return {"active": False, "message": failure_message(error), "error_type": type(error).__name__}


@router.get("/api/panel/rooms")
def rooms(after_id: int = Query(0, ge=0), token=Depends(require_panel)):
    rows = transaction(lambda db: [dict(row) for row in db.execute(text("""
        SELECT s.id,s.room_code,COUNT(m.id) AS message_count,MAX(m.created_at) AS last_message_at
        FROM game_sessions s LEFT JOIN chat_messages m ON m.game_session_id=s.id
        WHERE s.id > :after GROUP BY s.id,s.room_code ORDER BY s.id LIMIT 201
    """), {"after": after_id}).mappings()])
    with room_service.lock:
        live = {room.code for room in room_service.rooms.values()}
    for row in rows:
        row["live"] = row["room_code"] in live
    return {"rooms": rows[:200], "has_more": len(rows)>200, "next_after_id": rows[min(len(rows),200)-1]["id"] if rows else after_id}


@router.get("/api/panel/checker/{code}")
def checker(code: str, before: str | None = Query(None, max_length=100), token=Depends(require_panel)):
    if len(code)>36:
        raise HTTPException(422, "Kode room terlalu panjang.")
    # Timestamp+ID cursor offers stable pages, including equal timestamps.
    params = {"code": code, "before": before or "9999"}
    rows = transaction(lambda db: db.execute(text("""
        SELECT id,trace,CONCAT(DATE_FORMAT(created_at,'%Y-%m-%d %H:%i:%s'), '|', id) AS trace_cursor
        FROM checker_traces WHERE room_code=:code
        AND CONCAT(DATE_FORMAT(created_at,'%Y-%m-%d %H:%i:%s'), '|', id) < :before
        ORDER BY created_at DESC,id DESC LIMIT 101
    """), params).mappings().all())
    archived = [json.loads(row["trace"]) if isinstance(row["trace"],str) else row["trace"] for row in rows[:100]]
    live = checker_service.list(code) if before is None else []
    merged = {item["id"]: item for item in archived}
    merged.update({item["id"]: item for item in live})
    return {"traces": sorted(merged.values(), key=lambda item:item["created_at"], reverse=True),
            "events": activity.list(code) if before is None else [], "has_more":len(rows)>100,
            "next_before": rows[min(len(rows),100)-1]["trace_cursor"] if rows else None}


def history_filter(room_code, date_from, date_to):
    if date_from == date.min:
        raise HTTPException(422, "Tanggal awal terlalu kecil.")
    if date_from and date_to and date_from > date_to:
        raise HTTPException(422, "Tanggal awal harus sebelum atau sama dengan tanggal akhir.")
    clauses = ["1=1"]
    params = {}
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


@router.get("/api/panel/history")
def history(room_code: str | None = Query(None,max_length=36), date_from: date | None = None,
            date_to: date | None = None, after_id: int = Query(0,ge=0), token=Depends(require_panel)):
    where,params = history_filter(room_code,date_from,date_to)
    params["after"] = after_id
    rows = transaction(lambda db: [dict(row) for row in db.execute(text("""
        SELECT m.id,m.sender_name,m.sender_kind,m.message,m.created_at,m.match_id,m.round_number,m.phase,s.room_code
        FROM chat_messages m LEFT JOIN game_sessions s ON s.id=m.game_session_id
        WHERE """+where+" AND m.id>:after ORDER BY m.id LIMIT 201"),params).mappings()])
    return {"messages":rows[:200], "has_more":len(rows)>200,
            "next_after_id":rows[min(len(rows),200)-1]["id"] if rows else after_id}


@router.get("/api/panel/history.csv")
def download(date_from: date | None = None, date_to: date | None = None, token=Depends(require_panel)):
    where, params = history_filter(None,date_from,date_to)
    # Build on disk beyond 1 MB; no giant in-memory transcript or long open DB transaction.
    output = SpooledTemporaryFile(max_size=1024*1024, mode="w+b")
    def write_row(values):
        buffer=io.StringIO(newline="")
        csv.writer(buffer).writerow(values)
        output.write(buffer.getvalue().encode("utf-8"))
    try:
        output.write(b"\xef\xbb\xbf")
        write_row(["chat_id","isi_chat"])
        maximum = transaction(lambda db: db.execute(text("SELECT COALESCE(MAX(id),0) FROM chat_messages")).scalar())
        after = 0
        while True:
            page_params = {**params,"after":after,"maximum":maximum}
            rows = transaction(lambda db: db.execute(text("""
                SELECT m.id,m.message FROM chat_messages m LEFT JOIN game_sessions s ON s.id=m.game_session_id
                WHERE """+where+" AND m.id>:after AND m.id<=:maximum ORDER BY m.id LIMIT 1000"),page_params).all())
            if not rows:
                break
            for chat_id,message in rows:
                write_row([chat_id,message])
            after=rows[-1][0]
        output.seek(0)
    except BaseException:
        output.close()
        raise
    def chunks():
        try:
            while chunk:=output.read(65536):
                yield chunk
        finally:
            output.close()
    return StreamingResponse(chunks(),media_type="text/csv; charset=utf-8",headers={
        "Content-Disposition": 'attachment; filename="riwayat-chat.csv"', "Cache-Control":"no-store"})
