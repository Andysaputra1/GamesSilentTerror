"""Rekam jejak keputusan bot pada seed tetap, untuk membuktikan perapian kode tidak mengubah logika bot.

Tiga bagian, masing-masing punya sidik sha256 sendiri:
a. putuskan: semua keputusan chat, vote, dan aksi malam di room 4–10 bot. Label NLU sempurna diambil dari rencana
   pengirim, jadi yang terekam hanya penalaran. Seluruh hasil putuskan ikut, termasuk tabel dan jejak tiap tahap.
b. templat: kalimat templat NLG, prompt LLM, dan chat tim untuk tiap rencana di bagian a, tanpa LLM.
c. langkah: satu langkah bot penuh lewat BrainRuntime.langkah dengan NLU tiruan yang deterministik dan penulis templat.
   Satu pemain manusia (diam, sesekali chat dari daftar tetap) ikut supaya label nama tampilan dan aturan nama teruji.
   Yang terekam: view, keputusan beserta penjelasan panel, konteks NLG, kalimat, chat tim, dan bacaan pencatat NLU.

Angka waktu proses (ms, detik) tidak ikut karena berubah tiap kali jalan. Kunci dict diurutkan saat ditulis, jadi
urutan kunci tidak memengaruhi sidik; isinya tetap harus sama.

Pakai (dari folder backend):
    python tests/jejak/rekam_jejak.py              cetak sidik
    python tests/jejak/rekam_jejak.py --tulis      simpan sidik ke tests/jejak/sidik.json
    python tests/jejak/rekam_jejak.py --cek        bandingkan dengan sidik.json, keluar 1 bila berbeda
    --simpan FOLDER                                tulis jejak lengkap per game untuk mencari selisih
"""

import hashlib
import itertools
import json
import os
import random
import sys
from multiprocessing import Pool
from pathlib import Path
from unittest.mock import patch

BACKEND = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(BACKEND))

from app.game import match_engine  # noqa: E402
from app.bot import fuzzy, nlg  # noqa: E402
from app.bot.bot_controller import BrainRuntime  # noqa: E402
from app.bot.nlu import NLUBersama, baca_chat  # noqa: E402
from tests.nlu_palsu import NLUPalsu  # noqa: E402

LETAK_ENGINE = "app.game.match_engine"
SIDIK = Path(__file__).with_name("sidik.json")
NAMA_BOT = ["NOX", "ECHO", "VEIL", "RAVEN", "ASH", "DUSK", "IRIS", "SAGE", "ONYX", "LARK"]
RONDE_MAKS = 30
# Pola NLU tiruan, sama dengan runtime_siap di tests/test_npc_brain.py.
POLA_OFFEND = r"curiga|hitman|vote|mencurigakan"
POLA_DEFEND = r"bukan hitman|jangan vote|jangan buru|disandera|percaya"
# Chat pemain manusia di bagian c; {t} diganti bot hidup yang dipilih acak dengan seed game.
CHAT_MANUSIA = ["Aku curiga {t}, dari tadi diam.", "{t}, kamu semalam ngapain?", "Aku percaya {t} bukan hitman.",
                "Ada yang punya info?", "Jangan vote {t} dulu.", "Vote {t} aja."]
# Paling banyak separuh core, supaya laptop tetap bisa dipakai.
PROSES = max(1, min(int(os.environ.get("JEJAK_PROSES", "8")), (os.cpu_count() or 2) // 2))


# Ubah hasil apa pun menjadi bentuk JSON yang stabil: DataFrame jadi kolom dan baris, set diurutkan.
def bentuk(x):
    if hasattr(x, "to_dict") and hasattr(x, "columns"):
        return {"kolom": [str(k) for k in x.columns], "indeks": bentuk(list(x.index)),
                "baris": [bentuk(list(b)) for b in x.itertuples(index=False)]}
    if hasattr(x, "to_dict") and hasattr(x, "index"):
        return {"indeks": bentuk(list(x.index)), "nilai": bentuk(list(x))}
    if isinstance(x, dict):
        return {str(k): bentuk(v) for k, v in x.items()}
    if isinstance(x, (list, tuple)):
        return [bentuk(v) for v in x]
    if isinstance(x, (set, frozenset)):
        return sorted((bentuk(v) for v in x), key=lambda v: json.dumps(v, sort_keys=True, default=str))
    if hasattr(x, "item") and not isinstance(x, (str, bytes)):
        return x.item()
    return x


# Satu baris jejak: JSON dengan kunci terurut.
def baris(*isi):
    return json.dumps(bentuk(list(isi)), sort_keys=True, ensure_ascii=False, default=str)


# UUID berurutan untuk satu game, supaya id pertandingan dan id pesan sama setiap kali jalan.
def uuid_berurutan():
    hitung = itertools.count()

    class Uuid:
        def __init__(self):
            self.hex = f"{next(hitung):032x}"

    return Uuid


# Label NLU sempurna dari rencana chat pengirim, seperti scripts/simulasi_keseimbangan.py.
def label_rencana(rencana):
    if rencana["intent"] is None or rencana["target"] is None:
        return "neutral", []
    return rencana["intent"], [{"pemain": rencana["target"], "relasi": rencana["intent"]},
                               *rencana.get("relasi_tambahan", [])]


# Konteks NLG seperti BrainRuntime.langkah: chat terbaru sepanjang konteks prompt dan suara Tribunal.
def konteks_nlg(ingatan, view):
    chat = sorted(ingatan.chat, key=lambda c: c["waktu"])[-nlg.JUMLAH_CHAT_KONTEKS:]
    return {"roster": [p["nama"] for p in view["pemain"]],
            "chat_terbaru": [{"pengirim": c["pengirim"], "teks": c["teks"], "intent": c.get("intent"),
                              "target": [{"pemain": t["pemain"], "relasi": t["relasi"]} for t in c.get("target", [])]}
                             for c in chat],
            "suara_tribunal": dict(view["suara_tribunal"])}


# Hasil tulisan tanpa angka waktu proses.
def tanpa_waktu(tulisan):
    return {k: v for k, v in tulisan.items() if k not in ("detik", "llm_detik", "ms")}


# Bagian a dan b: satu game semua bot dengan putuskan langsung; b menulis kalimat untuk tiap rencana chat.
def game_putuskan(argumen):
    jumlah, seed, langkah = argumen
    with patch(f"{LETAK_ENGINE}.uuid4", uuid_berurutan()):
        rng = random.Random(seed)
        nama = NAMA_BOT[:jumlah]
        match = match_engine.Match([], nama, rng=random.Random(rng.random()), now=0.0)
        otak = {n: fuzzy.Ingatan(n) for n in nama}
        riwayat = {n: [] for n in nama}
        label, jejak_a, jejak_b, t = {}, [], [], 0.0
        while match.phase != "finished" and match.round <= RONDE_MAKS:
            ronde, fase, durasi = match.round, match.phase, match.deadline - t
            for k in range(1, langkah + 1):
                for urutan, n in enumerate(sorted(otak)):
                    waktu = t + durasi * k / (langkah + 1) + urutan * 1e-6
                    if not match.players[n].alive or match.phase == "finished":
                        continue
                    ingatan = otak[n]
                    view = ingatan.sinkron_snapshot(match.snapshot(n), waktu)
                    for c in ingatan.chat:
                        if "intent" not in c:
                            intent, target = label.get(c["id"], ("neutral", []))
                            c.update(intent=intent, conf_intent=0.95, target=target)
                    hasil = fuzzy.putuskan(ingatan, view)
                    jejak_a.append(baris(jumlah, seed, ronde, fase, k, n, view, hasil))
                    npc, rc = hasil["npc_decision"], hasil["rencana_chat"]
                    persona = nlg.persona_bot(n, nama)
                    if hasil["nlg"] is not None:
                        konteks = konteks_nlg(ingatan, view)
                        hindari = tuple(riwayat[n][-12:]) + tuple(c["teks"] for c in konteks["chat_terbaru"])
                        tulisan = nlg.tulis_pesan(hasil["nlg"], konteks, None, persona, hindari=hindari)
                        prompt = nlg.buat_prompt(hasil["nlg"], konteks, persona)
                        riwayat[n].append(tulisan["teks"])
                        jejak_b.append(baris(jumlah, seed, ronde, fase, k, n, "publik", tanpa_waktu(tulisan), prompt))
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
                        elif npc["action"] in fuzzy.AKSI_RAHASIA:
                            if npc.get("pindah"):
                                match.cancel_action(n)
                            match.act(n, npc["action"], npc["target"])
                        if hasil.get("nlg_tim"):
                            tim = nlg.tulis_chat_tim(hasil["nlg_tim"], nama, None, persona)
                            prompt_tim = nlg.buat_prompt_tim(hasil["nlg_tim"], persona)
                            jejak_b.append(baris(jumlah, seed, ronde, fase, k, n, "tim", tanpa_waktu(tim), prompt_tim))
                            if tim["teks"]:
                                match.add_team_message(n, tim["teks"])
                            ingatan.catat_chat_tim(view, hasil["nlg_tim"], bool(tim["teks"]))
                    except ValueError as error:
                        jejak_a.append(baris("ilegal", n, str(error)))
            for n in otak:
                match.npc_decisions.add((ronde, fase, n))
            t += durasi
            match.tick(t)
        jejak_a.append(baris("akhir", match.winner, match.round))
    return jejak_a, jejak_b


# Runtime otak dengan NLU tiruan dan penulis templat, seperti runtime_siap di tes.
def runtime_tiruan():
    runtime = BrainRuntime()
    runtime.penulis_npc.konfigurasi.penulis = "templat"
    runtime.muat_sekarang(nlu=NLUBersama(NLUPalsu(POLA_OFFEND, POLA_DEFEND), "cadangan"))
    return runtime


# Bacaan pencatat NLU untuk satu chat pertandingan, seperti catat_nlu di NPCService.
def baca_pencatat(runtime, riwayat, match, pengirim, teks):
    roster = [match.labels.get(n, n) for n in match.players]
    return baca_chat(runtime.nlu, riwayat, match.labels.get(pengirim, pengirim), teks, roster)


# Bagian c: satu game lewat BrainRuntime.langkah dengan satu manusia yang diam dan sesekali chat.
def game_langkah(argumen):
    jumlah, seed, langkah = argumen
    with patch(f"{LETAK_ENGINE}.uuid4", uuid_berurutan()):
        rng = random.Random(seed)
        bots = NAMA_BOT[:jumlah - 1]
        match = match_engine.Match(["tamu"], bots, rng=random.Random(rng.random()), now=0.0,
                                   labels=match_engine.label_unik({"tamu": "Andy"}, bots))
        runtime = runtime_tiruan()
        otak = runtime.buat_otak(match, bots)
        riwayat_nlu, jejak, t = [], [], 0.0
        while match.phase != "finished" and match.round <= RONDE_MAKS:
            ronde, fase, durasi = match.round, match.phase, match.deadline - t
            for k in range(1, langkah + 1):
                waktu_langkah = t + durasi * k / (langkah + 1)
                hidup = [n for n in bots if match.players[n].alive]
                if match.can_chat("tamu") and hidup and rng.random() < 0.6:
                    teks = rng.choice(CHAT_MANUSIA).format(t=match.labels[rng.choice(hidup)])
                    match.add_message("tamu", teks, now=waktu_langkah - 1e-3)
                    bacaan = baca_pencatat(runtime, riwayat_nlu, match, "tamu", teks)
                    jejak.append(baris(jumlah, seed, ronde, fase, k, "tamu", teks, tanpa_waktu(bacaan)))
                for urutan, n in enumerate(sorted(otak)):
                    waktu = waktu_langkah + urutan * 1e-6
                    if not match.players[n].alive or match.phase == "finished":
                        continue
                    bot = otak[n]
                    bot.langkah += 1
                    snapshot = match_engine.snapshot_berlabel(match.snapshot(n), match.labels)
                    view, keputusan, konteks = runtime.langkah(bot, snapshot, waktu, selalu_jelaskan=True)
                    keputusan = {kunci: isi for kunci, isi in keputusan.items() if kunci != "waktu"}
                    jejak.append(baris(jumlah, seed, ronde, fase, k, n, view, keputusan, konteks))
                    npc = keputusan["npc_decision"]
                    match.npc_decisions.add((ronde, fase, n))
                    try:
                        if npc["action"] == "vote":
                            if npc.get("pindah"):
                                match.cancel_vote(n)
                            match.vote(n, match.username(npc["target"]))
                            runtime.catat_vote(bot, view, keputusan["rencana_vote"])
                        elif npc["action"] in fuzzy.AKSI_RAHASIA:
                            if npc.get("pindah"):
                                match.cancel_action(n)
                            match.act(n, npc["action"], match.username(npc["target"]))
                    except ValueError as error:
                        jejak.append(baris("ditolak", n, str(error)))
                    if keputusan.get("nlg_tim") is not None:
                        tim = runtime.tulis_tim(bot, keputusan["nlg_tim"], konteks["roster"], False)
                        terkirim = bool(tim["teks"]) and match.can_team_chat(n)
                        if terkirim:
                            match.add_team_message(n, tim["teks"])
                        runtime.catat_chat_tim(bot, view, keputusan["nlg_tim"], terkirim)
                        jejak.append(baris(n, "tim", tanpa_waktu(tim), terkirim))
                    if keputusan["nlg"] is not None:
                        tulisan = runtime.tulis(bot, keputusan["nlg"], konteks, pakai_llm=False)
                        jejak.append(baris(n, "kalimat", tanpa_waktu(tulisan)))
                        if tulisan["teks"] and match.can_chat(n):
                            pesan = match.add_message(n, tulisan["teks"], now=waktu)
                            runtime.catat_chat(bot, view, keputusan["rencana_chat"], tulisan["teks"])
                            bacaan = baca_pencatat(runtime, riwayat_nlu, match, n, pesan["message"])
                            jejak.append(baris(n, "dibaca", tanpa_waktu(bacaan)))
            t += durasi
            match.tick(t)
        jejak.append(baris("akhir", match.winner, match.round))
        runtime.tutup()
    return jejak


# Sidik sha256 dari gabungan sidik tiap game, sesuai urutan tugas.
def sidik(daftar_jejak):
    per_game = [hashlib.sha256("\n".join(j).encode("utf-8")).hexdigest() for j in daftar_jejak]
    return hashlib.sha256("".join(per_game).encode("utf-8")).hexdigest(), per_game


def turunkan_prioritas():
    if sys.platform == "win32":
        import ctypes

        kernel32 = ctypes.WinDLL("kernel32")
        kernel32.GetCurrentProcess.restype = ctypes.c_void_p
        kernel32.SetPriorityClass.argtypes = [ctypes.c_void_p, ctypes.c_uint32]
        kernel32.SetPriorityClass(kernel32.GetCurrentProcess(), 0x4000)
    else:
        os.nice(10)


def main():
    turunkan_prioritas()
    tugas_a = [(j, 2026 + 7919 * j + i, 3) for j in range(4, 11) for i in range(4)]
    tugas_c = [(j, 4049 + 104729 * j + i, 2) for j in range(4, 11) for i in range(2)]
    with Pool(PROSES, initializer=turunkan_prioritas) as kolam:
        hasil_a = kolam.map(game_putuskan, tugas_a, chunksize=1)
        hasil_c = kolam.map(game_langkah, tugas_c, chunksize=1)
    bagian = {"a_putuskan": sidik([a for a, _ in hasil_a]), "b_templat": sidik([b for _, b in hasil_a]),
              "c_langkah": sidik(hasil_c)}
    ringkasan = {nama: {"total": total, "baris": sum(len(j) for j in jejak)}
                 for (nama, (total, _)), jejak in zip(bagian.items(), ([a for a, _ in hasil_a], [b for _, b in hasil_a],
                                                                     hasil_c))}
    for nama, isi in ringkasan.items():
        print(f"{nama:11s} {isi['total']}  ({isi['baris']} baris)")
    if "--simpan" in sys.argv:
        folder = Path(sys.argv[sys.argv.index("--simpan") + 1])
        folder.mkdir(parents=True, exist_ok=True)
        for i, (a, b) in enumerate(hasil_a):
            (folder / f"a_{tugas_a[i][0]}_{tugas_a[i][1]}.jsonl").write_text("\n".join(a), encoding="utf-8")
            (folder / f"b_{tugas_a[i][0]}_{tugas_a[i][1]}.jsonl").write_text("\n".join(b), encoding="utf-8")
        for i, c in enumerate(hasil_c):
            (folder / f"c_{tugas_c[i][0]}_{tugas_c[i][1]}.jsonl").write_text("\n".join(c), encoding="utf-8")
    if "--tulis" in sys.argv:
        SIDIK.write_text(json.dumps(ringkasan, indent=2) + "\n", encoding="utf-8")
    if "--cek" in sys.argv:
        tersimpan = json.loads(SIDIK.read_text(encoding="utf-8"))
        beda = [nama for nama in ringkasan if ringkasan[nama] != tersimpan.get(nama)]
        print("sidik sama" if not beda else f"sidik BERBEDA: {', '.join(beda)}")
        sys.exit(1 if beda else 0)


if __name__ == "__main__":
    main()
