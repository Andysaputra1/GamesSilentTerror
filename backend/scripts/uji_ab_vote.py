"""Uji A/B kebijakan vote saat bukti lemah (PAKSA_VOTE_BUKTI_LEMAH) dengan aturan engine terbaru.

Semua kursi bot memakai SATU metode (otak hasil ekspor notebook), komposisi engine, label NLU sempurna, LANGKAH
keputusan per fase, seed sama untuk kedua kebijakan. Keluaran: win rate warga ± CI95 dan akurasi vote warga (porsi
suara warga yang mengenai Hitman). Dasar kebijakan per metode di notebook (bagian Kebijakan Vote saat Bukti Lemah).

Pemakaian (dari folder backend, Python dengan numpy + pandas + skfuzzy, mis. venv prethesis):
    python scripts/uji_ab_vote.py . 200 6 [jumlah_pemain=6]
"""

import importlib.util
import math
import random
import sys
from multiprocessing import Pool
from pathlib import Path

BACKEND = Path(sys.argv[1]).resolve()
sys.path.insert(0, str(BACKEND))
from app.module import match_engine  # noqa: E402

NAMA = ["NOX", "ECHO", "VEIL", "RAVEN", "ASH", "DUSK", "IRIS", "SAGE", "ONYX", "LARK"]
RONDE_MAKS = 30


def muat(nama):
    berkas = BACKEND / "app" / "module" / "npc_brain" / "generated" / f"{nama}.py"
    spec = importlib.util.spec_from_file_location(f"ab_{nama}", berkas)
    modul = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(modul)
    return modul


MODUL = {"fuzzy": muat("otak_fuzzy"), "utility": muat("otak_utility"), "bt": muat("otak_bt")}


def label_rencana(rencana):
    if rencana["intent"] is None or rencana["target"] is None:
        return "neutral", []
    return rencana["intent"], [{"pemain": rencana["target"], "relasi": rencana["intent"]}]


def satu_game(argumen):
    metode, paksa, jumlah, seed, langkah = argumen
    modul = MODUL[metode]
    modul.PAKSA_VOTE_BUKTI_LEMAH = paksa
    rng = random.Random(seed)
    nama = NAMA[:jumlah]
    match = match_engine.Match([], nama, rng=random.Random(rng.random()), now=0.0)
    match.npc_decisions = set()
    otak = {n: modul.Ingatan(n) for n in nama}
    label, ilegal, t = {}, 0, 0.0
    suara_warga = suara_tepat = 0
    while match.phase != "finished" and match.round <= RONDE_MAKS:
        ronde, fase, durasi = match.round, match.phase, match.durations[match.phase]
        for k in range(1, langkah + 1):
            waktu = t + durasi * k / (langkah + 1)
            for n in sorted(otak):
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
                        rekaman = match.add_message(n, npc["message"])
                        label[rekaman["id"]] = label_rencana(rc)
                        ingatan.catat_aksi_bot(view, rc)
                    if npc["action"] == "vote":
                        match.vote(n, npc["target"])
                        if match.players[n].role != "hitman":
                            suara_warga += 1
                            suara_tepat += match.players[npc["target"]].role == "hitman"
                    elif npc["action"] in modul.AKSI_RAHASIA:
                        match.act(n, npc["action"], npc["target"])
                        ingatan.catat_aksi_rahasia(ronde, npc["action"], npc["target"])
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
    with Pool() as kolam:
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
