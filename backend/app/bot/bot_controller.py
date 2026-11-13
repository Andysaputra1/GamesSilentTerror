"""
Pengendali bot: urutan satu langkah setiap bot, dari jam permainan sampai vote, aksi malam, dan chat terkirim.

Bot diperlakukan seperti pemain tanpa browser. Otak bersama (BrainRuntime) memuat NLU (nlu.py), logika Fuzzy
(ingatan.py bahan bukti, fuzzy_controller.py putuskan, fungsi fuzzy di folder fuzzy/), dan penulis kalimat (nlg_controller.py, isi tahapnya di folder nlg/),
lalu menyimpan ingatan dan persona tiap bot per pertandingan.

Alurnya
1. Saat server nyala, main.py memanggil brain_runtime.mulai_memuat: fuzzy, IndoBERT, lalu rantai penulis dimuat di latar
2. Jam di main.py memanggil jalankan_bot_yang_sudah_waktunya tiap 0,5 detik
3. Data pertandingan yang sudah selesai dibuang
4. Tiap room: fase persiapan menjalankan prepare, fase lain menjalankan brain_turn untuk bot yang sudah waktunya
5. prepare: Tunggu otak siap, bagi persona dan siapkan ingatan tiap bot, lalu buka ronde 1
6. brain_turn (satu langkah satu bot):
   6.1 Lihat: Ambil snapshot permainan milik bot
   6.2 Pikir: ingatan mencatat snapshot, IndoBERT membaca chat baru, lalu fuzzy_controller.putuskan memutuskan
       (BrainRuntime.langkah)
   6.3 Aksi: Kirim vote atau aksi rahasia ke game (pindah pilihan malam bila otak memintanya), lalu vote yang diterima
       masuk ingatan bot
   6.4 Chat tim: Bila ada rekan manusia, tulis kalimat dan simpan di kanal tim, tanpa database, siaran, atau NLU
   6.5 Tulis chat: Minta giliran bicara, tulis kalimat (NLG), jeda mengetik, simpan chat
   6.6 Kirim: Siarkan chat ke room
   6.7 Catat: Simpan jejak untuk panel checker, IndoBERT membaca kalimat bot

Chat manusia masuk lewat sockets/chat.py dan services/chat_service.py, lalu bacaannya dicatat catat_nlu di file ini.
"""

from __future__ import annotations

import asyncio
import importlib
import json
import logging
import re
import threading
import time
from dataclasses import dataclass, field
from datetime import datetime
from functools import partial
from time import perf_counter
from typing import TYPE_CHECKING

from app.bot import nlg_controller
from app.bot.nlg.pengaturan import JamPenulis, PenulisNPC, tanpa_lapor
from app.bot.nlg.prompt import JUMLAH_CHAT_KONTEKS, buat_prompt
from app.bot.nlg.templat import persona_bot
from app.bot.nlu import NLUBersama, NLUIndoBERT, baca_chat, baca_chat_baru, folder_model
from app.bot.penjelasan import jelaskan
from app.bot.penjelasan import lengkapi as lengkapi_penjelasan
from app.bot.penjelasan import ringkas as ringkas_penjelasan
from app.config.settings import settings
from app.game.match_engine import phase_durations
from app.services.checker_service import EksekutorTercatat, checker_service, label_antrean
from app.services.persistence_service import PersistenceError, PersistenceService
from app.services.room_service import room_service
from app.services.survey_service import survey_service
from app.sockets.server import emit_room, sio

if TYPE_CHECKING:
    # Hanya untuk editor (Ctrl+klik). Saat program jalan modul ini dimuat di _muat, supaya server cepat nyala.
    from app.bot import fuzzy, fuzzy_controller

logger = logging.getLogger("shadow_heist.npc")
logger_otak = logging.getLogger("shadow_heist.npc_brain")

# Modul logika tiap metode: (bahan, pengendali, fungsi fuzzy). Game sekarang hanya memakai fuzzy: ingatan memegang
# Ingatan dan bahan bukti, fuzzy_controller memegang putuskan (mengimpor ingatan dan fuzzy), dan paket fuzzy memegang
# daftar sistem dan mesin Mamdani yang dibaca penjelasan panel.
METODE_MODUL = {"fuzzy": ("ingatan", "fuzzy_controller", "fuzzy")}
# Pemuatan otak yang gagal dicoba ulang paling cepat setelah jeda ini (detik).
JEDA_MUAT_ULANG_DETIK = 60
# Batas waktu keputusan otak dan penulisan kalimat (termasuk rantai LLM) agar bot tidak menggantung.
BATAS_LANGKAH_DETIK = 25
BATAS_TULIS_DETIK = 25
# Cadangan saat penulis LLM melewati batas: kalimat templat tidak memanggil jaringan, jadi jauh lebih cepat.
BATAS_TEMPLAT_DETIK = 10
# Pemicu cepat: jarak minimal antar-langkah bot yang dipanggil/dituduh (langkah biasa: NPC_STEP_SECONDS).
JEDA_SEGERA_DETIK = 1.0
# Lantai bicara: bot per pertandingan yang boleh menyusun chat bersamaan. Dihitung per pertandingan, sedangkan
# thread penulis (eksekutor_nlg, 3 thread) dipakai bersama semua room, jadi kalimat bisa antre di belakang room lain.
LANTAI_MAKS = 3


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


class BrainRuntime:
    """Otak bersama semua bot: status muat, NLU, penulis kalimat, otak tiap bot per pertandingan, dan thread kerja.

    Keputusan berjalan di satu thread (otak-npc) karena ingatan bot dan memo NLU tidak dirancang paralel; kalimat
    ditulis di thread terpisah (nlg-npc) supaya LLM tidak menahan keputusan bot lain. Kedua eksekutor mencatat isi
    antreannya untuk kotak Antrean di panel Checker (EksekutorTercatat; urutan dan jumlah thread tetap).
    """

    # Status awal sebelum otak dimuat; konfigurasi penulis dari .env sampai panel mengubahnya.
    def __init__(self):
        self.lock = threading.RLock()
        self.modul = {}
        self.nlg = None
        self.nlu = None
        self.penulis_npc = PenulisNPC(self.lock)
        self.status = {"siap": False, "gagal": False, "detail": "Belum dimuat.", "progres": 0.0, "nlu": None}
        self.pertandingan: dict[str, dict[str, OtakBot]] = {}
        self._thread = None
        self._gagal_pada = None  # waktu (monotonic) pemuatan terakhir gagal; None = belum pernah gagal
        self.eksekutor_keputusan = EksekutorTercatat("otak", 1, thread_name_prefix="otak-npc")
        self.eksekutor_nlg = EksekutorTercatat("penulis", 3, thread_name_prefix="nlg-npc")

    # Ubah status muat otak di bawah kunci.
    def _set(self, **nilai):
        with self.lock:
            self.status.update(nilai)

    # Status otak dan rantai penulis untuk panel dan layar persiapan.
    def ringkasan(self):
        with self.lock:
            return {
                **self.status,
                **self.penulis_npc.ringkasan(),
                "pertandingan_aktif": len(self.pertandingan),
            }

    # Bangun ulang rantai penulis (key/link/urutan terbaru) lalu cek semua jalurnya di latar. Sebelum otak dimuat
    # rantai belum dibangun; _muat yang membangunnya. latar=False (cek sinkron) hanya dipakai tes.
    def segarkan_penulis(self, latar=True):
        if self.nlg is not None:
            self.penulis_npc.segarkan(latar)
        return self.ringkasan()

    # Muat modul fuzzy, NLU IndoBERT, lalu rantai penulis. Gagal: bot memakai aksi cadangan engine.
    # Alur: 1 modul fuzzy dan nlg -> 2.1.1 NLU titipan tes, atau 2.2.1 cari folder model -> 2.2.2 buka IndoBERT
    #       -> 3 bangun rantai penulis dan cek di latar -> 4 tandai siap
    def _muat(self, nlu=None):
        try:
            self._set(detail="Memuat logika fuzzy…", progres=0.1)
            for metode, nama in METODE_MODUL.items():
                self.modul[metode] = tuple(importlib.import_module(f"app.bot.{n}") for n in nama)
            self.nlg = nlg_controller
            self._set(detail="Memuat NLU IndoBERT (intent dan target)…", progres=0.35)
            if nlu is None:
                # Tanpa IndoBERT otak dianggap gagal dimuat: bot memakai aksi cadangan engine.
                intent_dir = folder_model(settings.npc_intent_model_dir, "intent")
                target_dir = folder_model(settings.npc_target_model_dir, "target")
                if not intent_dir or not target_dir:
                    raise FileNotFoundError("Folder model IndoBERT tidak ditemukan.")
                model = NLUIndoBERT(intent_dir, target_dir, settings.npc_nlu_device)
                logger_otak.info("IndoBERT dimuat dari %s dan %s", intent_dir, target_dir)
                nlu = NLUBersama(model, "indobert")
            self.nlu = nlu
            self._set(detail="Menyiapkan penulis kalimat…", progres=0.85)
            # Rantai dibangun sekarang dan dicek di latar: permainan tidak menunggu jaringan, dan jalur
            # yang belum selesai dicek tetap boleh dicoba (kegagalannya ditangani rantai).
            self.segarkan_penulis()
            self._set(siap=True, gagal=False, progres=1.0, detail="AI siap.", nlu=self.nlu.sumber)
            logger_otak.info("Otak NPC siap: NLU=%s", self.nlu.sumber)
        except Exception:
            logger_otak.exception("Otak NPC gagal dimuat.")
            self._gagal_pada = time.monotonic()
            self._set(
                siap=False, gagal=True,
                detail="Otak NPC gagal dimuat; bot memakai aksi cadangan engine.",
            )  # fmt: skip

    # Saat server nyala: muat otak di thread latar agar server langsung melayani request.
    # Alur: 1 sudah siap atau sedang dimuat: selesai -> 2 baru gagal (< JEDA_MUAT_ULANG_DETIK): selesai
    #       -> 3 jalankan _muat di thread latar
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

    # Panel mengubah penulis/rantai saat server berjalan; rantai baru langsung dipakai kalimat berikutnya.
    # Semua nilai divalidasi dulu (atomik) di PenulisNPC.atur.
    def atur(self, penulis=None, urutan_penulis=None, model_openrouter=None, model_tautan=None):
        if self.penulis_npc.atur(penulis, urutan_penulis, model_openrouter, model_tautan):
            self.segarkan_penulis()
        return self.ringkasan()

    # Otak tiap bot: persona bergiliran dan ingatan sendiri. Dipakai juga simulasi panel (tidak didaftarkan di sini).
    def buat_otak(self, match, bots):
        bots = sorted(bots)
        # Room mode cepat memakai durasi fase singkat; ingatan bot menghitung waktunya dari sini.
        cepat = match.durations == phase_durations(len(match.players), True)
        otak = {}
        for nama in bots:
            persona = persona_bot(nama, bots) if self.nlg else "santai"
            ingatan = self.modul["fuzzy"][0].Ingatan(nama, cepat=cepat)
            otak[nama] = OtakBot(nama, "fuzzy", persona, match.players[nama].role, ingatan)
        return otak

    # Sekali per pertandingan: persona dan ingatan setiap bot. Hasil: baris untuk arsip survei (kosong bila sudah).
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

    # Otak satu bot di satu pertandingan; None bila otak belum atau gagal dimuat.
    def otak_bot(self, match_id, nama) -> OtakBot | None:
        with self.lock:
            return self.pertandingan.get(match_id, {}).get(nama)

    # Buang ingatan pertandingan yang sudah tidak aktif.
    def lupakan_kecuali(self, match_ids):
        with self.lock:
            for match_id in [m for m in self.pertandingan if m not in match_ids]:
                del self.pertandingan[match_id]

    # Satu keputusan di thread otak: sinkron snapshot, NLU membaca chat baru, putuskan() metode bot, lalu penjelasan
    # untuk panel.
    # Penjelasan hanya untuk langkah yang bisa menjadi jejak: ada vote/aksi, rencana chat, atau chat tim; langkah diam
    # tidak dicatat. `waktu` mencatat lama tiap tahap (ms) dan `nlu_baru` chat yang baru dibaca IndoBERT di langkah
    # ini. selalu_jelaskan: simulasi panel ingin penjelasan juga untuk langkah diam; lapor(tahap) memberi tahu simulasi
    # (flowchart live) dan Checker (alur live, lewat brain_turn) tahap yang sedang berjalan.
    # Alur: 1 sinkron snapshot -> 2 NLU membaca chat baru -> 3 putuskan -> 4 chat yang baru dibaca -> 5 penjelasan
    #       -> 6 lama tiap tahap -> 7 konteks NLG
    def langkah(self, bot: OtakBot, snapshot, sekarang, selalu_jelaskan=False, lapor=tanpa_lapor):
        # modul = bot/fuzzy_controller.py (putuskan), paket_fuzzy = bot/fuzzy/ (keduanya dimuat di _muat).
        # Penjelasan panel membaca keduanya: ambang keputusan di fuzzy_controller, daftar sistem dan mesin di fuzzy/.
        _, modul, paket_fuzzy = self.modul[bot.metode]
        if TYPE_CHECKING:
            modul, paket_fuzzy = fuzzy_controller, fuzzy
        mulai, jumlah_chat_sebelumnya = time.perf_counter(), len(bot.ingatan.chat)
        lapor("nlu")
        view = bot.ingatan.sinkron_snapshot(snapshot, sekarang)
        baca_chat_baru(self.nlu, bot.ingatan, [p["nama"] for p in view["pemain"]], jumlah_chat_sebelumnya)
        selesai_nlu = time.perf_counter()
        lapor("logika")
        keputusan = modul.putuskan(bot.ingatan, view)
        selesai_logika = time.perf_counter()
        lapor("penjelasan")
        # Target ditulis pendek untuk panel, mis. "NOX: offend (0.91)".
        keputusan["nlu_baru"] = [
            {"pengirim": c["pengirim"], "teks": c["teks"], "intent": c.get("intent"),
             "confidence": c.get("conf_intent"),
             "target": [f"{t['pemain']}: {t['relasi']}"
                        + (f" ({t['prob']:.2f})" if t.get("prob") is not None else "")
                        for t in c.get("target") or []]}
            for c in bot.ingatan.chat[jumlah_chat_sebelumnya:]
        ]  # fmt: skip
        if (
            selalu_jelaskan
            or keputusan["nlg"] is not None
            or keputusan.get("nlg_tim") is not None
            or keputusan["npc_decision"]["action"] != "wait"
        ):
            keputusan["penjelasan"] = jelaskan(bot, (modul, paket_fuzzy), view, keputusan)
        keputusan["waktu"] = {
            "nlu_ms": round((selesai_nlu - mulai) * 1000, 1),
            "logika_ms": round((selesai_logika - selesai_nlu) * 1000, 1),
            "penjelasan_ms": round((time.perf_counter() - selesai_logika) * 1000, 1),
        }
        # Konteks NLG: chat terbaru sepanjang konteks prompt, dan suara Tribunal sebagai pemicu bela diri/bela orang.
        chat = sorted(bot.ingatan.chat, key=lambda c: c["waktu"])[-JUMLAH_CHAT_KONTEKS:]
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

    # Rencana menjadi kalimat (thread penulis), dengan pengaman aturan. pakai_llm=False: hanya templat, dipakai sebagai
    # cadangan cepat saat penulis LLM melewati batas waktu.
    # Alur: 1 pilih rantai (atau templat) -> 2 kalimat yang harus dihindari -> 3 tulis_pesan -> 4 catat lama LLM
    def tulis(self, bot: OtakBot, payload, konteks, pakai_llm=True, lapor=tanpa_lapor):
        penulis = self.penulis_npc.dipakai(pakai_llm)
        # Hindari kalimat sendiri yang lalu dan chat terbaru di room (bot lain tidak dikembari).
        hindari = tuple(bot.riwayat[-12:]) + tuple(c["teks"] for c in konteks["chat_terbaru"])
        jam = JamPenulis(penulis, lapor) if penulis is not None else None
        lapor("nlg" if jam else "aturan")  # tanpa LLM: templat langsung dinilai aturan
        tulisan = self.nlg.tulis_pesan(payload, konteks, jam, bot.persona, hindari=hindari)
        tulisan["llm_detik"] = round(jam.detik, 3) if jam else 0.0
        return tulisan

    # Chat tim (thread penulis): paket rencana menjadi kalimat, tanpa IndoBERT. Hasilnya tidak masuk riwayat kalimat
    # publik.
    def tulis_tim(self, bot: OtakBot, payload, roster, pakai_llm=True):
        return self.nlg.tulis_chat_tim(payload, roster, self.penulis_npc.dipakai(pakai_llm), bot.persona)

    # Pesan pengguna yang dikirim ke LLM penulis pada percobaan pertama (panel: masukan NLG, juga saat ditunda).
    # None bila kalimat ditulis templat saja.
    def prompt_nlg(self, bot: OtakBot, payload, konteks):
        if self.penulis_npc.dipakai() is None:
            return None
        return buat_prompt(payload, konteks, bot.persona)[1]

    # Dipanggil setelah pesan benar-benar terkirim.
    def catat_chat(self, bot: OtakBot, view, rencana, teks):
        bot.ingatan.catat_aksi_bot(view, rencana)
        bot.riwayat.append(teks)

    # Dipanggil setelah vote diterima engine.
    def catat_vote(self, bot: OtakBot, view, rencana):
        bot.ingatan.catat_vote_bot(view, rencana)

    # Dipanggil setelah rencana chat tim dikerjakan: yang dicatat pemicunya, bukan kalimatnya.
    def catat_chat_tim(self, bot: OtakBot, view, rencana, terkirim):
        bot.ingatan.catat_chat_tim(view, rencana, terkirim)

    # Server mati: hentikan thread keputusan dan penulis, lalu tutup koneksi rantai LLM.
    def tutup(self):
        self.eksekutor_keputusan.shutdown(wait=False, cancel_futures=True)
        self.eksekutor_nlg.shutdown(wait=False, cancel_futures=True)
        self.penulis_npc.tutup()


brain_runtime = BrainRuntime()


# Lama tiap tahap satu langkah bot (ms): NLU + sinkron ingatan, logika metode, penjelasan panel, lalu NLG
# (total, panggilan LLM, dan sisanya = aturan + templat).
def waktu_jejak(waktu, tulisan):
    hasil = dict(waktu or {})
    if tulisan:
        nlg, llm = tulisan.get("detik") or 0.0, tulisan.get("llm_detik") or 0.0
        hasil.update(nlg_ms=round(nlg * 1000, 1), llm_ms=round(llm * 1000, 1),
                     aturan_ms=round(max(0.0, nlg - llm) * 1000, 1))  # fmt: skip
    return hasil


# Isi jejak checker satu langkah otak; dipakai room asli (NPCService.brain_turn) dan simulasi panel.
# Alur: 1 lengkapi penjelasan dengan hasil engine dan NLG -> 2 isi tahap, metode, persona, dan keputusan ringkas
#       -> 3 ringkasan untuk daftar jejak
def isi_jejak(trace, match, otak, npc, rencana, tulisan, penolakan, durasi_ms, ditunda, penjelasan,
              waktu, nlu_sumber, masukan_nlg=None, chat_tim=None):  # fmt: skip
    penjelasan = lengkapi_penjelasan(penjelasan, npc, rencana, tulisan, penolakan, ditunda,
                                     masukan_nlg)  # fmt: skip
    trace.update(match_id=match.id, stage=(
        "npc_brain_rejected" if penolakan else "npc_brain"
    ), provider=f"otak:{otak.metode}", model=f"persona:{otak.persona}", intent=rencana.get(
        "intent"
    ), output=json.dumps(
        {
            "action": npc["action"],
            "target": npc["target"],
            "chat": {
                "aksi": rencana["aksi"],
                "jenis": rencana.get("jenis"),
                "target": rencana["target"],
                "role_diakui": rencana.get("role_diakui"),
                "alasan": rencana["alasan"][:2],
                "ditunda": ditunda,  # lantai bicara penuh/kembar: diputuskan ulang nanti
            },
            "nlg": (
                None
                if not tulisan
                else {
                    "sumber": tulisan["sumber"],
                    "pelanggaran": tulisan["pelanggaran"],
                }
            ),
            "nlu": nlu_sumber,
            # Hanya status dan panjang teks: isi chat tim rahasia.
            **({"chat_tim": chat_tim} if chat_tim else {}),
        },
        ensure_ascii=False,
        ),  # fmt: skip
        error=penolakan,
        duration_ms=durasi_ms,
        timings=waktu,
        penjelasan=penjelasan,
        ringkas=ringkas_penjelasan(penjelasan),  # untuk daftar jejak tanpa memuat penjelasan
    )
    return trace


# NLG dengan batas waktu. Jika penulis LLM terlalu lama, kalimat tetap dikirim dari templat agar
# rencana bot tidak hilang. Thread LLM yang tertinggal selesai sendiri; rantai penulis mencatat
# hasilnya (mis. mengistirahatkan jalur yang lambat) untuk kalimat berikutnya.
# lapor(tahap): simulasi panel dan alur live Checker memantau tahap NLG (nlg, llm, aturan).
# Alur: 1 tulis di thread NLG dengan batas BATAS_TULIS_DETIK -> 2 lewat batas: templat di thread bawaan -> 3 catat
#       percobaan LLM yang melewati batas
async def tulis_kalimat(runtime, otak, payload, konteks, lapor=None):
    loop = asyncio.get_running_loop()
    tulis = runtime.tulis if lapor is None else partial(runtime.tulis, lapor=lapor)
    try:
        return await asyncio.wait_for(
            loop.run_in_executor(runtime.eksekutor_nlg, tulis, otak, payload, konteks),
            timeout=BATAS_TULIS_DETIK,
        )
    except TimeoutError:
        logger.warning("Kalimat %s melewati %s detik; memakai templat.", otak.nama,
                       BATAS_TULIS_DETIK)  # fmt: skip
    # Thread bawaan, bukan eksekutor NLG: jangan antre di belakang panggilan LLM yang tertahan.
    tulisan = await asyncio.wait_for(
        asyncio.to_thread(tulis, otak, payload, konteks, False),
        timeout=BATAS_TEMPLAT_DETIK,
    )
    batas = {"sumber": "llm", "status": f"melewati batas {BATAS_TULIS_DETIK} detik"}
    return {**tulisan, "percobaan": [batas, *tulisan["percobaan"]]}


# Chat tim dengan batas waktu sisa malam: bila penulis LLM terlalu lama, kabar tetap sampai lewat templat.
# Alur: 1 tulis di thread NLG dengan batas sisa malam -> 2 lewat batas: templat di thread bawaan
async def tulis_kalimat_tim(runtime, otak, payload, roster, sisa_detik):
    loop = asyncio.get_running_loop()
    try:
        return await asyncio.wait_for(
            loop.run_in_executor(runtime.eksekutor_nlg, runtime.tulis_tim, otak, payload, roster),
            timeout=max(1.0, min(BATAS_TULIS_DETIK, sisa_detik - 2)),
        )
    except TimeoutError:
        logger.warning("Chat tim %s melewati batas waktu; memakai templat.", otak.nama)
    return await asyncio.wait_for(
        asyncio.to_thread(runtime.tulis_tim, otak, payload, roster, False),
        timeout=BATAS_TEMPLAT_DETIK,
    )


# Riwayat pencatat NLU per pertandingan (konteks target, urut kronologis); dibuang saat pertandingan usai.
riwayat_nlu: dict[str, list] = {}


# Roster berlabel dengan urutan yang sama seperti snapshot bot (kunci memo NLU ikut sama).
def roster_label(match):
    return [match.labels.get(nama, nama) for nama in match.players]


# Pencatat NLU: baca satu chat pertandingan dengan IndoBERT di thread keputusan (urut dengan langkah bot), simpan
# bacaannya ke riwayat chat, dan kembalikan hasilnya (None bila otak belum siap atau gagal). Dipakai chat manusia
# (services/chat_service.py) dan chat bot (brain_turn).
# Alur: 1 otak belum siap: None -> 2 nlu.baca_chat di thread keputusan -> 3 bangunkan bot yang dipanggil/dituduh
#       -> 4 simpan bacaan ke pesan di MySQL
async def catat_nlu(match, pengirim, teks, message_id=None, runtime=brain_runtime, room_code=None):
    if runtime.nlu is None or not runtime.modul:
        return None
    riwayat = riwayat_nlu.setdefault(match.id, [])
    label = match.labels.get(pengirim, pengirim)
    try:
        with label_antrean(room_code, label, "IndoBERT membaca chat", teks):
            tugas = asyncio.get_running_loop().run_in_executor(
                runtime.eksekutor_keputusan,
                baca_chat,
                runtime.nlu,
                riwayat,
                label,
                teks,
                roster_label(match),
            )
        nlu = await tugas
    except Exception:
        logger.exception("NLU chat gagal dicatat.")
        return None
    # Pemicu cepat: bot yang dipanggil chat ini (target neutral, dari IndoBERT atau aturan nama) atau dituduhnya
    # (target offend) melangkah pada putaran jam berikutnya, tanpa menunggu NPC_STEP_SECONDS. Lantai bicara dan aturan
    # chat otak (jatah, jeda, satu jawaban per panggilan) tetap menentukan apakah bot benar-benar bicara.
    for t in nlu.get("target", []):
        if t["relasi"] in ("neutral", "offend") and t["pemain"] != label:
            otak = runtime.otak_bot(match.id, match.username(t["pemain"]))
            if otak is not None:
                otak.segera = True
    if message_id is not None:
        try:
            await asyncio.to_thread(PersistenceService(room_code).record_nlu, message_id, nlu)
        except PersistenceError:
            logger.warning("Bacaan NLU tidak tersimpan (migrasi V9?).")
    return nlu


class NPCService:
    """Penjadwal bot: tiap putaran jam memilih bot yang sudah waktunya melangkah, lalu menjalankan langkahnya.

    Bot memakai services/room_service.py untuk melihat permainan dan untuk vote, aksi malam, chat tim, dan chat publik,
    sama seperti pemain memakai service. Pengiriman ke room lewat emit_room di sockets/server.py.
    """

    # broadcast = fungsi kirim ke room (emit_room); runtime boleh diganti otak tiruan di tes.
    def __init__(self, sio, *, broadcast=None, runtime=None):
        self.broadcast = broadcast or sio.emit
        self.tasks = set()
        self.preparing = set()
        self.runtime = runtime or brain_runtime
        # Lantai bicara: match_id → {bot yang sedang menyusun/mengetik chat: (intent, target) rencananya}.
        self.lantai: dict[str, dict[str, tuple]] = {}

    # Jalankan coroutine sebagai task yang dilacak agar bisa dibatalkan saat shutdown.
    def _spawn(self, coroutine):
        task = asyncio.create_task(coroutine)
        self.tasks.add(task)
        task.add_done_callback(self.tasks.discard)
        return task

    # Jadwal satu bot di fase ini: detik sejak fase mulai sebelum boleh melangkah (digeser per urutan agar bot tidak
    # bicara serentak) dan jeda antar-langkah, lebih pendek bila bot baru dipanggil atau dituduh (otak.segera).
    def _jadwal_langkah(self, otak, match, urutan):
        waktu_mulai = min(2.0, match.durations[match.phase] / 6) + (urutan % 4) * 0.7
        jeda = JEDA_SEGERA_DETIK if otak.segera else settings.npc_step_seconds
        return waktu_mulai, jeda

    # Otak mengambil langkah berkala menurut _jadwal_langkah; tidak ada langkah di detik terakhir fase.
    def _sudah_waktunya_melangkah(self, otak, match, lama_fase_berjalan, waktu_sekarang, urutan):
        waktu_mulai, jeda = self._jadwal_langkah(otak, match, urutan)
        if lama_fase_berjalan < waktu_mulai or match.deadline - waktu_sekarang < 1.0:
            return False
        return waktu_sekarang - otak.langkah_terakhir >= jeda

    # Layar persiapan: tunggu otak siap, bagi persona per bot, lalu buka ronde 1.
    # Alur: 1 mulai memuat otak -> 2 salin progres ke layar persiapan sampai siap atau gagal -> 3.1 siap: siapkan otak
    #       tiap bot dan catat metode bot ke arsip survei -> 4 buka ronde 1
    #       \> 3.2 gagal: buka ronde 1, bot memakai aksi cadangan engine
    async def prepare(self, code, match):
        detail = "AI siap."
        try:
            self.runtime.mulai_memuat()
            while True:
                status = self.runtime.ringkasan()
                # Jika batas tunggu lewat dan ronde 1 sudah mulai, otak tetap bergabung saat siap.
                if not room_service.progres_persiapan_ai(match, status["detail"], status["progres"]):
                    return
                if status["siap"] or status["gagal"]:
                    break
                await asyncio.sleep(0.5)
            if status["gagal"]:
                room_service.ai_siap(match, status["detail"])
                return
            rows = self.runtime.siapkan_pertandingan(match, code)
            if rows:
                detail = f"AI siap: {len(rows)} bot."
                try:
                    await asyncio.to_thread(survey_service.record_match_bots, rows)
                except PersistenceError:
                    logger.warning("Metode bot tidak tersimpan ke database (migrasi V7?).")
            room_service.ai_siap(match, detail)
        except Exception:
            logger.exception("Persiapan otak NPC gagal.")
            room_service.ai_siap(match, "Persiapan AI gagal; bot memakai aksi cadangan engine.")

    # Vote/aksi rahasia diterapkan segera lewat room_service; vote yang diterima masuk ingatan bot.
    # Hasil: (masih berlaku, pesan penolakan engine atau None).
    def _kirim_vote_atau_aksi(self, code, match, fase, otak, view, keputusan):
        keputusan_aksi = keputusan["npc_decision"]
        masih_berlaku, penolakan = room_service.pilihan_bot(code, match, fase, otak.nama, keputusan_aksi)
        if masih_berlaku and penolakan is None and keputusan_aksi["action"] == "vote":
            self.runtime.catat_vote(otak, view, keputusan["rencana_vote"])
        return masih_berlaku, penolakan

    # Chat tim rahasia, jadi tanpa lantai bicara, database, siaran, NLU, atau @traced (lihat room_service.chat_tim_bot).
    # Penerima membacanya lewat snapshot. Hasil untuk jejak: status dan panjang teks, tanpa isi.
    # Alur: 1 tulis kalimat dengan batas sisa malam -> 2 kirim ke kanal tim -> 3 pemicunya masuk ingatan bot
    async def _kirim_chat_tim(self, code, match, fase, otak, view, payload, roster):
        with label_antrean(code, otak.nama, "menulis chat tim"):
            tulisan = await tulis_kalimat_tim(
                self.runtime, otak, payload, roster, match.deadline - time.time()
            )
        teks = tulisan["teks"]
        terkirim = room_service.chat_tim_bot(code, match, fase, otak.nama, teks)
        self.runtime.catat_chat_tim(otak, view, payload, terkirim)
        status = "terkirim" if terkirim else "tidak terkirim" if teks else "kosong"
        return {"status": status, "panjang": len(teks)}

    # Lantai bicara: paling banyak LANTAI_MAKS bot menyusun/mengetik chat bersamaan per pertandingan (LLM menulis
    # paralel). Ditolak bila lantai penuh, bila bot lain sedang menulis rencana kembar (intent dan target sama: tidak
    # ada tuduhan atau pertanyaan serentak yang sama), atau bila rencana dibuat sebelum chat bot lain masuk. Bot yang
    # ditolak memutuskan ulang di langkah berikutnya dengan chat terbaru.
    # Alur: 1 lantai penuh atau rencana kembar: tolak -> 2 ada chat bot lain sesudah yang dilihat: tolak -> 3 ambil
    #       tempat di lantai dan tampilkan awan berpikir
    def _ambil_giliran_bicara(self, match, otak, id_chat_terakhir_dilihat, rencana_chat):
        penyusun = self.lantai.get(match.id, {})
        niat = (rencana_chat.get("intent"), rencana_chat.get("target"))
        if len(penyusun) >= LANTAI_MAKS or niat in penyusun.values():
            return False
        with room_service.lock:
            pesan = list(match.messages)
        semua_id = [m["id"] for m in pesan]
        pesan_baru = (
            pesan[semua_id.index(id_chat_terakhir_dilihat) + 1 :]
            if id_chat_terakhir_dilihat in semua_id
            else pesan
        )
        nama_bot = {p.name for p in match.players.values() if p.bot}
        if any(m["sender"] in nama_bot and m["sender"] != otak.nama for m in pesan_baru):
            return False
        self.lantai.setdefault(match.id, {})[otak.nama] = niat
        room_service.mulai_berpikir_bot(match, otak.nama)
        return True

    # Satu langkah bot: lihat permainan, berpikir, vote/aksi langsung, lalu kalimat lewat lantai bicara.
    # Untuk panel Checker, tahap yang sedang berjalan dilaporkan ke checker_service (alur live, lapor), lama antre dan
    # jeda ikut ke timings jejak, dan langkah yang error dicatat dengan jenis, pesan singkat, dan tahap gagalnya.
    # Alur: 1 lihat snapshot milik bot -> 2 berpikir di thread keputusan (NLU, fuzzy, penjelasan) -> 3 vote/aksi ke
    #       game -> 4 chat tim -> 5 giliran bicara, tulis kalimat, jeda mengetik, simpan chat -> 6 jejak checker,
    #       siaran chat, NLU membaca kalimat bot -> 7 selesai: lepas lantai bicara, bot tidak sibuk
    #       \> 1.2 / 3.2 room berganti, bot tersingkir, atau fase berganti selama berpikir: berhenti [lanjut 7]
    async def brain_turn(self, code, match, otak):
        waktu_mulai = perf_counter()
        sedang_bicara = gagal = False
        # Panel Checker: tahap brain_turn saat ini (dicatat bila error), alur live, hasil langkah, dan jenis error.
        tahap, langkah_live, hasil_langkah, jenis_error = "lihat", None, "diam", None
        try:
            # 1 lihat snapshot milik bot
            dilihat = room_service.lihat_untuk_bot(code, match, otak.nama)
            if dilihat is None:
                return
            fase, snapshot, id_chat_terakhir_dilihat = dilihat
            otak.segera = False  # snapshot ini sudah memuat chat pemicunya
            waktu_sekarang = time.time()
            otak.langkah += 1
            # Alur live Checker: tahap pertama antre thread otak (dipakai bersama semua bot dan IndoBERT chat manusia).
            langkah_live = checker_service.mulai_langkah(code, match.id, otak.nama, otak.langkah)
            lapor = langkah_live.lapor
            loop = asyncio.get_running_loop()

            # 2 berpikir di thread keputusan, dengan batas waktu. Tahap L baru saat thread keputusan benar-benar mulai
            # (bisa antre di belakang bot lain).
            def pikirkan_langkah():
                room_service.tandai_tahap_bot(match, otak.nama, "L")
                return self.runtime.langkah(otak, snapshot, waktu_sekarang, lapor=lapor)

            tahap = "berpikir"
            with label_antrean(code, otak.nama, "berpikir (NLU + Fuzzy)"):
                tugas = loop.run_in_executor(self.runtime.eksekutor_keputusan, pikirkan_langkah)
            view, keputusan, konteks = await asyncio.wait_for(tugas, timeout=BATAS_LANGKAH_DETIK)
            keputusan_aksi, rencana_chat = keputusan["npc_decision"], keputusan["rencana_chat"]

            # 3 vote dan aksi rahasia langsung ke game, tidak menunggu kalimat selesai diketik
            tahap = "vote_aksi"
            lapor("engine")
            masih_berlaku, penolakan = self._kirim_vote_atau_aksi(
                code, match, fase, otak, view, keputusan
            )
            if not masih_berlaku:
                hasil_langkah = "basi"
                return  # fase berganti selama bot berpikir: keputusan basi dibuang

            # 4 chat tim. Pilihan yang ditolak engine tidak dikabarkan ke rekan.
            status_tim = None
            if keputusan.get("nlg_tim") is not None and not penolakan:
                tahap = "chat_tim"
                lapor("tim")
                status_tim = await self._kirim_chat_tim(
                    code, match, fase, otak, view, keputusan["nlg_tim"], konteks["roster"]
                )

            # 5 minta giliran bicara, tulis kalimat, jeda mengetik, lalu simpan chat
            kalimat = pesan_terkirim = id_pesan = None
            lapor("giliran")  # alur live: engine_ms dan tim_ms berhenti di sini
            chat_ditunda = keputusan["nlg"] is not None and not self._ambil_giliran_bicara(
                match, otak, id_chat_terakhir_dilihat, rencana_chat
            )
            if keputusan["nlg"] is not None and not chat_ditunda:
                sedang_bicara = True
                tahap = "tulis"
                lapor("antre_nlg")
                penulis = "LLM" if self.runtime.penulis_npc.dipakai() is not None else "templat"
                with label_antrean(code, otak.nama, f"menulis kalimat ({penulis})"):
                    kalimat = await tulis_kalimat(
                        self.runtime, otak, keputusan["nlg"], konteks, lapor=lapor
                    )
                # Jeda mengetik: balasan instan terasa seperti mesin.
                lama_mengetik = min(4.0, max(1.0, len(kalimat["teks"]) / 30))
                lapor("ketik")
                if match.deadline - time.time() > lama_mengetik + 1:
                    await asyncio.sleep(lama_mengetik)
                # Chat masuk hanya jika fase masih sama dan bot masih boleh bicara; ingatan dicatat setelah terkirim.
                tahap = "kirim"
                lapor("simpan")
                pesan_terkirim, id_pesan = room_service.chat_bot(
                    code, match, fase, otak.nama, kalimat["teks"]
                )
                if pesan_terkirim:
                    self.runtime.catat_chat(otak, view, rencana_chat, kalimat["teks"])

            # 6 jejak untuk panel checker (tanpa role pemain lain), siaran chat, bacaan IndoBERT
            tahap = "jejak"
            lapor("jejak")  # alur live: simpan_ms berhenti di sini
            jejak = None
            if (
                pesan_terkirim
                or keputusan_aksi["action"] != "wait"
                or penolakan
                or chat_ditunda
                or status_tim
            ):
                hasil_langkah = "ditunda" if chat_ditunda else "ditolak" if penolakan else "bertindak"
                # Masukan NLG ikut dicatat, juga saat ditunda: panel tetap melihat apa yang akan ditulis.
                masukan_nlg = (
                    None if keputusan["nlg"] is None
                    else {"rencana": keputusan["nlg"],
                          "prompt": self.runtime.prompt_nlg(otak, keputusan["nlg"], konteks)}
                )  # fmt: skip
                kalimat_terkirim = kalimat if pesan_terkirim else None
                jejak = isi_jejak(
                    checker_service.begin(
                        code,
                        otak.nama,
                        kalimat_terkirim["teks"] if kalimat_terkirim else keputusan_aksi["action"],
                    ),
                    match,
                    otak,
                    keputusan_aksi,
                    rencana_chat,
                    kalimat_terkirim,
                    penolakan,
                    round((perf_counter() - waktu_mulai) * 1000, 2),
                    chat_ditunda,
                    keputusan.get("penjelasan"),  # hanya dibaca panel admin
                    {**waktu_jejak(keputusan.get("waktu"), kalimat_terkirim),
                     **langkah_live.waktu_tunggu()},
                    getattr(self.runtime.nlu, "sumber", None),
                    masukan_nlg,
                    status_tim,
                )  # fmt: skip
                # Jejak sudah ada: langkah keluar dari alur live (siaran dan arsip DB di luar duration_ms).
                checker_service.selesai_langkah(langkah_live, hasil_langkah)
            if pesan_terkirim:
                tahap = "kirim"
                await self.broadcast("receive_chat", pesan_terkirim, to=code)
            if jejak is not None:
                tahap = "jejak"
                # Disimpan di thread latar: tulisan DB (hingga ±12 KB penjelasan per jejak) tidak menahan
                # event loop game. Jejak di memori (checker) sudah tersedia sejak checker_service.begin.
                try:
                    await asyncio.to_thread(PersistenceService(code).record_trace, jejak)
                except PersistenceError:
                    pass  # gagal simpan tidak menghentikan bot; jejak tetap ada di memori checker
            # Di latar: lantai bicara tidak ditahan selama NLU membaca kalimat ini.
            if pesan_terkirim:
                self._spawn(
                    catat_nlu(
                        match, otak.nama, pesan_terkirim["message"], id_pesan, self.runtime, code
                    )
                )
        except Exception as error:
            gagal, hasil_langkah, jenis_error = True, "error", type(error).__name__
            logger.exception("Langkah otak %s gagal.", otak.nama)
            # Pesan singkat untuk panel: path lokal dan nilai rahasia (key, token, password) disamarkan.
            pesan = re.sub(r"(?:[A-Za-z]:)?(?:[\\/][\w.-]+){2,}", "<path>", str(error))
            pesan = re.sub(
                r"(?i)\b(?:sk-[\w-]{6,}|bearer\s+\S+|(?:api[_-]?key|key|token|password|secret)\s*[=:]\s*\S+)",
                "<rahasia>",
                pesan,
            )
            jejak_gagal = checker_service.begin(code, otak.nama, "NPC brain")
            jejak_gagal.update(
                match_id=match.id, stage="npc_brain_error", provider=f"otak:{otak.metode}",
                error=jenis_error, error_pesan=pesan[:200], error_tahap=tahap,
                langkah=otak.langkah, duration_ms=round((perf_counter() - waktu_mulai) * 1000, 2),
            )  # fmt: skip
            if langkah_live is not None:
                # Tahap live saat gagal (mis. masih antre thread otak) dan lama tiap tahap sampai gagal.
                jejak_gagal.update(
                    tahap_live=langkah_live.lihat()["tahap"], tahap_ms=langkah_live.lama_sekarang()
                )
            if isinstance(error, TimeoutError):
                # Batas yang terlewati: keputusan (asyncio.wait_for), atau templat cadangan sesudah LLM melewati batas.
                jejak_gagal["batas_detik"] = {
                    "berpikir": BATAS_LANGKAH_DETIK, "tulis": BATAS_TEMPLAT_DETIK,
                    "chat_tim": BATAS_TEMPLAT_DETIK,
                }.get(tahap)  # fmt: skip
        finally:
            # 7 selesai, juga saat error: alur live ditutup, lepas giliran bicara, dan tandai bot tidak sibuk.
            if langkah_live is not None:
                checker_service.selesai_langkah(langkah_live, hasil_langkah, jenis_error)
            penyusun = self.lantai.get(match.id, {})
            if sedang_bicara and penyusun.pop(otak.nama, None) is not None and not penyusun:
                del self.lantai[match.id]
            room_service.selesai_langkah_bot(match, otak.nama, gagal)
            otak.sibuk = False
            otak.langkah_terakhir = time.time()

    # PANEL: kondisi tiap bot room ini untuk kolom "Kondisi sekarang" di Checker, hanya dari penanda yang sudah ada: status
    # dan hak pemain di engine (snapshot), kartu pemantauan (I/L/O, awan berpikir), otak (sibuk, segera,
    # langkah_terakhir), lantai bicara, hasil langkah terakhir (checker_service), dan _jadwal_langkah untuk detik sampai
    # langkah berikutnya (sama dengan penjadwal). Hanya membaca; tidak mengubah jadwal atau otak.
    # Alur: 1 pertandingan live room -> 2 tiap bot: status, hak, dan penanda -> 3 detik sampai langkah berikutnya
    #       -> 4 hasil langkah terakhir pertandingan ini -> 5 sibuk menutup langkah atau belum mulai
    def kondisi_bot(self, code):
        waktu_sekarang = time.time()
        hasil_terakhir = checker_service.hasil_langkah(code)
        with room_service.lock:
            room = room_service.rooms.get(code)
            match = room.match if room else None
            if match is None:
                return []
            berjalan = not match.winner and match.ai_controlled and match.phase not in ("preparing", "finished")
            lama_fase_berjalan = match.phase_length() - (match.deadline - waktu_sekarang)
            nama_bot_hidup = sorted(p.name for p in match.players.values() if p.bot and p.alive)
            lantai = self.lantai.get(match.id, {})
            daftar = []
            for peserta in sorted((p for p in match.players.values() if p.bot), key=lambda p: p.name):
                otak = self.runtime.otak_bot(match.id, peserta.name)
                saya = match.snapshot(peserta.name)["me"]
                status = (
                    "dieksekusi" if not peserta.alive else "disandera" if peserta.hostage
                    else "dibungkam" if peserta.gagged else "aktif"
                )  # fmt: skip
                berikutnya = None
                if berjalan and otak is not None and peserta.alive and not otak.sibuk:
                    waktu_mulai, jeda = self._jadwal_langkah(
                        otak, match, nama_bot_hidup.index(peserta.name)
                    )
                    sisa = max(0.0, waktu_mulai - lama_fase_berjalan,
                               otak.langkah_terakhir + jeda - waktu_sekarang)  # fmt: skip
                    # Tidak ada langkah di detik terakhir fase: langkah berikutnya di fase sesudahnya.
                    berikutnya = round(sisa, 1) if match.deadline - waktu_sekarang - sisa >= 1.0 else None
                terakhir = hasil_terakhir.get(peserta.name)
                if terakhir and terakhir["match_id"] != match.id:
                    terakhir = None
                # Sibuk sesudah jejak langkah ini dibuat (siaran chat, arsip DB): hasilnya lebih baru daripada akhir
                # langkah sebelumnya. Sibuk sebelum langkah mulai: hasil terakhir milik langkah sebelumnya.
                menutup = bool(
                    otak and otak.sibuk and terakhir and terakhir["langkah"] == otak.langkah
                    and datetime.fromisoformat(terakhir["selesai"]).timestamp() > otak.langkah_terakhir
                )  # fmt: skip
                daftar.append({
                    "nama": peserta.name, "role": peserta.role, "status": status, "fase": match.phase,
                    "otak": otak is not None, "sibuk": bool(otak and otak.sibuk), "menutup": menutup,
                    "segera": bool(otak and otak.segera), "langkah": otak.langkah if otak else None,
                    "kartu": match.bot_tahap.get(peserta.name), "berpikir": peserta.name in match.bot_berpikir,
                    "berikutnya_detik": berikutnya,
                    "lantai": {"terisi": len(lantai), "maks": LANTAI_MAKS, "saya": peserta.name in lantai},
                    "hak": {"chat": saya["can_chat"], "vote": saya["can_vote"], "sudah_vote": saya["vote"] is not None,
                            "aksi": saya["ability"] if saya["can_act"] else None,
                            "sudah_aksi": bool(saya["action"]), "chat_tim": match.can_team_chat(peserta.name)},
                    "terakhir": terakhir,
                })  # fmt: skip
        return daftar

    # Dipanggil jam permainan tiap 0,5 detik: menyuruh bot yang sudah waktunya melangkah, tanpa menunggu manusia
    # mengirim chat.
    # Alur: 1 cari pertandingan yang masih berjalan -> 2 buang data pertandingan yang sudah selesai -> 3.1 persiapan:
    #       siapkan otak bot sekali -> 3.2 fase berjalan: jalankan brain_turn untuk bot yang sudah waktunya
    def jalankan_bot_yang_sudah_waktunya(self):
        waktu_sekarang = time.time()
        with room_service.lock:
            id_pertandingan_aktif = {
                r.match.id for r in room_service.rooms.values() if r.match and not r.match.winner
            }

            # Data pertandingan yang sudah selesai dibuang, supaya memori server tidak penuh.
            self.preparing &= id_pertandingan_aktif
            self.lantai = {m: bot for m, bot in self.lantai.items() if m in id_pertandingan_aktif}
            for match_id in [m for m in riwayat_nlu if m not in id_pertandingan_aktif]:
                del riwayat_nlu[match_id]
            self.runtime.lupakan_kecuali(id_pertandingan_aktif)

            for room in list(room_service.rooms.values()):
                match = room.match
                if not match or match.winner or not match.ai_controlled:
                    continue  # belum ada game, sudah selesai, atau bukan game ber-AI
                if match.phase == "preparing":
                    # Layar persiapan: muat otak dan siapkan ingatan bot sekali per pertandingan.
                    if match.id not in self.preparing:
                        self.preparing.add(match.id)
                        self._spawn(self.prepare(room.code, match))
                    continue
                lama_fase_berjalan = match.phase_length() - (match.deadline - waktu_sekarang)
                nama_bot_hidup = sorted(p.name for p in match.players.values() if p.bot and p.alive)
                for urutan, nama in enumerate(nama_bot_hidup):
                    otak = self.runtime.otak_bot(match.id, nama)
                    if otak is None:
                        continue  # otak gagal dimuat: engine mengisi aksi cadangan di deadline
                    if not otak.sibuk and self._sudah_waktunya_melangkah(
                        otak, match, lama_fase_berjalan, waktu_sekarang, urutan
                    ):
                        otak.sibuk = True
                        self._spawn(self.brain_turn(room.code, match, otak))

    # Hentikan request NPC ketika backend shutdown supaya tidak ada task yang tertinggal.
    async def close(self):
        for task in list(self.tasks):
            task.cancel()
        await asyncio.gather(*self.tasks, return_exceptions=True)


npc_service = NPCService(sio, broadcast=emit_room)
