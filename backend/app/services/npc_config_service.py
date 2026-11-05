"""Konfigurasi otak NPC dari panel (penulis kalimat dan rantai penulis); .env tetap nilai awal.

Disimpan di baris panel_configuration id=2 agar tidak bercampur dengan konfigurasi provider LLM
(id=1) yang ditulis ulang utuh oleh simpan_konfigurasi_ai.

Alurnya saat server nyala (muat_konfigurasi_npc, dipanggil main.py sebelum otak dimuat)
1. Baca baris id=2 dari DB
2. Baris kosong: selesai, otak memakai nilai .env
3. Ada isi: titipkan ke runtime otak, yang baru membangun rantai penulisnya saat otak dimuat. Isi tidak valid diabaikan, otak memakai nilai .env

Alurnya saat panel menyimpan (save_npc_configuration)
1. Terapkan dulu ke runtime otak, yang sekaligus memvalidasi. Nilai salah ditolak sebelum menyentuh DB
2. Tulis nilai yang berlaku ke DB
3. Gagal tulis: kembalikan runtime ke konfigurasi sebelumnya, lalu teruskan errornya
"""

import json
import logging

from app.config.database import jalankan_transaksi
from app.models import panel_queries
from app.module.npc_brain.runtime import brain_runtime

BARIS_NPC = 2
logger = logging.getLogger("shadow_heist.npc_config")


# Baca konfigurasi tersimpan lalu terapkan ke runtime saat backend dimulai.
def muat_konfigurasi_npc():
    def read(database):
        value = panel_queries.panel_configuration(database, BARIS_NPC)
        return json.loads(value) if isinstance(value, str) else value

    stored = jalankan_transaksi(read)
    if stored:
        try:
            # Baris lama tanpa urutan/model penulis → None → nilai .env dipertahankan.
            brain_runtime.atur(
                penulis=stored.get("penulis"),
                urutan_penulis=stored.get("urutan_penulis"),
                model_openrouter=stored.get("model_openrouter"),
                model_tautan=stored.get("model_tautan"),
            )
        except ValueError:
            logger.warning("Konfigurasi NPC tersimpan tidak valid; memakai nilai .env.")


# Validasi lewat runtime terlebih dahulu, simpan nilai efektifnya, lalu kembalikan ringkasan terbaru.
def save_npc_configuration(penulis, urutan_penulis=None, model_openrouter=None, model_tautan=None):
    before = brain_runtime.ringkasan()
    summary = brain_runtime.atur(
        penulis=penulis,
        urutan_penulis=urutan_penulis,
        model_openrouter=model_openrouter,
        model_tautan=model_tautan,
    )
    config = {
        "penulis": summary["penulis_diminta"],
        "urutan_penulis": summary["urutan_penulis"],
        "model_openrouter": summary["model_openrouter"],
        "model_tautan": summary["model_tautan"],
    }

    try:
        jalankan_transaksi(
            lambda database: panel_queries.write_panel_configuration(
                database, BARIS_NPC, json.dumps(config)
            )
        )
    except Exception:
        # Gagal simpan: kembalikan runtime ke konfigurasi sebelumnya agar panel dan server konsisten.
        brain_runtime.atur(
            penulis=before["penulis_diminta"],
            urutan_penulis=before["urutan_penulis"],
            model_openrouter=before["model_openrouter"],
            model_tautan=before["model_tautan"],
        )
        raise
    return summary
