"""Uji A/B kebijakan paksa vote saat warga kritis (PAKSA_VOTE_KRITIS) dengan aturan engine terbaru.

Semua kursi bot memakai otak Fuzzy di app/bot/fuzzy.py, komposisi engine, label NLU sempurna, LANGKAH keputusan
per fase, seed sama untuk kedua kebijakan. Keluaran: win rate warga ± CI95 dan akurasi vote warga (porsi suara warga
yang mengenai Hitman). Dasar kebijakan di notebook (bagian Kebijakan Vote saat Bukti Lemah).

Pemakaian (dari folder backend, dengan dependensi backend di requirements.txt; app/bot/nlg.py membaca pengaturan app):
    python scripts/uji_ab_vote.py . 200 6 [jumlah_pemain=6]
"""

import math
import os
import random
import sys
from multiprocessing import Pool
from pathlib import Path

BACKEND = Path(sys.argv[1]).resolve()
sys.path.insert(0, str(BACKEND))
from app.bot import fuzzy  # noqa: E402
from app.bot import nlg as NLG  # noqa: E402  (hanya templat chat tim, tanpa LLM)
from app.game import match_engine  # noqa: E402

NAMA = ["NOX", "ECHO", "VEIL", "RAVEN", "ASH", "DUSK", "IRIS", "SAGE", "ONYX", "LARK"]
RONDE_MAKS = 30
MODUL = {"fuzzy": fuzzy}
# Paling banyak separuh core, supaya mesin tetap bisa dipakai. SIM_PROSES boleh menurunkannya lagi.
PROSES = max(1, min(int(os.environ.get("SIM_PROSES", "64")), (os.cpu_count() or 2) // 2))


def label_rencana(rencana):
    if rencana["intent"] is None or rencana["target"] is None:
        return "neutral", []
    return rencana["intent"], [
        {"pemain": rencana["target"], "relasi": rencana["intent"]},
        *rencana.get("relasi_tambahan", []),
    ]


def satu_game(argumen):
    metode, paksa, jumlah, seed, langkah = argumen
    modul = MODUL[metode]
    modul.PAKSA_VOTE_KRITIS = paksa
    rng = random.Random(seed)
    nama = NAMA[:jumlah]
    match = match_engine.Match([], nama, rng=random.Random(rng.random()), now=0.0)
    match.npc_decisions = set()
    otak = {n: modul.Ingatan(n) for n in nama}
    label, ilegal, t = {}, 0, 0.0
    suara_warga = suara_tepat = 0
    while match.phase != "finished" and match.round <= RONDE_MAKS:
        # Dari deadline, bukan durasi tetap: suara seri menambah waktu Tribunal yang lebih pendek dari satu fase.
        ronde, fase, durasi = match.round, match.phase, match.deadline - t
        for k in range(1, langkah + 1):
            for urutan, n in enumerate(sorted(otak)):
                # Jam maju sedikit tiap bot, seperti jam server. Dengan jam yang persis sama, chat bot lain pada
                # langkah ini tidak terbaca sebagai chat baru.
                waktu = t + durasi * k / (langkah + 1) + urutan * 1e-6
                if not match.players[n].alive or match.phase == "finished":
                    continue
                ingatan = otak[n]
                view = ingatan.sinkron_snapshot(match.snapshot(n), waktu)
                for c in ingatan.chat:
                    if "intent" not in c:
                        intent, target = label.get(c["id"], ("neutral", []))
                        c.update(intent=intent, conf_intent=0.95, target=target)
                hasil = modul.putuskan(ingatan, view)
                npc, rc = hasil["npc_decision"], hasil["rencana_chat"]
                try:
                    if rc["kirim"]:
                        if not match.can_chat(n):
                            raise ValueError("chat tanpa izin")
                        rekaman = match.add_message(n, npc["message"], now=waktu)
                        label[rekaman["id"]] = label_rencana(rc)
                        ingatan.catat_aksi_bot(view, rc)
                    if npc["action"] == "vote":
                        if npc.get("pindah"):
                            match.cancel_vote(n)
                        match.vote(n, npc["target"])
                        ingatan.catat_vote_bot(view, hasil["rencana_vote"])
                        if match.players[n].role != "hitman":
                            suara_warga += 1
                            suara_tepat += match.players[npc["target"]].role == "hitman"
                    elif npc["action"] in modul.AKSI_RAHASIA:
                        if npc.get("pindah"):
                            match.cancel_action(n)
                        match.act(n, npc["action"], npc["target"])
                    # Chat tim hanya ada bila rekan manusia aktif, jadi di room semua bot paket ini selalu kosong.
                    if hasil.get("nlg_tim"):
                        teks = NLG.tulis_chat_tim(hasil["nlg_tim"], nama, None, "santai")["teks"]
                        if teks:
                            match.add_team_message(n, teks)
                        ingatan.catat_chat_tim(view, hasil["nlg_tim"], bool(teks))
                except ValueError:
                    ilegal += 1
        for n in otak:
            match.npc_decisions.add((ronde, fase, n))
        t += durasi
        match.tick(t)
    return metode, paksa, match.winner, suara_warga, suara_tepat, ilegal


if __name__ == "__main__":
    n_game, langkah = int(sys.argv[2]), int(sys.argv[3])
    jumlah = int(sys.argv[4]) if len(sys.argv) > 4 else 6
    tugas = [(m, p, jumlah, 4242 + i, langkah) for m in MODUL for p in (True, False) for i in range(n_game)]
    with Pool(processes=PROSES) as kolam:
        hasil = kolam.map(satu_game, tugas, chunksize=2)
    print(f"{n_game} game per sel, {jumlah} pemain, {langkah} langkah per fase")
    for m in MODUL:
        for p in (True, False):
            bagian = [h for h in hasil if h[0] == m and h[1] == p]
            menang = sum(h[2] == "civilians" for h in bagian) / n_game
            ci = 1.96 * math.sqrt(menang * (1 - menang) / n_game)
            sw, st = sum(h[3] for h in bagian), sum(h[4] for h in bagian)
            print(f"{m:8} paksa={p!s:5}: warga {100 * menang:.1f}% ± {100 * ci:.1f}, akurasi vote warga "
                  f"{100 * st / max(1, sw):.0f}% ({st}/{sw}), aksi ilegal {sum(h[5] for h in bagian)}")
