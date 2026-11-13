"""Production administration, isolated from player authentication."""

from datetime import date
from pathlib import Path
from typing import Literal
from fastapi import APIRouter, Depends, HTTPException, Query, Response
from fastapi.responses import FileResponse, StreamingResponse
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from pydantic import BaseModel, Field, SecretStr
from app.config.settings import settings
from app.config.database import PersistenceError
from app.middleware.auth_limits import limit_auth
from app.middleware.safe_validation import SafeValidationRoute
from app.services import panel_service
from app.services.panel_service import (
    AlamatTunnelDitolak,
    FilterRiwayatSalah,
    LoginPanelGagal,
    PanelBelumSiap,
)

router = APIRouter(tags=["panel"], route_class=SafeValidationRoute)
ASSETS = Path(__file__).resolve().parents[2] / "public" / "panel"
bearer = HTTPBearer(auto_error=False)


# Jalankan operasi panel; database gagal menjadi HTTP 503 dan filter riwayat yang salah menjadi HTTP 422.
def _jalankan(operasi):
    try:
        return operasi()
    except PersistenceError as error:
        raise HTTPException(503, str(error)) from error
    except FilterRiwayatSalah as error:
        raise HTTPException(422, str(error)) from error


# Validasi sesi panel sebelum endpoint dijalankan.
def require_panel(
    response: Response, credentials: HTTPAuthorizationCredentials | None = Depends(bearer)
):
    response.headers["Cache-Control"] = "no-store"
    if not credentials or not settings.panel_password_hash:
        raise HTTPException(401, "Login administrator diperlukan.")
    if not _jalankan(lambda: panel_service.sesi_berlaku(credentials.credentials)):
        raise HTTPException(401, "Sesi panel berakhir. Silakan login lagi.")
    return credentials.credentials


class Login(BaseModel):
    username: str = Field(min_length=1, max_length=100)
    password: str = Field(min_length=1, max_length=256)


# Minta service memeriksa kredensial admin dan membuat sesi; kembalikan token atau error HTTP.
@router.post("/api/panel/login", dependencies=[Depends(limit_auth)])
def login(body: Login, response: Response):
    response.headers["Cache-Control"] = "no-store"
    try:
        return {"access_token": panel_service.login(body.username, body.password)}
    except LoginPanelGagal as error:
        raise HTTPException(401, str(error)) from error
    except (PanelBelumSiap, PersistenceError) as error:
        raise HTTPException(503, str(error)) from error


# Hapus sesi panel terautentikasi dari database.
@router.post("/api/panel/logout", status_code=204)
def logout(token=Depends(require_panel)):
    _jalankan(lambda: panel_service.logout(token))


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


# Sajikan dokumen menu 08 (HTML mandiri berskrip inline): Peta Dokumen, ERD, Proses AI, Arsitektur, Bedah Alur,
# Bedah Otak Fuzzy, Cara Kerja Bot, Kode dan Diagram Alir Fuzzy, Kode NLG, serta Dataset, Kode, dan Diagram Alir NLU.
# Sandbox memberi origin terpisah sehingga skrip dokumen tidak bisa membaca data panel di origin yang sama.
@router.get("/panel/dokumen/{nama}", include_in_schema=False)
def dokumen(
    nama: Literal[
        "peta-dokumen", "erd", "proses-ai", "arsitektur", "bedah-alur",
        "kode-fuzzy", "diagram-alir-fuzzy", "bedah-otak-fuzzy", "cara-kerja-bot", "kode-nlg",
        "dataset-nlu", "kode-nlu-intent", "kode-nlu-target", "diagram-alir-nlu",
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


# Kembalikan konfigurasi AI setelah autentikasi panel berhasil.
@router.get("/api/panel/config")
def config(token=Depends(require_panel)):
    return panel_service.config_view()


class Configuration(BaseModel):
    provider: Literal["api", "docker"]
    endpoint: str = Field(default="", max_length=2048)
    api_key: SecretStr | None = None
    key_source: Literal["default", "custom"] | None = None
    tunnel_token: SecretStr | None = None
    clear_tunnel_token: bool = False
    model: str | None = Field(default=None, max_length=100)


# Simpan konfigurasi AI; alamat tunnel yang ditolak 422, isian lain yang salah 400.
@router.put("/api/panel/config")
def set_config(body: Configuration, token=Depends(require_panel)):
    try:
        return panel_service.simpan_konfigurasi(
            body.provider,
            body.endpoint,
            api_key=body.api_key.get_secret_value() if body.api_key else "",
            key_source=body.key_source,
            tunnel_token=body.tunnel_token.get_secret_value() if body.tunnel_token else "",
            clear_tunnel_token=body.clear_tunnel_token,
            model=body.model,
        )
    except AlamatTunnelDitolak as error:
        raise HTTPException(422, str(error)) from error
    except PersistenceError as error:
        raise HTTPException(503, "Konfigurasi gagal disimpan.") from error
    except ValueError as error:
        raise HTTPException(400, str(error)) from error


# Daftar room yang pernah tercatat (cursor ID), jumlah pesan, dan tanda room yang masih hidup di memori.
@router.get("/api/panel/rooms")
def rooms(after_id: int = Query(0, ge=0), token=Depends(require_panel)):
    return _jalankan(lambda: panel_service.daftar_room(after_id))


# Daftar jejak per halaman; detail diambil lewat endpoint jejak tunggal.
@router.get("/api/panel/checker/{code}")
def checker(
    code: str, before: str | None = Query(None, max_length=100), token=Depends(require_panel)
):
    if len(code) > 36:
        raise HTTPException(422, "Kode room terlalu panjang.")
    return _jalankan(lambda: panel_service.halaman_checker(code, before))


# Satu jejak lengkap beserta penjelasan keputusan bot (parameter, penalaran metode, NLG).
@router.get("/api/panel/checker/{code}/jejak/{trace_id}")
def checker_trace(code: str, trace_id: str, token=Depends(require_panel)):
    if (
        len(code) > 36
        or len(trace_id) != 32
        or any(karakter not in "0123456789abcdef" for karakter in trace_id)
    ):
        raise HTTPException(422, "Kode room atau ID jejak tidak valid.")
    jejak = _jalankan(lambda: panel_service.jejak_checker(code, trace_id))
    if jejak is None:
        raise HTTPException(404, "Jejak tidak ditemukan.")
    return jejak


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
    return _jalankan(
        lambda: panel_service.halaman_riwayat(
            room_code, date_from, date_to, after_id, before_id, urut, sender_kind
        )
    )


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
    berkas_csv = _jalankan(
        lambda: panel_service.ekspor_riwayat_csv(room_code, date_from, date_to, sender_kind, urut)
    )

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
