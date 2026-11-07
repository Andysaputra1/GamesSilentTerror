"""
Pengendali bot: urutan satu langkah setiap bot, dari jam permainan sampai vote, aksi malam, dan chat terkirim.

Bot diperlakukan seperti pemain tanpa browser. Otak bersama (BrainRuntime) memuat NLU (nlu.py), logika Fuzzy
(fuzzy.py), dan penulis kalimat (nlg.py), lalu menyimpan ingatan dan persona tiap bot per pertandingan.

Alurnya
1. Saat server nyala, main.py memanggil brain_runtime.mulai_memuat: fuzzy, IndoBERT, lalu rantai penulis dimuat di latar
2. Jam di main.py memanggil jalankan_bot_yang_sudah_waktunya tiap 0,5 detik
3. Data pertandingan yang sudah selesai dibuang
4. Tiap room: fase persiapan menjalankan prepare, fase lain menjalankan brain_turn untuk bot yang sudah waktunya
5. prepare: Tunggu otak siap, bagi persona dan siapkan ingatan tiap bot, lalu buka ronde 1
6. brain_turn (satu langkah satu bot):
   6.1 Lihat: Ambil snapshot permainan milik bot
   6.2 Pikir: ingatan mencatat snapshot, IndoBERT membaca chat baru, lalu fuzzy memutuskan (BrainRuntime.langkah)
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
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from functools import partial
from time import perf_counter
from typing import TYPE_CHECKING

from app.bot import nlg
from app.bot.nlu import NLUBersama, NLUIndoBERT, baca_chat, baca_chat_baru, folder_model, teks_target
from app.bot.penjelasan import jelaskan
from app.bot.penjelasan import lengkapi as lengkapi_penjelasan
from app.bot.penjelasan import ringkas as ringkas_penjelasan
from app.config.settings import settings
from app.game.match_engine import phase_durations, snapshot_berlabel
from app.services.checker_service import checker_service
from app.services.persistence_service import PersistenceError, PersistenceService
from app.services.room_service import room_service
from app.services.survey_service import survey_service
from app.sockets.server import emit_room, sio

if TYPE_CHECKING:
    # Hanya untuk editor (Ctrl+klik). Saat program jalan modul ini dimuat di _muat, supaya server cepat nyala.
    from app.bot import fuzzy

logger = logging.getLogger("shadow_heist.npc")
logger_otak = logging.getLogger("shadow_heist.npc_brain")

# Modul logika tiap metode; game sekarang hanya memakai fuzzy (bot/fuzzy.py).
METODE_MODUL = {"fuzzy": "fuzzy"}
# Pemuatan otak yang gagal dicoba ulang paling cepat setelah jeda ini (detik).
JEDA_MUAT_ULANG_DETIK = 60
# Aksi rahasia yang dipetakan dari keputusan otak ke Match.act.
AKSI_RAHASIA = {"gag", "hostage", "guard", "peek"}
# Batas waktu keputusan otak dan penulisan kalimat (termasuk rantai LLM) agar bot tidak menggantung.
BATAS_LANGKAH_DETIK = 25
BATAS_TULIS_DETIK = 25
# Cadangan saat penulis LLM melewati batas: kalimat templat tidak memanggil jaringan, jadi jauh lebih cepat.
BATAS_TEMPLAT_DETIK = 10
# Pemicu cepat: jarak minimal antar-langkah bot yang dipanggil/dituduh (langkah biasa: NPC_STEP_SECONDS).
JEDA_SEGERA_DETIK = 1.0
# Lantai bicara: bot per pertandingan yang boleh menyusun chat bersamaan (= thread eksekutor NLG; Ollama
# mengantrekan permintaan di atas OLLAMA_NUM_PARALLEL).
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
    ditulis di thread terpisah (nlg-npc) supaya LLM tidak menahan keputusan bot lain.
    """

    def __init__(self):
        self.lock = threading.RLock()
        self.modul = {}
        self.nlg = None
        self.nlu = None
        self.penulis_npc = nlg.PenulisNPC(self.lock)
        self.status = {"siap": False, "gagal": False, "detail": "Belum dimuat.", "progres": 0.0, "nlu": None}
        self.pertandingan: dict[str, dict[str, OtakBot]] = {}
        self._thread = None
        self._gagal_pada = None  # waktu (monotonic) pemuatan terakhir gagal; None = belum pernah gagal
        self.eksekutor_keputusan = ThreadPoolExecutor(1, thread_name_prefix="otak-npc")
        self.eksekutor_nlg = ThreadPoolExecutor(3, thread_name_prefix="nlg-npc")

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
                self.modul[metode] = importlib.import_module(f"app.bot.{nama}")
            self.nlg = nlg
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
            persona = self.nlg.persona_bot(nama, bots) if self.nlg else "santai"
            ingatan = self.modul["fuzzy"].Ingatan(nama, cepat=cepat)
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
    # tahap yang sedang berjalan (flowchart live).
    # Alur: 1 sinkron snapshot -> 2 NLU membaca chat baru -> 3 putuskan -> 4 chat yang baru dibaca -> 5 penjelasan
    #       -> 6 lama tiap tahap -> 7 konteks NLG
    def langkah(self, bot: OtakBot, snapshot, sekarang, selalu_jelaskan=False, lapor=nlg.tanpa_lapor):
        # modul = bot/fuzzy.py (dimuat di _muat), jadi modul.putuskan ada di file itu.
        modul = self.modul[bot.metode]
        if TYPE_CHECKING:
            modul = fuzzy
        mulai, jumlah_chat_sebelumnya = time.perf_counter(), len(bot.ingatan.chat)
        lapor("nlu")
        view = bot.ingatan.sinkron_snapshot(snapshot, sekarang)
        baca_chat_baru(self.nlu, bot.ingatan, [p["nama"] for p in view["pemain"]], jumlah_chat_sebelumnya)
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
            or keputusan.get("nlg_tim") is not None
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

    # Rencana menjadi kalimat (thread penulis), dengan pengaman aturan. pakai_llm=False: hanya templat, dipakai sebagai
    # cadangan cepat saat penulis LLM melewati batas waktu.
    # Alur: 1 pilih rantai (atau templat) -> 2 kalimat yang harus dihindari -> 3 tulis_pesan -> 4 catat lama LLM
    def tulis(self, bot: OtakBot, payload, konteks, pakai_llm=True, lapor=nlg.tanpa_lapor):
        penulis = self.penulis_npc.dipakai(pakai_llm)
        # Hindari kalimat sendiri yang lalu dan chat terbaru di room (bot lain tidak dikembari).
        hindari = tuple(bot.riwayat[-12:]) + tuple(c["teks"] for c in konteks["chat_terbaru"])
        jam = nlg.JamPenulis(penulis, lapor) if penulis is not None else None
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
        return self.nlg.buat_prompt(payload, konteks, bot.persona)[1]

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
# lapor(tahap): simulasi panel memantau tahap NLG (nlg, llm, aturan).
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


# Pindah pilihan malam: batal lalu pilih ulang, dalam lock pemanggil. Bila pilihan baru ditolak engine,
# pilihan lama kembali utuh beserta urutannya, dan penolakan diteruskan ke pemanggil.
def pindahkan_aksi_malam(match, nama, kemampuan, target):
    sebelum = dict(match.actions)
    match.cancel_action(nama)
    try:
        match.act(nama, kemampuan, target)
    except ValueError:
        match.actions = sebelum
        raise


# Pindah suara saat waktu tambahan. Pemanggil memegang kunci room. Bila suara baru ditolak, suara lama dikembalikan,
# supaya bot tidak kehilangan suaranya.
def pindahkan_vote(match, nama, target):
    lama = match.votes.get(nama)
    match.cancel_vote(nama)
    try:
        match.vote(nama, target)
    except ValueError:
        match.vote(nama, lama)
        raise


# Riwayat pencatat NLU per pertandingan (konteks target, urut kronologis); dibuang saat pertandingan usai.
riwayat_nlu: dict[str, list] = {}


# Roster berlabel dengan urutan yang sama seperti snapshot bot (kunci memo NLU ikut sama).
def roster_label(match):
    return [match.labels.get(nama, nama) for nama in match.players]


# PEMICU CEPAT: bot yang dipanggil chat baru (target neutral, dari IndoBERT atau aturan nama) atau dituduhnya
# (target offend) melangkah pada putaran jam berikutnya, tanpa menunggu NPC_STEP_SECONDS. Bacaan NLU yang dipakai
# sama dengan bacaan bot (memo NLUBersama). Lantai bicara dan aturan chat otak (jatah, jeda, satu jawaban per
# panggilan) tetap menentukan apakah bot benar-benar bicara.
def tandai_dipanggil(runtime, match, pengirim, nlu):
    for t in nlu.get("target", []):
        if t["relasi"] in ("neutral", "offend") and t["pemain"] != pengirim:
            otak = runtime.otak_bot(match.id, match.username(t["pemain"]))
            if otak is not None:
                otak.segera = True


# PENCATAT NLU: baca satu chat pertandingan dengan IndoBERT di thread keputusan (urut dengan langkah bot),
# simpan bacaannya ke riwayat chat, dan kembalikan hasilnya (None bila otak belum siap atau gagal).
async def catat_nlu(match, pengirim, teks, message_id=None, runtime=brain_runtime, room_code=None):
    if runtime.nlu is None or not runtime.modul:
        return None
    riwayat = riwayat_nlu.setdefault(match.id, [])
    label = match.labels.get(pengirim, pengirim)
    try:
        nlu = await asyncio.get_running_loop().run_in_executor(
            runtime.eksekutor_keputusan,
            baca_chat,
            runtime.nlu,
            riwayat,
            label,
            teks,
            roster_label(match),
        )
    except Exception:
        logger.exception("NLU chat gagal dicatat.")
        return None
    tandai_dipanggil(runtime, match, label, nlu)
    if message_id is not None:
        try:
            await asyncio.to_thread(PersistenceService(room_code).record_nlu, message_id, nlu)
        except PersistenceError:
            logger.warning("Bacaan NLU tidak tersimpan (migrasi V9?).")
    return nlu


class NPCService:
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

    # Otak mengambil langkah berkala; bot digeser beberapa detik agar tidak berbicara serentak. Bot yang baru
    # dipanggil atau dituduh (otak.segera) melangkah lebih cepat, minimal JEDA_SEGERA_DETIK sesudah langkah terakhir.
    def _sudah_waktunya_melangkah(self, otak, match, lama_fase_berjalan, waktu_sekarang, urutan):
        waktu_mulai = min(2.0, match.durations[match.phase] / 6) + (urutan % 4) * 0.7
        if lama_fase_berjalan < waktu_mulai or match.deadline - waktu_sekarang < 1.0:
            return False
        jeda = JEDA_SEGERA_DETIK if otak.segera else settings.npc_step_seconds
        return waktu_sekarang - otak.langkah_terakhir >= jeda

    # PERSIAPAN: tunggu otak siap, bagi persona per bot, lalu buka ronde 1.
    async def prepare(self, code, match):
        detail = "AI siap."
        try:
            self.runtime.mulai_memuat()
            while True:
                status = self.runtime.ringkasan()
                with room_service.lock:
                    if match.winner:
                        return
                    # Jika batas tunggu lewat dan ronde 1 sudah mulai, otak tetap bergabung saat siap.
                    match.update_preparation(detail=status["detail"], progress=status["progres"])
                if status["siap"] or status["gagal"]:
                    break
                await asyncio.sleep(0.5)
            if status["gagal"]:
                with room_service.lock:
                    match.mark_ai_ready(detail=status["detail"])
                return
            rows = self.runtime.siapkan_pertandingan(match, code)
            if rows:
                detail = f"AI siap: {len(rows)} bot."
                try:
                    await asyncio.to_thread(survey_service.record_match_bots, rows)
                except PersistenceError:
                    logger.warning("Metode bot tidak tersimpan ke database (migrasi V7?).")
            with room_service.lock:
                match.mark_ai_ready(detail=detail)
        except Exception:
            logger.exception("Persiapan otak NPC gagal.")
            with room_service.lock:
                match.mark_ai_ready(detail="Persiapan AI gagal; bot memakai aksi cadangan engine.")

    # Keputusan masih berlaku jika room, pertandingan, dan fasenya sama serta deadline belum lewat.
    def _berlaku(self, code, match, key):
        room = room_service.rooms.get(code)
        return bool(
            room
            and room.match is match
            and not match.winner
            and key == (match.id, match.round, match.phase)
            and time.time() < match.deadline
        )

    # Vote/aksi rahasia diterapkan segera. Hasil: (masih berlaku, pesan penolakan engine atau None).
    def _kirim_vote_atau_aksi(self, code, match, fase, otak, view, keputusan):
        keputusan_aksi = keputusan["npc_decision"]
        with room_service.lock:
            if not self._berlaku(code, match, fase):
                return False, None
            # Otak sudah memutuskan fase ini: tunggu/abstain miliknya dihormati, bukan diganti aksi acak
            # engine. Ditandai setelah keputusan ada, sehingga langkah yang error/timeout sebelum pernah
            # memutuskan apa pun tetap mendapat aksi cadangan engine di akhir fase.
            match.npc_decisions.add((fase[1], fase[2], otak.nama))
            try:
                if keputusan_aksi["action"] == "vote":
                    if keputusan_aksi.get("pindah"):
                        pindahkan_vote(match, otak.nama, match.username(keputusan_aksi["target"]))
                    else:
                        match.vote(otak.nama, match.username(keputusan_aksi["target"]))
                    self.runtime.catat_vote(otak, view, keputusan["rencana_vote"])
                elif keputusan_aksi["action"] in AKSI_RAHASIA:
                    aksi = keputusan_aksi["action"]
                    target = match.username(keputusan_aksi["target"])
                    if keputusan_aksi.get("pindah"):
                        pindahkan_aksi_malam(match, otak.nama, aksi, target)
                    else:
                        match.act(otak.nama, aksi, target)
            except ValueError as error:
                return True, str(error)
            return True, None

    # CHAT TIM: rahasia, jadi tanpa lantai bicara, database, siaran, NLU, atau fungsi @traced (lihat
    # room_service.team_chat). Penerima membacanya lewat snapshot. Hasil untuk jejak: status dan panjang teks.
    async def _kirim_chat_tim(self, code, match, fase, otak, view, payload, roster):
        tulisan = await tulis_kalimat_tim(
            self.runtime, otak, payload, roster, match.deadline - time.time()
        )
        teks, terkirim = tulisan["teks"], False
        with room_service.lock:
            if teks and self._berlaku(code, match, fase) and match.can_team_chat(otak.nama):
                match.add_team_message(otak.nama, teks)
                terkirim = True
            self.runtime.catat_chat_tim(otak, view, payload, terkirim)
        status = "terkirim" if terkirim else "tidak terkirim" if teks else "kosong"
        return {"status": status, "panjang": len(teks)}

    # LANTAI BICARA: paling banyak LANTAI_MAKS bot menyusun/mengetik chat bersamaan per pertandingan (LLM
    # menulis paralel). Ditolak bila lantai penuh, bila bot lain sedang menulis rencana kembar (intent dan
    # target sama: tidak ada tuduhan atau pertanyaan serentak yang sama), atau bila rencana dibuat sebelum
    # chat bot lain masuk. Bot yang ditolak memutuskan ulang di langkah berikutnya dengan chat terbaru.
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
        with room_service.lock:
            match.bot_berpikir.add(otak.nama)  # pemain melihat awan berpikir selama kalimat disusun
        return True

    # LANGKAH OTAK: baca keadaan game → bot berpikir → vote/aksi langsung → kalimat lewat lantai bicara.
    async def brain_turn(self, code, match, otak):
        waktu_mulai = perf_counter()
        sedang_bicara = gagal = False
        try:
            # INPUT: apa yang dilihat bot sekarang
            with room_service.lock:
                room = room_service.rooms.get(code)
                if (
                    not room
                    or room.match is not match
                    or match.winner
                    or match.phase == "preparing"
                    or not match.players[otak.nama].alive
                ):
                    return
                fase = (match.id, match.round, match.phase)
                otak.segera = False  # snapshot ini sudah memuat chat pemicunya
                snapshot = snapshot_berlabel(match.snapshot(otak.nama), match.labels)
                id_chat_terakhir_dilihat = match.messages[-1]["id"] if match.messages else None
                # Huruf kecil di kartu bot untuk pemantauan: I terima input, L logika, O output.
                match.bot_tahap[otak.nama] = "I"
            waktu_sekarang = time.time()
            otak.langkah += 1
            loop = asyncio.get_running_loop()

            # PROSES: bot berpikir di jalur keputusan, dengan batas waktu.
            # Tahap L baru saat thread keputusan benar-benar mulai (bisa antre di belakang bot lain).
            def pikirkan_langkah():
                with room_service.lock:
                    match.bot_tahap[otak.nama] = "L"
                return self.runtime.langkah(otak, snapshot, waktu_sekarang)

            view, keputusan, konteks = await asyncio.wait_for(
                loop.run_in_executor(self.runtime.eksekutor_keputusan, pikirkan_langkah),
                timeout=BATAS_LANGKAH_DETIK,
            )
            keputusan_aksi, rencana_chat = keputusan["npc_decision"], keputusan["rencana_chat"]

            # OUTPUT 1: vote dan aksi rahasia langsung ke game, tidak menunggu kalimat selesai diketik
            masih_berlaku, penolakan = self._kirim_vote_atau_aksi(
                code, match, fase, otak, view, keputusan
            )
            if not masih_berlaku:
                return  # fase berganti selama bot berpikir: keputusan basi dibuang

            # Pilihan yang ditolak engine tidak dikabarkan ke rekan.
            status_tim = None
            if keputusan.get("nlg_tim") is not None and not penolakan:
                status_tim = await self._kirim_chat_tim(
                    code, match, fase, otak, view, keputusan["nlg_tim"], konteks["roster"]
                )

            # OUTPUT 2: minta giliran bicara, tulis kalimat, jeda mengetik, lalu kirim chat
            kalimat = pesan_terkirim = id_pesan = None
            chat_ditunda = keputusan["nlg"] is not None and not self._ambil_giliran_bicara(
                match, otak, id_chat_terakhir_dilihat, rencana_chat
            )
            if keputusan["nlg"] is not None and not chat_ditunda:
                sedang_bicara = True
                kalimat = await tulis_kalimat(self.runtime, otak, keputusan["nlg"], konteks)
                # Jeda mengetik: balasan instan terasa seperti mesin.
                lama_mengetik = min(4.0, max(1.0, len(kalimat["teks"]) / 30))
                if match.deadline - time.time() > lama_mengetik + 1:
                    await asyncio.sleep(lama_mengetik)
                # Chat dikirim hanya jika fase masih sama dan bot masih boleh bicara; ingatan dicatat
                # setelah terkirim.
                with room_service.lock:
                    if (
                        kalimat["teks"]
                        and self._berlaku(code, match, fase)
                        and match.can_chat(otak.nama)
                    ):
                        try:
                            id_pesan = PersistenceService(code).record_bot_message(
                                username=otak.nama,
                                message=kalimat["teks"],
                                context={"match_id": match.id, "round_number": match.round,
                                         "phase": match.phase},
                            )  # fmt: skip
                        except PersistenceError:
                            logger.warning(
                                "Chat bot %s tidak tersimpan; tidak disiarkan.", otak.nama
                            )
                        else:
                            pesan_terkirim = match.add_message(otak.nama, kalimat["teks"])
                            # Kalimat sudah tampil; awan berpikir hilang bersama pesan.
                            match.bot_berpikir.discard(otak.nama)
                            self.runtime.catat_chat(otak, view, rencana_chat, kalimat["teks"])

            # OUTPUT 3: jejak untuk panel checker (tanpa role pemain lain), siaran chat, bacaan IndoBERT
            jejak = None
            if (
                pesan_terkirim
                or keputusan_aksi["action"] != "wait"
                or penolakan
                or chat_ditunda
                or status_tim
            ):
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
                    waktu_jejak(keputusan.get("waktu"), kalimat_terkirim),
                    getattr(self.runtime.nlu, "sumber", None),
                    masukan_nlg,
                    status_tim,
                )
            if pesan_terkirim:
                await self.broadcast("receive_chat", pesan_terkirim, to=code)
            if jejak is not None:
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
            gagal = True
            logger.exception("Langkah otak %s gagal.", otak.nama)
            jejak_gagal = checker_service.begin(code, otak.nama, "NPC brain")
            jejak_gagal.update(
                match_id=match.id, stage="npc_brain_error", error=type(error).__name__
            )
        finally:
            # Selesai, juga saat error: lepas giliran bicara dan tandai bot tidak sibuk.
            penyusun = self.lantai.get(match.id, {})
            if sedang_bicara and penyusun.pop(otak.nama, None) is not None and not penyusun:
                del self.lantai[match.id]
            with room_service.lock:
                match.bot_berpikir.discard(otak.nama)
                # Langkah gagal/timeout tetap di L agar terlihat macet sampai langkah berikutnya.
                if not gagal and match.bot_tahap.get(otak.nama) == "L":
                    match.bot_tahap[otak.nama] = "O"
            otak.sibuk = False
            otak.langkah_terakhir = time.time()

    # Dipanggil jam permainan tiap 0,5 detik: menyuruh bot yang sudah waktunya melangkah, tanpa menunggu
    # manusia mengirim chat.
    def jalankan_bot_yang_sudah_waktunya(self):
        waktu_sekarang = time.time()
        with room_service.lock:
            # INPUT: pertandingan yang masih berjalan
            id_pertandingan_aktif = {
                r.match.id for r in room_service.rooms.values() if r.match and not r.match.winner
            }

            # PROSES: buang data pertandingan yang sudah selesai, supaya memori server tidak penuh
            self.preparing &= id_pertandingan_aktif
            self.lantai = {m: bot for m, bot in self.lantai.items() if m in id_pertandingan_aktif}
            for match_id in [m for m in riwayat_nlu if m not in id_pertandingan_aktif]:
                del riwayat_nlu[match_id]
            self.runtime.lupakan_kecuali(id_pertandingan_aktif)

            # OUTPUT: tiap room menyiapkan otak bot, atau menjalankan bot yang sudah waktunya
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
