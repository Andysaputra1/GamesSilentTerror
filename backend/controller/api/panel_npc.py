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
        "claude_bedrock": {
            "label": "Claude · Amazon Bedrock",
            "sumber": "AMAZON_API_KEY di server",
        },
        "claude_api": {"label": "Claude API · Anthropic", "sumber": "ANTHROPIC_API_KEY di server"},
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
    urutan_penulis: list[Literal["claude_bedrock", "claude_api", "openrouter", "tautan"]] | None = (
        Field(default=None, max_length=4)
    )
    model_openrouter: str | None = Field(default=None, max_length=100)


@router.get("/api/panel/npc")
# PANEL: status pemuatan otak, sumber NLU, rantai penulis, dan pilihan konfigurasi.
def npc_status(token=Depends(require_panel)):
    return {"status": brain_runtime.ringkasan(), "pilihan": PILIHAN}


@router.put("/api/panel/npc")
# PANEL: simpan konfigurasi. Metode berlaku untuk pertandingan berikutnya; rantai penulis langsung.
def npc_update(body: NPCConfig, token=Depends(require_panel)):
    try:
        status = save_npc_configuration(
            body.metode, body.penulis, body.validasi, body.urutan_penulis, body.model_openrouter
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
