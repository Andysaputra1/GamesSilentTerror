"""
Runtime otak NPC di backend: memuat otak, menyimpan otak tiap bot, lalu menjalankan langkah keputusan dan penulisan kalimat.

Alurnya
1. Memuat otak di thread latar (mulai_memuat): Modul fuzzy dan NLG, IndoBERT, lalu rantai penulis kalimat
2. Mengecek rantai penulis di latar (segarkan_penulis), supaya permainan tidak menunggu jaringan
3. Awal pertandingan (siapkan_pertandingan): Buat persona dan ingatan tiap bot
4. Tiap langkah bot (langkah, thread keputusan): IndoBERT membaca chat baru, fuzzy memutuskan, penjelasan dibuat untuk panel
5. Bot mau chat (tulis, thread penulis): Rencana jadi kalimat lewat LLM atau templat, lalu diperiksa aturan
6. Chat atau vote sudah terjadi (catat_chat, catat_vote): Masuk ingatan bot
7. Chat baru masuk (baca_chat): IndoBERT membaca sekali dan hasilnya masuk memo, jadi bot tidak menghitung ulang

Catatan
- Modul penalaran dan NLG berasal dari ekspor notebook (`generated/`), jadi logika bot sama
  dengan yang diuji di skripsi.
- Satu NLU (IndoBERT) dipakai bersama semua bot. Hasil anotasi chat publik disimpan (memo)
  karena identik untuk semua bot, dan inferensi model diserialkan agar aman antar-thread.
- Setiap bot punya ingatan dan persona sendiri; semua bot memakai metode fuzzy.
- Keputusan dijalankan di satu thread pekerja (logika notebook tidak dirancang paralel);
  penulisan kalimat berjalan di thread terpisah supaya LLM tidak menahan keputusan bot lain.
"""

from __future__ import annotations

import copy
import importlib
import json
import logging
import re
import threading
import time
import warnings
from collections import OrderedDict
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING
from urllib.parse import urlsplit

from app.config.settings import (
    BACKEND_DIR, JALUR_PENULIS_NPC, POLA_MODEL_OPENROUTER,
    PROJECT_DIR, settings,
)  # fmt: skip
from app.services.ai_config_service import ai_runtime
from app.module.match_engine import phase_durations
from app.module.npc_brain.penjelasan import jelaskan

if TYPE_CHECKING:
    # Hanya untuk editor (Ctrl+klik). Saat program jalan modul ini dimuat di _muat, supaya server cepat nyala.
    from app.module.npc_brain.generated import otak_fuzzy

logger =logging.getLogger("shadow_heist.npc_brain")

# scikit-fuzzy memanggil np.maximum dengan argumen ketiga posisional; peringatannya tidak memengaruhi hasil.
warnings.filterwarnings("ignore", category=DeprecationWarning, module=r"skfuzzy(\..*)?")

# Modul logika tiap metode; game sekarang hanya memakai fuzzy.
METODE_MODUL = {"fuzzy": "otak_fuzzy"}
# Nama model di link LLM (Ollama/OpenAI), mis. qwen3:4b-instruct atau qwen3:14b.
POLA_MODEL_TAUTAN = re.compile(
    r"[A-Za-z0-9][A-Za-z0-9._-]*(?:/[A-Za-z0-9._-]+)*(?::[A-Za-z0-9._-]+)?"
)
PENULIS_VALID = {"otomatis", "templat"}
# Jalur rantai penulis: openrouter dan tautan (link LLM sendiri, mis. Ollama lewat tunnel).
JALUR_PENULIS = JALUR_PENULIS_NPC
# Pemuatan otak yang gagal dicoba ulang paling cepat setelah jeda ini (detik).
JEDA_MUAT_ULANG_DETIK = 60

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
        # Kata umum (pair_builder.json) untuk aturan nama di anotasi_chat: tidak pernah dianggap nama pemain.
        self.common_words = getattr(nlu, "common_words", frozenset())
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


# Target NLU → teks pendek untuk panel, mis. "NOX: offend (0.91)".
def teks_target(target):
    return [
        f"{t['pemain']}: {t['relasi']}"
        + (f" ({t['prob']:.2f})" if t.get("prob") is not None else "")
        for t in target or []
    ]


# Pengganti lapor(tahap) saat tidak ada pemantau; hanya simulasi panel yang memantau tahap.
def _tanpa_lapor(tahap):
    pass


class _JamPenulis:
    """Penulis yang mencatat total lama panggilan LLM satu kalimat (satu objek per kalimat)."""

    def __init__(self, penulis, lapor=_tanpa_lapor):
        self.penulis, self.detik, self.lapor = penulis, 0.0, lapor

    def __getattr__(self, nama):
        return getattr(self.penulis, nama)

    def tulis(self, sistem, pesan):
        mulai = time.perf_counter()
        self.lapor("llm")
        try:
            return self.penulis.tulis(sistem, pesan)
        finally:
            self.detik += time.perf_counter() - mulai
            self.lapor("aturan")  # kalimat diperiksa aturan, lalu ulang LLM atau templat bila ditolak


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
    # Pemicu cepat: chat baru memanggil (target neutral) atau menuduh bot ini; langkah berikutnya tidak menunggu
    # NPC_STEP_SECONDS. Dihapus saat langkah mengambil snapshot.
    segera: bool = False


@dataclass
class KonfigurasiNPC:
    penulis: str = "otomatis"
    # Prioritas rantai penulis; jalur yang tidak tercantum dinonaktifkan.
    urutan_penulis: list = field(default_factory=lambda: list(JALUR_PENULIS))
    model_openrouter: str = ""  # kosong = model OpenRouter dari Konfigurasi AI/.env (qwen/qwen3-14b)
    model_tautan: str = ""  # kosong = model Ollama dari Konfigurasi AI/.env (OLLAMA_MODEL)


# Folder model pertama yang ada: pengaturan eksplisit, artifacts backend, lalu folder skripsi.
def folder_model(nilai, jenis) -> Path | None:
    if nilai and not Path(nilai).is_dir():
        # Salah ketik path di .env tidak boleh lolos diam-diam ke model lain.
        logger.warning("Folder model %s dari pengaturan tidak ditemukan: %s", jenis, nilai)
    nama_artifact, relatif = FOLDER_MODEL[jenis]
    kandidat = [
        nilai,
        BACKEND_DIR / "artifacts" / "indobert" / nama_artifact,
        PROJECT_DIR.parent / "training" / "prethesis" / "ai_2_dataset_baru" / relatif,
    ]
    return next((Path(p) for p in kandidat if p and Path(p).is_dir()), None)


# Daftar model di link LLM (Ollama /api/tags, atau OpenAI /v1/models) memakai klien penulis yang sama
# (token tunnel ikut). Kosong bila link tidak menjawab.
def _daftar_model_tautan(penulis, batas):
    data, _ = penulis._minta("GET", f"{penulis.url}/api/tags", batas=batas)
    if isinstance(data, dict) and isinstance(data.get("models"), list):
        nama = [m.get("name") or m.get("model") for m in data["models"]]
    else:
        data, _ = penulis._minta("GET", f"{penulis.url}/v1/models", batas=batas)
        ok = isinstance(data, dict) and isinstance(data.get("data"), list)
        nama = [m.get("id") for m in data["data"]] if ok else []
    return sorted({n for n in nama if isinstance(n, str) and n})


class BrainRuntime:
    def __init__(self):
        self.lock = threading.RLock()
        self.modul = {}
        self.nlg = None
        self.nlu = None
        self.penulis = None
        self.keterangan_penulis = {}  # jalur → alasan tidak masuk rantai (mis. key belum diisi)
        self.konfigurasi = KonfigurasiNPC(
            settings.npc_writer,
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
        # Model yang ada di link LLM (hasil cek terakhir), untuk pilihan model di panel.
        self.model_tautan_tersedia = []
        self.pertandingan: dict[str, dict[str, OtakBot]] = {}
        self._thread = None
        self._gagal_pada = None  # waktu (monotonic) pemuatan terakhir gagal; None = belum pernah gagal
        self.eksekutor_keputusan = ThreadPoolExecutor(1, thread_name_prefix="otak-npc")
        self.eksekutor_nlg = ThreadPoolExecutor(3, thread_name_prefix="nlg-npc")

    def _set(self, **nilai):
        with self.lock:
            self.status.update(nilai)

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
                "hasil_cek": getattr(p, "hasil_cek", None),
            })  # fmt: skip
        return baris

    # Status otak dan rantai penulis untuk panel dan layar persiapan.
    def ringkasan(self):
        with self.lock:
            penulis = self.penulis if self.konfigurasi.penulis != "templat" else None
            # Jalur yang menulis kalimat berikutnya: yang pertama siap (tidak ditolak dan tidak istirahat).
            berikut = penulis.terdepan() if penulis else None
            return {
                **self.status,
                "penulis_diminta": self.konfigurasi.penulis,
                "penulis_aktif": berikut is not None,
                "penulis": berikut.jalur if berikut else "templat",
                "model_penulis": berikut.model if berikut else None,
                "urutan_penulis": list(self.konfigurasi.urutan_penulis),
                "model_openrouter": self.konfigurasi.model_openrouter,
                "model_tautan": self.konfigurasi.model_tautan,
                "model_tautan_bawaan": ai_runtime.current().ollama_model,
                "model_tautan_tersedia": list(self.model_tautan_tersedia),
                "rantai_penulis": self._status_rantai(penulis, berikut),
                "pertandingan_aktif": len(self.pertandingan),
            }

    # RANTAI PENULIS sesuai urutan panel: key OpenRouter dan link LLM (Docker/tunnel) dari Konfigurasi AI
    # panel. Jalur tanpa key/link dilewati; semua gagal → templat.
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
            "openrouter": config.openrouter_api_key_value,
            "tautan": link,
        }
        model = {
            "openrouter": self.konfigurasi.model_openrouter or config.openrouter_model,
            "tautan": self.konfigurasi.model_tautan or config.ollama_model,
        }
        # Token tanpa spasi; None jika tidak diatur.
        token = config.ollama_tunnel_token
        try:
            rantai, self.keterangan_penulis = self.nlg.buat_rantai(
                self.konfigurasi.urutan_penulis, kunci, model,
                token_tautan=(token.get_secret_value().strip() or None) if token else None,
            )  # fmt: skip
        except Exception:
            logger.exception("Rantai penulis gagal disiapkan; memakai templat.")
            return None
        return rantai

    # Hit provider langsung; link juga diuji menghasilkan jawaban setelah penemuan model.
    # Hanya status yang dicatat, tanpa key. Penghitung dinaikkan pemanggil (segarkan_penulis).
    def _cek_penulis(self, penulis):
        try:
            with self._kunci_cek:
                hasil = []
                for p in penulis.daftar:
                    mulai = time.monotonic()
                    p.hasil_cek = {"keadaan": "memeriksa"}
                    status = p.cek()
                    if status == "ok" and p.jalur == "tautan":
                        teks, status = p.tulis("Jawab singkat.", "Balas: ok")
                        if status == "ok" and not (teks or "").strip():
                            status = p.gagal("jawaban pengujian kosong")[1]
                    p.hasil_cek = {
                        "keadaan": "berhasil" if status == "ok" else "gagal",
                        "waktu": time.time(),
                        "durasi_ms": round((time.monotonic() - mulai) * 1000),
                        "detail": status,
                    }
                    hasil.append((p.jalur, status))
                    if p.jalur == "tautan":
                        self.model_tautan_tersedia = (
                            _daftar_model_tautan(p, self.nlg.BATAS_CEK_DETIK)
                            if status == "ok"
                            else []
                        )
                logger.info("Cek penulis: %s", "; ".join(f"{j}={h}" for j, h in hasil))
        except Exception:
            logger.exception("Cek rantai penulis gagal.")
        finally:
            with self.lock:
                self._cek_tertunda -= 1
                self.status["sedang_cek_penulis"] = self._cek_tertunda > 0

    # Bangun ulang rantai (key/link/urutan terbaru) lalu cek semua jalurnya di latar.
    # latar=False (cek sinkron) hanya dipakai tes; panel membaca progres lewat polling.
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

    def _muat(self, nlu=None):
        try:
            self._set(detail="Memuat logika fuzzy…", progres=0.1)
            for metode, nama in METODE_MODUL.items():
                self.modul[metode] = importlib.import_module(f"app.module.npc_brain.generated.{nama}")
            self.nlg = importlib.import_module("app.module.npc_brain.generated.nlg")
            self._set(detail="Memuat NLU IndoBERT (intent dan target)…", progres=0.35)
            if nlu is None:
                # Tanpa IndoBERT otak dianggap gagal dimuat: bot memakai aksi cadangan engine.
                intent_dir = folder_model(settings.npc_intent_model_dir, "intent")
                target_dir = folder_model(settings.npc_target_model_dir, "target")
                if not intent_dir or not target_dir:
                    raise FileNotFoundError("Folder model IndoBERT tidak ditemukan.")
                model = self.nlg.NLUIndoBERT(intent_dir, target_dir, settings.npc_nlu_device)
                logger.info("IndoBERT dimuat dari %s dan %s", intent_dir, target_dir)
                nlu = NLUBersama(model, "indobert")
            self.nlu = nlu
            self._set(detail="Menyiapkan penulis kalimat…", progres=0.85)
            # Rantai dibangun sekarang dan dicek di latar: permainan tidak menunggu jaringan, dan jalur
            # yang belum selesai dicek tetap boleh dicoba (kegagalannya ditangani rantai).
            self.segarkan_penulis()
            self._set(siap=True, gagal=False, progres=1.0, detail="AI siap.", nlu=self.nlu.sumber)
            logger.info("Otak NPC siap: NLU=%s", self.nlu.sumber)
        except Exception:
            logger.exception("Otak NPC gagal dimuat.")
            self._gagal_pada = time.monotonic()
            self._set(
                siap=False, gagal=True,
                detail="Otak NPC gagal dimuat; bot memakai aksi cadangan engine.",
            )  # fmt: skip

    # STARTUP: muat modul otak, NLU, dan penulis di thread latar agar server langsung melayani request.
    def mulai_memuat(self):
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
                target=self._muat, daemon=True, name="muat-otak-npc"
            )
            self._thread.start()

    # Dipakai tes: muat sinkron, NLU palsu bisa dititipkan.
    def muat_sekarang(self, nlu=None):
        self._muat(nlu)

    # PANEL: ubah penulis/rantai saat server berjalan; rantai penulis langsung dipakai kalimat
    # berikutnya. Semua nilai divalidasi dulu (atomik).
    def atur(
        self,
        penulis=None,
        urutan_penulis=None,
        model_openrouter=None,
        model_tautan=None,
    ):
        if penulis is not None and penulis not in PENULIS_VALID:
            raise ValueError("Penulis kalimat tidak dikenal.")
        if urutan_penulis is not None:
            if not set(urutan_penulis) <= set(JALUR_PENULIS) or len(set(urutan_penulis)) != len(
                urutan_penulis
            ):
                raise ValueError("Urutan penulis berisi jalur yang tidak dikenal atau ganda.")
        if model_openrouter is not None:
            model_openrouter = model_openrouter.strip()
            if model_openrouter and not POLA_MODEL_OPENROUTER.fullmatch(model_openrouter):
                raise ValueError("Model OpenRouter harus berbentuk penyedia/model.")
        if model_tautan is not None:
            model_tautan = model_tautan.strip()
            if model_tautan and (
                len(model_tautan) > 100 or not POLA_MODEL_TAUTAN.fullmatch(model_tautan)
            ):
                raise ValueError("Nama model link LLM tidak valid (contoh: qwen3:4b-instruct).")
        with self.lock:
            k = self.konfigurasi
            sebelum = (k.penulis, list(k.urutan_penulis), k.model_openrouter, k.model_tautan)
            if penulis is not None:
                k.penulis = penulis
            if urutan_penulis is not None:
                k.urutan_penulis = urutan_penulis
            if model_openrouter is not None:
                k.model_openrouter = model_openrouter
            if model_tautan is not None:
                k.model_tautan = model_tautan
            rantai_berubah = sebelum != (
                k.penulis,
                list(k.urutan_penulis),
                k.model_openrouter,
                k.model_tautan,
            )
        if rantai_berubah:
            self.segarkan_penulis()
        return self.ringkasan()

    # Otak tiap bot; dipakai juga simulasi panel (tidak didaftarkan di sini).
    def buat_otak(self, match, bots):
        bots = sorted(bots)
        # Room mode cepat memakai durasi fase singkat; ingatan bot menghitung waktunya dari sini.
        cepat = match.durations == phase_durations(len(match.players), True)
        otak = {}
        for nama in bots:
            persona = self.nlg.persona_bot(nama, bots) if self.nlg else "santai"
            ingatan = self.modul["fuzzy"].Ingatan(nama, cepat=cepat)
            otak[nama] = OtakBot(nama, "fuzzy", persona, match.players[nama].role, ingatan)
        return otak

    # Sekali per pertandingan: persona dan ingatan setiap bot.
    def siapkan_pertandingan(self, match, room_code):
        with self.lock:
            if match.id in self.pertandingan:
                return []
            bots = sorted(p.name for p in match.players.values() if p.bot)
            otak = self.buat_otak(match, bots)
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
    # `waktu` mencatat lama tiap tahap (ms) dan `nlu_baru` chat yang baru dibaca IndoBERT di langkah ini.
    # selalu_jelaskan: simulasi panel ingin penjelasan juga untuk langkah diam; lapor(tahap) memberi tahu
    # simulasi tahap yang sedang berjalan (flowchart live).
    def langkah(self, bot: OtakBot, snapshot, sekarang, selalu_jelaskan=False, lapor=_tanpa_lapor):
        # modul = generated/otak_fuzzy.py (dimuat di _muat), jadi modul.putuskan ada di file itu.
        modul = self.modul[bot.metode]
        if TYPE_CHECKING:
            modul = otak_fuzzy
        mulai, jumlah_chat_sebelumnya = time.perf_counter(), len(bot.ingatan.chat)
        lapor("nlu")
        view = bot.ingatan.sinkron_snapshot(snapshot, sekarang, self.nlu)
        selesai_nlu = time.perf_counter()
        lapor("logika")
        keputusan = modul.putuskan(bot.ingatan, view)
        selesai_logika = time.perf_counter()
        lapor("penjelasan")
        keputusan["nlu_baru"] = [
            {"pengirim": c["pengirim"], "teks": c["teks"], "intent": c.get("intent"),
             "confidence": c.get("conf_intent"), "target": teks_target(c.get("target"))}
            for c in bot.ingatan.chat[jumlah_chat_sebelumnya:]
        ]  # fmt: skip
        if (
            selalu_jelaskan
            or keputusan["nlg"] is not None
            or keputusan["npc_decision"]["action"] != "wait"
        ):
            keputusan["penjelasan"] = jelaskan(bot, modul, view, keputusan)
        keputusan["waktu"] = {
            "nlu_ms": round((selesai_nlu - mulai) * 1000, 1),
            "logika_ms": round((selesai_logika - selesai_nlu) * 1000, 1),
            "penjelasan_ms": round((time.perf_counter() - selesai_logika) * 1000, 1),
        }
        # Konteks NLG: chat terbaru sepanjang konteks prompt, dan suara Tribunal sebagai pemicu bela diri/bela orang.
        chat = sorted(bot.ingatan.chat, key=lambda c: c["waktu"])[-self.nlg.JUMLAH_CHAT_KONTEKS :]
        konteks = {
            "roster": [p["nama"] for p in view["pemain"]],
            "chat_terbaru": [
                {"pengirim": c["pengirim"], "teks": c["teks"], "intent": c.get("intent"),
                 "target": [{"pemain": t["pemain"], "relasi": t["relasi"]} for t in c.get("target", [])]}
                for c in chat
            ],
            "suara_tribunal": dict(view["suara_tribunal"]),
        }  # fmt: skip
        return view, keputusan, konteks

    # NLG (thread penulis): rencana → kalimat, dengan pengaman aturan.
    # pakai_llm=False: hanya templat, dipakai sebagai cadangan cepat saat penulis LLM melewati batas waktu.
    def tulis(self, bot: OtakBot, payload, konteks, pakai_llm=True, lapor=_tanpa_lapor):
        with self.lock:
            pakai = pakai_llm and self.konfigurasi.penulis != "templat"
            penulis = self.penulis if pakai else None
        # Hindari kalimat sendiri yang lalu dan chat terbaru di room (bot lain tidak dikembari).
        hindari = tuple(bot.riwayat[-12:]) + tuple(c["teks"] for c in konteks["chat_terbaru"])
        jam = _JamPenulis(penulis, lapor) if penulis is not None else None
        lapor("nlg" if jam else "aturan")  # tanpa LLM: templat langsung dinilai aturan
        tulisan = self.nlg.tulis_pesan(payload, konteks, jam, bot.persona, hindari=hindari)
        tulisan["llm_detik"] = round(jam.detik, 3) if jam else 0.0
        return tulisan

    # Pesan pengguna yang dikirim ke LLM penulis pada percobaan pertama (panel: masukan NLG, juga saat ditunda).
    # None bila kalimat ditulis templat saja.
    def prompt_nlg(self, bot: OtakBot, payload, konteks):
        with self.lock:
            if self.penulis is None or self.konfigurasi.penulis == "templat":
                return None
        return self.nlg.buat_prompt(payload, konteks, bot.persona)[1]

    # PENCATAT NLU: baca satu chat dengan IndoBERT seperti ingatan bot (konteks = `riwayat` milik pemanggil,
    # urut kronologis). Hasil sama dengan bacaan bot dan masuk memo NLU, jadi bot tidak menghitung ulang.
    # Target neutral (pemain yang diajak bicara) ikut dengan asalnya: IndoBERT dan/atau aturan nama.
    # `konteks` = chat sebelumnya yang ikut dibaca Model 2 (maks KONTEKS_MAKS = 12) dan `daftar_pemain` = roster saat
    # itu; keduanya disimpan untuk riwayat panel dan ekspor format dataset (target sebagai {pemain, relasi}).
    def baca_chat(self, riwayat, pengirim, teks, roster):
        mulai = time.perf_counter()
        modul = self.modul["fuzzy"]
        konteks = [
            {"pengirim": c["pengirim"], "teks": c["teks"], "intent": c.get("intent"),
             "target": [{"pemain": t["pemain"], "relasi": t["relasi"]} for t in c.get("target", [])]}
            for c in riwayat[-modul.KONTEKS_MAKS:]
        ]  # fmt: skip
        chat = modul.anotasi_chat(
            self.nlu, {"pengirim": pengirim, "teks": teks}, riwayat, list(roster)
        )
        riwayat.append(chat)
        del riwayat[:-50]
        return {"intent": chat["intent"], "confidence": round(chat["conf_intent"], 3),
                "target": [{"pemain": t["pemain"], "relasi": t["relasi"],
                            "prob": None if t.get("prob") is None else round(t["prob"], 3),
                            "sumber": list(t.get("sumber", []))}
                           for t in chat["target"]],
                "konteks": konteks, "daftar_pemain": list(roster),
                "sumber": self.nlu.sumber, "ms": round((time.perf_counter() - mulai) * 1000, 1)}  # fmt: skip

    # Dipanggil setelah pesan benar-benar terkirim.
    def catat_chat(self, bot: OtakBot, view, rencana, teks):
        bot.ingatan.catat_aksi_bot(view, rencana)
        bot.riwayat.append(teks)

    # Dipanggil setelah vote diterima engine.
    def catat_vote(self, bot: OtakBot, view, rencana):
        bot.ingatan.catat_vote_bot(view, rencana)

    def tutup(self):
        self.eksekutor_keputusan.shutdown(wait=False, cancel_futures=True)
        self.eksekutor_nlg.shutdown(wait=False, cancel_futures=True)
        if self.penulis is not None:
            self.penulis.tutup()


brain_runtime = BrainRuntime()
