"""Simulasi keseimbangan komposisi role dengan aturan engine terbaru.

Semua kursi bot memakai otak Fuzzy di app/bot/fuzzy_1.py dan fuzzy_2.py, label NLU sempurna dari rencana
pengirim, LANGKAH keputusan per fase, engine Match asli. Angka lama di GAME_CONCEPT diukur dengan metode campuran.

Pemakaian (dari folder backend, dengan dependensi backend di requirements.txt; app/bot/nlg.py membaca pengaturan app):
    python scripts/simulasi_keseimbangan.py . 200 6 "7:2/2/1" "8:2/2/1"
"""

import math
import os
import random
import sys
from multiprocessing import Pool
from pathlib import Path

BACKEND = Path(sys.argv[1]).resolve()
sys.path.insert(0, str(BACKEND))
from app.bot import fuzzy_1, fuzzy_2  # noqa: E402
from app.bot import nlg  # noqa: E402  (hanya templat chat tim, tanpa LLM)
from app.game import match_engine  # noqa: E402

NAMA = ["NOX", "ECHO", "VEIL", "RAVEN", "ASH", "DUSK", "IRIS", "SAGE", "ONYX", "LARK"]
RONDE_MAKS = 30
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
    jumlah, komposisi, seed, langkah = argumen
    match_engine.KOMPOSISI_PERAN[jumlah] = komposisi
    rng = random.Random(seed)
    nama = NAMA[:jumlah]
    match = match_engine.Match([], nama, rng=random.Random(rng.random()), now=0.0)
    match.npc_decisions = set()
    otak = {n: fuzzy_1.Ingatan(n) for n in nama}
    label, ilegal, t = {}, 0, 0.0
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
                hasil = fuzzy_2.putuskan(ingatan, view)
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
                    elif npc["action"] in fuzzy_2.AKSI_RAHASIA:
                        if npc.get("pindah"):
                            match.cancel_action(n)
                        match.act(n, npc["action"], npc["target"])
                    # Chat tim hanya ada bila rekan manusia aktif, jadi di room semua bot paket ini selalu kosong.
                    if hasil.get("nlg_tim"):
                        teks = nlg.tulis_chat_tim(hasil["nlg_tim"], nama, None, "santai")["teks"]
                        if teks:
                            match.add_team_message(n, teks)
                        ingatan.catat_chat_tim(view, hasil["nlg_tim"], bool(teks))
                except ValueError:
                    ilegal += 1
        for n in otak:
            match.npc_decisions.add((ronde, fase, n))
        t += durasi
        match.tick(t)
    return match.winner, match.round, ilegal


if __name__ == "__main__":
    n_game, langkah = int(sys.argv[2]), int(sys.argv[3])
    sel = []
    for teks in sys.argv[4:]:
        jumlah, susunan = teks.split(":")
        sel.append((int(jumlah), tuple(int(x) for x in susunan.split("/"))))
    tugas = [(j, k, 2026 + 7919 * j + i, langkah) for j, k in sel for i in range(n_game)]
    with Pool(processes=PROSES) as kolam:
        hasil = kolam.map(satu_game, tugas, chunksize=4)
    print(f"{n_game} game per sel, {langkah} langkah per fase")
    for idx, (jumlah, komposisi) in enumerate(sel):
        bagian = hasil[idx * n_game:(idx + 1) * n_game]
        menang = sum(w == "civilians" for w, _, _ in bagian) / n_game
        ci = 1.96 * math.sqrt(menang * (1 - menang) / n_game)
        tanpa = sum(w is None for w, _, _ in bagian)
        ronde = sum(r for _, r, _ in bagian) / n_game
        ilegal = sum(x for _, _, x in bagian)
        print(f"{jumlah} pemain {komposisi[0]}/{komposisi[1]}/{komposisi[2]}: warga {100 * menang:.1f}% ± "
              f"{100 * ci:.1f}, rata ronde {ronde:.2f}, tanpa pemenang {tanpa}, aksi ilegal {ilegal}")
