"""NPC independen: otak hasil notebook skripsi (NLU IndoBERT → fuzzy → NLG).

Setiap bot memakai ingatan dan persona sendiri.
"""

import asyncio
import json
import logging
import time
from functools import partial
from time import perf_counter

from app.module.checker_service import checker_service
from app.module.npc_brain.penjelasan import lengkapi as lengkapi_penjelasan
from app.module.npc_brain.penjelasan import ringkas as ringkas_penjelasan
from app.module.npc_brain.runtime import brain_runtime
from app.module.persistence_service import PersistenceService, PersistenceError
from app.module.match_engine import snapshot_berlabel
from app.module.room_service import room_service
from app.module.survey_service import survey_service
from app.config.settings import settings

logger = logging.getLogger("shadow_heist.npc")

# Aksi rahasia yang dipetakan dari keputusan otak ke Match.act.
AKSI_RAHASIA = {"gag", "hostage", "guard", "peek"}
# Batas waktu keputusan otak dan penulisan kalimat (termasuk rantai LLM) agar bot tidak menggantung.
BATAS_LANGKAH_DETIK = 25
BATAS_TULIS_DETIK = 25
# Cadangan saat penulis LLM melewati batas: kalimat templat (tetap divalidasi IndoBERT) jauh lebih cepat.
BATAS_TEMPLAT_DETIK = 10
# Pemicu cepat: jarak minimal antar-langkah bot yang dipanggil/dituduh (langkah biasa: NPC_STEP_SECONDS).
JEDA_SEGERA_DETIK = 1.0
# Lantai bicara: bot per pertandingan yang boleh menyusun chat bersamaan (= thread eksekutor NLG; Ollama
# mengantrekan permintaan di atas OLLAMA_NUM_PARALLEL).
LANTAI_MAKS = 3


# Lama tiap tahap satu langkah bot (ms): NLU + sinkron ingatan, logika metode, penjelasan panel, lalu NLG
# (total, panggilan LLM, dan sisanya = aturan + validasi IndoBERT + templat).
def waktu_jejak(waktu, tulisan):
    hasil = dict(waktu or {})
    if tulisan:
        nlg, llm = tulisan.get("detik") or 0.0, tulisan.get("llm_detik") or 0.0
        hasil.update(nlg_ms=round(nlg * 1000, 1), llm_ms=round(llm * 1000, 1),
                     validasi_ms=round(max(0.0, nlg - llm) * 1000, 1))  # fmt: skip
    return hasil


# Isi jejak checker satu langkah otak; dipakai room asli (NPCService._trace) dan simulasi panel.
def isi_jejak(trace, match, otak, npc, rencana, tulisan, penolakan, durasi_ms, ditunda, penjelasan,
              waktu, nlu_sumber, masukan_nlg=None):  # fmt: skip
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
                "target": rencana["target"],
                "klaim": rencana.get("klaim", False),
                "alasan": rencana["alasan"][:2],
                "ditunda": ditunda,  # lantai bicara penuh/kembar: diputuskan ulang nanti
            },
            "nlg": (
                None
                if not tulisan
                else {
                    "sumber": tulisan["sumber"],
                    "lolos_nlu": tulisan["lolos_nlu"],
                    "pelanggaran": tulisan["pelanggaran"],
                }
            ),
            "nlu": nlu_sumber,
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


# NLG dengan batas waktu. Jika penulis LLM terlalu lama, kalimat tetap dikirim dari templat (tetap
# divalidasi IndoBERT) agar rencana bot tidak hilang. Thread LLM yang tertinggal selesai sendiri;
# rantai penulis mencatat hasilnya (mis. mengistirahatkan jalur yang lambat) untuk kalimat berikutnya.
# lapor(tahap): simulasi panel memantau tahap NLG (nlg, llm, validasi).
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
            runtime.baca_chat,
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
        self.sio = sio
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
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("Persiapan otak NPC gagal.")
            with room_service.lock:
                match.mark_ai_ready(detail="Persiapan AI gagal; bot memakai aksi cadangan engine.")

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

            pandangan, keputusan, konteks = await asyncio.wait_for(
                loop.run_in_executor(self.runtime.eksekutor_keputusan, pikirkan_langkah),
                timeout=BATAS_LANGKAH_DETIK,
            )
            keputusan_aksi, rencana_chat = keputusan["npc_decision"], keputusan["rencana_chat"]

            # OUTPUT 1: vote dan aksi rahasia langsung ke game, tidak menunggu kalimat selesai diketik
            masih_berlaku, penolakan = self._kirim_vote_atau_aksi(
                code, match, fase, otak, keputusan_aksi
            )
            if not masih_berlaku:
                return  # fase berganti selama bot berpikir: keputusan basi dibuang

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
                                reply_to_id=None,
                            )  # fmt: skip
                        except PersistenceError:
                            logger.warning(
                                "Chat bot %s tidak tersimpan; tidak disiarkan.", otak.nama
                            )
                        else:
                            pesan_terkirim = match.add_message(otak.nama, kalimat["teks"])
                            # Kalimat sudah tampil; awan berpikir hilang bersama pesan.
                            match.bot_berpikir.discard(otak.nama)
                            self.runtime.catat_chat(otak, pandangan, rencana_chat, kalimat["teks"])

            # OUTPUT 3: jejak untuk panel checker (tanpa role pemain lain), siaran chat, bacaan IndoBERT
            jejak = None
            if pesan_terkirim or keputusan_aksi["action"] != "wait" or penolakan or chat_ditunda:
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
                )
            if pesan_terkirim:
                await self.broadcast("receive_chat", pesan_terkirim, to=code)
            if jejak is not None:
                # Disimpan di thread latar: tulisan DB (hingga ±12 KB penjelasan per jejak) tidak menahan
                # event loop game. Jejak di memori (checker) sudah tersedia sejak checker_service.begin.
                try:
                    await asyncio.to_thread(PersistenceService(code).record_trace, jejak)
                except PersistenceError:
                    pass
            if (
                pesan_terkirim
            ):  # di latar: lantai bicara tidak ditahan selama NLU membaca kalimat ini
                self._spawn(
                    catat_nlu(
                        match, otak.nama, pesan_terkirim["message"], id_pesan, self.runtime, code
                    )
                )
        except asyncio.CancelledError:
            raise
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
    def _kirim_vote_atau_aksi(self, code, match, fase, otak, keputusan_aksi):
        with room_service.lock:
            if not self._berlaku(code, match, fase):
                return False, None
            # Otak sudah memutuskan fase ini: tunggu/abstain miliknya dihormati, bukan diganti aksi acak
            # engine. Ditandai setelah keputusan ada, sehingga langkah yang error/timeout sebelum pernah
            # memutuskan apa pun tetap mendapat aksi cadangan engine di akhir fase.
            match.npc_decisions.add((fase[1], fase[2], otak.nama))
            try:
                if keputusan_aksi["action"] == "vote":
                    match.vote(otak.nama, match.username(keputusan_aksi["target"]))
                elif keputusan_aksi["action"] in AKSI_RAHASIA:
                    match.act(
                        otak.nama,
                        keputusan_aksi["action"],
                        match.username(keputusan_aksi["target"]),
                    )
                    self.runtime.catat_aksi(
                        otak, match.round, keputusan_aksi["action"], keputusan_aksi["target"]
                    )
            except ValueError as error:
                return True, str(error)
            return True, None

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

    # Hentikan request NPC ketika backend shutdown supaya tidak ada task yang tertinggal.
    async def close(self):
        for task in list(self.tasks):
            task.cancel()
        await asyncio.gather(*self.tasks, return_exceptions=True)
