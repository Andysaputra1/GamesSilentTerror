"""Simulasi panel: satu pertandingan tiruan (admin + bot pilihan) dengan engine, otak, NLU, dan NLG yang
sama seperti room asli, tanpa room, socket, maupun database. Waktu permainan maju per putaran: setiap
putaran semua bot hidup melangkah sekali, berurutan, sehingga bot berikutnya membaca chat bot sebelumnya
(seperti lantai bicara di room asli). Jejaknya berbentuk sama dengan jejak checker.
"""

import asyncio
import time
from collections import OrderedDict

from app.module.checker_service import jejak_baru
from app.module.match_engine import Match, label_unik, snapshot_berlabel
from app.module.npc_brain.runtime import brain_runtime
from app.module.npc_service import (
    AKSI_RAHASIA, BATAS_LANGKAH_DETIK, isi_jejak, roster_label, tulis_kalimat, waktu_jejak,
)  # fmt: skip
from app.module.room_service import BOT_NAMES

KODE = "SIMULASI"
PEMAIN = "sim_pemain"  # username admin di engine; tampil dengan nama pilihan admin
MAKS_SIMULASI = 5  # simulasi terlama dibuang
MULAI_FASE = 2.0  # detik setelah fase mulai sebelum bot melangkah (sama dengan NPCService._due)


class Simulasi:
    def __init__(self, nama, metode):
        bots = list(BOT_NAMES[: len(metode)])
        self.match = Match([PEMAIN], bots, now=0.0, labels=label_unik({PEMAIN: nama}, bots))
        self.otak = brain_runtime.buat_otak(self.match, dict(zip(bots, metode)))
        self.id = self.match.id
        self.jam = MULAI_FASE  # waktu permainan (detik sejak mulai)
        self.riwayat = []  # riwayat pencatat NLU (konteks target)
        self.events = []  # pengumuman engine yang sudah dikirim ke panel
        self.lock = asyncio.Lock()
        # nama → tahap yang sedang dikerjakan (flowchart live di panel lewat polling).
        self.progres = {}

    def _lapor(self, nama):
        def lapor(tahap):
            self.progres[nama] = {"tahap": tahap, "sejak": time.monotonic()}

        return lapor

    def lihat_progres(self):
        sekarang = time.monotonic()
        return {
            nama: {"tahap": p["tahap"], "detik": round(sekarang - p["sejak"], 1)}
            for nama, p in list(self.progres.items())
        }

    def ringkasan(self):
        m = self.match
        mulai = m.deadline - m.durations.get(m.phase, 0)
        return {
            "id": self.id, "ronde": m.round, "fase": m.phase, "pemenang": m.winner,
            "detik": round(max(0.0, self.jam - mulai), 1), "durasi": m.durations.get(m.phase),
            "bisa_chat": not m.winner and m.can_chat(PEMAIN),
            "pemain": [
                {"nama": m.labels[p.name], "manusia": not p.bot, "role": p.role, "hidup": p.alive,
                 "status": "dieksekusi" if not p.alive else "disandera" if p.hostage
                 else "dibungkam" if p.gagged else "aktif",
                 "metode": getattr(self.otak.get(p.name), "metode", None),
                 "persona": getattr(self.otak.get(p.name), "persona", None)}
                for p in m.players.values()
            ],
        }  # fmt: skip

    # Pengumuman engine yang baru muncul (events dipangkas 40 terakhir, jadi dicocokkan lewat irisan).
    def _sistem(self):
        lama, baru = self.events, list(self.match.events)
        j = next(
            j for j in range(min(len(lama), len(baru)), -1, -1) if baru[:j] == lama[len(lama) - j :]
        )
        self.events = baru
        return [{**jejak_baru(KODE, "SISTEM", teks), "stage": "sistem"} for teks in baru[j:]]

    async def _baca(self, pengirim, teks):
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(
            brain_runtime.eksekutor_keputusan, brain_runtime.baca_chat, self.riwayat,
            self.match.labels[pengirim], teks, roster_label(self.match),
        )  # fmt: skip

    # Satu langkah bot persis seperti NPCService.brain_turn: keputusan → vote/aksi ke engine → kalimat.
    async def _langkah(self, otak):
        m, loop, mulai = self.match, asyncio.get_running_loop(), time.perf_counter()
        lapor = self._lapor(m.labels[otak.nama])
        otak.langkah += 1
        snapshot = snapshot_berlabel(m.snapshot(otak.nama), m.labels)
        view, hasil, konteks = await asyncio.wait_for(
            loop.run_in_executor(brain_runtime.eksekutor_keputusan, brain_runtime.langkah, otak,
                                 snapshot, self.jam, True, lapor),
            timeout=BATAS_LANGKAH_DETIK,
        )  # fmt: skip
        npc, rencana = hasil["npc_decision"], hasil["rencana_chat"]
        m.npc_decisions.add((m.round, m.phase, otak.nama))
        penolakan = tulisan = nlu = None
        lapor("engine")
        try:
            if npc["action"] == "vote":
                m.vote(otak.nama, m.username(npc["target"]))
            elif npc["action"] in AKSI_RAHASIA:
                m.act(otak.nama, npc["action"], m.username(npc["target"]))
                brain_runtime.catat_aksi(otak, m.round, npc["action"], npc["target"])
        except ValueError as error:
            penolakan = str(error)
        if hasil["nlg"] is not None:
            tulisan = await tulis_kalimat(brain_runtime, otak, hasil["nlg"], konteks, lapor)
            if tulisan["teks"] and m.can_chat(otak.nama):
                lapor("kirim")
                m.add_message(otak.nama, tulisan["teks"])
                brain_runtime.catat_chat(otak, view, rencana, tulisan["teks"])
                nlu = await self._baca(otak.nama, tulisan["teks"])
            else:
                tulisan = None
        trace = jejak_baru(KODE, otak.nama, tulisan["teks"] if tulisan else npc["action"])
        isi_jejak(trace, m, otak, npc, rencana, tulisan, penolakan,
                  round((time.perf_counter() - mulai) * 1000, 2), False, hasil.get("penjelasan"),
                  waktu_jejak(hasil.get("waktu"), tulisan), brain_runtime.nlu.sumber)  # fmt: skip
        trace["nlu"] = nlu
        lapor("selesai")
        return trace

    async def _putaran(self, detik):
        m = self.match
        # Bot tidak melangkah di detik terakhir fase (NPCService._due); waktu tidak melewati deadline.
        self.jam = min(self.jam + detik, m.deadline - 1.0)
        jejak = []
        for nama in sorted(self.otak):
            if m.players[nama].alive:
                self._lapor(nama)("menunggu")
        for nama in sorted(self.otak):
            if not m.winner and m.players[nama].alive:
                jejak += [await self._langkah(self.otak[nama]), *self._sistem()]
        return jejak

    async def kirim(self, teks, detik):
        m = self.match
        if m.winner or not m.can_chat(PEMAIN):
            raise ValueError(
                "Kamu tidak bisa chat sekarang (malam, dibungkam, atau permainan selesai)."
            )
        m.add_message(PEMAIN, teks)
        trace = {**jejak_baru(KODE, m.labels[PEMAIN], teks), "stage": "delivered", "manusia": True}
        lapor = self._lapor(m.labels[PEMAIN])
        lapor("nlu_pesan")
        trace["nlu"] = await self._baca(PEMAIN, teks)
        lapor("selesai")
        trace["timings"] = {"nlu_ms": trace["nlu"]["ms"]}
        return [trace, *await self._putaran(detik)]

    async def jalan(self, detik):
        if self.match.winner:
            raise ValueError("Permainan sudah selesai.")
        return await self._putaran(detik)

    # Lompat ke akhir fase: engine menyelesaikan fase (cadangan aksi bot yang belum memutuskan, hasil malam,
    # eksekusi Tribunal), lalu semua bot melangkah sekali di awal fase baru.
    async def fase(self, detik):
        m = self.match
        if m.winner:
            raise ValueError("Permainan sudah selesai.")
        self.jam = m.deadline
        m.tick(self.jam)
        jejak = self._sistem()
        if m.winner:
            return jejak
        self.jam = m.deadline - m.durations[m.phase] + MULAI_FASE
        return jejak + await self._putaran(0.0)


class SimulasiService:
    def __init__(self):
        self.simulasi: OrderedDict[str, Simulasi] = OrderedDict()

    def mulai(self, nama, metode):
        if not brain_runtime.status["siap"]:
            brain_runtime.mulai_memuat()
            raise RuntimeError(brain_runtime.status["detail"])
        sim = Simulasi(nama, metode)
        self.simulasi[sim.id] = sim
        while len(self.simulasi) > MAKS_SIMULASI:
            self.simulasi.popitem(last=False)
        return {**sim.ringkasan(), "jejak": sim._sistem()}

    # aksi: "kirim" (chat admin lalu satu putaran bot), "jalan" (putaran tanpa chat), "fase" (fase berikutnya).
    async def jalankan(self, sim_id, aksi, teks="", detik=3.0):
        sim = self.simulasi.get(sim_id)
        if sim is None:
            raise KeyError("Simulasi tidak ditemukan atau sudah dibuang. Mulai simulasi baru.")
        async with sim.lock:
            sim.progres = {}
            if aksi == "kirim":
                jejak = await sim.kirim(teks, detik)
            elif aksi == "jalan":
                jejak = await sim.jalan(detik)
            else:
                jejak = await sim.fase(detik)
        return {**sim.ringkasan(), "jejak": jejak}

    def progres(self, sim_id):
        sim = self.simulasi.get(sim_id)
        if sim is None:
            raise KeyError("Simulasi tidak ditemukan atau sudah dibuang. Mulai simulasi baru.")
        return {"berjalan": sim.lock.locked(), "progres": sim.lihat_progres()}


simulasi_service = SimulasiService()
