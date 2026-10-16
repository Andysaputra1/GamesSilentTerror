"""Panel: status dan konfigurasi otak NPC (metode penalaran, rantai penulis kalimat, validasi NLG)."""

from typing import Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from controller.api.panel import require_panel
from controller.middleware.auth_limits import limit_auth
from controller.middleware.safe_validation import SafeValidationRoute
from services.npc_brain.runtime import brain_runtime
from services.npc_config_service import save_npc_configuration
from services.persistence_service import PersistenceError
from services.simulasi_service import simulasi_service

router = APIRouter(tags=["panel-npc"], route_class=SafeValidationRoute)

PILIHAN = {
    "metode": {
        "campuran": "Campuran (bot dibagi bergiliran: fuzzy, utility, behavior tree)",
        "fuzzy": "Fuzzy Logic Mamdani",
        "utility": "Utility AI",
        "bt": "Behavior Tree",
        "llm": "LLM murni (mode lama, pembanding)",
    },
    "penulis": {
        "otomatis": "Rantai LLM sesuai prioritas; semua gagal → templat",
        "templat": "Templat bervariasi saja (tanpa LLM)",
    },
    # Jalur rantai penulis: nama tampilan dan asal key/link-nya (nilai key tidak pernah dikirim).
    "jalur_penulis": {
        "openrouter": {"label": "OpenRouter", "sumber": "API key di menu Konfigurasi AI"},
        "tautan": {
            "label": "LLM sendiri lewat link",
            "sumber": "URL tunnel (Docker/Ollama) di menu Konfigurasi AI",
        },
    },
}


class NPCConfig(BaseModel):
    metode: Literal["campuran", "fuzzy", "utility", "bt", "llm"]
    penulis: Literal["otomatis", "claude", "templat"]  # "claude" = nilai lama, sama dengan otomatis
    validasi: bool = True
    # None = pertahankan urutan/model yang tersimpan (klien panel lama).
    urutan_penulis: list[Literal["openrouter", "tautan"]] | None = Field(default=None, max_length=2)
    model_openrouter: str | None = Field(default=None, max_length=100)
    # Model di link LLM; "" = model Ollama dari Konfigurasi AI/.env.
    model_tautan: str | None = Field(default=None, max_length=100)


@router.get("/api/panel/npc")
# PANEL: status pemuatan otak, sumber NLU, rantai penulis, dan pilihan konfigurasi.
def npc_status(token=Depends(require_panel)):
    return {"status": brain_runtime.ringkasan(), "pilihan": PILIHAN}


@router.put("/api/panel/npc")
# PANEL: simpan konfigurasi. Metode berlaku untuk pertandingan berikutnya; rantai penulis langsung.
def npc_update(body: NPCConfig, token=Depends(require_panel)):
    try:
        status = save_npc_configuration(
            body.metode,
            body.penulis,
            body.validasi,
            body.urutan_penulis,
            body.model_openrouter,
            body.model_tautan,
        )
    except ValueError as error:
        raise HTTPException(400, str(error)) from error
    except PersistenceError as error:
        raise HTTPException(503, "Konfigurasi NPC gagal disimpan.") from error
    return {"status": status, "pilihan": PILIHAN}


@router.post("/api/panel/npc/cek-penulis", dependencies=[Depends(limit_auth)])
# PANEL: hit semua jalur aktif di latar; status per jalur dibaca lewat GET agar tidak timeout.
def npc_check_writers(token=Depends(require_panel)):
    return {"status": brain_runtime.segarkan_penulis(latar=True), "pilihan": PILIHAN}


class SimulasiBaru(BaseModel):
    nama: str = Field(default="Pemain", min_length=1, max_length=40)
    # Metode tiap bot, urut NOX, ECHO, ... (3–9 bot: 4–10 pemain bersama admin).
    metode: list[Literal["fuzzy", "utility", "bt"]] = Field(min_length=3, max_length=9)


class SimulasiAksi(BaseModel):
    aksi: Literal["kirim", "jalan", "fase"]
    teks: str = Field(default="", max_length=500)
    detik: float = Field(
        default=3.0, ge=0, le=60
    )  # waktu permainan yang dilewati sebelum bot melangkah


@router.post("/api/panel/simulasi")
# SIMULASI: pertandingan tiruan dengan otak, NLU, dan NLG asli; tidak menyentuh room atau database.
def simulasi_mulai(body: SimulasiBaru, token=Depends(require_panel)):
    try:
        return simulasi_service.mulai(body.nama.strip() or "Pemain", body.metode)
    except RuntimeError as error:
        raise HTTPException(503, f"Otak NPC belum siap: {error} Coba lagi sebentar.") from error


@router.post("/api/panel/simulasi/{sim_id}")
async def simulasi_aksi(sim_id: str, body: SimulasiAksi, token=Depends(require_panel)):
    if body.aksi == "kirim" and not body.teks.strip():
        raise HTTPException(422, "Tulis chat terlebih dahulu.")
    try:
        return await simulasi_service.jalankan(sim_id, body.aksi, body.teks.strip(), body.detik)
    except KeyError as error:
        raise HTTPException(404, str(error.args[0])) from error
    except ValueError as error:
        raise HTTPException(400, str(error)) from error


@router.get("/api/panel/simulasi/{sim_id}/progres")
# SIMULASI: tahap yang sedang dikerjakan tiap pemain (NLU, logika, NLG, ...) untuk flowchart live.
def simulasi_progres(sim_id: str, token=Depends(require_panel)):
    try:
        return simulasi_service.progres(sim_id)
    except KeyError as error:
        raise HTTPException(404, str(error.args[0])) from error
