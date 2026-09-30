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
import time
import warnings
from collections import OrderedDict
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import urlsplit

from config.settings import (
    BACKEND_DIR, JALUR_PENULIS_NPC, POLA_MODEL_OPENROUTER, PROJECT_DIR, settings,
)  # fmt: skip
from services.ai_runtime_service import ai_runtime
from services.match_engine import phase_durations
from services.npc_brain.penjelasan import jelaskan

logger = logging.getLogger("shadow_heist.npc_brain")

# scikit-fuzzy memanggil np.maximum dengan argumen ketiga posisional; peringatannya tidak memengaruhi hasil.
warnings.filterwarnings("ignore", category=DeprecationWarning, module=r"skfuzzy(\..*)?")

METODE_MODUL = {"fuzzy": "otak_fuzzy", "utility": "otak_utility", "bt": "otak_bt"}
URUTAN_CAMPURAN = ("fuzzy", "utility", "bt")
METODE_VALID = {"campuran", "fuzzy", "utility", "bt", "llm"}
# "claude" = nilai lama penulis, diperlakukan seperti otomatis.
PENULIS_VALID = {"otomatis", "claude", "templat"}
# Jalur rantai penulis: claude_bedrock, claude_api, openrouter, tautan (link LLM sendiri).
JALUR_PENULIS = JALUR_PENULIS_NPC

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
    # Prioritas rantai penulis; jalur yang tidak tercantum dinonaktifkan.
    urutan_penulis: list = field(default_factory=lambda: list(JALUR_PENULIS))
    model_openrouter: str = ""  # kosong = model OpenRouter dari notebook


# Nilai SecretStr tanpa spasi; None jika tidak diatur.
def _rahasia(nilai):
    return (nilai.get_secret_value().strip() or None) if nilai else None


# Pemuatan otak yang gagal dicoba ulang paling cepat setelah jeda ini (detik).
JEDA_MUAT_ULANG_DETIK = 60


# Folder model pertama yang ada: pengaturan eksplisit, artifacts backend, lalu folder skripsi.
def folder_model(nilai, jenis) -> Path | None:
    if nilai and not Path(nilai).is_dir():
        # Salah ketik path di .env tidak boleh lolos diam-diam ke model lain atau NLU cadangan.
        logger.warning("Folder model %s dari pengaturan tidak ditemukan: %s", jenis, nilai)
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
        self.keterangan_penulis = {}  # jalur → alasan tidak masuk rantai (mis. key belum diisi)
        self.konfigurasi = KonfigurasiNPC(
            settings.npc_method,
            "otomatis" if settings.npc_writer == "claude" else settings.npc_writer,
            settings.npc_validate_nlg,
            settings.npc_writer_order.split(",") if settings.npc_writer_order else [],
            settings.npc_openrouter_model,
        )
        self.status = {"siap": False, "gagal": False, "detail": "Belum dimuat.", "progres": 0.0,
                       "nlu": None, "sedang_cek_penulis": False}  # fmt: skip
        self._kunci_cek = threading.Lock()  # satu cek rantai penulis pada satu waktu
        # Cek yang sedang berjalan atau antre; selama > 0 panel menampilkan "Sedang dicek…".
        self._cek_tertunda = 0
        # Host link LLM dan asalnya (panel/.env) untuk ditampilkan di panel.
        self.alamat_tautan = None
        self.pertandingan: dict[str, dict[str, OtakBot]] = {}
        self._thread = None
        self.eksekutor_keputusan = ThreadPoolExecutor(1, thread_name_prefix="otak-npc")
        self.eksekutor_nlg = ThreadPoolExecutor(3, thread_name_prefix="nlg-npc")

    def _set(self, **nilai):
        with self.lock:
            self.status.update(nilai)

    _gagal_pada = None  # waktu (monotonic) pemuatan terakhir gagal; None = belum pernah gagal

    # STARTUP: muat modul otak, NLU, dan penulis di thread latar agar server langsung melayani request.
    def mulai_memuat(self, analysis=None):
        with self.lock:
            # Sudah dimuat (termasuk lewat muat_sekarang) atau sedang dimuat: jangan memuat ulang,
            # karena pemuatan ulang di latar mengganti NLU dan modul yang sedang dipakai bot.
            if self.status["siap"] or (self._thread is not None and self._thread.is_alive()):
                return
            # Pemuatan yang gagal dicoba lagi (mis. saat pertandingan berikutnya disiapkan), paling
            # cepat setelah jeda agar kegagalan permanen tidak memuat ulang di setiap persiapan.
            if (
                self._gagal_pada is not None
                and time.monotonic() - self._gagal_pada < JEDA_MUAT_ULANG_DETIK
            ):
                return
            self.status.update(gagal=False, detail="Memuat otak NPC…", progres=0.0)
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
            # Rantai dibangun sekarang dan dicek di latar: permainan tidak menunggu jaringan, dan jalur
            # yang belum selesai dicek tetap boleh dicoba (kegagalannya ditangani rantai).
            self.segarkan_penulis()
            self._set(siap=True, gagal=False, progres=1.0, detail="AI siap.", nlu=self.nlu.sumber)
            logger.info("Otak NPC siap: NLU=%s", self.nlu.sumber)
        except Exception as error:
            logger.exception("Otak NPC gagal dimuat.")
            self._gagal_pada = time.monotonic()
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

    # RANTAI PENULIS sesuai urutan panel. Key Claude dari environment server; key OpenRouter dan link LLM
    # (Docker/tunnel) dari Konfigurasi AI panel. Jalur tanpa key dilewati; semua gagal → templat.
    def _buat_penulis(self):
        self.keterangan_penulis = {}
        if self.konfigurasi.penulis == "templat":
            return None
        config = ai_runtime.current()
        link = (config.ollama_base_url or "").strip() or None
        # Host dan asal link ditampilkan di panel: link bawaan .env (mis. localhost) mudah dikenali.
        self.alamat_tautan = link and {
            "host": urlsplit(link).netloc,
            "sumber": "panel" if ai_runtime.diatur_panel("ollama_base_url") else ".env",
        }
        kunci = {
            "claude_bedrock": _rahasia(settings.amazon_api_key),
            "claude_api": _rahasia(settings.anthropic_api_key),
            "openrouter": config.openrouter_api_key_value,
            "tautan": link,
        }
        model = {
            "openrouter": self.konfigurasi.model_openrouter or None,
            "tautan": config.ollama_model,
        }
        try:
            rantai, self.keterangan_penulis = self.nlg.buat_rantai(
                self.konfigurasi.urutan_penulis, kunci, model,
                region=settings.npc_bedrock_region, token_tautan=_rahasia(config.ollama_tunnel_token),
            )  # fmt: skip
        except Exception:
            logger.exception("Rantai penulis gagal disiapkan; memakai templat.")
            return None
        return rantai

    # Bangun ulang rantai (key/link/urutan terbaru) lalu cek semua jalurnya. latar=False dipakai tombol
    # "Cek ulang" di panel agar hasilnya langsung terlihat; selain itu cek berjalan di thread latar.
    def segarkan_penulis(self, latar=True):
        with self.lock:
            if self.nlg is None:
                return self.ringkasan()
            lama, self.penulis = self.penulis, self._buat_penulis()
            penulis = self.penulis
            if penulis is not None:
                # Dinaikkan sebelum thread cek mulai agar ringkasan langsung "sedang dicek".
                self._cek_tertunda += 1
                self.status["sedang_cek_penulis"] = True
        if lama is not None:
            # Koneksi rantai lama dilepas setelah kalimat yang mungkin sedang ditulis selesai.
            penutup = threading.Timer(2 * self.nlg.BATAS_WAKTU_DETIK, lama.tutup)
            penutup.daemon = True
            penutup.start()
        if penulis is not None:
            if latar:
                threading.Thread(
                    target=self._cek_penulis, args=(penulis,), daemon=True, name="cek-penulis"
                ).start()
            else:
                self._cek_penulis(penulis)
        return self.ringkasan()

    # Claude dan OpenRouter: satu pesan pendek (key, izin model, saldo); link: daftar model.
    # Hanya status yang dicatat, tanpa key. Penghitung dinaikkan pemanggil (segarkan_penulis).
    def _cek_penulis(self, penulis):
        try:
            with self._kunci_cek:
                hasil = penulis.cek()
                logger.info("Cek penulis: %s", "; ".join(f"{j}={h}" for j, _, h in hasil))
        except Exception:
            logger.exception("Cek rantai penulis gagal.")
        finally:
            with self.lock:
                self._cek_tertunda -= 1
                self.status["sedang_cek_penulis"] = self._cek_tertunda > 0

    # PANEL: ubah metode/penulis/validasi/rantai saat server berjalan. Metode berlaku untuk pertandingan
    # berikutnya; rantai penulis langsung dipakai kalimat berikutnya. Semua nilai divalidasi dulu (atomik).
    def atur(
        self, metode=None, penulis=None, validasi=None, urutan_penulis=None, model_openrouter=None
    ):
        if metode is not None and metode not in METODE_VALID:
            raise ValueError("Metode NPC tidak dikenal.")
        if penulis is not None and penulis not in PENULIS_VALID:
            raise ValueError("Penulis kalimat tidak dikenal.")
        if urutan_penulis is not None:
            urutan_penulis = list(urutan_penulis)
            if not set(urutan_penulis) <= set(JALUR_PENULIS) or len(set(urutan_penulis)) != len(
                urutan_penulis
            ):
                raise ValueError("Urutan penulis berisi jalur yang tidak dikenal atau ganda.")
        if model_openrouter is not None:
            model_openrouter = model_openrouter.strip()
            if model_openrouter and not POLA_MODEL_OPENROUTER.fullmatch(model_openrouter):
                raise ValueError("Model OpenRouter harus berbentuk penyedia/model.")
        with self.lock:
            k = self.konfigurasi
            sebelum = (k.penulis, list(k.urutan_penulis), k.model_openrouter)
            if metode is not None:
                k.metode = metode
            if validasi is not None:
                k.validasi = bool(validasi)
            if penulis is not None:
                k.penulis = "otomatis" if penulis == "claude" else penulis
            if urutan_penulis is not None:
                k.urutan_penulis = urutan_penulis
            if model_openrouter is not None:
                k.model_openrouter = model_openrouter
            rantai_berubah = sebelum != (k.penulis, list(k.urutan_penulis), k.model_openrouter)
        if rantai_berubah:
            self.segarkan_penulis()
        return self.ringkasan()

    def ringkasan(self):
        with self.lock:
            penulis = self.penulis if self.konfigurasi.penulis != "templat" else None
            # Jalur yang menulis kalimat berikutnya: yang pertama siap (tidak ditolak dan tidak istirahat).
            berikut = penulis.terdepan() if penulis else None
            return {
                **self.status,
                "metode": self.konfigurasi.metode,
                "penulis_diminta": self.konfigurasi.penulis,
                "validasi": self.konfigurasi.validasi,
                "penulis_aktif": berikut is not None,
                "penulis": berikut.jalur if berikut else "templat",
                "model_penulis": berikut.model if berikut else None,
                "urutan_penulis": list(self.konfigurasi.urutan_penulis),
                "model_openrouter": self.konfigurasi.model_openrouter,
                "rantai_penulis": self._status_rantai(penulis, berikut),
                "pertandingan_aktif": len(self.pertandingan),
            }

    # Status tiap jalur untuk panel: jalur aktif sesuai prioritas, lalu yang dinonaktifkan. Tanpa nilai key.
    def _status_rantai(self, penulis, berikut):
        anggota = {p.jalur: p for p in (penulis.daftar if penulis else [])}
        urutan = self.konfigurasi.urutan_penulis
        baris = []
        for jalur in urutan + [j for j in JALUR_PENULIS if j not in urutan]:
            p = anggota.get(jalur)
            if self.konfigurasi.penulis == "templat" or jalur not in urutan:
                keadaan, status = "nonaktif", "mode templat" if jalur in urutan else "dinonaktifkan"
            elif p is None:
                keadaan, status = "tidak_ada", self.keterangan_penulis.get(jalur, "belum dimuat")
            elif not p.aktif:
                keadaan, status = "ditolak", p.status
            elif not p.siap():
                keadaan, status = "istirahat", p.status
            else:
                keadaan, status = ("dipakai" if p is berikut else "siap"), p.status
            # Penghitung panggilan/token berlaku sejak rantai terakhir dibangun (token cek ikut dihitung).
            baris.append({
                "jalur": jalur, "keadaan": keadaan, "status": status,
                "model": p.model if p else None, "panggilan": p.panggilan if p else 0,
                "token_masuk": p.token_masuk if p else 0, "token_keluar": p.token_keluar if p else 0,
                "alamat": self.alamat_tautan if jalur == "tautan" else None,
            })  # fmt: skip
        return baris

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
    # Penjelasan panel checker dihitung di thread ini juga (ingatan bot hanya diubah thread ini), hanya
    # untuk langkah yang bisa menjadi jejak: ada vote/aksi atau rencana chat. Langkah diam tidak dicatat.
    def langkah(self, bot: OtakBot, snapshot, sekarang):
        modul = self.modul[bot.metode]
        view = bot.ingatan.sinkron_snapshot(snapshot, sekarang, self.nlu)
        hasil = modul.putuskan(bot.ingatan, view)
        if hasil["nlg"] is not None or hasil["npc_decision"]["action"] != "wait":
            hasil["penjelasan"] = jelaskan(bot, modul, view, hasil)
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
    # pakai_llm=False: hanya templat, dipakai sebagai cadangan cepat saat penulis LLM melewati batas waktu.
    def tulis(self, bot: OtakBot, payload, konteks, pakai_llm=True):
        with self.lock:
            pakai = pakai_llm and self.konfigurasi.penulis != "templat"
            penulis = self.penulis if pakai else None
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
        if self.penulis is not None:
            self.penulis.tutup()


brain_runtime = BrainRuntime()
