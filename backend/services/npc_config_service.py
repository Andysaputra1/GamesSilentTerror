"""Konfigurasi otak NPC dari panel (metode, penulis kalimat, validasi); .env tetap nilai awal.

Disimpan di baris panel_configuration id=2 agar tidak bercampur dengan konfigurasi provider LLM
(id=1) yang ditulis ulang utuh oleh save_panel_configuration.
"""

import json

from sqlalchemy import text

from services.npc_brain.runtime import brain_runtime
from services.persistence_service import PersistenceService

BARIS_NPC = 2


# Baca konfigurasi tersimpan lalu terapkan ke runtime saat backend dimulai.
def load_npc_configuration():
    def read(database):
        value = database.execute(
            text("SELECT config FROM panel_configuration WHERE id=:id"), {"id": BARIS_NPC}
        ).scalar()
        return json.loads(value) if isinstance(value, str) else value

    stored = PersistenceService._run(read)
    if stored:
        brain_runtime.atur(
            metode=stored.get("metode"),
            penulis=stored.get("penulis"),
            validasi=stored.get("validasi"),
        )
    return brain_runtime.ringkasan()


# Validasi lewat runtime terlebih dahulu, simpan, lalu kembalikan ringkasan terbaru.
def save_npc_configuration(metode, penulis, validasi):
    before = brain_runtime.ringkasan()
    summary = brain_runtime.atur(metode=metode, penulis=penulis, validasi=validasi)
    config = {"metode": metode, "penulis": penulis, "validasi": bool(validasi)}

    def write(database):
        database.execute(
            text("""
            INSERT INTO panel_configuration(id, config) VALUES(:id, :config)
            ON DUPLICATE KEY UPDATE config=:config
        """),
            {"id": BARIS_NPC, "config": json.dumps(config)},
        )

    try:
        PersistenceService._run(write)
    except Exception:
        # Gagal simpan: kembalikan runtime ke konfigurasi sebelumnya agar panel dan server konsisten.
        brain_runtime.atur(
            metode=before["metode"], penulis=before["penulis_diminta"], validasi=before["validasi"]
        )
        raise
    return summary
