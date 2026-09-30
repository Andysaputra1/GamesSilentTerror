"""Runtime otak NPC di backend.

- Modul penalaran dan NLG berasal dari ekspor notebook (`generated/`), jadi logika bot sama
  dengan yang diuji di skripsi.
- Satu NLU (IndoBERT) dipakai bersama semua bot. Hasil anotasi chat publik disimpan (memo)
  karena identik untuk semua bot, dan inferensi model diserialkan agar aman antar-thread.
- Setiap bot punya ingatan, metode (fuzzy/utility/bt/llm), dan persona sendiri.
- Keputusan dijalankan di satu thread pekerja (logika notebook tidak dirancang paralel);
  penulisan kalimat berjalan di thread terpisah supaya LLM tidak menahan keputusan bot lain.
"""

from __future__ import annotations

import copy
import importlib
import json
import logging
import random
import re
import threading
import warnings
from collections import OrderedDict
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from pathlib import Path

from config.settings import BACKEND_DIR, PROJECT_DIR, settings
from services.match_engine import phase_durations

logger = logging.getLogger("shadow_heist.npc_brain")

# scikit-fuzzy memanggil np.maximum dengan argumen ketiga posisional; peringatannya tidak memengaruhi hasil.
warnings.filterwarnings("ignore", category=DeprecationWarning, module=r"skfuzzy(\..*)?")

METODE_MODUL = {"fuzzy": "otak_fuzzy", "utility": "otak_utility", "bt": "otak_bt"}
URUTAN_CAMPURAN = ("fuzzy", "utility", "bt")
METODE_VALID = {"campuran", "fuzzy", "utility", "bt", "llm"}
PENULIS_VALID = {"otomatis", "claude", "templat"}

# Label SVM lama → intent NLU baru; hanya dipakai bila IndoBERT tidak tersedia.
INTENT_SVM = {
    "accusing": "offend", "persuading": "offend", "bluffing": "offend", "deflecting": "offend",
    "menuduh": "offend", "membujuk": "offend", "menggertak": "offend", "mengelak": "offend",
    "defending": "defend", "membela": "defend", "offend": "offend", "defend": "defend",
}  # fmt: skip

# Lokasi default model IndoBERT: artifacts backend, lalu folder skripsi di sebelah repo Games.
FOLDER_MODEL = {
    "intent": ("intent", "models/notebook_standalone/intent_classifier_transformer"),
    "target": ("target", "models/target_classifier/target_classifier_transformer"),
}


class NLUBersama:
    """Satu NLU untuk semua bot: hasil disimpan (memo) dan inferensi model diserialkan."""

    def __init__(self, nlu, sumber, maks=4096):
        self.nlu, self.sumber, self.maks = nlu, sumber, maks
        self.ambang = getattr(nlu, "ambang", 0.0)
        self._memo = OrderedDict()
        self._lock = threading.Lock()

    # Ambil dari memo atau hitung sekali; salinan dikembalikan agar ingatan bot tidak saling berbagi objek.
    def _ingat(self, kunci, hitung):
        with self._lock:
            if kunci not in self._memo:
                self._memo[kunci] = hitung()
                if len(self._memo) > self.maks:
                    self._memo.popitem(last=False)
            self._memo.move_to_end(kunci)
            return copy.deepcopy(self._memo[kunci])

    # Roster ikut menjadi kunci memo: IndoBERT mengganti nama pemain sebelum membaca intent.
    def intent(self, teks, daftar_pemain=()):
        daftar = tuple(daftar_pemain)
        return self._ingat(("intent", teks, daftar), lambda: self.nlu.intent(teks, daftar))

    def target(self, pengirim, teks, konteks, daftar_pemain, label_intent):
        kunci = (
            "target", pengirim, teks, json.dumps(konteks, sort_keys=True, ensure_ascii=False),
            tuple(daftar_pemain), label_intent,
        )  # fmt: skip
        return self._ingat(
            kunci, lambda: self.nlu.target(pengirim, teks, konteks, daftar_pemain, label_intent)
        )


class NLUCadangan:
    """Pengganti IndoBERT: intent dari SVM lama dan target dari nama pemain yang disebut.

    Kualitasnya jauh di bawah IndoBERT; sumber NLU dicatat di trace agar data penelitian
    dari mode ini bisa dipisahkan.
    """

    ambang = 0.0

    def __init__(self, analysis=None):
        self.analysis = analysis

    def intent(self, teks, daftar_pemain=()):
        try:
            label = self.analysis.predict_intent(teks) if self.analysis else "neutral"
        except Exception:
            return "neutral", 0.0
        return INTENT_SVM.get(str(label).lower(), "neutral"), 0.7

    def target(self, pengirim, teks, konteks, daftar_pemain, label_intent):
        if label_intent == "neutral":
            return []
        kata = {w.casefold() for w in re.findall(r"\w+", teks)}
        disebut = [p for p in daftar_pemain if p != pengirim and p.casefold() in kata]
        if (
            not disebut
            and label_intent == "defend"
            and re.search(r"\b(aku|saya|gw|gue)\b", teks, re.I)
        ):
            disebut = [pengirim]
        return [{"pemain": p, "relasi": label_intent, "prob": None} for p in disebut] or [
            {"pemain": "tidak_diketahui", "relasi": label_intent, "prob": None}
        ]


@dataclass
class OtakBot:
    nama: str
    metode: str
    persona: str
    peran: str
    ingatan: object | None
    riwayat: list = field(default_factory=list)
    sibuk: bool = False
    langkah_terakhir: float = 0.0
    langkah: int = 0


@dataclass
class KonfigurasiNPC:
    metode: str = "campuran"
    penulis: str = "otomatis"
    validasi: bool = True


# Folder model pertama yang ada: pengaturan eksplisit, artifacts backend, lalu folder skripsi.
def folder_model(nilai, jenis) -> Path | None:
    nama_artifact, relatif = FOLDER_MODEL[jenis]
    kandidat = [
        nilai,
        BACKEND_DIR / "artifacts" / "indobert" / nama_artifact,
        PROJECT_DIR.parent / "training" / "prethesis" / "ai_2_dataset_baru" / relatif,
    ]
    return next((Path(p) for p in kandidat if p and Path(p).is_dir()), None)


class BrainRuntime:
    def __init__(self):
        self.lock = threading.RLock()
        self.modul = {}
        self.nlg = None
        self.nlu = None
        self.penulis = None
        self.konfigurasi = KonfigurasiNPC(
            settings.npc_method, settings.npc_writer, settings.npc_validate_nlg
        )
        self.status = {"siap": False, "gagal": False, "detail": "Belum dimuat.", "progres": 0.0,
                       "nlu": None, "penulis": None}  # fmt: skip
        self.pertandingan: dict[str, dict[str, OtakBot]] = {}
        self._thread = None
        self.eksekutor_keputusan = ThreadPoolExecutor(1, thread_name_prefix="otak-npc")
        self.eksekutor_nlg = ThreadPoolExecutor(3, thread_name_prefix="nlg-npc")

    def _set(self, **nilai):
        with self.lock:
            self.status.update(nilai)

    # STARTUP: muat modul otak, NLU, dan penulis di thread latar agar server langsung melayani request.
    def mulai_memuat(self, analysis=None):
        with self.lock:
            # Sudah dimuat (termasuk lewat muat_sekarang) atau sedang dimuat: jangan memuat ulang,
            # karena pemuatan ulang di latar mengganti NLU dan modul yang sedang dipakai bot.
            if self._thread is not None or self.status["siap"]:
                return
            self._thread = threading.Thread(
                target=self._muat, args=(analysis,), daemon=True, name="muat-otak-npc"
            )
            self._thread.start()

    # Dipakai test dan skrip: muat sinkron.
    def muat_sekarang(self, analysis=None, nlu=None):
        self._muat(analysis, nlu)

    def _muat(self, analysis=None, nlu=None):
        try:
            self._set(detail="Memuat logika fuzzy, utility AI, dan behavior tree…", progres=0.1)
            for metode, nama in METODE_MODUL.items():
                self.modul[metode] = importlib.import_module(f"services.npc_brain.generated.{nama}")
            self.nlg = importlib.import_module("services.npc_brain.generated.nlg")
            self._set(detail="Memuat NLU IndoBERT (intent dan target)…", progres=0.35)
            self.nlu = nlu if nlu is not None else self._buat_nlu(analysis)
            self._set(detail="Menyiapkan penulis kalimat…", progres=0.85)
            self.penulis = self._buat_penulis()
            self._set(
                siap=True, gagal=False, progres=1.0, detail="AI siap.", nlu=self.nlu.sumber,
                penulis=getattr(self.penulis, "jalur", None) or "templat",
            )  # fmt: skip
            logger.info(
                "Otak NPC siap: NLU=%s, penulis=%s", self.nlu.sumber, self.status["penulis"]
            )
        except Exception as error:
            logger.exception("Otak NPC gagal dimuat.")
            self._set(
                siap=False, gagal=True, galat=type(error).__name__,
                detail="Otak NPC gagal dimuat; bot memakai aksi cadangan engine.",
            )  # fmt: skip

    def _buat_nlu(self, analysis):
        intent_dir = folder_model(settings.npc_intent_model_dir, "intent")
        target_dir = folder_model(settings.npc_target_model_dir, "target")
        if intent_dir and target_dir:
            try:
                model = self.nlg.NLUIndoBERT(intent_dir, target_dir, settings.npc_nlu_device)
                logger.info("IndoBERT dimuat dari %s dan %s", intent_dir, target_dir)
                return NLUBersama(model, "indobert")
            except Exception:
                logger.exception("IndoBERT gagal dimuat; memakai NLU cadangan.")
        else:
            logger.warning("Folder IndoBERT tidak ditemukan; memakai NLU cadangan (SVM + nama).")
        return NLUBersama(NLUCadangan(analysis), "cadangan")

    # Penulis Claude hanya jika konfigurasi mengizinkan dan key tersedia; kegagalan → templat.
    def _buat_penulis(self):
        if self.konfigurasi.penulis == "templat":
            return None
        try:
            if settings.anthropic_api_key:
                return self.nlg.PenulisClaude(
                    "claude_api", settings.anthropic_api_key.get_secret_value().strip()
                )
            if settings.amazon_api_key:
                self.nlg.REGION_BEDROCK = settings.npc_bedrock_region
                return self.nlg.PenulisClaude(
                    "claude_bedrock", settings.amazon_api_key.get_secret_value().strip()
                )
        except Exception:
            logger.exception("Penulis Claude gagal disiapkan; memakai templat.")
        return None

    # PANEL: ubah metode/penulis/validasi saat server berjalan (berlaku untuk pertandingan berikutnya).
    def atur(self, metode=None, penulis=None, validasi=None):
        with self.lock:
            if metode is not None:
                if metode not in METODE_VALID:
                    raise ValueError("Metode NPC tidak dikenal.")
                self.konfigurasi.metode = metode
            if validasi is not None:
                self.konfigurasi.validasi = bool(validasi)
            if penulis is not None:
                if penulis not in PENULIS_VALID:
                    raise ValueError("Penulis kalimat tidak dikenal.")
                self.konfigurasi.penulis = penulis
                if self.nlg is not None:
                    self.penulis = self._buat_penulis()
                    self.status["penulis"] = getattr(self.penulis, "jalur", None) or "templat"
            return self.ringkasan()

    def ringkasan(self):
        with self.lock:
            return {
                **{k: v for k, v in self.status.items()},
                "metode": self.konfigurasi.metode,
                "penulis_diminta": self.konfigurasi.penulis,
                "validasi": self.konfigurasi.validasi,
                "penulis_aktif": bool(self.penulis and getattr(self.penulis, "aktif", False)),
                "pertandingan_aktif": len(self.pertandingan),
            }

    # Metode per bot: satu metode untuk semua, atau campuran bergiliran (urutan diacak per pertandingan).
    def _bagi_metode(self, match_id, bots):
        metode = self.konfigurasi.metode
        if metode != "campuran":
            return {nama: metode for nama in bots}
        urutan = list(URUTAN_CAMPURAN)
        random.Random(match_id).shuffle(urutan)
        return {nama: urutan[i % len(urutan)] for i, nama in enumerate(bots)}

    # Sekali per pertandingan: metode, persona, dan ingatan setiap bot.
    def siapkan_pertandingan(self, match, room_code):
        with self.lock:
            if match.id in self.pertandingan:
                return []
            bots = sorted(p.name for p in match.players.values() if p.bot)
            metode = self._bagi_metode(match.id, bots)
            cepat = match.durations == phase_durations(len(match.players), True)
            otak = {}
            for nama in bots:
                m = metode[nama] if metode[nama] == "llm" or metode[nama] in self.modul else "llm"
                persona = self.nlg.persona_bot(nama, bots) if self.nlg else "santai"
                ingatan = self.modul[m].Ingatan(nama, cepat=cepat) if m in self.modul else None
                otak[nama] = OtakBot(nama, m, persona, match.players[nama].role, ingatan)
            self.pertandingan[match.id] = otak
            return [
                {"match_id": match.id, "room_code": room_code, "bot_name": b.nama,
                 "method": b.metode, "persona": b.persona, "role": b.peran}
                for b in otak.values()
            ]  # fmt: skip

    def otak_bot(self, match_id, nama) -> OtakBot | None:
        with self.lock:
            return self.pertandingan.get(match_id, {}).get(nama)

    # Buang ingatan pertandingan yang sudah tidak aktif.
    def lupakan_kecuali(self, match_ids):
        with self.lock:
            for match_id in [m for m in self.pertandingan if m not in match_ids]:
                del self.pertandingan[match_id]

    # KEPUTUSAN (thread otak): sinkron snapshot → anotasi NLU → putuskan() metode bot.
    def langkah(self, bot: OtakBot, snapshot, sekarang):
        modul = self.modul[bot.metode]
        view = bot.ingatan.sinkron_snapshot(snapshot, sekarang, self.nlu)
        hasil = modul.putuskan(bot.ingatan, view)
        chat = sorted(bot.ingatan.chat, key=lambda c: c["waktu"])[-8:]
        konteks = {
            "roster": [p["nama"] for p in view["pemain"]],
            "chat_terbaru": [
                {"pengirim": c["pengirim"], "teks": c["teks"], "intent": c.get("intent"),
                 "target": [{"pemain": t["pemain"], "relasi": t["relasi"]} for t in c.get("target", [])]}
                for c in chat
            ],
        }  # fmt: skip
        return view, hasil, konteks

    # NLG (thread penulis): rencana → kalimat, dengan pengaman aturan dan validasi IndoBERT.
    def tulis(self, bot: OtakBot, payload, konteks):
        with self.lock:
            penulis = self.penulis if self.konfigurasi.penulis != "templat" else None
            nlu = self.nlu if self.konfigurasi.validasi else None
        # Hindari kalimat sendiri yang lalu dan chat terbaru di room (bot lain tidak dikembari).
        hindari = tuple(bot.riwayat[-12:]) + tuple(c["teks"] for c in konteks["chat_terbaru"])
        return self.nlg.tulis_pesan(payload, konteks, nlu, penulis, bot.persona, hindari=hindari)

    # Dipanggil setelah pesan benar-benar terkirim.
    def catat_chat(self, bot: OtakBot, view, rencana, teks):
        bot.ingatan.catat_aksi_bot(view, rencana)
        bot.riwayat.append(teks)

    def catat_aksi(self, bot: OtakBot, ronde, aksi, target):
        bot.ingatan.catat_aksi_rahasia(ronde, aksi, target)

    def tutup(self):
        self.eksekutor_keputusan.shutdown(wait=False, cancel_futures=True)
        self.eksekutor_nlg.shutdown(wait=False, cancel_futures=True)


brain_runtime = BrainRuntime()
