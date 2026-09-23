"""Panel development backend. Data operasional dan perubahan AI hanya untuk admin."""

from pathlib import Path
from typing import Literal
from fastapi import APIRouter, Depends, HTTPException, Response
from fastapi.responses import FileResponse
from pydantic import BaseModel
from config.settings import settings
from controller.middleware.auth import require_authenticated_user
from module.ollama_client import model_available
from services.activity_service import activity
from services.ai_runtime_service import ai_runtime
from services.checker_service import checker_service
from services.room_service import room_service

router = APIRouter(tags=["development-admin"])
ASSETS = Path(__file__).resolve().parents[2] / "public" / "admin"


# Batasi API development ke akun admin yang tercantum dalam konfigurasi.
def require_admin(response: Response, user=Depends(require_authenticated_user)):
    response.headers["Cache-Control"] = "no-store"
    allowed = {name.strip() for name in settings.admin_usernames.split(",") if name.strip()}
    if settings.app_environment != "development" or user.username not in allowed:
        raise HTTPException(403, "Panel ini hanya untuk admin development.")
    return user


# Arahkan alamat admin lama ke panel yang sekarang digunakan.
@router.get("/admin", include_in_schema=False)
def panel_redirect():
    from fastapi.responses import RedirectResponse

    return RedirectResponse("/panel", status_code=307)


# Sajikan hanya nama aset admin yang ada dalam daftar izin.
@router.get("/admin/assets/{asset}", include_in_schema=False)
def assets(asset: Literal["admin.js", "admin.css"]):
    return FileResponse(ASSETS / asset, headers={"Cache-Control": "no-store"})


class ProviderChoice(BaseModel):
    provider: Literal["api", "docker"]
    model: Literal["8", "14"]


# Ringkas provider aktif tanpa mengirim nilai API key ke browser.
def runtime_view():
    selected = ai_runtime.current()
    return {
        "provider": selected.ai_provider,
        "model": selected.ollama_model,
        "api_model": selected.openai_model,
        "api_configured": bool(selected.openai_api_key_value),
        "source": "panel (memory)" if ai_runtime.override else "environment",
    }


# Gabungkan konfigurasi aktif dan hasil pemeriksaan ketersediaan model lokal.
@router.get("/api/admin/status")
async def status(user=Depends(require_admin)):
    selected = ai_runtime.current()
    return {
        **runtime_view(),
        "username": user.username,
        "ollama_model_available": await model_available(config=selected),
    }


# Periksa kesiapan provider sebelum mengganti override untuk request berikutnya.
@router.post("/api/admin/provider")
async def provider(body: ProviderChoice, user=Depends(require_admin)):
    selected = ai_runtime.current().model_copy(update={"ollama_model": f"qwen3:{body.model}b"})
    if body.provider == "api" and not selected.openai_api_key_value:
        raise HTTPException(400, "API key belum dikonfigurasi di environment backend.")
    if body.provider == "docker" and not await model_available(config=selected):
        raise HTTPException(
            400, "Ollama/model belum tersedia. Unduh model dan periksa container terlebih dahulu."
        )
    ai_runtime.select(body.provider, body.model)
    activity.record(
        None,
        "AIRuntimeService.select",
        {"username": user.username, **body.model_dump()},
        result=runtime_view(),
    )
    return runtime_view()


# Hapus override sementara dan catat pengembalian konfigurasi ke environment.
@router.post("/api/admin/provider/reset")
def reset(user=Depends(require_admin)):
    ai_runtime.reset()
    activity.record(
        None, "AIRuntimeService.reset", {"username": user.username}, result=runtime_view()
    )
    return runtime_view()


# Salin daftar ruangan aktif beserta fase dan tenggat di bawah lock.
@router.get("/api/admin/rooms")
def rooms(user=Depends(require_admin)):
    with room_service.lock:
        return {
            "rooms": [
                {
                    **room_service.snapshot(room),
                    "round": room.match.round if room.match else None,
                    "deadline": room.match.deadline if room.match else None,
                }
                for room in room_service.rooms.values()
            ]
        }


# Ambil jejak aktivitas terbaru, dengan filter kode ruangan opsional.
@router.get("/api/admin/activity")
def events(code: str | None = None, user=Depends(require_admin)):
    return {"events": activity.list(code.upper() if code else None)}


# Validasi kode heksadesimal sebelum membaca jejak analisis ruangan.
@router.get("/api/admin/rooms/{code}/traces")
def traces(code: str, user=Depends(require_admin)):
    if len(code) != 6 or any(c not in "0123456789ABCDEF" for c in code.upper()):
        raise HTTPException(400, "Kode room harus 6 karakter heksadesimal.")
    return {"traces": checker_service.list(code.upper())}
