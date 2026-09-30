"""Panel: status dan konfigurasi otak NPC (metode penalaran, penulis kalimat, validasi NLG)."""

from typing import Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from controller.api.panel import require_panel
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
        "otomatis": "Claude bila key tersedia, selain itu templat",
        "claude": "Claude (gagal/timeout → templat)",
        "templat": "Templat bervariasi saja (tanpa LLM)",
    },
}


class NPCConfig(BaseModel):
    metode: Literal["campuran", "fuzzy", "utility", "bt", "llm"]
    penulis: Literal["otomatis", "claude", "templat"]
    validasi: bool = True


@router.get("/api/panel/npc")
# PANEL: status pemuatan otak, sumber NLU, penulis aktif, dan pilihan konfigurasi.
def npc_status(token=Depends(require_panel)):
    return {"status": brain_runtime.ringkasan(), "pilihan": PILIHAN}


@router.put("/api/panel/npc")
# PANEL: simpan konfigurasi; berlaku untuk pertandingan yang dimulai setelahnya.
def npc_update(body: NPCConfig, token=Depends(require_panel)):
    try:
        status = save_npc_configuration(body.metode, body.penulis, body.validasi)
    except ValueError as error:
        raise HTTPException(400, str(error)) from error
    except PersistenceError as error:
        raise HTTPException(503, "Konfigurasi NPC gagal disimpan.") from error
    return {"status": status, "pilihan": PILIHAN}
