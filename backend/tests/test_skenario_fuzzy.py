"""Skenario permainan npc_fuzzy: situasi berlabel manual dan perilaku yang wajib dipilih bot.

Dipindah dari notebook skripsi (bagian Skenario Permainan dan Hasil Skenario). Chat diberi label NLU manual, jadi yang
diuji hanya penalaran. Harapan hanya perilaku yang jelas benar menurut aturan game; kasus ambigu boleh punya beberapa
jawaban. Notebook sekarang hanya untuk laporan, jadi skenario di sini yang menjadi patokan kode bot.

Isi skenario dan cek_harapan disalin apa adanya dari notebook; nama pembantu (ch, buat_ingatan, buat_view, jam) sama
dengan di notebook supaya mudah dicocokkan dengan laporan.
"""

import hashlib
import json
import unittest

from app.bot.fuzzy import (
    INTENT_AKSI,
    Ingatan,
    URUTAN_FASE,
    baris_pemain,
    bot_terkunci,
    durasi_fase,
    seri_acak,
    putuskan,
)
from app.bot.nlg import tulis_pesan
from app.bot.nlu import pemain_disebut

# fmt: off
PEMAIN_DEMO = ["Nara", "Andi", "Budi", "Citra", "Dodi", "Eka"]
BOT_DEMO = "Nara"
DURASI_DEMO = durasi_fase(len(PEMAIN_DEMO))
_AWAL_FASE = {"day": 0, "tribunal": DURASI_DEMO["day"], "night": DURASI_DEMO["day"] + DURASI_DEMO["tribunal"]}
PANJANG_RONDE = sum(DURASI_DEMO.values())


# Waktu absolut contoh dengan urutan fase siang → Tribunal → malam seperti engine. Ronde 1 tanpa Tribunal, jadi
# semua waktu sesudah siang ronde 1 maju sepanjang satu Tribunal.
def jam(ronde, fase, detik):
    awal = (ronde - 1) * PANJANG_RONDE + _AWAL_FASE[fase]
    if (ronde, fase) != (1, "day"):
        awal -= DURASI_DEMO["tribunal"]
    return awal + detik


# Chat berlabel manual untuk menguji penalaran tanpa kesalahan NLU. sumber (opsional) = asal target seperti keluaran
# anotasi_chat: ["indobert"], ["nama"], atau keduanya.
def ch(ronde, fase, detik, pengirim, teks, intent="neutral", target=(), conf=0.95, sumber=None):
    kunci = f"{ronde}|{fase}|{detik}|{pengirim}|{teks}"
    pasangan = [(t, intent) if isinstance(t, str) else t for t in target]
    return {"id": hashlib.md5(kunci.encode()).hexdigest()[:12], "ronde": ronde, "fase": fase,
            "waktu": jam(ronde, fase, detik), "pengirim": pengirim, "teks": teks, "intent": intent,
            "conf_intent": conf, "target": [{"pemain": p, "relasi": r, **({"sumber": list(sumber)} if sumber else {})}
                                            for p, r in pasangan]}


# Menyusun ingatan bot sampai fase tertentu.
def buat_ingatan(chats=(), votes=(), eksekusi=(), sampai=(1, "day"), gag_bot=(), aksi_bot=(), bot=BOT_DEMO,
                 peran="civilian", intel=(), keluar=(), vote_bot=()):
    ingatan = Ingatan(bot, jumlah_awal=len(PEMAIN_DEMO), peran=peran)
    R, fase = sampai
    for r in range(1, R + 1):
        for f in ("day", "tribunal", "night"):
            if (r, f) != (1, "tribunal") and (r, URUTAN_FASE[f]) <= (R, URUTAN_FASE[fase]):
                ingatan.mulai_fase[(r, f)] = jam(r, f, 0)
    for c in chats:
        ingatan.catat_chat(c)
    for r, pemilih, target in votes:
        ingatan.catat_vote(r, pemilih, target)
    for e in eksekusi:  # (ronde, nama) atau (ronde, nama, role korban dari pengumuman jumlah Hitman)
        ingatan.catat_eksekusi(*e)
    for k in keluar:  # pemain yang keluar di tengah pertandingan: (ronde, nama[, role dari pengumuman])
        ingatan.catat_keluar(*k)
    ingatan.gag_bot.update(gag_bot)
    ingatan.aksi_bot.extend(aksi_bot)
    ingatan.vote_bot.extend(vote_bot)
    ingatan.intel = [{"ronde": r, "pemain": p, "peran": x} for r, p, x in intel]
    return ingatan


# Target Hostage di antara calon yang bernilai sama: yang pertama menurut seri_acak bot dan ronde itu.
def seri_teratas(calon, ronde, bot=BOT_DEMO):
    return min(calon, key=lambda p: seri_acak(bot, ronde, p))


# Kemampuan role pada fase tertentu menurut engine: Gag (Hitman, siang); Hostage, Guard, Peek (malam).
def kemampuan_fase(fase, peran):
    if fase == "day" and peran == "hitman":
        return "gag"
    if fase == "night":
        return {"hitman": "hostage", "spy": "guard", "stalker": "peek"}.get(peran)
    return None


# View keputusan seperti hasil sinkron_snapshot (ability/can_act mengikuti aturan engine). sandera = {nama: ronde malam}
# korban Hostage yang sudah diumumkan server.
# hitman=2 menguji Syndicate pada roster yang sama; rekan dan aksi_rekan hanya berarti untuk bot Hitman.
def buat_view(ronde, fase, detik, *, peran="civilian", mati=(), suara=None, bot=BOT_DEMO,
              next_gag=1, next_peek=1, last_guard=None, hitman=1, spy=1, rekan=(), aksi_rekan=(), hitman_tersisa=None,
              sandera=None, hostage=False, **status):
    ability = kemampuan_fase(fase, peran)
    # Sama dengan engine: Hostage tidak punya aksi apa pun.
    can_act = (bool(ability) and not hostage and (ability != "gag" or ronde >= next_gag)
               and (ability != "peek" or ronde >= next_peek))
    saya = {"nama": bot, "role": peran, "can_chat": fase in ("day", "tribunal"), "can_vote": fase == "tribunal",
            "can_cancel_vote": False, "ability": ability, "can_act": can_act, "can_cancel_action": False,
            "last_guard": last_guard, "rekan": list(rekan), "aksi_rekan": [{"pemain": p, "target": t} for p, t in aksi_rekan],
            "rekan_spy": [], "aksi_rekan_spy": [], "korban_gag_tim": [], "rekan_manusia": [], "chat_tim": [],
            "hasil_sandera": []}
    saya.update(status)
    return {"ronde": ronde, "fase": fase, "waktu": jam(ronde, fase, detik),
            "deadline": jam(ronde, fase, DURASI_DEMO[fase]), "durasi": DURASI_DEMO,
            "pemain": [{"nama": p, "hidup": p not in mati, "sandera": (sandera or {}).get(p)} for p in PEMAIN_DEMO],
            "komposisi": {"hitman": hitman, "spy": spy, "stalker": 1, "civilian": len(PEMAIN_DEMO) - hitman - spy - 1},
            "hitman_tersisa": hitman_tersisa, "tribunal_tambahan": False, "saya": saya, "suara_tribunal": dict(suara or {})}

# Skenario permainan; harapan hanya perilaku yang jelas benar menurut aturan game.
def daftar_skenario():
    S = []

    # Riwayat siang ronde 1 yang dipakai ulang di skenario Tribunal digeser ke siang ronde 2 (ronde 1 tanpa Tribunal).
    def ke_ronde_2(chats):
        return [ch(2, c["fase"], c["waktu"] - jam(1, c["fase"], 0), c["pengirim"], c["teks"], c["intent"],
                   [(t["pemain"], t["relasi"]) for t in c["target"]], c["conf_intent"]) for c in chats]

    # ---------------------------------------------------------------- Civilian
    S.append(dict(nama="01 Awal game hening", cerita="Siang pertama, belum ada chat.",
                  ingatan=buat_ingatan(sampai=(1, "day")), view=buat_view(1, "day", 30),
                  harapan={"chat": [("tanya_info", None), ("tunggu", None)], "chat_bukan": [("tuduh", None)]}))

    r1 = [ch(1, "day", 10, "Andi", "Nara dari tadi diam, aku curiga Nara.", "offend", ["Nara"]),
          ch(1, "day", 20, "Budi", "Iya, Nara mencurigakan.", "offend", ["Nara"])]
    S.append(dict(nama="02 Bot dituduh dua pemain", cerita="Andi dan Budi menuduh bot. Tekanan 2/5 belum terdesak, dan penuduh yang menyerang orang baik menjadi tersangka teratas.",
                  ingatan=buat_ingatan(r1, sampai=(1, "day")), view=buat_view(1, "day", 30),
                  harapan={"chat": [("bela_diri", "Andi")], "jenis": "tunjuk_orang", "chat_tanpa_nilai": True, "konteks": {"bot_dituduh_baru": ["Andi", "Budi"]},
                           "pemicu": ["Andi", "Budi"]}))

    gag_r2 = [ch(2, "day", 10, "Citra", "Dodi alibinya berubah-ubah.", "offend", ["Dodi"]),
              ch(2, "day", 25, "Citra", "Aku yakin Dodi Hitman, vote Dodi.", "offend", ["Dodi"]),
              ch(2, "day", 50, "Andi", "Aku belum yakin siapa."),
              ch(2, "day", 60, "Dodi", "Citra terlalu cepat menuduh.", "offend", ["Citra"]),
              ch(2, "day", 80, "Budi", "Kita dengar yang lain dulu."),
              ch(2, "day", 100, "Eka", "Setuju, tunggu dulu.")]
    gag_v2 = [(2, "Citra", "Dodi"), (2, "Eka", "Dodi"), (2, "Dodi", "Citra"), (2, "Andi", "Citra"), (2, "Budi", "Andi")]
    gag_r3 = [ch(3, "day", 10, "Eka", "Semalam sepi ya."), ch(3, "day", 20, "Andi", "Siapa yang mau mulai?"),
              ch(3, "day", 25, "Dodi", "Pagi semua."), ch(3, "day", 30, "Budi", "Aku masih bingung.")]
    S.append(dict(nama="03 Korban Gag menuduh Dodi", cerita="Citra kemungkinan di-Gag setelah menuduh Dodi.",
                  ingatan=buat_ingatan(gag_r2 + gag_r3, gag_v2, sampai=(3, "day")), view=buat_view(3, "day", 40),
                  harapan={"tersangka": "Dodi", "chat": [("tuduh", "Dodi")]}))
    S.append(dict(nama="04 Vote setelah pola Gag", cerita="Tribunal ronde 3 sudah 80% berjalan.",
                  ingatan=buat_ingatan(gag_r2 + gag_r3, gag_v2, sampai=(3, "tribunal")),
                  view=buat_view(3, "tribunal", 60, suara={"Citra": "Dodi"}),
                  harapan={"vote": [("vote", "Dodi")]}))

    san_r2 = [ch(2, "day", 10, "Eka", "Budi dari tadi ngeles terus.", "offend", ["Budi"]),
              ch(2, "day", 30, "Eka", "Aku curiga Budi Hitman.", "offend", ["Budi"]),
              ch(2, "day", 40, "Andi", "Hmm, bisa jadi."),
              ch(2, "day", 60, "Budi", "Eka asal tuduh aja.", "offend", ["Eka"]),
              ch(2, "day", 80, "Citra", "Tunggu bukti dulu."),
              ch(2, "day", 90, "Dodi", "Iya.")]
    san_v2 = [(2, "Andi", "Budi"), (2, "Budi", "Andi"), (2, "Citra", "Dodi"), (2, "Dodi", "Citra")]
    san_r3 = [ch(3, "day", 10, "Andi", "Eka kok diam?"), ch(3, "day", 25, "Citra", "Mungkin Eka lagi afk."),
              ch(3, "day", 40, "Dodi", "Ayo bahas lagi."),
              ch(3, "day", 55, "Budi", "Aku masih curiga Andi.", "offend", ["Andi"])]
    S.append(dict(nama="05 Korban Hostage menuduh Budi", cerita="Eka menuduh Budi, lalu diumumkan disandera malam 2.",
                  ingatan=buat_ingatan(san_r2 + san_r3, san_v2, sampai=(3, "day")),
                  view=buat_view(3, "day", 70, sandera={"Eka": 2}),
                  harapan={"tersangka": "Budi", "chat": [("tuduh", "Budi")]}))
    S.append(dict(nama="06 Vote setelah pola Hostage", cerita="Tribunal ronde 3, Andi sudah vote Budi.",
                  ingatan=buat_ingatan(san_r2 + san_r3, san_v2, sampai=(3, "tribunal")),
                  view=buat_view(3, "tribunal", 60, suara={"Andi": "Budi"}, sandera={"Eka": 2}),
                  harapan={"vote": [("vote", "Budi")]}))

    bel_r2 = [ch(2, "day", 10, "Eka", "Halo semua."), ch(2, "day", 30, "Andi", "Ayo mulai diskusi."),
              ch(2, "day", 50, "Budi", "Belum ada petunjuk."), ch(2, "day", 70, "Citra", "Iya."),
              ch(2, "day", 90, "Dodi", "Sepi.")]
    bel_v2 = [(2, "Andi", "Budi"), (2, "Budi", "Andi"), (2, "Citra", "Dodi"), (2, "Dodi", "Citra")]
    bel_r3 = [ch(3, "day", 20, "Andi", "Eka dari tadi diam, pasti Hitman.", "offend", ["Eka"]),
              ch(3, "day", 35, "Citra", "Iya vote Eka aja.", "offend", ["Eka"]),
              ch(3, "day", 45, "Budi", "Hmm."), ch(3, "day", 50, "Dodi", "Bisa jadi.")]
    S.append(dict(nama="07 Tidak membela korban Hostage lewat chat", cerita="Andi dan Citra menuduh Eka yang sudah disandera. Korban sudah diumumkan, jadi tidak perlu dibela.",
                  ingatan=buat_ingatan(bel_r2 + bel_r3, bel_v2, sampai=(3, "day")),
                  view=buat_view(3, "day", 60, sandera={"Eka": 2}),
                  harapan={"chat_bukan": [("bela_orang", "Eka")]}))
    S.append(dict(nama="08 Tidak ikut vote korban Hostage", cerita="Dua suara sudah ke Eka.",
                  ingatan=buat_ingatan(bel_r2 + bel_r3, bel_v2, sampai=(3, "tribunal")),
                  view=buat_view(3, "tribunal", 60, suara={"Andi": "Eka", "Citra": "Eka"}, sandera={"Eka": 2}),
                  harapan={"vote_bukan": ["Eka"]}))

    eks_r2 = [ch(2, "day", 15, "Dodi", "Andi mencurigakan banget.", "offend", ["Andi"]),
              ch(2, "day", 40, "Budi", "Setuju, Andi aneh.", "offend", ["Andi"]),
              ch(2, "day", 60, "Andi", "Aku bukan Hitman!", "defend", ["Andi"]),
              ch(2, "day", 80, "Citra", "Hmm."), ch(2, "day", 90, "Eka", "Aku ikut kalian saja.")]
    eks_v2 = [(2, "Dodi", "Andi"), (2, "Budi", "Andi"), (2, "Eka", "Andi"), (2, "Andi", "Dodi"), (2, "Citra", "Dodi")]
    eks_r3 = [ch(3, "day", 10, "Citra", "Andi ternyata bukan Hitman."), ch(3, "day", 25, "Budi", "Waduh."),
              ch(3, "day", 30, "Eka", "Terus siapa?"),
              ch(3, "day", 40, "Dodi", "Mungkin Citra.", "offend", ["Citra"])]
    S.append(dict(nama="09 Pendorong eksekusi warga", cerita="Dodi penuduh pertama Andi yang ternyata bukan Hitman.",
                  ingatan=buat_ingatan(eks_r2 + eks_r3, eks_v2, [(2, "Andi")], sampai=(3, "day")),
                  view=buat_view(3, "day", 60, mati=["Andi"]),
                  harapan={"tersangka": "Dodi", "chat": [("tuduh", "Dodi")]}))

    ser_r2 = [ch(2, "day", 20, "Budi", "Nara pasti Hitman.", "offend", ["Nara"]),
              ch(2, "day", 50, "Andi", "Belum tentu Nara.", "defend", ["Nara"]),
              ch(2, "day", 70, "Citra", "Kita lihat dulu."), ch(2, "day", 80, "Dodi", "Oke."),
              ch(2, "day", 90, "Eka", "Sip.")]
    ser_v2 = [(2, "Budi", "Nara"), (2, "Andi", "Citra"), (2, "Citra", "Budi"), (2, "Dodi", "Eka"), (2, "Eka", "Dodi")]
    ser_r3 = [ch(3, "day", 15, "Budi", "Vote Nara hari ini.", "offend", ["Nara"]), ch(3, "day", 20, "Citra", "Hmm."),
              ch(3, "day", 30, "Dodi", "Kenapa Nara?"), ch(3, "day", 35, "Eka", "Alasannya apa?")]
    S.append(dict(nama="10 Budi terus menyerang bot", cerita="Budi menuduh dan vote bot dua ronde.",
                  ingatan=buat_ingatan(ser_r2 + ser_r3, ser_v2, sampai=(3, "day")), view=buat_view(3, "day", 40),
                  harapan={"tersangka": "Budi", "chat": [("bela_diri", "Budi")], "jenis": "tunjuk_orang"}))

    kla_r2 = [ch(2, "day", 10, "Andi", "Halo."), ch(2, "day", 20, "Budi", "Mulai yuk."),
              ch(2, "day", 30, "Citra", "Siap."), ch(2, "day", 40, "Dodi", "Oke."), ch(2, "day", 50, "Eka", "Sip.")]
    kla_v2 = [(2, "Andi", "Budi"), (2, "Budi", "Andi"), (2, "Citra", "Dodi"), (2, "Dodi", "Citra")]
    kla_r3 = [ch(3, "day", 10, "Andi", "Aku Stalker, semalam aku peek Citra dan dia Hitman.", "offend", ["Citra"]),
              ch(3, "day", 25, "Citra", "Bohong, aku yang Stalker. Aku peek Andi, dia Hitman.", "offend", ["Andi"]),
              ch(3, "day", 40, "Budi", "Wah dua-duanya ngaku Stalker."), ch(3, "day", 50, "Dodi", "Bingung."),
              ch(3, "day", 55, "Eka", "Terus gimana?")]
    S.append(dict(nama="11 Bentrok klaim Stalker", cerita="Andi dan Citra sama-sama mengaku Stalker.",
                  ingatan=buat_ingatan(kla_r2 + kla_r3, kla_v2, sampai=(3, "day")), view=buat_view(3, "day", 65),
                  harapan={"dua_teratas": ["Andi", "Citra"], "chat": [("tanya_info", None), ("tunggu", None)]}))

    end_r2 = [ch(2, "day", 10, "Dodi", "Halo."), ch(2, "day", 20, "Andi", "Eka aneh.", "offend", ["Eka"]),
              ch(2, "day", 30, "Budi", "Setuju, Eka aneh.", "offend", ["Eka"]),
              ch(2, "day", 40, "Citra", "Aku belum tahu."), ch(2, "day", 50, "Eka", "Aku warga!", "defend", ["Eka"])]
    end_v2 = [(2, "Andi", "Eka"), (2, "Budi", "Eka"), (2, "Citra", "Eka"), (2, "Eka", "Andi")]
    end_r3 = [ch(3, "day", 10, "Citra", "Eka ternyata bukan Hitman."), ch(3, "day", 20, "Andi", "Dodi kok diam terus."),
              ch(3, "day", 30, "Budi", "Citra dari tadi aneh.", "offend", ["Citra"])]
    end_v3 = [(3, "Andi", "Budi"), (3, "Budi", "Andi")]
    end_r4 = [ch(4, "day", 10, "Andi", "Tinggal sedikit nih."),
              ch(4, "day", 20, "Budi", "Aku curiga Andi.", "offend", ["Andi"]),
              ch(4, "day", 30, "Andi", "Aku curiga Budi.", "offend", ["Budi"])]
    S.append(dict(nama="12 Akhir game kritis", cerita="Citra dan Dodi disandera; dua warga bebas tersisa, tidak vote berarti kalah.",
                  ingatan=buat_ingatan(end_r2 + end_r3 + end_r4, end_v2 + end_v3, [(2, "Eka")], sampai=(4, "tribunal")),
                  view=buat_view(4, "tribunal", 60, mati=["Eka"], suara={"Andi": "Budi", "Budi": "Andi"},
                                 sandera={"Dodi": 2, "Citra": 3}),
                  harapan={"warga_terdesak_min": 0.8, "vote": [("vote", "Andi"), ("vote", "Budi")]}))

    dib_r1 = [ch(1, "day", 10, "Andi", "Citra mencurigakan.", "offend", ["Citra"]),
              ch(1, "day", 20, "Budi", "Iya Citra sus.", "offend", ["Citra"]),
              ch(1, "day", 30, "Dodi", "Citra bukan Hitman, dia dari tadi membantu.", "defend", ["Citra"]),
              ch(1, "day", 40, "Eka", "Setuju, jangan asal vote Citra.", "defend", ["Citra"])]
    S.append(dict(nama="13 Tuduhan tanpa bukti dibela", cerita="Dua menuduh, dua membela Citra, tanpa bukti keras.",
                  ingatan=buat_ingatan(dib_r1, sampai=(1, "day")), view=buat_view(1, "day", 60),
                  harapan={"chat_bukan": [("tuduh", "Citra")]}))

    ali_r1 = [ch(1, "day", 10, "Andi", "Budi alibinya aneh.", "offend", ["Budi"]),
              ch(1, "day", 20, "Budi", "Justru Citra yang aneh.", "offend", ["Citra"]),
              ch(1, "day", 35, "Dodi", "Budi kok malah nuduh Citra?", "offend", ["Budi"]),
              ch(1, "day", 45, "Budi", "Eka juga mencurigakan.", "offend", ["Eka"]),
              ch(1, "day", 60, "Citra", "Budi mengalihkan terus.", "offend", ["Budi"])]
    S.append(dict(nama="14 Pengalihan berulang", cerita="Budi selalu menjawab tuduhan dengan menuduh orang lain.",
                  ingatan=buat_ingatan(ali_r1, sampai=(1, "day")), view=buat_view(1, "day", 80),
                  harapan={"tersangka": "Budi"}))

    bgag_r2 = [ch(2, "day", 10, "Andi", "Siapa yang curiga?"),
               ch(2, "day", 20, "Nara", "Aku curiga Dodi.", "offend", ["Dodi"]),
               ch(2, "day", 60, "Budi", "Hmm."), ch(2, "day", 70, "Citra", "Oke."), ch(2, "day", 80, "Eka", "Lanjut.")]
    bgag_v2 = [(2, "Nara", "Dodi"), (2, "Andi", "Budi"), (2, "Budi", "Citra"), (2, "Citra", "Eka"), (2, "Dodi", "Nara"),
               (2, "Eka", "Andi")]
    bgag_r3 = [ch(3, "day", 10, "Andi", "Pagi."), ch(3, "day", 15, "Dodi", "Halo semua."),
               ch(3, "day", 20, "Eka", "Mulai lagi.")]
    aksi = [{"ronde": 2, "fase": "day", "waktu": jam(2, "day", 20), "aksi": "tuduh", "intent": "offend", "target": "Dodi"}]
    S.append(dict(nama="15 Bot di-Gag setelah menuduh", cerita="Bot kena Gag di ronde 2 tepat setelah menuduh Dodi.",
                  ingatan=buat_ingatan(bgag_r2 + bgag_r3, bgag_v2, sampai=(3, "day"), gag_bot=[2], aksi_bot=aksi),
                  view=buat_view(3, "day", 30),
                  harapan={"tersangka": "Dodi", "chat": [("tuduh", "Dodi")]}))

    # ---------------------------------------------------------------- Stalker
    st_r2 = [ch(2, "day", 10, "Andi", "Halo semua."), ch(2, "day", 25, "Budi", "Ayo mulai."),
             ch(2, "day", 40, "Citra", "Aku belum curiga siapa-siapa."), ch(2, "day", 55, "Dodi", "Santai dulu."),
             ch(2, "day", 70, "Eka", "Oke.")]
    S.append(dict(nama="16 Stalker menemukan Hitman", cerita="Peek malam 1: Dodi adalah Hitman. Tribunal baru mulai.",
                  ingatan=buat_ingatan(st_r2, sampai=(2, "tribunal"), peran="stalker", intel=[(1, "Dodi", "hitman")]),
                  view=buat_view(2, "tribunal", 5, peran="stalker", next_peek=3),
                  harapan={"tersangka": "Dodi", "chat": [("tuduh", "Dodi")], "jenis": "hasil_peek", "role_diakui": "stalker", "vote": [("vote", "Dodi")]}))

    sb_r2 = [ch(2, "day", 10, "Andi", "Citra mencurigakan.", "offend", ["Citra"]),
             ch(2, "day", 25, "Budi", "Setuju, Citra aneh.", "offend", ["Citra"]),
             ch(2, "day", 40, "Citra", "Aku bukan Hitman.", "defend", ["Citra"]),
             ch(2, "day", 55, "Dodi", "Hmm."), ch(2, "day", 70, "Eka", "Lihat nanti.")]
    S.append(dict(nama="17 Stalker membela pemain bersih", cerita="Peek: Citra bersih, padahal suara mengarah ke Citra.",
                  ingatan=buat_ingatan(sb_r2, sampai=(2, "tribunal"), peran="stalker", intel=[(1, "Citra", "civilian")]),
                  view=buat_view(2, "tribunal", 60, peran="stalker", next_peek=3,
                                 suara={"Andi": "Citra", "Budi": "Citra"}),
                  harapan={"chat": [("bela_orang", "Citra")], "jenis": "peek_bersih", "role_diakui": "stalker", "vote_bukan": ["Citra"]}))
    S.append(dict(nama="18 Stalker memilih target Peek", cerita="Malam ronde 2 setelah pola Gag yang menunjuk Dodi.",
                  ingatan=buat_ingatan(gag_r2, gag_v2, sampai=(2, "night"), peran="stalker"),
                  view=buat_view(2, "night", 10, peran="stalker", next_peek=2),
                  harapan={"aksi": [("peek", "Dodi")]}))
    S.append(dict(nama="19 Stalker: Peek belum tersedia", cerita="Cooldown Peek: baru bisa lagi di ronde 3.",
                  ingatan=buat_ingatan(gag_r2, gag_v2, sampai=(2, "night"), peran="stalker"),
                  view=buat_view(2, "night", 10, peran="stalker", next_peek=3),
                  harapan={"aksi": [("tidak_bisa", None)]}))

    pal_r3 = [ch(3, "day", 10, "Andi", "Aku Stalker, semalam aku peek Citra, dia Hitman.", "offend", ["Citra"]),
              ch(3, "day", 20, "Budi", "Serius?"), ch(3, "day", 30, "Dodi", "Wah."),
              ch(3, "day", 40, "Eka", "Citra jawab dong.")]
    S.append(dict(nama="20 Stalker tahu klaim palsu", cerita="Andi mengaku Stalker, padahal Stalker-nya bot.",
                  ingatan=buat_ingatan(kla_r2 + pal_r3, kla_v2, sampai=(3, "day"), peran="stalker"),
                  view=buat_view(3, "day", 50, peran="stalker", next_peek=3),
                  harapan={"tersangka": "Andi", "chat": [("tuduh", "Andi"), ("bela_orang", "Citra")]}))

    # ---------------------------------------------------------------- Spy
    S.append(dict(nama="21 Spy menjaga penuduh tersangka", cerita="Citra menuduh Dodi (tersangka kuat) dan kemungkinan di-Gag.",
                  ingatan=buat_ingatan(gag_r2, gag_v2, sampai=(2, "night"), peran="spy"),
                  view=buat_view(2, "night", 10, peran="spy"),
                  harapan={"aksi": [("guard", "Citra")], "nilai_aksi": {"Citra": 1.0, "Andi": 0.15, "Budi": 0.15}}))
    S.append(dict(nama="22 Guard boleh ke target yang sama", cerita="Semalam Spy sudah menjaga Citra. Guard boleh berulang, dan Citra tetap paling terancam.",
                  ingatan=buat_ingatan(gag_r2, gag_v2, sampai=(2, "night"), peran="spy"),
                  view=buat_view(2, "night", 10, peran="spy", last_guard="Citra"),
                  harapan={"aksi": [("guard", "Citra")]}))
    S.append(dict(nama="23 Spy disandera tidak bisa beraksi",
                  cerita="Spy sudah disandera: chat, vote, dan skill malam terkunci.",
                  ingatan=buat_ingatan(gag_r2, gag_v2, sampai=(2, "night"), peran="spy"),
                  view=buat_view(2, "night", 10, peran="spy", hostage=True, can_chat=False, can_vote=False),
                  harapan={"aksi": [("tidak_bisa", None)], "chat": [("tunggu", None)]}))

    # ---------------------------------------------------------------- Hitman
    S.append(dict(nama="24 Hitman dituduh", cerita="Andi dan Budi menuduh bot Hitman.",
                  ingatan=buat_ingatan(r1, sampai=(1, "day"), peran="hitman"),
                  view=buat_view(1, "day", 30, peran="hitman"),
                  harapan={"chat": [("bela_diri", "Nara")], "chat_tanpa_nilai": True}))

    hs_r1 = [ch(1, "day", 10, "Andi", "Aku Stalker, aku curiga Nara.", "offend", ["Nara"]),
             ch(1, "day", 25, "Budi", "Oke."), ch(1, "day", 40, "Citra", "Hmm."),
             ch(1, "day", 55, "Dodi", "Lanjut."), ch(1, "day", 70, "Eka", "Sip.")]
    S.append(dict(nama="25 Hitman tidak menyandera penuduh tunggal",
                  cerita="Andi mengaku Stalker dan hanya menuduh bot. Menyanderanya membuka Hitman: 0,85 × (1 − 0,5 × 1) = 0,425, "
                         "kalah dari warga lain yang bernilai 0,50. Seri diputus seri_acak.",
                  ingatan=buat_ingatan(hs_r1, sampai=(1, "night"), peran="hitman"),
                  view=buat_view(1, "night", 10, peran="hitman"),
                  harapan={"aksi": [("hostage", seri_teratas(["Budi", "Citra", "Dodi", "Eka"], 1))], "aksi_bukan": ["Andi"],
                           "nilai_aksi": {"Andi": 0.425, "Budi": 0.5, "Citra": 0.5, "Dodi": 0.5, "Eka": 0.5}}))

    tj_r1 = [ch(1, "day", 10, "Andi", "Halo."), ch(1, "day", 20, "Budi", "Hai."), ch(1, "day", 30, "Citra", "Mulai."),
             ch(1, "day", 40, "Dodi", "Oke."), ch(1, "day", 50, "Eka", "Sip.")]
    tj_v2 = [(2, "Andi", "Budi"), (2, "Budi", "Andi"), (2, "Citra", "Dodi"), (2, "Dodi", "Citra"), (2, "Eka", "Dodi")]
    tj_r2 = [ch(2, "day", 10, "Citra", "Nara aneh dari tadi.", "offend", ["Nara"]),
             ch(2, "day", 20, "Eka", "Setuju, Nara mencurigakan.", "offend", ["Nara"]),
             ch(2, "day", 30, "Andi", "Hmm."), ch(2, "day", 40, "Budi", "Oke."), ch(2, "day", 50, "Dodi", "Lanjut.")]
    S.append(dict(nama="26 Hostage gagal semalam tidak membuat target diutamakan",
                  cerita="Hostage ke Eka semalam gagal. Guard boleh berulang, jadi gagal semalam tidak mengubah nilai Eka. Citra dan "
                         "Eka sama-sama 0,85 × (1 − 0,5 × 1) = 0,425, kalah dari yang tidak menuduh (0,50). Seri diputus seri_acak.",
                  ingatan=buat_ingatan(tj_r1 + tj_r2, tj_v2, sampai=(2, "night"), peran="hitman"),
                  view=buat_view(2, "night", 10, peran="hitman", hasil_sandera=[{"ronde": 1, "pemain": "Eka", "berhasil": False}]),
                  harapan={"aksi": [("hostage", seri_teratas(["Andi", "Budi", "Dodi"], 2))], "pengetahuan": {"gagal_sandera": {"Eka": 1}},
                           "nilai_aksi": {"Andi": 0.5, "Budi": 0.5, "Dodi": 0.5, "Citra": 0.425, "Eka": 0.425}}))

    gg_r1 = [ch(1, "day", 10, "Citra", "Nara mencurigakan dari tadi.", "offend", ["Nara"]),
             ch(1, "day", 20, "Andi", "Iya aku setuju, Nara aneh.", "offend", ["Nara"]),
             ch(1, "day", 35, "Citra", "Nanti kita vote Nara saja.", "offend", ["Nara"]),
             ch(1, "day", 45, "Budi", "Hmm."), ch(1, "day", 55, "Dodi", "Oke.")]
    S.append(dict(nama="27 Hitman memakai Gag",
                  cerita="Citra menggalang suara dan Andi ikut menuduh bot Hitman. Keduanya berbahaya, jadi nilai Gag keduanya sama-sama 85.",
                  ingatan=buat_ingatan(gg_r1, sampai=(1, "day"), peran="hitman"),
                  view=buat_view(1, "day", 70, peran="hitman"),
                  harapan={"aksi": [("gag", "Andi"), ("gag", "Citra")],
                           "nilai_aksi": {"Andi": 85.0, "Citra": 85.0, "Budi": 15.0, "Dodi": 15.0}}))

    q_r1 = [ch(1, "day", 10, "Andi", "Halo."), ch(1, "day", 20, "Budi", "Hai."), ch(1, "day", 30, "Citra", "Mulai yuk.")]
    S.append(dict(nama="28 Hitman menunda Gag", cerita="Siang sepi, belum ada yang mengancam, dan baru separuh siang.",
                  ingatan=buat_ingatan(q_r1, sampai=(1, "day"), peran="hitman"),
                  view=buat_view(1, "day", 60, peran="hitman"),
                  harapan={"aksi": [("tunggu", None)]}))

    kh_r1 = [ch(1, "day", 10, "Andi", "Budi aneh.", "offend", ["Budi"]),
             ch(1, "day", 25, "Citra", "Setuju, Budi mencurigakan.", "offend", ["Budi"]),
             ch(1, "day", 40, "Budi", "Aku bukan Hitman!", "defend", ["Budi"]),
             ch(1, "day", 55, "Dodi", "Hmm."), ch(1, "day", 70, "Eka", "Lanjut.")]
    S.append(dict(nama="29 Hitman vote kambing hitam", cerita="Warga menekan Budi; Hitman ikut mendorong eksekusi warga.",
                  ingatan=buat_ingatan(ke_ronde_2(kh_r1), sampai=(2, "tribunal"), peran="hitman"),
                  view=buat_view(2, "tribunal", 60, peran="hitman", suara={"Andi": "Budi"}),
                  harapan={"vote": [("vote", "Budi")]}))

    ml_r2 = ke_ronde_2(r1) + [ch(2, "day", 40, "Citra", "Eka juga aneh.", "offend", ["Eka"])]
    S.append(dict(nama="30 Hitman memimpin suara", cerita="Dua suara ke bot Hitman, satu ke Eka.",
                  ingatan=buat_ingatan(ml_r2, sampai=(2, "tribunal"), peran="hitman"),
                  view=buat_view(2, "tribunal", 60, peran="hitman", suara={"Andi": "Nara", "Budi": "Nara", "Citra": "Eka"}),
                  harapan={"vote": [("vote", "Eka")], "konteks": {"bot_dituduh_baru": ["Andi", "Budi"]}}))

    k_r1 = [ch(1, "day", 10, "Eka", "Nara aneh.", "offend", ["Nara"]), ch(1, "day", 20, "Andi", "Halo."),
            ch(1, "day", 30, "Budi", "Hai."), ch(1, "day", 40, "Citra", "Oke."), ch(1, "day", 50, "Dodi", "Sip.")]
    k_v2 = [(2, "Andi", "Budi"), (2, "Budi", "Andi"), (2, "Citra", "Dodi"), (2, "Dodi", "Citra")]
    k_r2 = [ch(2, "day", 10, "Andi", "Eka disandera semalam."), ch(2, "day", 20, "Budi", "Iya, sayang sekali."),
            ch(2, "day", 30, "Citra", "Hmm."), ch(2, "day", 40, "Dodi", "Lanjut.")]
    S.append(dict(nama="31 Hitman tidak menyandera korbannya", cerita="Eka sudah berhasil disandera semalam.",
                  ingatan=buat_ingatan(k_r1 + k_r2, k_v2, sampai=(2, "night"), peran="hitman"),
                  view=buat_view(2, "night", 10, peran="hitman", sandera={"Eka": 1},
                                 hasil_sandera=[{"ronde": 1, "pemain": "Eka", "berhasil": True}]),
                  harapan={"aksi": [("hostage", None)], "aksi_bukan": ["Eka"]}))
    S.append(dict(nama="32 Hitman: Gag belum tersedia", cerita="Gag dipakai di ronde 1; baru tersedia lagi di ronde 3.",
                  ingatan=buat_ingatan(k_r1 + k_r2, sampai=(2, "day"), peran="hitman"),
                  view=buat_view(2, "day", 50, peran="hitman", next_gag=3, sandera={"Eka": 1}),
                  harapan={"aksi": [("tidak_bisa", None)]}))

    # ---------------------------------------------------------------- Ditanya langsung
    t_r1 = [ch(1, "day", 10, "Andi", "Halo semua."),
            ch(1, "day", 20, "Budi", "Nara, menurutmu siapa yang paling mencurigakan?"),
            ch(1, "day", 30, "Citra", "Iya Nara, kamu curiga siapa?")]
    S.append(dict(nama="33 Warga ditanya langsung", cerita="Budi dan Citra bertanya langsung ke bot.",
                  ingatan=buat_ingatan(t_r1, sampai=(1, "day")), view=buat_view(1, "day", 40),
                  harapan={"chat": [("jawab", None)]}))
    S.append(dict(nama="34 Hitman ditanya langsung", cerita="Pertanyaan yang sama ke bot Hitman.",
                  ingatan=buat_ingatan(t_r1, sampai=(1, "day"), peran="hitman"),
                  view=buat_view(1, "day", 40, peran="hitman"),
                  harapan={"chat": [("jawab", None)]}))

    # ---------------------------------------------------------------- Syndicate (dua Hitman)
    rk_r1 = [ch(1, "day", 10, "Andi", "Dodi aneh dari tadi.", "offend", ["Dodi"]),
             ch(1, "day", 20, "Citra", "Setuju, Dodi mencurigakan.", "offend", ["Dodi"]),
             ch(1, "day", 30, "Eka", "Budi juga aneh.", "offend", ["Budi"]),
             ch(1, "day", 40, "Budi", "Aku warga.", "defend", ["Budi"])]
    S.append(dict(nama="35 Hitman tidak menuduh rekan", cerita="Rekan Syndicate (Dodi) sedang dituduh dua pemain.",
                  ingatan=buat_ingatan(rk_r1, sampai=(1, "day"), peran="hitman"),
                  view=buat_view(1, "day", 60, peran="hitman", hitman=2, rekan=["Dodi"]),
                  harapan={"rekan_aman": ["Dodi"], "chat_bukan": [("tuduh", "Dodi")]}))
    S.append(dict(nama="36 Hitman menyelamatkan rekan di Tribunal", cerita="Dua suara ke Dodi (rekan), satu ke Budi.",
                  ingatan=buat_ingatan(ke_ronde_2(rk_r1), sampai=(2, "tribunal"), peran="hitman"),
                  view=buat_view(2, "tribunal", 60, peran="hitman", hitman=2, rekan=["Dodi"],
                                 suara={"Andi": "Dodi", "Citra": "Dodi", "Eka": "Budi"}),
                  harapan={"rekan_aman": ["Dodi"], "vote": [("vote", "Budi")]}))
    S.append(dict(nama="37 Hitman mengikuti target Hostage rekan",
                  cerita="Andi mengaku Stalker dan mencurigai bot. Nilai tertinggi jatuh ke Budi, tetapi rekan (Dodi) sudah memilih Citra.",
                  ingatan=buat_ingatan(hs_r1, sampai=(1, "night"), peran="hitman"),
                  view=buat_view(1, "night", 10, peran="hitman", hitman=2, rekan=["Dodi"], aksi_rekan=[("Dodi", "Citra")]),
                  harapan={"aksi": [("hostage", "Citra")]}))
    S.append(dict(nama="38 Hitman tidak menyandera rekan", cerita="Ancaman terbesar (Andi) ternyata rekan Syndicate.",
                  ingatan=buat_ingatan(hs_r1, sampai=(1, "night"), peran="hitman"),
                  view=buat_view(1, "night", 10, peran="hitman", hitman=2, rekan=["Andi"]),
                  harapan={"rekan_aman": ["Andi"], "aksi": [("hostage", None)]}))
    S.append(dict(nama="39 Gag bersama sudah dipakai rekan", cerita="Rekan sudah memakai Gag Syndicate ronde ini.",
                  ingatan=buat_ingatan(gg_r1, sampai=(1, "day"), peran="hitman"),
                  view=buat_view(1, "day", 70, peran="hitman", hitman=2, rekan=["Budi"], next_gag=3),
                  harapan={"aksi": [("tidak_bisa", None)]}))

    lb_r2 = [ch(2, "day", 10, "Eka", "Budi dari tadi ngeles terus.", "offend", ["Budi"]),
             ch(2, "day", 30, "Eka", "Aku curiga Budi Hitman.", "offend", ["Budi"]),
             ch(2, "day", 40, "Andi", "Dodi juga aneh.", "offend", ["Dodi"]),
             ch(2, "day", 60, "Budi", "Eka asal tuduh aja.", "offend", ["Eka"]),
             ch(2, "day", 80, "Citra", "Tunggu bukti dulu.")]
    lb_v2 = [(2, "Nara", "Dodi"), (2, "Andi", "Dodi"), (2, "Citra", "Dodi"), (2, "Budi", "Andi")]
    lb_r3 = [ch(3, "day", 10, "Andi", "Eka kok diam?"), ch(3, "day", 25, "Citra", "Eka kan disandera semalam."),
             ch(3, "day", 40, "Budi", "Aku masih curiga Andi.", "offend", ["Andi"])]
    S.append(dict(nama="40 Perburuan berlanjut setelah satu Hitman dieksekusi",
                  cerita="Stalker tahu Dodi Hitman dan Dodi sudah dieksekusi, tetapi Hitman ada dua.",
                  ingatan=buat_ingatan(lb_r2 + lb_r3, lb_v2, [(2, "Dodi")], sampai=(3, "day"), peran="stalker",
                                       intel=[(1, "Dodi", "hitman")]),
                  view=buat_view(3, "day", 70, peran="stalker", hitman=2, mati=["Dodi"], next_peek=3, sandera={"Eka": 2}),
                  harapan={"tersangka": "Budi", "chat": [("tuduh", "Budi")]}))
    S.append(dict(nama="41 Syndicate hampir unggul", cerita="Skenario 12 dengan dua Hitman: warga bebas ≈ Hitman hidup.",
                  ingatan=buat_ingatan(end_r2 + end_r3 + end_r4, end_v2 + end_v3, [(2, "Eka")], sampai=(4, "tribunal")),
                  view=buat_view(4, "tribunal", 60, mati=["Eka"], hitman=2, suara={"Andi": "Budi", "Budi": "Andi"},
                                 sandera={"Dodi": 2, "Citra": 3}),
                  harapan={"warga_terdesak_min": 0.95, "vote": [("vote", None)]}))

    # ---------------------------------------------------------------- Pengumuman jumlah Hitman (room ≥ 2 Hitman)
    S.append(dict(nama="42 Eksekusi warga menurut pengumuman",
                  cerita="Skenario 09 di room dua Hitman: Hitman tersisa tetap 2 setelah Andi dieksekusi, jadi Andi warga.",
                  ingatan=buat_ingatan(eks_r2 + eks_r3, eks_v2, [(2, "Andi", False)], sampai=(3, "day")),
                  view=buat_view(3, "day", 60, mati=["Andi"], hitman=2, hitman_tersisa=2),
                  harapan={"tersangka": "Dodi", "chat": [("tuduh", "Dodi")]}))

    ph_r2 = [ch(2, "day", 10, "Citra", "Dodi alibinya aneh.", "offend", ["Dodi"]),
             ch(2, "day", 25, "Eka", "Setuju, Dodi mencurigakan.", "offend", ["Dodi"]),
             ch(2, "day", 40, "Budi", "Dodi bukan Hitman, jangan buru-buru vote Dodi.", "defend", ["Dodi"]),
             ch(2, "day", 55, "Andi", "Hmm."), ch(2, "day", 70, "Dodi", "Aku warga!", "defend", ["Dodi"])]
    ph_v2 = [(2, "Nara", "Dodi"), (2, "Citra", "Dodi"), (2, "Eka", "Dodi"), (2, "Andi", "Dodi"),
             (2, "Budi", "Citra"), (2, "Dodi", "Citra")]
    ph_r3 = [ch(3, "day", 10, "Andi", "Pagi."), ch(3, "day", 20, "Citra", "Satu Hitman sudah ketemu."),
             ch(3, "day", 30, "Eka", "Tinggal satu lagi.")]
    S.append(dict(nama="43 Eksekusi Hitman menurut pengumuman",
                  cerita="Hitman tersisa turun jadi 1 setelah Dodi dieksekusi: pendorong eksekusi Dodi tidak dicurigai.",
                  ingatan=buat_ingatan(ph_r2 + ph_r3, ph_v2, [(2, "Dodi", True)], sampai=(3, "day")),
                  view=buat_view(3, "day", 40, mati=["Dodi"], hitman=2, hitman_tersisa=1),
                  harapan={"chat_bukan": [("tuduh", "Citra"), ("tuduh", "Eka"), ("tuduh", "Andi")],
                           "alasan_bukan": ["eksekusi Dodi"]}))

    # Bot Hitman yang rekannya (Dodi) dieksekusi: tahu korbannya Hitman, jadi tidak memakai eksekusi itu sebagai
    # bukti "salah eksekusi", baik dengan pengumuman jumlah Hitman (44) maupun tanpa pengumuman (45).
    rh_v2 = [(2, "Nara", "Citra"), (2, "Citra", "Dodi"), (2, "Eka", "Dodi"), (2, "Andi", "Dodi"),
             (2, "Budi", "Eka"), (2, "Dodi", "Citra")]
    rh_r3 = ph_r3 + [ch(3, "day", 35, "Citra", "Nara dari tadi aneh, jangan-jangan rekan Dodi.", "offend", ["Nara"])]
    for nomor, eksekusi, tersisa, keterangan in (("44", (2, "Dodi", True), 1, "dengan pengumuman"),
                                                  ("45", (2, "Dodi"), None, "tanpa pengumuman")):
        S.append(dict(nama=f"{nomor} Hitman tidak memakai eksekusi rekan ({keterangan})",
                      cerita="Rekan Syndicate (Dodi) dieksekusi setelah Citra menggalang suara; Citra kini menuduh bot.",
                      ingatan=buat_ingatan(ph_r2 + rh_r3, rh_v2, [eksekusi], sampai=(3, "day"), peran="hitman"),
                      view=buat_view(3, "day", 45, peran="hitman", mati=["Dodi"], hitman=2, rekan=["Dodi"],
                                     hitman_tersisa=tersisa),
                      harapan={"chat": [("bela_diri", None)], "alasan_bukan": ["eksekusi Dodi"]}))

    # ---------------------------------------------------------------- Dipanggil (pertanyaan langsung ke bot)
    # Target neutral datang dari persepsi: IndoBERT (label manual bersumber "indobert") atau aturan nama. ch_nama memakai
    # aturan nama yang sama dengan anotasi_chat (pemain_disebut), tanpa IndoBERT.
    def ch_nama(ronde, fase, detik, pengirim, teks):
        disebut = pemain_disebut(teks, PEMAIN_DEMO, pengirim, frozenset())
        return ch(ronde, fase, detik, pengirim, teks, "neutral", [(n, "neutral") for n in disebut], sumber=["nama"])

    pg_r1 = [ch(1, "day", 10, "Andi", "Halo semua."), ch(1, "day", 20, "Citra", "Ayo mulai diskusi.")]
    S.append(dict(nama="46 Dipanggil nama tanpa tanda tanya",
                  cerita="Budi menulis 'Nara kamu curiga siapa' tanpa tanda tanya, nama di depan kalimat.",
                  ingatan=buat_ingatan(pg_r1 + [ch_nama(1, "day", 30, "Budi", "Nara kamu curiga siapa")]),
                  view=buat_view(1, "day", 40),
                  harapan={"chat": [("jawab", None)], "konteks": {"penanya": "Budi"}}))
    S.append(dict(nama="47 Dipanggil lewat panggilan",
                  cerita="Citra memanggil bot 'Nar'; hanya aturan nama yang mengenalinya.",
                  ingatan=buat_ingatan(pg_r1 + [ch_nama(1, "day", 30, "Citra", "Nar, menurutmu siapa yang paling aneh?")]),
                  view=buat_view(1, "day", 40),
                  harapan={"chat": [("jawab", None)], "konteks": {"penanya": "Citra"}}))
    km_r1 = [ch(1, "day", 10, "Andi", "Halo semua."), ch(1, "day", 20, "Nara", "Aku masih menyimak dulu."),
             ch(1, "day", 38, "Budi", "Terus kamu curiga siapa?", "neutral", [("Nara", "neutral")], sumber=["indobert"])]
    aksi_km = [{"ronde": 1, "fase": "day", "waktu": jam(1, "day", 20), "aksi": "tanya_info", "intent": "neutral",
                "target": None}]
    S.append(dict(nama="48 Dipanggil lewat kata kamu",
                  cerita="Bot baru bicara, lalu Budi bertanya 'Terus kamu curiga siapa?'; hanya IndoBERT yang tahu "
                         "'kamu' adalah bot.",
                  ingatan=buat_ingatan(km_r1, aksi_bot=aksi_km), view=buat_view(1, "day", 45),
                  harapan={"chat": [("jawab", None)], "konteks": {"penanya": "Budi"}}))
    S.append(dict(nama="49 Pertanyaan untuk semua tidak memaksa jawaban",
                  cerita="Eka bertanya ke semua orang ('Ada yang tau ...?'); bot bukan target neutral.",
                  ingatan=buat_ingatan(pg_r1 + [ch_nama(1, "day", 30, "Eka", "Ada yang tau sisa waktu vote?")]),
                  view=buat_view(1, "day", 40),
                  harapan={"chat_bukan": [("jawab", None)], "konteks": {"penanya": None}}))
    dj_r1 = pg_r1 + [ch_nama(1, "day", 25, "Budi", "Nara, kamu curiga siapa?"),
                     ch(1, "day", 32, "Nara", "Aku belum yakin, kalian curiga siapa?"), ch(1, "day", 40, "Citra", "Hmm.")]
    aksi_dj = [{"ronde": 1, "fase": "day", "waktu": jam(1, "day", 32), "aksi": "jawab", "intent": "neutral",
                "target": None}]
    S.append(dict(nama="50 Sudah menjawab tidak menjawab lagi",
                  cerita="Bot sudah menjawab pertanyaan Budi dan belum ada pertanyaan baru ke bot.",
                  ingatan=buat_ingatan(dj_r1, aksi_bot=aksi_dj), view=buat_view(1, "day", 60),
                  harapan={"chat_bukan": [("jawab", None)]}))
    aksi_habis = [{"ronde": 1, "fase": "day", "waktu": jam(1, "day", d), "aksi": "tanya_info", "intent": "neutral",
                   "target": None} for d in (5, 22, 40)]
    S.append(dict(nama="51 Jatah inisiatif habis tetap menjawab",
                  cerita="Bot sudah memakai 3 chat inisiatif siang ini, lalu Andi bertanya langsung. Jawab memakai atap reaktif.",
                  ingatan=buat_ingatan(pg_r1 + [ch_nama(1, "day", 60, "Andi", "Nara, kamu curiga siapa?")],
                                       aksi_bot=aksi_habis),
                  view=buat_view(1, "day", 70),
                  harapan={"chat": [("jawab", None)], "pemicu": ["Andi"]}))
    tanya_05 = ch_nama(3, "day", 62, "Citra", "Nara, menurutmu siapa Hitman-nya?")
    S.append(dict(nama="52 Ditanya saat ada tersangka kuat",
                  cerita="Skenario 05 ditambah pertanyaan Citra ke bot: jawaban yang menyebut Budi didahulukan.",
                  ingatan=buat_ingatan(san_r2 + san_r3 + [tanya_05], san_v2, sampai=(3, "day")),
                  view=buat_view(3, "day", 70, sandera={"Eka": 2}),
                  harapan={"chat": [("jawab", "Budi")], "chat_tanpa_nilai": True}))
    S.append(dict(nama="53 Hitman dipanggil menjawab seperti warga",
                  cerita="Warga menekan Budi; Dodi memanggil bot Hitman 'Nar'. Bot menjawab dengan bukti publik saja.",
                  ingatan=buat_ingatan(kh_r1 + [ch_nama(1, "day", 80, "Dodi", "Nar, kamu curiga siapa?")], peran="hitman"),
                  view=buat_view(1, "day", 90, peran="hitman"),
                  harapan={"chat": [("jawab", None)]}))

    # ---------------------------------------------------------------- Pemain keluar di tengah pertandingan
    kl_v2 = [(2, "Dodi", "Andi"), (2, "Budi", "Andi"), (2, "Andi", "Dodi"), (2, "Citra", "Dodi"), (2, "Eka", "Budi")]
    kl_r3 = [ch(3, "day", 10, "Citra", "Andi keluar dari permainan."), ch(3, "day", 25, "Budi", "Waduh."),
             ch(3, "day", 30, "Eka", "Terus siapa?"), ch(3, "day", 40, "Dodi", "Mungkin Citra.", "offend", ["Citra"])]
    S.append(dict(nama="54 Pemain keluar: penuduhnya tidak disalahkan",
                  cerita="Seperti skenario 09, tetapi Tribunal ronde 2 seri dan Andi keluar dari permainan.",
                  ingatan=buat_ingatan(eks_r2 + kl_r3, kl_v2, sampai=(3, "day"), keluar=[(3, "Andi")]),
                  view=buat_view(3, "day", 60, mati=["Andi"]),
                  harapan={"chat_bukan": [("tuduh", "Dodi"), ("tuduh", "Budi")], "alasan_bukan": ["eksekusi Andi"]}))
    S.append(dict(nama="55 Hitman memilih ulang setelah target keluar",
                  cerita="Malam 1: target Hostage bot (Andi) keluar sehingga aksinya dibuang engine; bot memilih lagi.",
                  ingatan=buat_ingatan(hs_r1, sampai=(1, "night"), peran="hitman", keluar=[(1, "Andi")]),
                  view=buat_view(1, "night", 20, peran="hitman", mati=["Andi"]),
                  harapan={"aksi": [("hostage", None)], "aksi_bukan": ["Andi"]}))
    rp_r2 = [c for c in tj_r2 if c["pengirim"] != "Andi"]
    S.append(dict(nama="56 Hitman: pilihan ulang malam tercatat",
                  cerita="Malam 1 target bot (Andi) keluar; bot memilih ulang Eka, tetapi Eka tidak disandera (dijaga Spy). "
                         "Hasil server mencatat pilihan ulang itu sebagai satu malam gagal ke Eka.",
                  ingatan=buat_ingatan(tj_r1 + rp_r2, [v for v in tj_v2 if "Andi" not in v], sampai=(2, "night"), peran="hitman",
                                       keluar=[(1, "Andi")]),
                  view=buat_view(2, "night", 10, peran="hitman", mati=["Andi"],
                                 hasil_sandera=[{"ronde": 1, "pemain": "Eka", "berhasil": False}]),
                  harapan={"aksi": [("hostage", None)], "aksi_bukan": ["Andi"],
                           "pengetahuan": {"gagal_sandera": {"Eka": 1}}}))

    # ---------------------------------------------------------------- Aturan chat menuduh sama untuk ketiga metode
    gema_r3 = gag_r3 + [ch(3, "day", 32, "Eka", "Aku juga curiga Dodi.", "offend", ["Dodi"]),
                        ch(3, "day", 35, "Andi", "Iya, Dodi paling mencurigakan.", "offend", ["Dodi"])]
    S.append(dict(nama="57 Anti-gema: tuduhan ketiga tidak diulang",
                  cerita="Skenario 03, tetapi Eka dan Andi sudah menuduh Dodi di fase ini: bot tidak jadi suara ketiga.",
                  ingatan=buat_ingatan(gag_r2 + gema_r3, gag_v2, sampai=(3, "day")), view=buat_view(3, "day", 40),
                  harapan={"tersangka": "Dodi", "chat_bukan": [("tuduh", "Dodi")]}))
    aksi_ungkap = [{"ronde": 2, "fase": "tribunal", "waktu": jam(2, "tribunal", 5), "aksi": "tuduh", "jenis": "hasil_peek", "intent": "offend",
                    "target": "Dodi"}]
    S.append(dict(nama="58 Sudah mengungkap: tidak menuduh lagi",
                  cerita="Skenario 16 setelah Stalker mengungkap Dodi di Tribunal ini: tidak menambah 'curiga sama Dodi'.",
                  ingatan=buat_ingatan(st_r2, sampai=(2, "tribunal"), peran="stalker", intel=[(1, "Dodi", "hitman")],
                                       aksi_bot=aksi_ungkap),
                  view=buat_view(2, "tribunal", 20, peran="stalker", next_peek=3),
                  harapan={"chat_bukan": [("tuduh", "Dodi")], "vote": [("vote", "Dodi")]}))

    # ---------------------------------------------------------------- Vote Hitman
    S.append(dict(nama="59 Hitman tidak membuka vote",
                  cerita="Skenario 29 sebelum Andi vote: Tribunal sudah lewat separuh, belum ada suara warga.",
                  ingatan=buat_ingatan(ke_ronde_2(kh_r1), sampai=(2, "tribunal"), peran="hitman"),
                  view=buat_view(2, "tribunal", 60, peran="hitman"),
                  harapan={"vote": [("abstain", None)]}))

    # ---------------------------------------------------------------- Rumus bukti final
    # Harapan "tabel", "fitur_hitman", dan "konteks" memeriksa angkanya langsung.
    tk = [ch(1, "day", 10, "Andi", "Citra aneh.", "offend", ["Citra"]),
          ch(1, "day", 20, "Dodi", "Citra bukan Hitman.", "defend", ["Citra"]),
          ch(2, "day", 10, "Andi", "Citra makin aneh.", "offend", ["Citra"]),
          ch(2, "day", 20, "Budi", "Setuju, Citra aneh.", "offend", ["Citra"])]
    S.append(dict(nama="60 Tekanan dan dukungan: tiap orang sekali",
                  cerita="Andi menuduh Citra dua ronde, hanya dihitung sekali dengan nilai terbaru. Pembelaan Dodi sudah lewat satu ronde.",
                  ingatan=buat_ingatan(tk, sampai=(2, "day")), view=buat_view(2, "day", 30),
                  harapan={"tabel": {"Citra": {"tekanan": 2 / 4, "dukungan": 0.7 / 4}}}))

    al_1 = [ch(1, "day", 10, "Andi", "Budi aneh.", "offend", ["Budi"]),
            ch(1, "day", 20, "Budi", "Justru Citra yang aneh.", "offend", ["Citra"]),
            ch(1, "day", 30, "Eka", "Dodi aneh.", "offend", ["Dodi"]),
            ch(1, "day", 40, "Dodi", "Kamu yang aneh, Eka.", "offend", ["Eka"])]
    S.append(dict(nama="61 Alihkan tuduhan: hanya menuduh = 1",
                  cerita="Budi membalas dengan menuduh pihak ketiga, Dodi membalas menuduh penuduhnya. Keduanya bernilai 1.",
                  ingatan=buat_ingatan(al_1), view=buat_view(1, "day", 50),
                  harapan={"tabel": {"Budi": {"alihkan_tuduhan": 1.0}, "Dodi": {"alihkan_tuduhan": 1.0}}}))
    al_05 = [ch(1, "day", 10, "Andi", "Budi aneh.", "offend", ["Budi"]),
             ch(1, "day", 20, "Budi", "Aku bukan Hitman, justru Citra yang aneh.", "defend", [("Budi", "defend"), ("Citra", "offend")])]
    S.append(dict(nama="62 Alihkan tuduhan: membela diri sekaligus menuduh = 0,5",
                  cerita="Balasan Budi membela diri dan menuduh Citra dalam satu kalimat.",
                  ingatan=buat_ingatan(al_05), view=buat_view(1, "day", 30),
                  harapan={"tabel": {"Budi": {"alihkan_tuduhan": 0.5}}}))
    al_0 = [ch(1, "day", 10, "Andi", "Budi aneh.", "offend", ["Budi"]),
            ch(1, "day", 20, "Budi", "Aku bukan Hitman.", "defend", ["Budi"]),
            ch(1, "day", 30, "Eka", "Dodi aneh.", "offend", ["Dodi"]),
            ch(1, "day", 40, "Dodi", "Citra bukan Hitman.", "defend", ["Citra"])]
    S.append(dict(nama="63 Alihkan tuduhan: hanya membela = 0",
                  cerita="Budi hanya membela diri, Dodi hanya membela orang lain.",
                  ingatan=buat_ingatan(al_0), view=buat_view(1, "day", 50),
                  harapan={"tabel": {"Budi": {"alihkan_tuduhan": 0.0}, "Dodi": {"alihkan_tuduhan": 0.0}}}))
    al_x = [ch(1, "day", 10, "Andi", "Budi aneh.", "offend", ["Budi"]),
            ch(1, "day", 15, "Budi", "Hmm."),
            ch(1, "day", 20, "Budi", "Citra yang aneh.", "offend", ["Citra"]),
            ch(1, "day", 30, "Eka", "Budi aneh juga.", "offend", ["Budi"]),
            ch(1, "day", 40, "Andi", "Dodi juga aneh.", "offend", ["Dodi"])]
    S.append(dict(nama="64 Alihkan tuduhan: tidak membalas tidak dihitung",
                  cerita="Chat tanpa relasi dilewati. Tuduhan Eka ke Budi tidak dibalas, jadi tidak masuk pembagi; Dodi tidak pernah membalas.",
                  ingatan=buat_ingatan(al_x), view=buat_view(1, "day", 50),
                  harapan={"tabel": {"Budi": {"alihkan_tuduhan": 1.0}, "Dodi": {"alihkan_tuduhan": 0.0}}}))
    al_rata = [ch(1, "day", 10, "Andi", "Budi aneh.", "offend", ["Budi"]),
               ch(1, "day", 15, "Budi", "Citra yang aneh.", "offend", ["Citra"]),
               ch(1, "day", 20, "Citra", "Budi aneh.", "offend", ["Budi"]),
               ch(1, "day", 25, "Budi", "Aku warga, justru Eka.", "defend", [("Budi", "defend"), ("Eka", "offend")]),
               ch(1, "day", 30, "Eka", "Budi aneh.", "offend", ["Budi"]),
               ch(1, "day", 35, "Budi", "Aku warga.", "defend", ["Budi"]),
               ch(1, "day", 40, "Andi", "Dodi aneh.", "offend", ["Dodi"]),
               ch(1, "day", 41, "Eka", "Dodi aneh juga.", "offend", ["Dodi"]),
               ch(1, "day", 45, "Dodi", "Citra yang aneh.", "offend", ["Citra"])]
    S.append(dict(nama="65 Alihkan tuduhan: jumlah nilai dibagi jumlah balasan",
                  cerita="Balasan Budi 1, 0,5, dan 0 menjadi 0,5. Dodi membalas dua tuduhan dengan satu chat, jadi dihitung sekali.",
                  ingatan=buat_ingatan(al_rata), view=buat_view(1, "day", 60),
                  harapan={"tabel": {"Budi": {"alihkan_tuduhan": 0.5}, "Dodi": {"alihkan_tuduhan": 1.0}}}))
    al_r = [ch(1, "day", 10, "Andi", "Budi aneh.", "offend", ["Budi"]),
            ch(1, "day", 20, "Budi", "Citra yang aneh.", "offend", ["Citra"]),
            ch(2, "day", 10, "Andi", "Dodi aneh.", "offend", ["Dodi"]),
            ch(2, "tribunal", 5, "Dodi", "Citra yang aneh.", "offend", ["Citra"])]
    S.append(dict(nama="66 Alihkan tuduhan: meluruh dan hanya fase yang sama",
                  cerita="Balasan Budi sudah lewat satu ronde. Tuduhan ke Dodi saat siang tidak dibalas di fase itu.",
                  ingatan=buat_ingatan(al_r, sampai=(2, "tribunal")), view=buat_view(2, "tribunal", 20),
                  harapan={"tabel": {"Budi": {"alihkan_tuduhan": 0.7}, "Dodi": {"alihkan_tuduhan": 0.0}}}))

    mb = [ch(2, "day", 10, "Andi", "Nara aneh.", "offend", ["Nara"]),
          ch(2, "day", 12, "Budi", "Nara aneh.", "offend", ["Nara"]),
          ch(2, "day", 14, "Budi", "Nara makin aneh.", "offend", ["Nara"]),
          ch(2, "day", 16, "Budi", "Vote Nara.", "offend", ["Nara"]),
          ch(2, "day", 18, "Dodi", "Nara aneh.", "offend", ["Nara"]),
          ch(3, "day", 10, "Andi", "Masih Nara.", "offend", ["Nara"]),
          ch(3, "day", 12, "Citra", "Nara lagi.", "offend", ["Nara"])]
    S.append(dict(nama="67 Menuduh orang baik: dua ronde berturut-turut",
                  cerita="Andi menuduh dua ronde. Budi melewati batas 1 di ronde lalu, jadi nilainya dipotong sebelum meluruh. "
                         "Citra vote lalu menuduh. Dodi hanya menuduh ronde lalu. Eka hanya vote ronde lalu.",
                  ingatan=buat_ingatan(mb, [(2, "Citra", "Nara"), (2, "Eka", "Nara")], sampai=(3, "day")), view=buat_view(3, "day", 20),
                  harapan={"tabel": {"Andi": {"menuduh_orang_baik": 0.85}, "Budi": {"menuduh_orang_baik": 0.7},
                                     "Citra": {"menuduh_orang_baik": 1.0}, "Dodi": {"menuduh_orang_baik": 0.35},
                                     "Eka": {"menuduh_orang_baik": 0.7}}}))
    pk = [ch(1, "day", 10, "Andi", "Aku Stalker, semalam aku peek Nara, dia Hitman.", "offend", ["Nara"])]
    S.append(dict(nama="68 Mengaku Peek bot lalu menyebutnya Hitman",
                  cerita="Bot warga tahu dirinya bukan Hitman, jadi Andi pasti bohong.",
                  ingatan=buat_ingatan(pk), view=buat_view(1, "day", 20),
                  harapan={"tabel": {"Andi": {"menuduh_orang_baik": 1.0, "klaim_role_bermasalah": 1.0}}}))
    S.append(dict(nama="69 Hitman tidak memakai bukti pasti baik",
                  cerita="Kalimat yang sama, bot Hitman: sudut pandang publik membaca Nara sebagai tertuduh Peek.",
                  ingatan=buat_ingatan(pk, peran="hitman"), view=buat_view(1, "day", 20, peran="hitman"),
                  harapan={"tabel": {"Andi": {"menuduh_orang_baik": 0.0}, "Nara": {"klaim_role_bermasalah": 0.8}}}))

    sp = [ch(1, "day", 10, "Andi", "Aku Spy, semalam aku guard."),
          ch(1, "day", 20, "Budi", "Aku Spy juga."),
          ch(1, "day", 30, "Citra", "Budi aneh.", "offend", ["Budi"])]
    S.append(dict(nama="70 Spy room 2 mengenali pengaku palsu",
                  cerita="Bot Spy tahu rekannya Budi. Andi mengaku Spy, jadi pasti bohong. Budi pasti baik, dan Citra menuduh orang baik.",
                  ingatan=buat_ingatan(sp, peran="spy"), view=buat_view(1, "day", 40, peran="spy", spy=2, rekan_spy=["Budi"]),
                  harapan={"tabel": {"Andi": {"klaim_role_bermasalah": 1.0}, "Budi": {"klaim_role_bermasalah": 0.0, "kecurigaan": 0.0},
                                     "Citra": {"menuduh_orang_baik": 0.5}},
                           "pengetahuan": {"pasti_orang_baik": {"Nara", "Budi"}}, "konteks": {"klaim_bentrok": []}}))
    S.append(dict(nama="71 Spy room 1 melihat pengaku Spy",
                  cerita="Andi mengaku Spy, padahal Spy-nya bot.",
                  ingatan=buat_ingatan(sp[:1], peran="spy"), view=buat_view(1, "day", 40, peran="spy"),
                  harapan={"tabel": {"Andi": {"klaim_role_bermasalah": 1.0}}}))
    pk_r = [ch(1, "day", 10, "Andi", "Aku Stalker, semalam aku peek Citra, dia Hitman.", "offend", ["Citra"]),
            ch(1, "day", 20, "Budi", "Aku Spy.")]
    S.append(dict(nama="72 Tuduhan Peek tidak meluruh, mengaku sendirian bukan bukti",
                  cerita="Dua ronde sesudah tuduhan Peek Andi, Citra tetap 0,8. Andi dan Budi yang mengaku sendirian tetap 0.",
                  ingatan=buat_ingatan(pk_r, sampai=(3, "day")), view=buat_view(3, "day", 20),
                  harapan={"tabel": {"Citra": {"klaim_role_bermasalah": 0.8}, "Andi": {"klaim_role_bermasalah": 0.0},
                                     "Budi": {"klaim_role_bermasalah": 0.0}}}))
    bt = [ch(1, "day", 10, "Andi", "Aku Stalker, semalam aku peek Citra, dia Hitman.", "offend", ["Citra"]),
          ch(1, "day", 20, "Budi", "Bohong, aku yang Stalker.", "offend", ["Andi"])]
    S.append(dict(nama="73 Pengaku bentrok: tuduhan Peek tidak dihitung",
                  cerita="Andi dan Budi sama-sama mengaku Stalker. Tuduhan Peek Andi ke Citra tidak dihitung.",
                  ingatan=buat_ingatan(bt), view=buat_view(1, "day", 30),
                  harapan={"tabel": {"Andi": {"klaim_role_bermasalah": 0.6}, "Budi": {"klaim_role_bermasalah": 0.6},
                                     "Citra": {"klaim_role_bermasalah": 0.0}},
                           "konteks": {"klaim_bentrok": ["Andi", "Budi"], "chat_membingungkan": 0.8}}))
    S.append(dict(nama="74 Stalker tahu kedua pengaku bohong",
                  cerita="Bot Stalker melihat bentrok yang sama, jadi tidak ada lagi yang perlu ditanyakan.",
                  ingatan=buat_ingatan(bt, peran="stalker"), view=buat_view(1, "day", 30, peran="stalker"),
                  harapan={"tabel": {"Andi": {"klaim_role_bermasalah": 1.0}, "Budi": {"klaim_role_bermasalah": 1.0},
                                     "Citra": {"klaim_role_bermasalah": 0.0}},
                           "konteks": {"klaim_bentrok": [], "chat_membingungkan": 0.0}}))

    sl = [ch(2, "day", 5, "Citra", "Dodi baik kok.", "defend", ["Dodi"]),
          ch(2, "day", 10, "Eka", "Aku Stalker, semalam aku peek Dodi, dia bukan Hitman.", "defend", ["Dodi"]),
          ch(2, "day", 12, "Eka", "Aku juga sudah peek Budi, dia bukan Hitman.", "defend", ["Budi"]),
          ch(2, "day", 20, "Andi", "Eka sudah cek, Dodi bukan Hitman.", "defend", ["Dodi"])]
    S.append(dict(nama="75 Klaim bersih terbukti salah",
                  cerita="Dodi dieksekusi dan diumumkan Hitman. Klaim Eka terbukti salah, jadi klaim bersihnya ke Budi batal. Citra membela lebih "
                         "dulu, sedangkan Andi hanya mengulang klaim Eka.",
                  ingatan=buat_ingatan(sl, eksekusi=[(2, "Dodi", True)], sampai=(3, "day")),
                  view=buat_view(3, "day", 20, mati=["Dodi"], hitman=2, hitman_tersisa=1),
                  harapan={"tabel": {"Eka": {"klaim_role_bermasalah": 0.8, "memihak_hitman": 0.8 * 0.9},
                                     "Budi": {"bersih_klaim": 0.0, "memihak_hitman": 0.0},
                                     "Citra": {"memihak_hitman": 0.8 * 0.9}, "Andi": {"memihak_hitman": 0.3 * 0.9}}}))
    S.append(dict(nama="76 Klaim bersih belum terbukti salah",
                  cerita="Kalimat yang sama tanpa eksekusi: klaim bersih tetap berlaku dan meluruh, belum ada yang memihak Hitman.",
                  ingatan=buat_ingatan(sl, sampai=(3, "day")), view=buat_view(3, "day", 20),
                  harapan={"tabel": {"Budi": {"bersih_klaim": 0.8 * 0.9}, "Eka": {"klaim_role_bermasalah": 0.0, "memihak_hitman": 0.0},
                                     "Citra": {"memihak_hitman": 0.0}}}))
    bh = [ch(2, "day", 5, "Budi", "Dodi bukan Hitman.", "defend", ["Dodi"])]
    S.append(dict(nama="77 Memihak Hitman menurut hasil Peek",
                  cerita="Stalker tahu Dodi Hitman dari Peek, jadi pembelaan Budi langsung bernilai penuh.",
                  ingatan=buat_ingatan(bh, sampai=(2, "day"), peran="stalker", intel=[(1, "Dodi", "hitman")]),
                  view=buat_view(2, "day", 20, peran="stalker", hitman=2, next_peek=3),
                  harapan={"tabel": {"Budi": {"memihak_hitman": 0.8, "jejak_kedua": 0.8, "bukti_total": 2 * 0.8}}}))
    S.append(dict(nama="78 Publik tidak memakai pengetahuan rekan",
                  cerita="Bot Hitman tahu Dodi rekannya, tetapi tabel publik tidak boleh membocorkannya.",
                  ingatan=buat_ingatan(bh, sampai=(2, "day"), peran="hitman"),
                  view=buat_view(2, "day", 20, peran="hitman", hitman=2, rekan=["Dodi"]),
                  harapan={"tabel": {"Budi": {"memihak_hitman": 0.0}}}))
    S.append(dict(nama="79 Memihak Hitman yang keluar",
                  cerita="Dodi keluar dan jumlah Hitman yang diumumkan turun, jadi terbukti Hitman walau bukan lewat eksekusi.",
                  ingatan=buat_ingatan(bh, sampai=(3, "day"), keluar=[(2, "Dodi", True)]),
                  view=buat_view(3, "day", 20, mati=["Dodi"], hitman=2, hitman_tersisa=1),
                  harapan={"tabel": {"Budi": {"memihak_hitman": 0.8 * 0.9}}}))
    S.append(dict(nama="80 Klaim Civilian bukan bentrok",
                  cerita="Tiga pemain mengaku Civilian. Klaim itu dikenali, tetapi Civilian bisa banyak.",
                  ingatan=buat_ingatan([ch(1, "day", 10, "Andi", "Aku cuma civilian."), ch(1, "day", 20, "Budi", "Aku civilian."),
                                        ch(1, "day", 30, "Citra", "Civilian nih aku.")]),
                  view=buat_view(1, "day", 40),
                  harapan={"tabel": {"Andi": {"klaim_role_bermasalah": 0.0}, "Budi": {"klaim_role_bermasalah": 0.0},
                                     "Citra": {"klaim_role_bermasalah": 0.0}}, "konteks": {"klaim_bentrok": []}}))

    # ---------------------------------------------------------------- Fitur Hitman final
    fh_chat = [ch(2, "day", 10, "Andi", "Nara aneh.", "offend", ["Nara"]),
               ch(2, "day", 20, "Citra", "Nara aneh.", "offend", ["Nara"]),
               ch(2, "day", 25, "Citra", "Budi juga aneh.", "offend", ["Budi"]),
               ch(3, "day", 10, "Andi", "Nara dan Citra sama-sama aneh.", "offend", ["Nara", "Citra"]),
               ch(3, "day", 20, "Budi", "Dodi aneh.", "offend", ["Dodi"])]
    S.append(dict(nama="81 Fitur Hitman: tuduhan ke tim dan jejak",
                  cerita="Andi menuduh dan vote bot, Budi menuduh dan vote rekan (bobot separuh), Citra menuduh dua orang di ronde lalu. "
                         "Eka korban Hostage dan Dodi rekan, jadi keduanya tidak masuk tabel.",
                  ingatan=buat_ingatan(fh_chat, [(2, "Andi", "Nara"), (2, "Budi", "Dodi")], sampai=(3, "day"), peran="hitman"),
                  view=buat_view(3, "day", 30, peran="hitman", hitman=2, rekan=["Dodi"], sandera={"Eka": 2}, korban_gag_tim=["Citra"]),
                  harapan={"fitur_hitman": {"Andi": {"menuduh_tim": 1.0, "ancaman_sekarang": 0.5, "jejak_tuduhan": 0.6},
                                            "Budi": {"menuduh_tim": 0.25 + 0.5 * 0.7, "ancaman_sekarang": 0.25, "jejak_tuduhan": 1.0},
                                            "Citra": {"menuduh_tim": 0.5 * 0.7, "ancaman_sekarang": 0.0, "jejak_tuduhan": 0.3}},
                           "bukan_fitur_hitman": ["Eka", "Dodi", "Nara"]}))
    S.append(dict(nama="82 Fitur Hitman: vote ronde ini dan klaim yang bicara",
                  cerita="Andi vote bot ronde ini (1), Budi vote rekan (0,5). Citra mengaku Stalker dan bicara di fase ini.",
                  ingatan=buat_ingatan([ch(2, "tribunal", 5, "Citra", "Aku Stalker.")], sampai=(2, "tribunal"), peran="hitman"),
                  view=buat_view(2, "tribunal", 20, peran="hitman", hitman=2, rekan=["Dodi"], suara={"Andi": "Nara", "Budi": "Dodi"}),
                  harapan={"fitur_hitman": {"Andi": {"ancaman_sekarang": 1.0, "menuduh_tim": 1.0}, "Budi": {"ancaman_sekarang": 0.5, "menuduh_tim": 0.5},
                                            "Citra": {"ancaman_sekarang": 0.5, "mengaku_role_penting": 1.0}}}))

    # ---------------------------------------------------------------- Konteks final
    S.append(dict(nama="83 Menyebut bot tanpa pertanyaan dijawab",
                  cerita="Budi menyebut bot dalam kalimat neutral yang bukan pertanyaan. Pemicu jawab sengaja tanpa pola pertanyaan.",
                  ingatan=buat_ingatan(pg_r1 + [ch(1, "day", 30, "Budi", "Nara tadi bilang gitu.")]), view=buat_view(1, "day", 40),
                  harapan={"chat": [("jawab", None)], "konteks": {"penanya": "Budi"}}))
    S.append(dict(nama="84 Menyebut bot dalam pembelaan bukan pertanyaan",
                  cerita="Budi membela bot. Kalimat itu bukan neutral, jadi bot tidak dianggap ditanya.",
                  ingatan=buat_ingatan(pg_r1 + [ch(1, "day", 30, "Budi", "Nara bukan Hitman, kan?", "defend", ["Nara"])]),
                  view=buat_view(1, "day", 40),
                  harapan={"chat_bukan": [("jawab", None)], "konteks": {"penanya": None}}))
    S.append(dict(nama="85 Sudah membela diri: pemilih lama tidak dihitung lagi",
                  cerita="Bot sudah membela diri di Tribunal ini, lalu tidak ada tuduhan baru. Suara Andi ke bot tidak memicu pembelaan lagi.",
                  ingatan=buat_ingatan(sampai=(2, "tribunal"), aksi_bot=[
                      {"ronde": 2, "fase": "tribunal", "waktu": jam(2, "tribunal", 5), "aksi": "bela_diri", "intent": "defend", "target": "Nara"}]),
                  view=buat_view(2, "tribunal", 10, suara={"Andi": "Nara"}),
                  harapan={"konteks": {"bot_dituduh_baru": []}}))

    # ---------------------------------------------------------------- Pengetahuan final
    S.append(dict(nama="86 Vote pasti melewati Hitman yang sudah mati",
                  cerita="Stalker pernah Peek Dodi dan Budi, keduanya Hitman. Dodi sudah dieksekusi, jadi vote pasti ke Budi.",
                  ingatan=buat_ingatan(sampai=(4, "tribunal"), peran="stalker", intel=[(1, "Dodi", "hitman"), (3, "Budi", "hitman")],
                                       eksekusi=[(2, "Dodi", True)]),
                  view=buat_view(4, "tribunal", 5, peran="stalker", hitman=2, hitman_tersisa=1, mati=["Dodi"], next_peek=5),
                  harapan={"vote": [("vote", "Budi")], "chat": [("tuduh", "Budi")], "jenis": "hasil_peek",
                           "pengetahuan": {"hitman_diketahui": ["Dodi", "Budi"]}}))

    # ---------------------------------------------------------------- Ide #31: hanya yang masih bisa bersuara
    sd = [ch(1, "day", 10, "Eka", "Budi aneh.", "offend", ["Budi"]),
          ch(1, "day", 20, "Andi", "Budi aneh juga.", "offend", ["Budi"])]
    S.append(dict(nama="87 Korban Hostage tidak menaikkan tekanan",
                  cerita="Eka menuduh Budi lalu diumumkan disandera. Tuduhannya tidak dihitung, korban keluar dari pembagi, dan tetap menjadi jejak.",
                  ingatan=buat_ingatan(sd, sampai=(2, "day")), view=buat_view(2, "day", 20, sandera={"Eka": 1}),
                  harapan={"tabel": {"Budi": {"tekanan": 0.7 / 3, "n_penuduh": 1, "penuduh_dibungkam": 0.9}}}))
    tb = [ch(2, "day", 10, "Citra", "Budi aneh.", "offend", ["Budi"]),
          ch(2, "day", 15, "Citra", "Dodi bukan Hitman.", "defend", ["Dodi"]),
          ch(2, "day", 20, "Andi", "Budi aneh juga.", "offend", ["Budi"])]
    S.append(dict(nama="88 Yang tersingkir tidak dihitung",
                  cerita="Citra menuduh dan vote Budi serta membela Dodi, lalu dieksekusi. Hanya tuduhan Andi yang tersisa.",
                  ingatan=buat_ingatan(tb, [(2, "Citra", "Budi")], [(2, "Citra")], sampai=(3, "day")), view=buat_view(3, "day", 20, mati=["Citra"]),
                  harapan={"tabel": {"Budi": {"tekanan": 0.7 / 3, "n_penuduh": 1}, "Dodi": {"dukungan": 0.0, "n_pembela": 0}}}))
    bs = [ch(1, "day", 10, "Eka", "Aku Stalker, semalam aku peek Dodi, dia bukan Hitman.", "defend", ["Dodi"])]
    S.append(dict(nama="89 Klaim bersih dari pengaku yang disandera",
                  cerita="Eka mengklaim Dodi bersih lalu disandera. Eka tidak lagi menjadi pembela, tetapi klaim bersihnya tetap berlaku.",
                  ingatan=buat_ingatan(bs, sampai=(2, "day")), view=buat_view(2, "day", 20, sandera={"Eka": 1}),
                  harapan={"tabel": {"Dodi": {"dukungan": 0.0, "n_pembela": 0, "bersih_klaim": 0.8 * 0.9}}}))

    # ---------------------------------------------------------------- Tindakan dan aksi tanpa sistem fuzzy
    nj = [ch(2, "day", 10, "Andi", "Nara aneh.", "offend", ["Nara"]),
          ch(2, "day", 20, "Budi", "Nara sama Eka mencurigakan.", "offend", ["Nara", "Eka"]),
          ch(2, "day", 30, "Citra", "Oke."), ch(2, "day", 40, "Dodi", "Lanjut.")]
    S.append(dict(nama="90 Hostage: ancaman dikurangi jejak",
                  cerita="Andi hanya menuduh bot (jejak 1), Budi menuduh bot dan Eka (jejak 0,5), Citra tidak menuduh. Ancaman Andi dan Budi "
                         "sama, tetapi jejak Budi lebih kecil, jadi Budi lebih aman disandera.",
                  ingatan=buat_ingatan(nj, sampai=(2, "night"), peran="hitman"), view=buat_view(2, "night", 10, peran="hitman"),
                  harapan={"aksi": [("hostage", "Budi")],
                           "fitur_hitman": {"Andi": {"jejak_tuduhan": 1.0}, "Budi": {"jejak_tuduhan": 0.5}, "Citra": {"jejak_tuduhan": 0.0}},
                           "nilai_aksi": {"Andi": 0.85 * 0.5, "Budi": 0.85 * 0.75, "Citra": 0.5}}))
    S.append(dict(nama="91 Hostage: tuduhan ronde lalu berjejak lebih kecil",
                  cerita="Andi hanya menuduh bot di ronde lalu: jejak 0,6 dan ancaman 0,655, jadi nilainya 0,655 × 0,7 = 0,459, masih di bawah 0,50.",
                  ingatan=buat_ingatan([ch(1, "day", 10, "Andi", "Nara aneh.", "offend", ["Nara"])], sampai=(2, "night"), peran="hitman"),
                  view=buat_view(2, "night", 10, peran="hitman"),
                  harapan={"aksi": [("hostage", seri_teratas(["Budi", "Citra", "Dodi", "Eka"], 2))], "fitur_hitman": {"Andi": {"jejak_tuduhan": 0.6}}, "nilai_aksi": {"Andi": 0.4588, "Budi": 0.5}}))
    sg = [ch(1, "day", 10, "Eka", "Aku Stalker.")]
    S.append(dict(nama="92 Hostage: pengaku Stalker yang tidak menuduh paling diincar",
                  cerita="Eka mengaku Stalker tanpa menuduh siapa pun: tidak ada jejak, jadi ancaman 0,85 tetap utuh.",
                  ingatan=buat_ingatan(sg, sampai=(1, "night"), peran="hitman"), view=buat_view(1, "night", 10, peran="hitman"),
                  harapan={"aksi": [("hostage", "Eka")], "nilai_aksi": {"Eka": 0.85, "Andi": 0.5}}))
    S.append(dict(nama="93 Hostage: gagal semalam tidak meninggalkan target",
                  cerita="Hostage ke Eka gagal semalam. Eka tetap bernilai tertinggi.",
                  ingatan=buat_ingatan(sg, sampai=(2, "night"), peran="hitman"),
                  view=buat_view(2, "night", 10, peran="hitman", hasil_sandera=[{"ronde": 1, "pemain": "Eka", "berhasil": False}]),
                  harapan={"aksi": [("hostage", "Eka")], "pengetahuan": {"gagal_sandera": {"Eka": 1}}}))
    S.append(dict(nama="94 Hostage: gagal dua kali meninggalkan target teratas",
                  cerita="Hostage ke Eka sudah gagal dua kali, jadi Hitman pindah walau nilai Eka tertinggi.",
                  ingatan=buat_ingatan(sg, sampai=(3, "night"), peran="hitman"),
                  view=buat_view(3, "night", 10, peran="hitman", spy=2,
                                 hasil_sandera=[{"ronde": r, "pemain": "Eka", "berhasil": False} for r in (1, 2)]),
                  harapan={"aksi": [("hostage", seri_teratas(["Andi", "Budi", "Citra", "Dodi"], 3))], "aksi_bukan": ["Eka"], "pengetahuan": {"gagal_sandera": {"Eka": 2}}}))
    S.append(dict(nama="95 Gag: ancaman tinggi tidak menunggu sore",
                  cerita="Citra baru saja menuduh bot di awal siang. Input kedua Gag kini ancaman, bukan waktu, jadi nilainya sudah 85.",
                  ingatan=buat_ingatan([ch(1, "day", 10, "Citra", "Nara aneh.", "offend", ["Nara"])], sampai=(1, "day"), peran="hitman"),
                  view=buat_view(1, "day", 15, peran="hitman"),
                  harapan={"aksi": [("gag", "Citra")], "nilai_aksi": {"Citra": 85.0}}))
    S.append(dict(nama="96 Guard: nilai sama dengan terancam, seri menurut nama",
                  cerita="Belum ada chat, jadi terancam semua pemain 0 dan Guard jatuh ke nama pertama. Bot sendiri hanya cadangan.",
                  ingatan=buat_ingatan(sampai=(1, "night"), peran="spy"), view=buat_view(1, "night", 10, peran="spy"),
                  harapan={"aksi": [("guard", "Andi")], "nilai_aksi": {"Andi": 0.0, "Eka": 0.0}}))
    S.append(dict(nama="97 Bela diri mengalahkan tuduh bernilai tinggi",
                  cerita="Dodi tersangka kuat, tetapi Andi baru menuduh bot. Tuduhan selalu dibalas lebih dulu, tanpa nilai.",
                  ingatan=buat_ingatan(gag_r2 + gag_r3 + [ch(3, "day", 35, "Andi", "Nara dari tadi aneh.", "offend", ["Nara"])], gag_v2,
                                       sampai=(3, "day")),
                  view=buat_view(3, "day", 40),
                  harapan={"tersangka": "Dodi", "chat": [("bela_diri", "Dodi")], "jenis": "tunjuk_orang", "chat_tanpa_nilai": True,
                           "relasi_tambahan": [{"pemain": "Nara", "relasi": "defend"}]}))
    S.append(dict(nama="98 Hitman: bela diri mengalahkan tuduh kambing hitam",
                  cerita="Warga menekan Budi, tetapi Eka baru menuduh bot Hitman. Bot membalas lebih dulu, tanpa nilai.",
                  ingatan=buat_ingatan(ke_ronde_2(kh_r1) + [ch(2, "day", 75, "Eka", "Nara juga aneh.", "offend", ["Nara"])],
                                       sampai=(2, "day"), peran="hitman"),
                  view=buat_view(2, "day", 80, peran="hitman"),
                  harapan={"chat": [("bela_diri", "Nara")], "chat_tanpa_nilai": True}))
    # ---------------------------------------------------------------- Fase 5: daftar tindakan
    aj = [ch(3, "day", d, p, "Oke.") for d, p in ((5, "Andi"), (10, "Budi"), (15, "Citra"), (20, "Eka"))]
    aj_v = [(2, "Dodi", "Nara")]
    aj_a = [{"ronde": 3, "fase": "day", "waktu": jam(3, "day", 5), "aksi": "tuduh", "jenis": "alasan_curiga", "intent": "offend", "target": "Dodi"}]
    S.append(dict(nama="99 Pemain diam menjadi jenis tanya_info",
                  cerita="Dodi belum bicara di ronde ini dan sudah dituduh bot, sedangkan obrolan ramai. Sistem ajak_bicara menilai jenis ini.",
                  ingatan=buat_ingatan(aj, aj_v, sampai=(3, "day"), aksi_bot=aj_a), view=buat_view(3, "day", 50),
                  harapan={"chat": [("tanya_info", "Dodi")], "jenis": "pemain_diam"}))
    S.append(dict(nama="100 Klaim palsu menjadi jenis tuduh",
                  cerita="Suara Tribunal mengarah ke bot Hitman yang sudah dicurigai dan sudah membela diri, jadi klaim Peek palsu keluar sebagai tuduh.",
                  ingatan=buat_ingatan([ch(2, "day", 10, "Andi", "Aku Stalker, semalam aku peek Nara, dia Hitman.", "offend", ["Nara"])],
                                       sampai=(2, "tribunal"), peran="hitman", aksi_bot=[
                                           {"ronde": 2, "fase": "tribunal", "waktu": jam(2, "tribunal", 2), "aksi": "bela_diri", "intent": "defend", "target": "Nara"}]),
                  view=buat_view(2, "tribunal", 30, peran="hitman", suara={"Andi": "Nara", "Budi": "Nara", "Citra": "Nara"}),
                  harapan={"chat": [("tuduh", "Andi")], "jenis": "klaim_peek", "role_diakui": "stalker"}))
    # ---------------------------------------------------------------- Fase 5: aturan bersama chat
    def aksi_chat(ronde, fase, daftar):
        return [{"ronde": ronde, "fase": fase, "waktu": jam(ronde, fase, d), "aksi": a, "intent": INTENT_AKSI[a], "target": t, "pemicu": p}
                for d, a, t, p in daftar]

    tuduh_andi = ch(3, "day", 42, "Andi", "Nara aneh.", "offend", ["Nara"])
    S.append(dict(nama="101 Membela diri walau jatah inisiatif habis",
                  cerita="Tiga chat inisiatif sudah terpakai, lalu Andi menuduh bot.",
                  ingatan=buat_ingatan([tuduh_andi], sampai=(3, "day"),
                                       aksi_bot=aksi_chat(3, "day", [(5, "tanya_info", None, None), (20, "tanya_info", "Budi", None), (35, "tanya_info", "Dodi", None)])),
                  view=buat_view(3, "day", 45),
                  harapan={"chat": [("bela_diri", None)], "chat_tanpa_nilai": True, "pemicu": ["Andi"]}))
    S.append(dict(nama="102 Jatah inisiatif habis tanpa pemicu menunggu",
                  cerita="Tiga chat inisiatif sudah terpakai dan tidak ada pemicu.",
                  ingatan=buat_ingatan(sampai=(3, "day"), aksi_bot=aksi_chat(3, "day", [(5, "tanya_info", None, None), (20, "tanya_info", "Budi", None), (35, "tanya_info", "Dodi", None)])),
                  view=buat_view(3, "day", 70), harapan={"chat": [("tunggu", None)]}))
    jeda_a = aksi_chat(3, "day", [(40, "bela_diri", "Nara", ["Andi"])])
    S.append(dict(nama="103 Penuduh sama menunggu jeda",
                  cerita="Bot baru membalas Andi, lalu Andi menuduh lagi. Jeda siang 14,4 detik belum lewat.",
                  ingatan=buat_ingatan([ch(3, "day", 45, "Andi", "Nara makin aneh.", "offend", ["Nara"])], sampai=(3, "day"), aksi_bot=jeda_a),
                  view=buat_view(3, "day", 50), harapan={"chat": [("tunggu", None)], "konteks": {"bot_dituduh_baru": ["Andi"]}}))
    S.append(dict(nama="104 Penuduh sama dibalas sesudah jeda",
                  cerita="Situasi yang sama, tetapi jeda sudah lewat.",
                  ingatan=buat_ingatan([ch(3, "day", 45, "Andi", "Nara makin aneh.", "offend", ["Nara"])], sampai=(3, "day"), aksi_bot=jeda_a),
                  view=buat_view(3, "day", 60), harapan={"chat": [("bela_diri", None)], "pemicu": ["Andi"]}))
    S.append(dict(nama="105 Penuduh berbeda langsung dibalas",
                  cerita="Bot baru membalas Andi, lalu Budi dan Andi menuduh. Masih jeda, jadi hanya Budi yang menjadi pemicu.",
                  ingatan=buat_ingatan([ch(3, "day", 44, "Andi", "Nara makin aneh.", "offend", ["Nara"]), ch(3, "day", 45, "Budi", "Nara aneh.", "offend", ["Nara"])],
                                       sampai=(3, "day"), aksi_bot=jeda_a),
                  view=buat_view(3, "day", 50), harapan={"chat": [("bela_diri", None)], "pemicu": ["Budi"]}))
    for nomor, fase, atap, detik in (("106", "day", 8, 100), ("107", "tribunal", 5, 40)):
        penuh = aksi_chat(3, fase, [(i, "bela_diri", "Nara", ["Andi"]) for i in range(1, atap + 1)])
        S.append(dict(nama=f"{nomor} Atap reaktif {fase} {atap}",
                      cerita="Atap balasan fase ini sudah habis, jadi tuduhan baru tidak lagi dibalas.",
                      ingatan=buat_ingatan([ch(3, fase, detik - 2, "Budi", "Nara aneh.", "offend", ["Nara"])], sampai=(3, fase), aksi_bot=penuh),
                      view=buat_view(3, fase, detik), harapan={"chat_bukan": [("bela_diri", None), ("jawab", None)], "konteks": {"bot_dituduh_baru": ["Budi"]}}))
        kurang = aksi_chat(3, fase, [(i, "bela_diri", "Nara", ["Andi"]) for i in range(1, atap)])
        S.append(dict(nama=f"{nomor}b Di bawah atap reaktif {fase} masih membalas",
                      cerita="Satu balasan lagi masih boleh.",
                      ingatan=buat_ingatan([ch(3, fase, detik - 2, "Budi", "Nara aneh.", "offend", ["Nara"])], sampai=(3, fase), aksi_bot=kurang),
                      view=buat_view(3, fase, detik), harapan={"chat": [("bela_diri", None)]}))
    S.append(dict(nama="108 Hasil Peek memakai jatah inisiatif",
                  cerita="Stalker sudah memakai 2 chat inisiatif Tribunal, jadi chat_pasti tidak mengirim lagi. Vote pasti tetap jalan.",
                  ingatan=buat_ingatan(sampai=(2, "tribunal"), peran="stalker", intel=[(1, "Dodi", "hitman")],
                                       aksi_bot=aksi_chat(2, "tribunal", [(2, "tanya_info", None, None), (8, "tanya_info", "Budi", None)])),
                  view=buat_view(2, "tribunal", 30, peran="stalker", next_peek=3),
                  harapan={"chat_bukan": [("tuduh", "Dodi")], "vote": [("vote", "Dodi")]}))
    S.append(dict(nama="109 Hasil Peek tidak terhalang balasan",
                  cerita="Stalker sudah membalas dua kali di Tribunal. Balasan memakai atap reaktif, jadi jatah inisiatif masih utuh.",
                  ingatan=buat_ingatan(sampai=(2, "tribunal"), peran="stalker", intel=[(1, "Dodi", "hitman")],
                                       aksi_bot=aksi_chat(2, "tribunal", [(2, "jawab", None, ["Andi"]), (8, "jawab", None, ["Budi"])])),
                  view=buat_view(2, "tribunal", 30, peran="stalker", next_peek=3),
                  harapan={"chat": [("tuduh", "Dodi")], "jenis": "hasil_peek", "role_diakui": "stalker", "bukti_klaim": "semalam peek Dodi, dia Hitman"}))
    # ---------------------------------------------------------------- Fase 5: jenis bela_diri, per role
    palsu_r1 = [(20, "Citra", "Aku Stalker, semalam aku peek Nara, dia Hitman."), (25, "Andi", "Nara aneh."), (30, "Budi", "Nara aneh.")]
    PERAN_SEMUA = ("civilian", "spy", "stalker", "hitman")
    awal_r1 = [ch(1, "day", 25, "Andi", "Nara aneh.", "offend", ["Nara"])]
    tiga_r3 = [ch(3, "day", d, p, "Nara aneh.", "offend", ["Nara"]) for d, p in ((20, "Andi"), (25, "Budi"), (30, "Citra"))]
    for i, peran in enumerate(PERAN_SEMUA):
        S.append(dict(nama=f"11{i} Bela diri terlalu awal: {peran}", cerita="Ronde 1, satu penuduh, belum terdesak.",
                      ingatan=buat_ingatan(awal_r1, sampai=(1, "day"), peran=peran), view=buat_view(1, "day", 30, peran=peran),
                      harapan={"chat": [("bela_diri", "Nara")], "jenis": "terlalu_awal", "pemicu": ["Andi"], "chat_tanpa_nilai": True}))
        S.append(dict(nama=f"11{i}b Buka role saat terdesak: {peran}", cerita="Tiga penuduh, tekanan tinggi, dan tidak ada malam yang bisa dijadikan bukti.",
                      ingatan=buat_ingatan(tiga_r3, sampai=(3, "day"), peran=peran), view=buat_view(3, "day", 35, peran=peran),
                      harapan={"chat": [("bela_diri", "Nara")], "jenis": "buka_role",
                               "role_diakui": {"hitman": "civilian"}.get(peran, peran), "bukti_klaim": None}))
    S.append(dict(nama="114 Spy membuka role dengan bukti Guard", cerita="Spy terdesak dan semalam menjaga Budi. Budi saksi, bukan target.",
                  ingatan=buat_ingatan(tiga_r3, sampai=(3, "day"), peran="spy"), view=buat_view(3, "day", 35, peran="spy", last_guard="Budi"),
                  harapan={"chat": [("bela_diri", "Nara")], "jenis": "role_bukti_aksi", "role_diakui": "spy", "bukti_klaim": "semalam jaga Budi", "relasi_tambahan": []}))
    S.append(dict(nama="115 Stalker membuka role dengan hasil Peek", cerita="Stalker terdesak dan pernah Peek Budi yang bersih. Hasil itu ikut membela Budi.",
                  ingatan=buat_ingatan(tiga_r3, sampai=(3, "day"), peran="stalker", intel=[(2, "Budi", "civilian")]),
                  view=buat_view(3, "day", 35, peran="stalker", next_peek=4),
                  harapan={"chat": [("bela_diri", "Nara")], "jenis": "role_bukti_aksi", "role_diakui": "stalker",
                           "bukti_klaim": "semalam peek Budi, dia bukan Hitman", "relasi_tambahan": [{"pemain": "Budi", "relasi": "defend"}]}))
    S.append(dict(nama="115b Hasil Peek lama tidak disebut semalam", cerita="Peek Budi dilakukan dua malam lalu, dan malam tadi Stalker tidak bisa Peek.",
                  ingatan=buat_ingatan(tiga_r3, sampai=(3, "day"), peran="stalker", intel=[(1, "Budi", "civilian")]),
                  view=buat_view(3, "day", 35, peran="stalker", next_peek=4),
                  harapan={"chat": [("bela_diri", "Nara")], "jenis": "role_bukti_aksi", "bukti_klaim": "di malam ronde 1 peek Budi, dia bukan Hitman"}))
    palsu = [ch(3, "day", 20, "Citra", "Aku Stalker, semalam aku peek Nara, dia Hitman.", "offend", ["Nara"]),
             ch(3, "day", 25, "Andi", "Nara aneh.", "offend", ["Nara"]), ch(3, "day", 30, "Budi", "Nara aneh.", "offend", ["Nara"])]
    S.append(dict(nama="116 Hitman berisiko tinggi memakai Spy palsu", cerita="Risiko tinggi, jadi Guard palsu ke warga dengan kecurigaan publik terendah, seri menurut nama.",
                  ingatan=buat_ingatan(palsu, sampai=(3, "day"), peran="hitman"), view=buat_view(3, "day", 35, peran="hitman"),
                  harapan={"chat": [("bela_diri", "Nara")], "jenis": "role_bukti_aksi", "role_diakui": "spy", "bukti_klaim": "semalam jaga Andi"}))
    S.append(dict(nama="117 Hitman ronde 1 tidak mengarang Guard", cerita="Belum ada malam sebelum ronde 1, jadi Spy palsu tanpa bukti Guard.",
                  ingatan=buat_ingatan([ch(1, "day", d, p, t, "offend", ["Nara"]) for d, p, t in palsu_r1], sampai=(1, "day"), peran="hitman"),
                  view=buat_view(1, "day", 35, peran="hitman"),
                  harapan={"chat": [("bela_diri", "Nara")], "jenis": "buka_role", "role_diakui": "spy", "bukti_klaim": None}))
    dibuka = [{"ronde": 2, "fase": "day", "waktu": jam(2, "day", 5), "aksi": "bela_diri", "intent": "defend", "target": "Nara", "role_diakui": "civilian"}]
    S.append(dict(nama="118 Role hanya dibuka sekali", cerita="Bot sudah pernah membuka role, lalu terdesak lagi. Penuduh ikut dicurigai, jadi bot menunjuk penuduh.",
                  ingatan=buat_ingatan(tiga_r3, sampai=(3, "day"), aksi_bot=dibuka), view=buat_view(3, "day", 35),
                  harapan={"chat": [("bela_diri", None)], "jenis": "tunjuk_orang", "role_diakui": None}))
    klaim_andi = ch(3, "day", 10, "Eka", "Aku Stalker, semalam aku peek Andi, dia bukan Hitman.", "defend", ["Andi"])
    tuduh_r3 = ch(3, "day", 30, "Andi", "Nara aneh.", "offend", ["Nara"])
    for i, (peran, chats, opsi) in enumerate((("civilian", [klaim_andi, tuduh_r3], {}), ("spy", [klaim_andi, tuduh_r3], {}),
                                              ("stalker", [tuduh_r3], {"intel": [(2, "Andi", "civilian")]}), ("hitman", [tuduh_r3], {}))):
        S.append(dict(nama=f"12{i} Bela diri tanpa bukti: {peran}", cerita="Satu penuduh di ronde 3 yang tidak layak dituduh balik.",
                      ingatan=buat_ingatan(chats, sampai=(3, "day"), peran=peran, **opsi), view=buat_view(3, "day", 40, peran=peran, next_peek=4),
                      harapan={"chat": [("bela_diri", "Nara")], "jenis": "tanpa_bukti"}))
        S.append(dict(nama=f"12{i}b Bahaya salah vote: {peran}", cerita="Warga kritis, role sudah dibuka, dan tidak ada yang layak ditunjuk.",
                      ingatan=buat_ingatan(chats, sampai=(3, "day"), peran=peran, aksi_bot=dibuka, **opsi),
                      view=buat_view(3, "day", 40, peran=peran, next_peek=4, mati=["Dodi"], sandera={"Budi": 2}),
                      harapan={"chat": [("bela_diri", "Nara")], "jenis": "bahaya_salah_vote", "warga_terdesak_min": 0.75}))
    tunjuk = gag_r2 + gag_r3 + [ch(3, "day", 35, "Andi", "Nara dari tadi aneh.", "offend", ["Nara"])]
    for i, peran in enumerate(("spy", "stalker")):
        S.append(dict(nama=f"13{i} Tunjuk orang lain: {peran}", cerita="Dodi tersangka kuat, dan Andi baru menuduh bot.",
                      ingatan=buat_ingatan(tunjuk, gag_v2, sampai=(3, "day"), peran=peran), view=buat_view(3, "day", 40, peran=peran, next_peek=4),
                      harapan={"chat": [("bela_diri", "Dodi")], "jenis": "tunjuk_orang", "relasi_tambahan": [{"pemain": "Nara", "relasi": "defend"}]}))
    S.append(dict(nama="132 Hitman menunjuk kambing hitam", cerita="Citra mengaku Peek Budi sebagai Hitman, jadi Budi kambing hitam. Eka baru menuduh bot.",
                  ingatan=buat_ingatan([ch(3, "day", 10, "Citra", "Aku Stalker, semalam aku peek Budi, dia Hitman.", "offend", ["Budi"]), tuduh_r3], sampai=(3, "day"), peran="hitman"),
                  view=buat_view(3, "day", 40, peran="hitman"),
                  harapan={"chat": [("bela_diri", "Budi")], "jenis": "tunjuk_orang", "relasi_tambahan": [{"pemain": "Nara", "relasi": "defend"}]}))
    S.append(dict(nama="133 Tunjuk orang saat hampir kalah", cerita="Warga kritis dan role sudah dibuka, jadi tunjuk orang ditambah persuade bahaya salah vote.",
                  ingatan=buat_ingatan([c for c in tunjuk if c["pengirim"] != "Eka"], [v for v in gag_v2 if "Eka" not in v], sampai=(3, "day"), aksi_bot=dibuka),
                  view=buat_view(3, "day", 40, mati=["Eka"], sandera={"Budi": 2}),
                  harapan={"chat": [("bela_diri", None)], "chat_bukan": [("bela_diri", "Nara")], "jenis": "tunjuk_orang_bahaya", "warga_terdesak_min": 0.75}))
    # ---------------------------------------------------------------- Fase 5: paket jawab, per role
    tanya_budi = [ch_nama(2, "day", 30, "Citra", "Nara, menurutmu Budi gimana?")]
    for i, peran in enumerate(PERAN_SEMUA):
        S.append(dict(nama=f"14{i} Jawab membawa paket: {peran}", cerita="Citra bertanya tentang Budi. Belum ada tersangka, jadi kondisi ragu.",
                      ingatan=buat_ingatan(tanya_budi, sampai=(2, "day"), peran=peran), view=buat_view(2, "day", 40, peran=peran, next_peek=3),
                      harapan={"chat": [("jawab", None)], "chat_tanpa_nilai": True, "jenis": None, "pemicu": ["Citra"],
                               "paket": {"pertanyaan": "Nara, menurutmu Budi gimana?", "penanya": "Citra", "kondisi": "ragu", "tersangka": None,
                                         "pendapat_pemain": {"Budi": {"sikap": "percaya", "alasan": "Belum ada bukti kuat kalau Budi Hitman."}},
                                         "tindakan_sebelumnya": [], "jawaban_role": "aku orang baik", "chat_saya_ronde_ini": 0}}))
    bohong = [ch(2, "day", 10, "Eka", "Aku Stalker, semalam aku peek Dodi, dia bukan Hitman.", "defend", ["Dodi"])] + tanya_budi
    vote_peek = [{"ronde": 1, "target": "Andi", "alasan": ["Andi mengaku peek Citra sebagai Hitman."], "dinilai_ulang": False}]
    S.append(dict(nama="144 Paket Stalker tertutup tanpa kata Peek",
                  cerita="Stalker belum membuka role, pernah Peek Budi, dan alasan vote lamanya menyebut peek. Sumber itu tidak boleh sampai ke NLG.",
                  ingatan=buat_ingatan(bohong, sampai=(2, "day"), peran="stalker", intel=[(1, "Budi", "civilian")], vote_bot=vote_peek),
                  view=buat_view(2, "day", 40, peran="stalker", next_peek=3),
                  harapan={"chat": [("jawab", None)], "paket_bukan": ["peek"],
                           "paket": {"pendapat_pemain": {"Budi": {"sikap": "percaya", "alasan": "Aku yakin Budi bukan Hitman."}},
                                     "tindakan_sebelumnya": [{"tindakan": "vote", "ronde": 1, "target": "Andi", "alasan": []}]}}))
    S.append(dict(nama="145 Paket Stalker terbuka boleh menyebut Peek",
                  cerita="Role Stalker sudah dibuka, jadi alasan dengan sumber Peek boleh dikirim.",
                  ingatan=buat_ingatan(bohong, sampai=(2, "day"), peran="stalker", intel=[(1, "Budi", "civilian")], vote_bot=vote_peek,
                                       aksi_bot=[{"ronde": 1, "fase": "day", "waktu": jam(1, "day", 5), "aksi": "bela_diri", "intent": "defend", "target": "Nara", "role_diakui": "stalker"}]),
                  view=buat_view(2, "day", 40, peran="stalker", next_peek=3),
                  harapan={"chat": [("jawab", None)],
                           "paket": {"tindakan_sebelumnya": [{"tindakan": "vote", "ronde": 1, "target": "Andi", "alasan": ["Andi mengaku peek Citra sebagai Hitman."]}]}}))
    S.append(dict(nama="146 Alasan vote pasti tidak menyebut Peek", cerita="Skenario 16: alasan vote masuk tindakan_sebelumnya, jadi tidak boleh menyebut sumbernya.",
                  ingatan=buat_ingatan(st_r2, sampai=(2, "tribunal"), peran="stalker", intel=[(1, "Dodi", "hitman")]),
                  view=buat_view(2, "tribunal", 5, peran="stalker", next_peek=3),
                  harapan={"vote": [("vote", "Dodi")], "alasan_bukan": ["Hasil Peek"]}))
    S.append(dict(nama="147 Hitman: rekan selalu dipercaya di paket",
                  cerita="Citra bertanya tentang Dodi, rekan bot. Hitman memakai tabel publik, dan rekan selalu percaya.",
                  ingatan=buat_ingatan([ch_nama(2, "day", 30, "Citra", "Nara, menurutmu Dodi gimana?")], sampai=(2, "day"), peran="hitman"),
                  view=buat_view(2, "day", 40, peran="hitman", hitman=2, rekan=["Dodi"]),
                  harapan={"chat": [("jawab", None)], "paket": {"pendapat_pemain": {"Dodi": {"sikap": "percaya", "alasan": "Aku yakin Dodi bukan Hitman."}}}}))
    S.append(dict(nama="148 Paket menyebut tersangka teratas dan kondisi",
                  cerita="Skenario 52: Budi tersangka teratas, jadi paket membawa nama dan alasannya, dan niat rencana offend.",
                  ingatan=buat_ingatan(san_r2 + san_r3 + [tanya_05], san_v2, sampai=(3, "day")),
                  view=buat_view(3, "day", 70, sandera={"Eka": 2}),
                  harapan={"chat": [("jawab", "Budi")], "paket": {"kondisi": "yakin", "penanya": "Citra"}}))
    # ---------------------------------------------------------------- Fase 5: jenis tuduh
    S.append(dict(nama="149 Warga tidak menuduh dengan bukti tekanan saja",
                  cerita="Empat suara ke Dodi, jadi kecurigaannya 0,50, tetapi alasannya hanya banyak yang menuduh.",
                  ingatan=buat_ingatan(sampai=(3, "tribunal")),
                  view=buat_view(3, "tribunal", 20, suara={"Andi": "Dodi", "Budi": "Dodi", "Citra": "Dodi", "Eka": "Dodi"}),
                  harapan={"tersangka": "Dodi", "chat_bukan": [("tuduh", "Dodi")], "tabel": {"Dodi": {"kecurigaan": 0.5}}}))
    for nomor, peran in (("150", "spy"), ("151", "stalker")):
        S.append(dict(nama=f"{nomor} Tuduh dengan alasan: {peran}", cerita="Skenario 03 untuk role lain. Citra kemungkinan di-Gag setelah menuduh Dodi.",
                      ingatan=buat_ingatan(gag_r2 + gag_r3, gag_v2, sampai=(3, "day"), peran=peran),
                      view=buat_view(3, "day", 40, peran=peran, next_peek=4),
                      harapan={"chat": [("tuduh", "Dodi")], "jenis": "alasan_curiga"}))
    bela_h = [{"ronde": 3, "fase": "day", "waktu": jam(3, "day", 15), "aksi": "bela_diri", "intent": "defend", "target": "Nara"}]
    peek_h = [ch(3, "day", 10, "Andi", "Aku Stalker, semalam aku peek Nara, dia Hitman.", "offend", ["Nara"])]
    S.append(dict(nama="152 Hitman menyerang korban Gag tanpa menyebut Gag",
                  cerita="Citra di-Gag tim, dan Hitman sudah membalas tuduhan Andi. Serang korban Gag didahulukan.",
                  ingatan=buat_ingatan(peek_h, sampai=(3, "day"), peran="hitman", aksi_bot=bela_h),
                  view=buat_view(3, "day", 40, peran="hitman", korban_gag_tim=["Citra"], next_gag=5),
                  harapan={"chat": [("tuduh", "Citra")], "jenis": "serang_korban_gag", "alasan_bukan": ["Gag", "gag"], "pesan_bukan": ["gag"]}))
    S.append(dict(nama="153 Hitman balik menuduh penuduh",
                  cerita="Hitman sudah dicurigai, dan tuduhan Andi sudah lewat balasan pertama. Balik tuduh membawa pembelaan diri.",
                  ingatan=buat_ingatan(peek_h, sampai=(3, "day"), peran="hitman", aksi_bot=bela_h),
                  view=buat_view(3, "day", 40, peran="hitman", next_gag=5),
                  harapan={"chat": [("tuduh", "Andi")], "jenis": "balik_tuduh", "relasi_tambahan": [{"pemain": "Nara", "relasi": "defend"}]}))
    S.append(dict(nama="154 Hitman memelintir bukti publik",
                  cerita="Citra mengaku Peek Budi sebagai Hitman, sedangkan bot Hitman belum dicurigai.",
                  ingatan=buat_ingatan([ch(3, "day", 10, "Citra", "Aku Stalker, semalam aku peek Budi, dia Hitman.", "offend", ["Budi"])], sampai=(3, "day"), peran="hitman"),
                  view=buat_view(3, "day", 40, peran="hitman", next_gag=5),
                  harapan={"chat": [("tuduh", "Budi")], "jenis": "pelintir_bukti"}))
    S.append(dict(nama="155 Hitman belum dicurigai tidak balik menuduh",
                  cerita="Andi menuduh di ronde lalu, tetapi risiko Hitman masih rendah.",
                  ingatan=buat_ingatan([ch(2, "day", 10, "Andi", "Nara aneh.", "offend", ["Nara"])], sampai=(3, "day"), peran="hitman"),
                  view=buat_view(3, "day", 40, peran="hitman", next_gag=5),
                  harapan={"jenis_bukan": ["balik_tuduh"], "chat_bukan": [("tuduh", "Andi")]}))
    suara_h = {"Andi": "Nara", "Budi": "Nara", "Citra": "Nara"}
    peek_tribunal = [ch(2, "day", 10, "Andi", "Aku Stalker, semalam aku peek Nara, dia Hitman.", "offend", ["Nara"])]
    bela_t = {"ronde": 2, "fase": "tribunal", "waktu": jam(2, "tribunal", 2), "aksi": "bela_diri", "intent": "defend", "target": "Nara"}
    S.append(dict(nama="156 Klaim Peek palsu hanya sekali per game",
                  cerita="Situasi skenario 100, tetapi bot sudah pernah mengaku Peek.",
                  ingatan=buat_ingatan(peek_tribunal, sampai=(2, "tribunal"), peran="hitman", aksi_bot=[
                      bela_t, {"ronde": 1, "fase": "day", "waktu": jam(1, "day", 5), "aksi": "tuduh", "jenis": "klaim_peek", "intent": "offend", "target": "Eka", "role_diakui": "stalker"}]),
                  view=buat_view(2, "tribunal", 30, peran="hitman", suara=suara_h),
                  harapan={"jenis_bukan": ["klaim_peek"]}))
    S.append(dict(nama="157 Klaim Peek palsu tetap boleh sesudah mengaku role lain",
                  cerita="Hitman sudah mengaku Civilian. Tabel tuduh hanya membatasi klaim Peek palsu sekali per game, sedangkan syarat role sekali per game milik bela_diri.",
                  ingatan=buat_ingatan(peek_tribunal, sampai=(2, "tribunal"), peran="hitman", aksi_bot=[
                      dict(bela_t, role_diakui="civilian")]),
                  view=buat_view(2, "tribunal", 30, peran="hitman", suara=suara_h),
                  harapan={"chat": [("tuduh", "Andi")], "jenis": "klaim_peek", "role_diakui": "stalker"}))
    S.append(dict(nama="158 Anti-gema melewati korban Gag",
                  cerita="Dua pemain sudah menuduh Citra di fase ini, jadi Hitman tidak menjadi suara ketiga dan beralih ke jenis berikutnya.",
                  ingatan=buat_ingatan(peek_h + [ch(3, "day", d, p, "Citra aneh.", "offend", ["Citra"]) for d, p in ((12, "Budi"), (13, "Dodi"))],
                                       sampai=(3, "day"), peran="hitman", aksi_bot=bela_h),
                  view=buat_view(3, "day", 40, peran="hitman", korban_gag_tim=["Citra"], next_gag=5),
                  harapan={"chat_bukan": [("tuduh", "Citra")], "chat": [("tuduh", "Andi")], "jenis": "balik_tuduh"}))
    S.append(dict(nama="159 Warga tidak menuduh target yang sama dua kali dalam satu fase",
                  cerita="Bot sudah menuduh Dodi di fase ini, walau jedanya sudah lewat.",
                  ingatan=buat_ingatan(gag_r2 + gag_r3, gag_v2, sampai=(3, "day"),
                                       aksi_bot=[{"ronde": 3, "fase": "day", "waktu": jam(3, "day", 31), "aksi": "tuduh", "jenis": "alasan_curiga", "intent": "offend", "target": "Dodi"}]),
                  view=buat_view(3, "day", 50), harapan={"chat_bukan": [("tuduh", "Dodi")]}))
    # ---------------------------------------------------------------- Fase 5: jenis bela_orang, per role
    PERAN_WARGA = ("civilian", "spy", "stalker")
    dua_tuduh = [ch(3, "day", d, p, "Citra aneh.", "offend", ["Citra"]) for d, p in ((10, "Andi"), (15, "Budi"))]
    bela_dodi = [ch(3, "day", 20, "Dodi", "Citra bukan Hitman.", "defend", ["Citra"])]
    tuduh_rekan = [ch(3, "day", d, p, "Dodi aneh.", "offend", ["Dodi"]) for d, p in ((10, "Andi"), (15, "Budi"))]
    bela_eka = [ch(3, "day", 20, "Eka", "Dodi bukan Hitman.", "defend", ["Dodi"])]
    for i, peran in enumerate(PERAN_WARGA):
        S.append(dict(nama=f"16{i} Bela orang belum ada bukti: {peran}", cerita="Dua penuduh tanpa bukti lain, belum ada pembela.",
                      ingatan=buat_ingatan(dua_tuduh, sampai=(3, "day"), peran=peran), view=buat_view(3, "day", 30, peran=peran, next_peek=4),
                      harapan={"chat": [("bela_orang", "Citra")], "jenis": "belum_ada_bukti"}))
        S.append(dict(nama=f"16{i}b Bela orang ada pembela: {peran}", cerita="Dua penuduh tanpa bukti lain, dan Dodi sudah membela.",
                      ingatan=buat_ingatan(dua_tuduh + bela_dodi, sampai=(3, "day"), peran=peran), view=buat_view(3, "day", 30, peran=peran, next_peek=4),
                      harapan={"chat": [("bela_orang", "Citra")], "jenis": "ada_pembela"}))
        S.append(dict(nama=f"16{i}c Bela orang saat hampir kalah: {peran}", cerita="Warga kritis, jadi pembelaan ditambah persuade bahaya salah vote.",
                      ingatan=buat_ingatan(dua_tuduh[:1] + [ch(3, "day", 16, "Dodi", "Hmm."), ch(3, "day", 17, "Andi", "Oke.")], sampai=(3, "day"), peran=peran),
                      view=buat_view(3, "day", 30, peran=peran, next_peek=4, mati=["Eka"], sandera={"Budi": 2}),
                      harapan={"chat": [("bela_orang", "Citra")], "jenis": "belum_ada_bukti_bahaya", "warga_terdesak_min": 0.75}))
        S.append(dict(nama=f"16{i}d Bela orang pembela saat hampir kalah: {peran}", cerita="Warga kritis, dan Dodi sudah membela.",
                      ingatan=buat_ingatan(dua_tuduh[:1] + bela_dodi, sampai=(3, "day"), peran=peran),
                      view=buat_view(3, "day", 30, peran=peran, next_peek=4, mati=["Eka"], sandera={"Budi": 2}),
                      harapan={"chat": [("bela_orang", "Citra")], "jenis": "ada_pembela_bahaya"}))
    # Roster kecil: dua pemain keluar di ronde 1, jadi satu penuduh sudah menjadi tekanan 0,5.
    keluar_dua = [(1, "Dodi"), (1, "Eka")]
    satu_tuduh_r2 = [ch(2, "day", 10, "Andi", "Citra aneh.", "offend", ["Citra"])]
    for i, peran in enumerate(PERAN_WARGA):
        S.append(dict(nama=f"17{i} Bela orang terlalu awal: {peran}", cerita="Ronde 2, satu penuduh, roster tinggal empat pemain.",
                      ingatan=buat_ingatan(satu_tuduh_r2 + [ch(2, "day", 12, "Budi", "Hmm."), ch(2, "day", 14, "Andi", "Oke.")], sampai=(2, "day"), peran=peran, keluar=keluar_dua),
                      view=buat_view(2, "day", 20, peran=peran, next_peek=3, mati=["Dodi", "Eka"]),
                      harapan={"chat": [("bela_orang", "Citra")], "jenis": "terlalu_awal"}))
    S.append(dict(nama="173 Terlalu awal di 6 pemain tidak terkirim",
                  cerita="Satu penuduh dari empat pemain bebas hanya tekanan 0,25, jadi nilai sistem bela_orang masih di bawah 40. Ini perilaku sistem, bukan ambang yang disetel.",
                  ingatan=buat_ingatan(satu_tuduh_r2, sampai=(2, "day")), view=buat_view(2, "day", 20),
                  harapan={"chat_bukan": [("bela_orang", "Citra")]}))
    klaim_citra = [ch(3, "day", 5, "Eka", "Aku Stalker, semalam aku peek Citra, dia bukan Hitman.", "defend", ["Citra"])] + dua_tuduh
    for i, peran in enumerate(("civilian", "spy")):
        S.append(dict(nama=f"17{4 + i} Bela orang diklaim bersih: {peran}", cerita="Eka mengaku Stalker dan menyatakan Citra bersih. Eka hanya saksi.",
                      ingatan=buat_ingatan(klaim_citra, sampai=(3, "day"), peran=peran), view=buat_view(3, "day", 30, peran=peran),
                      harapan={"chat": [("bela_orang", "Citra")], "jenis": "diklaim_bersih", "role_diakui": None,
                               "tabel": {"Citra": {"bersih_klaim": 0.8}}}))
    S.append(dict(nama="176 Stalker tidak punya jenis diklaim bersih",
                  cerita="Koreksi tabel plan 10.1: bot Stalker tahu Eka berbohong, jadi klaim bersihnya batal menurut aturan 8.1 dan bersih_klaim selalu 0.",
                  ingatan=buat_ingatan(klaim_citra, sampai=(3, "day"), peran="stalker"), view=buat_view(3, "day", 30, peran="stalker", next_peek=4),
                  harapan={"jenis_bukan": ["diklaim_bersih"], "tabel": {"Citra": {"bersih_klaim": 0.0}, "Eka": {"klaim_role_bermasalah": 1.0}}}))
    dua_tuduh_r2 = [ch(2, "day", d, p, "Citra aneh.", "offend", ["Citra"]) for d, p in ((10, "Andi"), (15, "Budi"))]
    S.append(dict(nama="177 Stalker yakin tanpa sumber", cerita="Peek bersih, tetapi Citra belum terancam, jadi sumbernya tidak dibuka.",
                  ingatan=buat_ingatan(dua_tuduh_r2, sampai=(3, "day"), peran="stalker", intel=[(2, "Citra", "civilian")]),
                  view=buat_view(3, "day", 30, peran="stalker", next_peek=4),
                  harapan={"chat": [("bela_orang", "Citra")], "jenis": "yakin_bersih", "role_diakui": None, "pesan_bukan": ["peek", "stalker"]}))
    S.append(dict(nama="178 Spy membela rekan Spy", cerita="Citra rekan Spy bot, jadi pasti baik. Sumbernya tidak disebut.",
                  ingatan=buat_ingatan(dua_tuduh_r2, sampai=(3, "day"), peran="spy"),
                  view=buat_view(3, "day", 30, peran="spy", spy=2, rekan_spy=["Citra"]),
                  harapan={"chat": [("bela_orang", "Citra")], "jenis": "yakin_bersih", "role_diakui": None, "pesan_bukan": ["spy"]}))
    gema_bela = dua_tuduh + [ch(3, "day", d, p, "Citra bukan Hitman.", "defend", ["Citra"]) for d, p in ((20, "Dodi"), (25, "Eka"))]
    S.append(dict(nama="179 Klaim Stalker tetap disampaikan walau sudah digemakan", cerita="Dua pemain sudah membela Citra, tetapi hasil Peek tetap perlu disampaikan.",
                  ingatan=buat_ingatan(gema_bela, sampai=(3, "day"), peran="stalker", intel=[(2, "Citra", "civilian")]),
                  view=buat_view(3, "day", 30, peran="stalker", next_peek=4),
                  harapan={"chat": [("bela_orang", "Citra")], "jenis": "peek_bersih"}))
    S.append(dict(nama="180 Pembelaan biasa tidak mengulang gema", cerita="Situasi yang sama untuk Civilian: pembelaan ketiga tidak diulang.",
                  ingatan=buat_ingatan(gema_bela, sampai=(3, "day")), view=buat_view(3, "day", 30),
                  harapan={"chat_bukan": [("bela_orang", "Citra")]}))
    S.append(dict(nama="181 Belum dibela di fase ini", cerita="Bot sudah membela Citra di fase ini.",
                  ingatan=buat_ingatan(dua_tuduh, sampai=(3, "day"), aksi_bot=[
                      {"ronde": 3, "fase": "day", "waktu": jam(3, "day", 5), "aksi": "bela_orang", "jenis": "belum_ada_bukti", "intent": "defend", "target": "Citra"}]),
                  view=buat_view(3, "day", 30), harapan={"chat_bukan": [("bela_orang", "Citra")]}))
    rekan_h = {"peran": "hitman", "hitman": 2, "rekan": ["Dodi"], "next_gag": 5}

    def delapan_pemain(view):
        return dict(view, pemain=view["pemain"] + [{"nama": n, "hidup": True, "sandera": None} for n in ("Fani", "Gita")])

    tuduh_rekan_3 = tuduh_rekan + [ch(3, "day", 18, "Citra", "Dodi aneh.", "offend", ["Dodi"])]
    S.append(dict(nama="182 Hitman membela rekan: belum ada bukti", cerita="Dodi rekan bot ditekan tiga penuduh di room 8 pemain, dan citranya masih baik.",
                  ingatan=buat_ingatan(tuduh_rekan_3, sampai=(3, "day"), peran="hitman"), view=delapan_pemain(buat_view(3, "day", 30, **rekan_h)),
                  harapan={"chat": [("bela_orang", "Dodi")], "jenis": "belum_ada_bukti", "rekan_aman": ["Dodi"]}))
    S.append(dict(nama="183 Hitman membela rekan: ada pembela", cerita="Eka sudah membela Dodi, juga di room 8 pemain.",
                  ingatan=buat_ingatan(tuduh_rekan_3 + bela_eka, sampai=(3, "day"), peran="hitman"), view=delapan_pemain(buat_view(3, "day", 30, **rekan_h)),
                  harapan={"chat": [("bela_orang", "Dodi")], "jenis": "ada_pembela"}))
    S.append(dict(nama="184 Hitman membela rekan: terlalu awal", cerita="Ronde 2, satu penuduh, roster kecil.",
                  ingatan=buat_ingatan([ch(2, "day", 10, "Andi", "Citra aneh.", "offend", ["Citra"])], sampai=(2, "day"), peran="hitman", keluar=keluar_dua),
                  view=buat_view(2, "day", 20, peran="hitman", hitman=2, rekan=["Citra"], next_gag=5, mati=["Dodi", "Eka"]),
                  harapan={"chat": [("bela_orang", "Citra")], "jenis": "terlalu_awal"}))
    S.append(dict(nama="185 Hitman membela rekan: hampir kalah", cerita="Warga kritis menurut bot Hitman, jadi ditambah persuade bahaya salah vote.",
                  ingatan=buat_ingatan(tuduh_rekan, sampai=(3, "day"), peran="hitman"), view=buat_view(3, "day", 30, mati=["Eka"], **rekan_h),
                  harapan={"chat": [("bela_orang", "Dodi")], "jenis": "belum_ada_bukti_bahaya", "warga_terdesak_min": 0.75}))
    S.append(dict(nama="186 Hitman tidak membela rekan yang sudah dicurigai publik", cerita="Citra mengaku Peek Dodi sebagai Hitman, jadi kecurigaan publik Dodi ≥ 0,5.",
                  ingatan=buat_ingatan(tuduh_rekan + [ch(3, "day", 20, "Citra", "Aku Stalker, semalam aku peek Dodi, dia Hitman.", "offend", ["Dodi"])], sampai=(3, "day"), peran="hitman"),
                  view=buat_view(3, "day", 30, **rekan_h), harapan={"chat_bukan": [("bela_orang", "Dodi")]}))
    S.append(dict(nama="187 Hitman tidak membela rekan yang hampir dieksekusi", cerita="Lebih dari separuh suara ke Dodi, jadi pembelaan justru mencolok.",
                  ingatan=buat_ingatan(sampai=(3, "tribunal"), peran="hitman"),
                  view=buat_view(3, "tribunal", 20, peran="hitman", hitman=2, rekan=["Dodi"], suara={"Andi": "Dodi", "Budi": "Dodi", "Citra": "Eka"}),
                  harapan={"chat_bukan": [("bela_orang", "Dodi")]}))
    S.append(dict(nama="188 Hitman berisiko tinggi tidak membela rekan", cerita="Hitman sendiri sudah sangat dicurigai, jadi tidak ikut mencolok.",
                  ingatan=buat_ingatan(tuduh_rekan + [ch(2, "day", 10, "Citra", "Aku Stalker, semalam aku peek Nara, dia Hitman.", "offend", ["Nara"])], sampai=(3, "day"), peran="hitman"),
                  view=buat_view(3, "day", 30, **rekan_h), harapan={"chat_bukan": [("bela_orang", "Dodi")]}))
    # ---------------------------------------------------------------- Fase 5: jenis tanya_info dan tunggu, per role
    for i, peran in enumerate(PERAN_SEMUA):
        S.append(dict(nama=f"19{i} Ruangan hening: {peran}", cerita="Hanya satu chat, lalu lama hening.",
                      ingatan=buat_ingatan([ch(2, "day", 10, "Andi", "Halo.")], sampai=(2, "day"), peran=peran),
                      view=buat_view(2, "day", 40, peran=peran, next_peek=3, next_gag=3),
                      harapan={"chat": [("tanya_info", None)], "jenis": "ruangan_hening"}))
        S.append(dict(nama=f"19{i}b Pertanyaan umum: {peran}", cerita="Awal siang, belum ada chat dan belum hening.",
                      ingatan=buat_ingatan(sampai=(1, "day"), peran=peran), view=buat_view(1, "day", 5, peran=peran, next_gag=3),
                      harapan={"chat": [("tanya_info", None)], "jenis": "pertanyaan_umum"}))
        S.append(dict(nama=f"19{i}c Tunggu saat masih jeda: {peran}", cerita="Bot baru chat dan tidak ada pemicu.",
                      ingatan=buat_ingatan(sampai=(1, "day"), peran=peran, aksi_bot=[
                          {"ronde": 1, "fase": "day", "waktu": jam(1, "day", 35), "aksi": "tanya_info", "jenis": "pertanyaan_umum", "intent": "neutral", "target": None}]),
                      view=buat_view(1, "day", 40, peran=peran, next_gag=3), harapan={"chat": [("tunggu", None)]}))
    for nomor, peran in (("194", "spy"), ("195", "stalker")):
        S.append(dict(nama=f"{nomor} Pemain diam: {peran}", cerita="Situasi skenario 99 untuk role lain.",
                      ingatan=buat_ingatan(aj, aj_v, sampai=(3, "day"), aksi_bot=aj_a, peran=peran), view=buat_view(3, "day", 50, peran=peran, next_peek=4),
                      harapan={"chat": [("tanya_info", "Dodi")], "jenis": "pemain_diam"}))
    aj_h = aj + [ch(2, "day", 10, "Citra", "Aku Stalker, semalam aku peek Dodi, dia Hitman.", "offend", ["Dodi"])]
    S.append(dict(nama="196 Hitman mengajak pemain diam", cerita="Dodi dicurigai publik dan belum bicara. Dulu ajak bicara hanya untuk warga.",
                  ingatan=buat_ingatan(aj_h, sampai=(3, "day"), aksi_bot=aj_a, peran="hitman"), view=buat_view(3, "day", 50, peran="hitman", next_gag=5),
                  harapan={"chat": [("tanya_info", "Dodi")], "jenis": "pemain_diam"}))
    S.append(dict(nama="197 Pemain diam tidak ada saat Tribunal", cerita="Situasi skenario 99 di Tribunal.",
                  ingatan=buat_ingatan(aj, aj_v, sampai=(3, "tribunal"), aksi_bot=[dict(aj_a[0], fase="tribunal", waktu=jam(3, "tribunal", 1))]), view=buat_view(3, "tribunal", 30),
                  harapan={"jenis_bukan": ["pemain_diam"]}))
    S.append(dict(nama="198 Tribunal hening tanpa pertanyaan", cerita="Tribunal tanpa chat. Hening dan pertanyaan umum hanya untuk siang, dan belum ada alasan untuk digali.",
                  ingatan=buat_ingatan(sampai=(2, "tribunal")), view=buat_view(2, "tribunal", 30),
                  harapan={"chat": [("tunggu", None)]}))
    # Bentrok yang bot belum tahu siapa yang bohong: bot Spy melihat dua pengaku Stalker, bot lain melihat dua pengaku Spy.
    for i, (peran, teks_klaim) in enumerate((("civilian", "Aku Spy."), ("spy", "Aku Stalker."), ("stalker", "Aku Spy."))):
        klaim_dua = [ch(3, "day", d, p, teks_klaim) for d, p in ((10, "Andi"), (20, "Citra"))]
        S.append(dict(nama=f"20{i} Klaim bentrok: {peran}", cerita="Dua pengaku role yang sama. Bot belum tahu siapa yang bohong.",
                      ingatan=buat_ingatan(klaim_dua, sampai=(3, "day"), peran=peran), view=buat_view(3, "day", 25, peran=peran, next_peek=4),
                      harapan={"chat": [("tanya_info", None)], "jenis": "klaim_bentrok", "konteks": {"klaim_bentrok": ["Andi", "Citra"]}}))
    S.append(dict(nama="203 Klaim bentrok boleh saat Tribunal", cerita="Bentrok yang sama saat Tribunal.",
                  ingatan=buat_ingatan([ch(3, "day", d, p, "Aku Spy.") for d, p in ((10, "Andi"), (20, "Citra"))], sampai=(3, "tribunal")), view=buat_view(3, "tribunal", 20),
                  harapan={"chat": [("tanya_info", None)], "jenis": "klaim_bentrok"}))
    S.append(dict(nama="204 Hitman tidak bertanya soal klaim bentrok", cerita="Hitman tahu siapa yang bohong, jadi tidak memakai jenis ini.",
                  ingatan=buat_ingatan([ch(3, "day", d, p, "Aku Spy.") for d, p in ((10, "Andi"), (20, "Citra"))], sampai=(3, "day"), peran="hitman"), view=buat_view(3, "day", 25, peran="hitman", next_gag=5),
                  harapan={"jenis_bukan": ["klaim_bentrok"]}))
    # Dua tersangka berdekatan: Andi dan Budi sama-sama pernah vote bot, jadi kecurigaan keduanya 0,50 dan keunggulan 0. Nilai tuduh di bawah 40.
    gali_v = [(2, "Andi", "Nara"), (2, "Budi", "Nara")]
    for i, peran in enumerate(("civilian", "spy", "stalker")):
        S.append(dict(nama=f"20{5 + i} Gali tersangka: {peran}", cerita="Dua tersangka berdekatan, nilai tuduh di bawah 40, dan obrolan ramai.",
                      ingatan=buat_ingatan(aj, gali_v, sampai=(3, "day"), peran=peran), view=buat_view(3, "day", 25, peran=peran, next_peek=4),
                      harapan={"chat": [("tanya_info", "Andi")], "jenis": "gali_tersangka", "tabel": {"Andi": {"kecurigaan": 0.5}, "Budi": {"kecurigaan": 0.5}}}))
    gali_h = [ch(3, "day", d, p, "Budi aneh.", "offend", ["Budi"]) for d, p in ((5, "Andi"), (8, "Citra"), (10, "Dodi"), (12, "Eka"))] + [ch(3, "day", 14, "Budi", "Bukan aku.")]
    S.append(dict(nama="208 Hitman menggali kambing hitam", cerita="Budi kambing hitam teratas. Tuduhan ke Budi sudah digemakan, jadi Hitman memakai tabel publik untuk menggalinya.",
                  ingatan=buat_ingatan(gali_h, sampai=(3, "day"), peran="hitman"), view=buat_view(3, "day", 18, peran="hitman", next_gag=5),
                  harapan={"chat": [("tanya_info", "Budi")], "jenis": "gali_tersangka"}))
    gali_a = [{"ronde": 3, "fase": "day", "waktu": jam(3, "day", 1), "aksi": "tanya_info", "jenis": "gali_tersangka", "intent": "neutral", "target": "Andi"}]
    S.append(dict(nama="209 Gali tersangka tidak dua kali dalam satu fase", cerita="Situasi skenario 205 sesudah bot menggali Andi. Jeda sudah lewat.",
                  ingatan=buat_ingatan(aj, gali_v, sampai=(3, "day"), aksi_bot=gali_a), view=buat_view(3, "day", 25), harapan={"chat": [("tunggu", None)]}))
    aj_tanya = [c for c in aj if c["pengirim"] != "Eka"] + [ch(3, "day", 16, "Eka", "Andi, kamu kenapa?")]
    S.append(dict(nama="210 Gali melewati pemain yang sudah diajak", cerita="Eka sudah bertanya ke Andi di ronde ini.",
                  ingatan=buat_ingatan(aj_tanya, gali_v, sampai=(3, "day")), view=buat_view(3, "day", 25),
                  harapan={"chat": [("tunggu", None)], "konteks": {"sudah_diajak": ["Andi"]}}))
    S.append(dict(nama="211 Gali tersangka boleh saat Tribunal", cerita="Situasi skenario 205 di Tribunal. Obrolan ramai dari siang tadi.",
                  ingatan=buat_ingatan(aj, gali_v, sampai=(3, "tribunal")), view=buat_view(3, "tribunal", 20),
                  harapan={"chat": [("tanya_info", "Andi")], "jenis": "gali_tersangka"}))
    S.append(dict(nama="212 Gali butuh alasan", cerita="Tidak ada tersangka dengan alasan yang bisa ditanyakan, jadi bot menunggu.",
                  ingatan=buat_ingatan(aj, sampai=(3, "day")), view=buat_view(3, "day", 25), harapan={"chat": [("tunggu", None)]}))
    # ---------------------------------------------------------------- Fase 5: aturan Gag
    vote_citra = [(2, "Citra", "Nara")]
    S.append(dict(nama="213 Gag menit awal untuk ancaman tinggi walau belum bicara", cerita="Citra vote bot di ronde lalu dan belum bicara di siang ini.",
                  ingatan=buat_ingatan(votes=vote_citra, sampai=(3, "day"), peran="hitman"), view=buat_view(3, "day", 5, peran="hitman"),
                  harapan={"aksi": [("gag", "Citra")], "fitur_hitman": {"Citra": {"bicara_ronde_ini": 0.0}}}))
    rekan_m = {"peran": "hitman", "hitman": 2, "rekan": ["Dodi"], "rekan_manusia": ["Dodi"]}
    S.append(dict(nama="214 Rekan manusia hidup menahan Gag sebelum 60%", cerita="Ancaman tinggi, tetapi rekan manusia diberi kesempatan memilih lebih dulu.",
                  ingatan=buat_ingatan(gg_r1, sampai=(1, "day"), peran="hitman"), view=buat_view(1, "day", 30, **rekan_m),
                  harapan={"aksi": [("tunggu", None)]}))
    S.append(dict(nama="215 Rekan manusia: Gag wajib pada 60%", cerita="Sudah 60% siang dan Gag belum terpakai.",
                  ingatan=buat_ingatan(gg_r1, sampai=(1, "day"), peran="hitman"), view=buat_view(1, "day", 72, **rekan_m),
                  harapan={"aksi": [("gag", "Andi"), ("gag", "Citra")]}))
    S.append(dict(nama="216 Rekan manusia yang tersingkir tidak menahan Gag", cerita="Dodi sudah mati, jadi bot bertindak sendiri.",
                  ingatan=buat_ingatan(gg_r1, sampai=(1, "day"), peran="hitman"), view=buat_view(1, "day", 30, mati=["Dodi"], **rekan_m),
                  harapan={"aksi": [("gag", "Andi"), ("gag", "Citra")]}))
    S.append(dict(nama="217 Gag wajib tepat pada 60% walau ancaman rendah", cerita="Siang sepi. Ancaman semua warga sama, jadi seri menurut nilai lalu nama.",
                  ingatan=buat_ingatan(q_r1, sampai=(1, "day"), peran="hitman"), view=buat_view(1, "day", 72, peran="hitman"),
                  harapan={"aksi": [("gag", "Andi")]}))
    S.append(dict(nama="218 Sebelum 60% Gag menunggu", cerita="Situasi yang sama, satu detik sebelum 60%.",
                  ingatan=buat_ingatan(q_r1, sampai=(1, "day"), peran="hitman"), view=buat_view(1, "day", 71, peran="hitman"),
                  harapan={"aksi": [("tunggu", None)]}))
    S.append(dict(nama="219 Gag wajib ke ancaman tertinggi yang belum bicara", cerita="Eka vote bot di ronde lalu dan belum bicara. Warga lain sudah bicara, tetapi ancamannya lebih rendah.",
                  ingatan=buat_ingatan([ch(3, "day", d, p, "Oke.") for d, p in ((5, "Andi"), (10, "Budi"), (15, "Citra"))], [(2, "Eka", "Nara")], sampai=(3, "day"), peran="hitman"),
                  view=buat_view(3, "day", 75, **rekan_m), harapan={"aksi": [("gag", "Eka")], "fitur_hitman": {"Eka": {"bicara_ronde_ini": 0.0}}}))
    S.append(dict(nama="220 Gag tidak ke korban Hostage atau rekan", cerita="Citra korban Hostage dan Dodi rekan. Andi ancaman berikutnya.",
                  ingatan=buat_ingatan(votes=[(2, "Citra", "Nara"), (2, "Dodi", "Nara"), (2, "Andi", "Nara")], sampai=(3, "day"), peran="hitman"),
                  view=buat_view(3, "day", 5, peran="hitman", hitman=2, rekan=["Dodi"], sandera={"Citra": 2}),
                  harapan={"aksi": [("gag", "Andi")], "aksi_bukan": ["Citra", "Dodi"], "bukan_fitur_hitman": ["Citra", "Dodi"]}))
    S.append(dict(nama="221 Gag tidak tersedia sesudah dipakai", cerita="Sudah 60% siang, tetapi Gag tim masih menunggu cooldown.",
                  ingatan=buat_ingatan(q_r1, sampai=(1, "day"), peran="hitman"), view=buat_view(1, "day", 80, peran="hitman", next_gag=3),
                  harapan={"aksi": [("tidak_bisa", None)]}))
    return S


SKENARIO = daftar_skenario()

# Skenario vote dan ajak vote (Fase 6), nomor 300-399. Terpisah dari sel skenario utama.
def skenario_vote():
    S = []

    # Eka menuduh Budi lalu disandera, jadi Budi tersangka kuat di Tribunal ronde 3.
    bukti_budi = [ch(2, "day", 10, "Eka", "Budi dari tadi ngeles terus.", "offend", ["Budi"]),
                  ch(2, "day", 30, "Eka", "Aku curiga Budi Hitman.", "offend", ["Budi"])]
    korban_eka = {"sandera": {"Eka": 2}}

    def ingatan_t(chats=(), votes=(), **opsi):
        return buat_ingatan(chats, votes, sampai=(3, "tribunal"), **opsi)

    # ---------------------------------------------------------------- 11.1 ajak vote
    S.append(dict(nama="300 Ajak menyatukan suara", cerita="Suara terbagi ke Budi dan Dodi. Bot yakin pada Budi, jadi mengajak menyatukan suara.",
                  ingatan=ingatan_t(bukti_budi), view=buat_view(3, "tribunal", 10, suara={"Andi": "Budi", "Citra": "Dodi"}, **korban_eka),
                  harapan={"vote": [("vote", "Budi")], "chat": [("tuduh", "Budi")], "jenis": "ajak_menyatukan"}))
    S.append(dict(nama="301 Jelaskan vote", cerita="Hanya satu target bersuara, dan bot akan vote langkah ini, jadi bot menjelaskan vote-nya.",
                  ingatan=ingatan_t(bukti_budi), view=buat_view(3, "tribunal", 10, suara={"Andi": "Budi"}, **korban_eka),
                  harapan={"vote": [("vote", "Budi")], "chat": [("tuduh", "Budi")], "jenis": "jelaskan_vote"}))
    S.append(dict(nama="302 Jelaskan vote sesudah vote", cerita="Bot sudah vote Budi di langkah lalu, jadi target diambil dari suara Tribunal.",
                  ingatan=ingatan_t(bukti_budi), view=buat_view(3, "tribunal", 10, suara={"Nara": "Budi"}, can_vote=False, can_cancel_vote=True, **korban_eka),
                  harapan={"chat": [("tuduh", "Budi")], "jenis": "jelaskan_vote"}))
    S.append(dict(nama="303 Ajak pindah saat waktu tambahan", cerita="Suara seri dan bot sudah vote Budi, jadi bot mengajak pindah ke Budi.",
                  ingatan=ingatan_t(bukti_budi),
                  view=dict(buat_view(3, "tribunal", 80, suara={"Nara": "Budi", "Andi": "Dodi"}, can_vote=False, can_cancel_vote=True, **korban_eka), tribunal_tambahan=True),
                  harapan={"chat": [("tuduh", "Budi")], "jenis": "ajak_pindah"}))
    S.append(dict(nama="304 Ajak vote sekali per Tribunal", cerita="Bot sudah mengajak ke orang lain di Tribunal ini, jadi tidak mengajak lagi walau jedanya lewat.",
                  ingatan=ingatan_t(bukti_budi, aksi_bot=[{"ronde": 3, "fase": "tribunal", "waktu": jam(3, "tribunal", 2), "aksi": "tuduh", "jenis": "jelaskan_vote",
                                                           "intent": "offend", "target": "Citra"}]),
                  view=buat_view(3, "tribunal", 40, suara={"Andi": "Budi"}, **korban_eka),
                  harapan={"vote": [("vote", "Budi")], "jenis_bukan": ["ajak_pindah", "ajak_menyatukan", "jelaskan_vote"]}))
    S.append(dict(nama="305 Target vote kurang dicurigai tidak diajak", cerita="Bot sudah vote Dodi yang kecurigaannya di bawah 0,40.",
                  ingatan=ingatan_t(), view=buat_view(3, "tribunal", 40, suara={"Nara": "Dodi"}, can_vote=False, can_cancel_vote=True),
                  harapan={"tabel": {"Dodi": {"kecurigaan": 0.15}}, "jenis_bukan": ["ajak_pindah", "ajak_menyatukan", "jelaskan_vote"]}))
    S.append(dict(nama="306 Sudah menuduh target yang sama tidak mengajak", cerita="Sekali per target per fase tetap berlaku, karena ajak vote adalah jenis tuduh.",
                  ingatan=ingatan_t(bukti_budi, aksi_bot=[{"ronde": 3, "fase": "tribunal", "waktu": jam(3, "tribunal", 2), "aksi": "tuduh", "jenis": "alasan_curiga",
                                                           "intent": "offend", "target": "Budi"}]),
                  view=buat_view(3, "tribunal", 40, suara={"Andi": "Budi"}, **korban_eka),
                  harapan={"chat_bukan": [("tuduh", "Budi")]}))
    S.append(dict(nama="307 Anti-gema berlaku pada ajak vote", cerita="Dua pemain lain sudah menuduh Budi di Tribunal ini.",
                  ingatan=ingatan_t(bukti_budi + [ch(3, "tribunal", d, p, "Budi aneh.", "offend", ["Budi"]) for d, p in ((2, "Andi"), (4, "Citra"))]),
                  view=buat_view(3, "tribunal", 10, suara={"Andi": "Budi"}, **korban_eka),
                  harapan={"vote": [("vote", "Budi")], "chat_bukan": [("tuduh", "Budi")]}))
    peek_budi = [ch(3, "day", 10, "Citra", "Aku Stalker, semalam aku peek Budi, dia Hitman.", "offend", ["Budi"])]
    S.append(dict(nama="308 Hitman mengajak ke kambing hitam", cerita="Suara warga terbagi, dan Budi kambing hitam kuat. Hitman ikut suara terbanyak dan mengajak menyatukan.",
                  ingatan=ingatan_t(peek_budi, peran="hitman"), view=buat_view(3, "tribunal", 60, peran="hitman", suara={"Andi": "Budi", "Citra": "Dodi"}),
                  harapan={"vote": [("vote", "Budi")], "chat": [("tuduh", "Budi")], "jenis": "ajak_menyatukan"}))
    S.append(dict(nama="309 Alasan Peek tidak bocor saat menjelaskan vote",
                  cerita="Eka mengaku Peek bot, jadi bot Stalker vote Eka. Stalker belum membuka role, jadi alasan yang menyebut peek tidak boleh ikut ke kalimat.",
                  ingatan=ingatan_t([ch(3, "day", 10, "Eka", "Aku Stalker, semalam aku peek Nara, dia Hitman.", "offend", ["Nara"]),
                                     ch(3, "tribunal", 3, "Eka", "Vote Nara.", "offend", ["Nara"])], peran="stalker",
                                    aksi_bot=[{"ronde": 3, "fase": "tribunal", "waktu": jam(3, "tribunal", 4), "aksi": "bela_diri", "intent": "defend", "target": "Nara"}]),
                  view=buat_view(3, "tribunal", 30, peran="stalker", next_peek=4, suara={"Nara": "Eka"}, can_vote=False, can_cancel_vote=True),
                  harapan={"chat": [("tuduh", "Eka")], "jenis": "jelaskan_vote", "pesan_bukan": ["peek"]}))
    S.append(dict(nama="310 Tanya info Tribunal hanya klaim bentrok dan gali",
                  cerita="Tribunal sepi dan bot belum vote. Hening, pertanyaan umum, dan pemain diam tidak berlaku saat Tribunal.",
                  ingatan=ingatan_t(), view=buat_view(3, "tribunal", 40),
                  harapan={"chat_bukan": [("tanya_info", None)]}))
    # ---------------------------------------------------------------- 11.2 vote warga
    S.append(dict(nama="320 Kesiapan tinggi langsung vote", cerita="Budi tersangka kuat dan Tribunal baru mulai. Kesiapan 85.",
                  ingatan=ingatan_t(bukti_budi), view=buat_view(3, "tribunal", 5, **korban_eka),
                  harapan={"vote": [("vote", "Budi")], "vote_paksa": False}))
    vote_andi = [(2, "Andi", "Nara")]
    S.append(dict(nama="321 Paruh awal Tribunal menunggu", cerita="Andi pernah vote bot, jadi kecurigaannya 0,50 dan kesiapan 50. Belum separuh Tribunal.",
                  ingatan=ingatan_t(votes=vote_andi), view=buat_view(3, "tribunal", 30),
                  harapan={"vote": [("tunggu", None)], "tabel": {"Andi": {"kecurigaan": 0.5}}}))
    S.append(dict(nama="322 Paruh akhir Tribunal vote", cerita="Situasi yang sama sesudah separuh Tribunal: kesiapan ≥ 45, jadi vote.",
                  ingatan=ingatan_t(votes=vote_andi), view=buat_view(3, "tribunal", 60),
                  harapan={"vote": [("vote", "Andi")], "vote_paksa": False}))
    vote_dua = [(2, "Andi", "Nara"), (2, "Budi", "Nara")]
    S.append(dict(nama="323 Ikut suara terbanyak", cerita="Andi dan Budi sama-sama 0,50, jadi keunggulan 0 dan kesiapan 15. Dua suara ke Budi, jadi bot ikut, bukan memilih Andi.",
                  ingatan=ingatan_t(votes=vote_dua), view=buat_view(3, "tribunal", 60, suara={"Citra": "Budi", "Dodi": "Budi"}),
                  harapan={"vote": [("vote", "Budi")], "vote_paksa": False, "tabel": {"Andi": {"kecurigaan": 0.5}, "Budi": {"kecurigaan": 0.5}}}))
    # Kritis tepat 0,75: warga bebas 3 dan satu Hitman. Tanpa bukti kesiapan 41,6, jadi penalaran memilih abstain.
    kritis = {"mati": ["Eka"], "sandera": {"Budi": 2}}
    eks_eka = [(2, "Eka")]
    S.append(dict(nama="324 Kritis tanpa bukti dipaksa vote", cerita="Warga kritis dan semua nilai sama, jadi pilihan diacak stabil. Korban Hostage tidak dipilih.",
                  ingatan=buat_ingatan(eksekusi=eks_eka, sampai=(3, "tribunal")), view=buat_view(3, "tribunal", 60, **kritis),
                  harapan={"vote": [("vote", None)], "vote_paksa": True, "vote_bukan": ["Budi", "Eka", "Nara"], "warga_terdesak_min": 0.75}))
    S.append(dict(nama="325 Tidak kritis tetap abstain", cerita="Tanpa bukti dan warga masih banyak: paksa hanya saat kritis.",
                  ingatan=ingatan_t(), view=buat_view(3, "tribunal", 60),
                  harapan={"vote": [("abstain", None)], "vote_paksa": False}))
    S.append(dict(nama="326 Kritis memilih tersangka teratas", cerita="Hanya Citra yang dituduh, jadi total buktinya paling besar dan tidak perlu diacak.",
                  ingatan=buat_ingatan([ch(3, "day", 10, "Andi", "Citra aneh.", "offend", ["Citra"])], eksekusi=eks_eka, sampai=(3, "tribunal")),
                  view=buat_view(3, "tribunal", 60, **kritis),
                  harapan={"vote": [("vote", "Citra")], "vote_paksa": True}))
    bersih_semua = [ch(2, "day", 5 + d, "Eka", f"Aku Stalker, semalam aku peek {p}, dia bukan Hitman.", "defend", [p]) for d, p in enumerate(("Andi", "Citra", "Dodi"))]
    S.append(dict(nama="327 Paksa melewati yang dibersihkan pengaku Stalker", cerita="Semua kandidat punya bersih_klaim 0,72, jadi tidak ada yang layak dipaksa.",
                  ingatan=buat_ingatan(bersih_semua, eksekusi=eks_eka, sampai=(3, "tribunal")), view=buat_view(3, "tribunal", 60, **kritis),
                  harapan={"vote": [("abstain", None)], "vote_paksa": False}))
    S.append(dict(nama="328 Paksa tidak ke rekan Spy", cerita="Citra rekan Spy bot, jadi pasti baik.",
                  ingatan=buat_ingatan(eksekusi=eks_eka, sampai=(3, "tribunal"), peran="spy"),
                  view=buat_view(3, "tribunal", 60, peran="spy", spy=2, rekan_spy=["Citra"], **kritis),
                  harapan={"vote": [("vote", None)], "vote_paksa": True, "vote_bukan": ["Citra", "Budi", "Eka", "Nara"]}))
    S.append(dict(nama="329 Hitman tidak dipaksa vote", cerita="Warga kritis menurut hitungan yang sama, tetapi paksa hanya untuk warga, dan Hitman tidak membuka vote.",
                  ingatan=buat_ingatan(eksekusi=eks_eka, sampai=(3, "tribunal"), peran="hitman"), view=buat_view(3, "tribunal", 60, peran="hitman", **kritis),
                  harapan={"vote": [("abstain", None)], "vote_paksa": False}))
    # ---------------------------------------------------------------- 11.3 vote Hitman
    rekan_dodi = {"peran": "hitman", "hitman": 2, "rekan": ["Dodi"]}
    S.append(dict(nama="330 Rekan pasti dieksekusi: Hitman ikut", cerita="Empat suara ke Dodi, tanpa pesaing, dan sisa pemilih dua (bot dan Dodi). Dodi tidak bisa lagi diselamatkan.",
                  ingatan=ingatan_t(peran="hitman"), view=buat_view(3, "tribunal", 10, suara={"Andi": "Dodi", "Budi": "Dodi", "Citra": "Dodi", "Eka": "Dodi"}, **rekan_dodi),
                  harapan={"vote": [("vote", "Dodi")]}))
    S.append(dict(nama="331 Rekan masih bisa selamat: samakan suara", cerita="Dua suara ke Dodi, satu ke Citra, sisa pemilih tiga. 2 tidak lebih dari 1 + 3, jadi Hitman menyamakan suara.",
                  ingatan=ingatan_t(peran="hitman"), view=buat_view(3, "tribunal", 10, suara={"Andi": "Dodi", "Budi": "Dodi", "Eka": "Citra"}, **rekan_dodi),
                  harapan={"vote": [("vote", "Citra")], "rekan_aman": ["Dodi"]}))
    S.append(dict(nama="332 Sisa pemilih tidak menghitung korban Hostage", cerita="Tiga suara ke Dodi. Eka korban Hostage, jadi sisa pemilih hanya bot dan Dodi: 3 lebih dari 0 + 2.",
                  ingatan=ingatan_t(peran="hitman"), view=buat_view(3, "tribunal", 10, suara={"Andi": "Dodi", "Budi": "Dodi", "Citra": "Dodi"}, sandera={"Eka": 2}, **rekan_dodi),
                  harapan={"vote": [("vote", "Dodi")]}))
    S.append(dict(nama="333 Tanpa korban Hostage rekan masih bisa selamat", cerita="Tiga suara ke Dodi dan Eka bebas, jadi sisa pemilih tiga: 3 tidak lebih dari 0 + 3. Belum ada pesaing, jadi Hitman memakai kambing hitam teratas.",
                  ingatan=ingatan_t(peran="hitman"), view=buat_view(3, "tribunal", 10, suara={"Andi": "Dodi", "Budi": "Dodi", "Citra": "Dodi"}, **rekan_dodi),
                  harapan={"vote": [("vote", None)], "vote_bukan": ["Dodi"]}))
    S.append(dict(nama="334 Hitman memimpin suara: samakan", cerita="Hitman sendiri memimpin. Aturan rekan pasti dieksekusi tidak berlaku untuk dirinya.",
                  ingatan=ingatan_t(peran="hitman"), view=buat_view(3, "tribunal", 10, peran="hitman", suara={"Andi": "Nara", "Budi": "Nara", "Citra": "Nara", "Eka": "Dodi"}),
                  harapan={"vote": [("vote", "Dodi")]}))
    S.append(dict(nama="335 Hitman menunggu arah suara", cerita="Belum separuh Tribunal dan tidak terdesak.",
                  ingatan=ingatan_t(peran="hitman"), view=buat_view(3, "tribunal", 10, peran="hitman", suara={"Andi": "Dodi"}),
                  harapan={"vote": [("tunggu", None)]}))
    S.append(dict(nama="336 Hitman tanpa suara warga abstain", cerita="Sudah lewat separuh Tribunal, belum ada suara.",
                  ingatan=ingatan_t(peran="hitman"), view=buat_view(3, "tribunal", 60, peran="hitman"),
                  harapan={"vote": [("abstain", None)]}))
    S.append(dict(nama="337 Hitman ikut pemimpin warga", cerita="Dua suara ke Citra, warga yang layak.",
                  ingatan=ingatan_t(peran="hitman"), view=buat_view(3, "tribunal", 60, peran="hitman", suara={"Andi": "Citra", "Budi": "Citra"}),
                  harapan={"vote": [("vote", "Citra")]}))
    S.append(dict(nama="338 Pemimpin tidak layak: kambing hitam teratas", cerita="Suara mengarah ke korban Hostage yang tidak ada di tabel fitur, jadi Hitman memilih kambing hitam teratas.",
                  ingatan=ingatan_t(peran="hitman"), view=buat_view(3, "tribunal", 60, peran="hitman", suara={"Andi": "Eka"}, sandera={"Eka": 2}),
                  harapan={"vote": [("vote", None)], "vote_bukan": ["Eka"]}))
    # ---------------------------------------------------------------- 11.4 seri
    def view_tambahan(suara, **opsi):
        return dict(buat_view(3, "tribunal", 80, suara=suara, can_vote=False, can_cancel_vote=True, **opsi), tribunal_tambahan=True)

    S.append(dict(nama="340 Warga pindah ke target lebih kuat yang tidak seri", cerita="Seri antara Dodi dan Citra. Bot vote Dodi, tetapi Budi lebih dicurigai, jadi bot pindah ke Budi.",
                  ingatan=ingatan_t(bukti_budi), view=view_tambahan({"Nara": "Dodi", "Andi": "Citra"}, **korban_eka),
                  harapan={"vote": [("vote", "Budi")], "vote_pindah": True, "chat": [("tuduh", "Budi")], "jenis": "ajak_pindah"}))
    S.append(dict(nama="341 Warga tidak pindah tanpa target lebih kuat", cerita="Bot sudah vote Budi, tersangka teratas.",
                  ingatan=ingatan_t(bukti_budi), view=view_tambahan({"Nara": "Budi", "Andi": "Dodi"}, **korban_eka),
                  harapan={"vote": [("tunggu", None)], "vote_pindah": False}))
    S.append(dict(nama="342 Warga seri kecurigaan tidak pindah", cerita="Bot vote Andi, dan Budi sama-sama 0,50. Pindah butuh kecurigaan yang lebih tinggi.",
                  ingatan=ingatan_t(votes=[(2, "Andi", "Nara"), (2, "Budi", "Nara")]), view=view_tambahan({"Nara": "Andi", "Citra": "Budi"}),
                  harapan={"vote": [("tunggu", None)], "vote_pindah": False, "tabel": {"Andi": {"kecurigaan": 0.5}, "Budi": {"kecurigaan": 0.5}}}))
    S.append(dict(nama="343 Pindah hanya sekali", cerita="Bot sudah pernah pindah ke Dodi di waktu tambahan ini, walau Budi lebih kuat.",
                  ingatan=ingatan_t(bukti_budi, vote_bot=[{"ronde": 3, "target": "Dodi", "alasan": [], "dinilai_ulang": True}]),
                  view=view_tambahan({"Nara": "Dodi", "Andi": "Citra"}, **korban_eka),
                  harapan={"vote": [("tidak_bisa", None)], "vote_pindah": False}))
    S.append(dict(nama="344 Tanpa waktu tambahan tidak menilai ulang", cerita="Bot boleh membatalkan suara, tetapi belum seri.",
                  ingatan=ingatan_t(bukti_budi), view=buat_view(3, "tribunal", 60, suara={"Nara": "Dodi", "Andi": "Citra"}, can_vote=False, can_cancel_vote=True, **korban_eka),
                  harapan={"vote": [("tidak_bisa", None)], "vote_pindah": False}))
    S.append(dict(nama="345 Bot yang belum vote memutuskan seperti biasa", cerita="Waktu tambahan, bot belum vote, jadi tidak ada suara yang dipindah.",
                  ingatan=ingatan_t(bukti_budi), view=dict(buat_view(3, "tribunal", 80, suara={"Andi": "Citra", "Citra": "Andi"}, **korban_eka), tribunal_tambahan=True),
                  harapan={"vote": [("vote", "Budi")], "vote_pindah": False, "jenis": "ajak_pindah"}))
    S.append(dict(nama="346 Tidak pindah ke yang pasti baik", cerita="Bot Spy vote Dodi. Citra rekan Spy dituduh banyak orang, tetapi pasti baik. Penuduhnya yang kini lebih dicurigai, jadi bot pindah ke salah satu penuduh.",
                  ingatan=ingatan_t([ch(3, "day", d, p, "Citra aneh.", "offend", ["Citra"]) for d, p in ((5, "Andi"), (8, "Budi"), (10, "Eka"))], peran="spy"),
                  view=view_tambahan({"Nara": "Dodi", "Andi": "Citra"}, peran="spy", spy=2, rekan_spy=["Citra"]),
                  harapan={"vote": [("vote", None)], "vote_bukan": ["Citra", "Dodi"], "vote_pindah": True}))
    S.append(dict(nama="347 Hitman mempertahankan seri", cerita="Seri antara rekan Dodi dan Citra, dan suara bot sudah ke Citra. Aturan samakan suara memberi target yang sama, jadi tidak pindah.",
                  ingatan=ingatan_t(peran="hitman"), view=view_tambahan({"Nara": "Citra", "Andi": "Dodi"}, peran="hitman", hitman=2, rekan=["Dodi"]),
                  harapan={"vote": [("tunggu", None)], "vote_pindah": False, "rekan_aman": ["Dodi"]}))
    S.append(dict(nama="348 Hitman pindah mengikuti aturan votenya", cerita="Dua suara ke Budi dan satu suara bot ke Citra. Pemimpin warga layak, jadi Hitman ikut.",
                  ingatan=ingatan_t(peran="hitman"), view=view_tambahan({"Nara": "Citra", "Andi": "Budi", "Eka": "Budi"}, peran="hitman"),
                  harapan={"vote": [("vote", "Budi")], "vote_pindah": True}))
    S.append(dict(nama="349 Hitman pindah ke rekan yang pasti dieksekusi", cerita="Empat suara ke Dodi, satu suara bot ke Andi, dan sisa pemilih hanya Dodi: 4 lebih dari 1 + 1.",
                  ingatan=ingatan_t(peran="hitman"), view=view_tambahan({"Nara": "Andi", "Budi": "Dodi", "Citra": "Dodi", "Eka": "Dodi", "Andi": "Dodi"}, peran="hitman", hitman=2, rekan=["Dodi"]),
                  harapan={"vote": [("vote", "Dodi")], "vote_pindah": True}))
    return S


SKENARIO += skenario_vote()

# Skenario malam dan chat tim (nomor 400–499), di sel sendiri supaya nomor lama tidak berubah.
# View malam seperti hasil sinkron_snapshot. Bot terkunci mengikuti sisa waktu; sesudah_kunci = langkah sesudah saat terkunci.
def view_malam(ronde, detik, peran, aksi_malam=None, manusia=(), sesudah_kunci=False, **status):
    terkunci = bot_terkunci(False, jam(ronde, "night", DURASI_DEMO["night"]), jam(ronde, "night", detik))
    bawaan = {"terkunci": terkunci, "saat_terkunci": terkunci and not sesudah_kunci, "aksi_malam": aksi_malam,
              "rekan_manusia": list(manusia), "can_team_chat": bool(manusia)}
    if aksi_malam:
        bawaan.update(can_act=False, can_cancel_action=True)
    return buat_view(ronde, "night", detik, peran=peran, **{**bawaan, **status})


# Bot Hitman dengan rekan Dodi; pilihan = target pilihan Dodi malam ini.
def hitman_malam(detik, aksi_malam=None, pilihan=None, manusia=True, ronde=1, **status):
    return view_malam(ronde, detik, "hitman", aksi_malam, ["Dodi"] if manusia else [], hitman=2, rekan=["Dodi"],
                      aksi_rekan=[("Dodi", pilihan)] if pilihan else [], **status)


# Bot Spy dengan rekan Dodi; pilihan = target Guard pilihan Dodi malam ini.
def spy_malam(detik, aksi_malam=None, pilihan=None, manusia=True, ronde=1, **status):
    return view_malam(ronde, detik, "spy", aksi_malam, ["Dodi"] if manusia else [], spy=2, rekan_spy=["Dodi"],
                      aksi_rekan_spy=[{"pemain": "Dodi", "target": pilihan}] if pilihan else [], **status)


def skenario_malam():
    S = []
    # Eka mengaku Stalker: nilai Hostage Eka 0,85; warga lain 0,50.
    sg = [ch(1, "day", 10, "Eka", "Aku Stalker.")]
    ing_h = lambda: buat_ingatan(sg, sampai=(1, "night"), peran="hitman")  # noqa: E731
    ing_s = lambda **k: buat_ingatan(sg, sampai=(1, "night"), peran="spy", **k)  # noqa: E731

    # ---------------------------------------------------------------- Hostage
    S.append(dict(nama="400 Hostage: pindah ikut manusia tepat 15 detik sebelum habis", cerita="Bot memilih Eka, rekan manusia memilih Citra, dan sisa malam tepat 15 detik.",
                  ingatan=ing_h(), view=hitman_malam(15, "Eka", "Citra"),
                  harapan={"aksi": [("hostage", "Citra")], "pindah": True, "tim": {"pemicu": "ikut_manusia", "target_saya": "Citra", "pilihan_rekan": "Citra"}}))
    S.append(dict(nama="401 Hostage: sebelum terkunci bot belum pindah", cerita="Sisa malam 16 detik. Nilai Citra di bawah 80% nilai Eka, jadi bot menyatakan pilihannya.",
                  ingatan=ing_h(), view=hitman_malam(14, "Eka", "Citra"),
                  harapan={"aksi": [("tunggu", None)], "pindah": False, "tim": {"pemicu": "beda", "target_saya": "Eka", "pilihan_rekan": "Citra"}}))
    S.append(dict(nama="402 Hostage: manusia berganti sesudah bot terkunci", cerita="Saat terkunci sudah lewat. Bot tetap, dan pilihan manusia menang seri di engine.",
                  ingatan=ing_h(), view=hitman_malam(20, "Eka", "Citra", sesudah_kunci=True),
                  harapan={"aksi": [("tunggu", None)], "pindah": False, "tim": None}))
    S.append(dict(nama="403 Hostage: terkunci dan manusia belum memilih", cerita="Tidak ada yang diikuti, jadi pilihan bot tetap dan bot diam.",
                  ingatan=ing_h(), view=hitman_malam(15, "Eka"), harapan={"aksi": [("tunggu", None)], "pindah": False, "tim": None}))
    S.append(dict(nama="404 Hostage: belum memilih saat terkunci langsung ikut manusia", cerita="Langkah pertama bot baru terjadi sesudah batas kunci. Ini memilih, bukan pindah.",
                  ingatan=ing_h(), view=hitman_malam(15, None, "Citra"),
                  harapan={"aksi": [("hostage", "Citra")], "pindah": False, "tim": {"pemicu": "ikut_manusia", "target_saya": "Citra"}}))
    S.append(dict(nama="405 Hostage: sebelum terkunci memilih sendiri walau manusia sudah memilih", cerita="Manusia baru diikuti saat terkunci, jadi bot memakai nilainya sendiri.",
                  ingatan=ing_h(), view=hitman_malam(5, None, "Citra"),
                  harapan={"aksi": [("hostage", "Eka")], "pindah": False, "tim": {"pemicu": "beda", "target_saya": "Eka", "pilihan_rekan": "Citra"}}))
    S.append(dict(nama="406 Hostage: rekan bot sudah memilih", cerita="Dodi bot dan sudah memilih Citra. Bot mengikuti, dan sesama bot tidak mengobrol.",
                  ingatan=ing_h(), view=hitman_malam(5, None, "Citra", manusia=False),
                  harapan={"aksi": [("hostage", "Citra")], "pindah": False, "tim": None}))
    S.append(dict(nama="407 Hostage: pilihan manusia diikuti walau gagal dua malam", cerita="Eka gagal dua malam dan biasanya dilewati, tetapi manusia memilih Eka.",
                  ingatan=buat_ingatan(sg, sampai=(3, "night"), peran="hitman"),
                  view=hitman_malam(15, "Andi", "Eka", ronde=3, hasil_sandera=[{"ronde": r, "pemain": "Eka", "berhasil": False} for r in (1, 2)]),
                  harapan={"aksi": [("hostage", "Eka")], "pindah": True}))

    # Eka 0,85, warga lain 0,50 seri menurut nama. daftar = (target, berhasil) tiap malam mulai ronde 1, dan malam sekarang sesudahnya.
    def hasil_malam(daftar):
        return [{"ronde": i, "pemain": t, "berhasil": ok} for i, (t, ok) in enumerate(daftar, 1)]

    def hostage_sesudah(daftar, **status):
        ronde = len(daftar) + 1
        return dict(ingatan=buat_ingatan(sg, sampai=(ronde, "night"), peran="hitman"),
                    view=buat_view(ronde, "night", 10, peran="hitman", spy=2, hasil_sandera=hasil_malam(daftar), **status))

    S.append(dict(nama="408 Hostage: A, A, B, lalu A tetap dilewati", cerita="Eka gagal dua kali, lalu Andi gagal sekali. Gagal di target lain tidak menghapus hitungan Eka.",
                  **hostage_sesudah([("Eka", False), ("Eka", False), ("Andi", False)]),
                  harapan={"aksi": [("hostage", seri_teratas(["Andi", "Budi", "Citra", "Dodi"], 4))], "aksi_bukan": ["Eka"], "pengetahuan": {"gagal_sandera": {"Eka": 2, "Andi": 1}}}))
    S.append(dict(nama="408b Hostage: gagal dua kali tidak harus berturut-turut", cerita="Urutan Eka, Andi, Eka. Eka sudah gagal dua kali walau diselingi Andi.",
                  **hostage_sesudah([("Eka", False), ("Andi", False), ("Eka", False)]),
                  harapan={"aksi": [("hostage", seri_teratas(["Andi", "Budi", "Citra", "Dodi"], 4))], "aksi_bukan": ["Eka"], "pengetahuan": {"gagal_sandera": {"Eka": 2, "Andi": 1}}}))
    S.append(dict(nama="408c Hostage: malam berhasil tidak menghapus hitungan gagal", cerita="Eka gagal, Budi berhasil disandera, lalu Eka gagal lagi.",
                  **hostage_sesudah([("Eka", False), ("Budi", True), ("Eka", False)], sandera={"Budi": 2}),
                  harapan={"aksi": [("hostage", seri_teratas(["Andi", "Citra", "Dodi"], 4))], "aksi_bukan": ["Eka", "Budi"], "pengetahuan": {"gagal_sandera": {"Eka": 2}}}))
    S.append(dict(nama="409 Hostage: dua target yang terus dijaga sama-sama dilewati", cerita="Pola dua Spy saling menjaga: Eka dan Andi masing-masing gagal dua kali, jadi Hitman tidak berputar di keduanya.",
                  **hostage_sesudah([("Eka", False), ("Eka", False), ("Andi", False), ("Eka", False), ("Andi", False)]),
                  harapan={"aksi": [("hostage", seri_teratas(["Budi", "Citra", "Dodi"], 6))], "aksi_bukan": ["Eka", "Andi"], "pengetahuan": {"gagal_sandera": {"Eka": 3, "Andi": 2}}}))
    semua_gagal = [(t, False) for t in ("Andi", "Budi", "Citra", "Dodi", "Eka") for _ in range(2)]
    S.append(dict(nama="409b Hostage: semua target sudah gagal dua kali tetap memilih", cerita="Tidak ada target lain, jadi aturan lewati tidak berlaku dan Hostage tetap terpakai.",
                  **hostage_sesudah(semua_gagal),
                  harapan={"aksi": [("hostage", "Eka")], "pengetahuan": {"gagal_sandera": {"Andi": 2, "Budi": 2, "Citra": 2, "Dodi": 2, "Eka": 2}}}))

    # ---------------------------------------------------------------- Guard
    buka_spy = [{"ronde": 2, "fase": "day", "waktu": jam(2, "day", 12), "aksi": "bela_diri", "jenis": "buka_role", "intent": "defend",
                 "target": "Nara", "alasan": ["Aku Spy."], "pemicu": ["Andi"], "role_diakui": "spy"}]
    sg2 = [ch(2, "day", 5, "Eka", "Aku Stalker.")]
    S.append(dict(nama="410 Guard: role terbuka dan dituduh ronde ini", cerita="Andi menuduh bot di ronde ini sesudah role terbuka, jadi bot menjaga diri walau Eka lebih terancam.",
                  ingatan=buat_ingatan(sg2 + [ch(2, "day", 10, "Andi", "Nara aneh.", "offend", ["Nara"])], sampai=(2, "night"), peran="spy", aksi_bot=buka_spy),
                  view=buat_view(2, "night", 5, peran="spy"), harapan={"aksi": [("guard", "Nara")]}))
    S.append(dict(nama="411 Guard: role terbuka dan di-vote ronde ini", cerita="Tribunal ronde ini Budi vote bot.",
                  ingatan=buat_ingatan(sg2, [(2, "Budi", "Nara")], sampai=(2, "night"), peran="spy", aksi_bot=buka_spy),
                  view=buat_view(2, "night", 5, peran="spy"), harapan={"aksi": [("guard", "Nara")]}))
    S.append(dict(nama="412 Guard: role terbuka tetapi tidak diserang ronde ini", cerita="Tuduhan Andi di ronde lalu, jadi aturan biasa berlaku.",
                  ingatan=buat_ingatan(sg2 + [ch(1, "day", 10, "Andi", "Nara aneh.", "offend", ["Nara"])], sampai=(2, "night"), peran="spy", aksi_bot=buka_spy),
                  view=buat_view(2, "night", 5, peran="spy"), harapan={"aksi": [("guard", "Eka")]}))
    S.append(dict(nama="413 Guard: role belum terbuka walau dituduh", cerita="Bot dituduh, tetapi role belum terbuka, jadi tetap menjaga orang lain.",
                  ingatan=buat_ingatan(sg2 + [ch(2, "day", 10, "Andi", "Nara aneh.", "offend", ["Nara"])], sampai=(2, "night"), peran="spy"),
                  view=buat_view(2, "night", 5, peran="spy"), harapan={"aksi": [("guard", "Eka")]}))
    S.append(dict(nama="414 Guard: target terancam tertinggi", cerita="Tanpa pilihan rekan, Eka yang mengaku Stalker paling terancam.",
                  ingatan=ing_s(), view=spy_malam(5), harapan={"aksi": [("guard", "Eka")], "nilai_aksi": {"Eka": 0.9, "Dodi": 0.0}}))
    S.append(dict(nama="415 Guard: menghindari target rekan Spy", cerita="Rekan manusia sudah menjaga Eka. Sisanya seri, jadi rekan Spy lebih dulu.",
                  ingatan=ing_s(), view=spy_malam(5, None, "Eka"), harapan={"aksi": [("guard", "Dodi")], "aksi_bukan": ["Eka"]}))
    S.append(dict(nama="416 Guard: seri ke rekan Spy lalu nama", cerita="Belum ada chat, semua terancam 0. Rekan Spy Dodi mengalahkan Andi yang namanya lebih awal.",
                  ingatan=buat_ingatan(sampai=(1, "night"), peran="spy"), view=spy_malam(5), harapan={"aksi": [("guard", "Dodi")]}))
    S.append(dict(nama="417 Guard: tidak ada yang diyakini baik", cerita="Pemain lain mati atau disandera, jadi bot menjaga diri sendiri.",
                  ingatan=buat_ingatan(sampai=(2, "night"), peran="spy"),
                  view=buat_view(2, "night", 5, peran="spy", mati=["Andi", "Budi", "Citra"], sandera={"Dodi": 1, "Eka": 1}),
                  harapan={"aksi": [("guard", "Nara")]}))
    s21 = next(s for s in SKENARIO if s["nama"].startswith("21"))
    S.append(dict(nama="418 Guard: tersangka tidak dijaga", cerita="Citra menuduh Dodi. Dodi tersangka kuat, jadi bukan calon Guard.",
                  ingatan=s21["ingatan"], view=s21["view"], harapan={"aksi": [("guard", "Citra")], "aksi_bukan": ["Dodi"]}))
    S.append(dict(nama="419 Guard: pindah bila Spy manusia memilih target sama", cerita="Bot menjaga Eka, lalu rekan manusia juga memilih Eka sebelum bot terkunci.",
                  ingatan=ing_s(), view=spy_malam(10, "Eka", "Eka"),
                  harapan={"aksi": [("guard", "Dodi")], "pindah": True, "tim": {"pemicu": "pindah_sama", "tim": "spy", "target_saya": "Dodi", "pilihan_rekan": "Eka"}}))
    S.append(dict(nama="420 Guard: sesudah terkunci tidak pindah", cerita="Target sama, tetapi sisa malam tepat 15 detik.",
                  ingatan=ing_s(), view=spy_malam(15, "Eka", "Eka"), harapan={"aksi": [("tunggu", None)], "pindah": False, "tim": None}))
    S.append(dict(nama="421 Guard: Spy manusia memilih target lain", cerita="Tidak ada bentrok. Spy tidak mengikuti pilihan manusia.",
                  ingatan=ing_s(), view=spy_malam(10, "Eka", "Andi"), harapan={"aksi": [("tunggu", None)], "pindah": False, "tim": None}))
    S.append(dict(nama="422 Guard: dua bot Spy tidak memilih target sama", cerita="Dodi bot sudah menjaga Eka, jadi bot memilih yang lain.",
                  ingatan=ing_s(), view=spy_malam(5, None, "Eka", manusia=False), harapan={"aksi": [("guard", "Dodi")], "aksi_bukan": ["Eka"], "tim": None}))
    S.append(dict(nama="423 Guard: dua bot Spy bentrok, nama lebih akhir yang pindah", cerita="Nara dan Dodi terlanjur memilih Eka bersamaan. Nara lebih akhir, jadi Nara pindah.",
                  ingatan=ing_s(), view=spy_malam(10, "Eka", "Eka", manusia=False), harapan={"aksi": [("guard", "Dodi")], "pindah": True, "tim": None}))
    S.append(dict(nama="424 Guard: dua bot Spy bentrok, nama lebih awal bertahan", cerita="Bot Andi lebih awal dari Dodi, jadi Andi bertahan.",
                  ingatan=buat_ingatan(sg, sampai=(1, "night"), peran="spy", bot="Andi"),
                  view=spy_malam(10, "Eka", "Eka", manusia=False, bot="Andi"), harapan={"aksi": [("tunggu", None)], "pindah": False}))
    S.append(dict(nama="425 Guard: rekan Spy yang disandera tidak dijaga", cerita="Dodi disandera. Korban tidak bisa disandera lagi, dan chat tim tidak terbaca olehnya.",
                  ingatan=buat_ingatan(sampai=(2, "night"), peran="spy"), view=spy_malam(5, ronde=2, sandera={"Dodi": 1}),
                  harapan={"aksi": [("guard", "Andi")], "aksi_bukan": ["Dodi"], "tim": None}))

    # ---------------------------------------------------------------- Peek
    semua_bersih = [(1, p, "civilian") for p in ("Andi", "Budi", "Citra", "Dodi", "Eka")]
    S.append(dict(nama="430 Peek: semua terlewat tetap dipakai", cerita="Semua pemain lain sudah diperiksa, jadi Peek ke pemain hidup mana pun.",
                  ingatan=buat_ingatan(sampai=(3, "night"), peran="stalker", intel=semua_bersih), view=buat_view(3, "night", 5, peran="stalker", next_peek=3),
                  harapan={"aksi": [("peek", None)], "aksi_bukan": ["Nara"]}))
    S.append(dict(nama="431 Peek: hanya tersisa korban Hostage", cerita="Pemain lain sudah mati, jadi korban pun tetap dipakai sebagai target.",
                  ingatan=buat_ingatan(sampai=(2, "night"), peran="stalker"),
                  view=buat_view(2, "night", 5, peran="stalker", mati=["Andi", "Budi", "Citra", "Dodi"], sandera={"Eka": 1}),
                  harapan={"aksi": [("peek", "Eka")]}))
    S.append(dict(nama="432 Peek: sudah memilih menunggu", cerita="Pilihan malam sudah ada, dan Peek tidak pernah pindah.",
                  ingatan=buat_ingatan(sampai=(1, "night"), peran="stalker"), view=view_malam(1, 15, "stalker", "Dodi"),
                  harapan={"aksi": [("tunggu", None)], "pindah": False, "tim": None}))
    S.append(dict(nama="433 Peek: cooldown tetap tidak bisa", cerita="Peek baru tersedia ronde 3.",
                  ingatan=buat_ingatan(sampai=(2, "night"), peran="stalker"), view=buat_view(2, "night", 5, peran="stalker", next_peek=3),
                  harapan={"aksi": [("tidak_bisa", None)]}))

    # ---------------------------------------------------------------- Chat tim
    S.append(dict(nama="440 Chat tim: Hitman baru memilih target", cerita="Bot memilih Eka dan memberi tahu rekan manusia beserta alasannya.",
                  ingatan=ing_h(), view=hitman_malam(5),
                  harapan={"aksi": [("hostage", "Eka")], "tim": {"pemicu": "pilih_target", "tim": "hitman", "target_saya": "Eka", "pilihan_rekan": None,
                                                                 "alasan": ["Eka mengaku punya role penting.", ], "chat_tim": []}}))
    S.append(dict(nama="441 Chat tim: Spy baru memilih target", cerita="Bot menjaga Eka dan memberi tahu rekan manusia beserta alasannya.",
                  ingatan=ing_s(), view=spy_malam(5),
                  harapan={"aksi": [("guard", "Eka")], "tim": {"pemicu": "pilih_target", "tim": "spy", "target_saya": "Eka", "alasan": ["Eka mengaku Stalker."]}}))
    S.append(dict(nama="442 Chat tim: Hitman setuju", cerita="Bot memilih Andi (0,50), rekan memilih Eka (0,85). Nilai target rekan ≥ 80%.",
                  ingatan=ing_h(), view=hitman_malam(5, "Andi", "Eka"),
                  harapan={"aksi": [("tunggu", None)], "tim": {"pemicu": "setuju", "target_saya": "Andi", "pilihan_rekan": "Eka"}}))
    S.append(dict(nama="443 Chat tim: Hitman setuju pada nilai sama", cerita="Andi dan Budi sama-sama 0,50.",
                  ingatan=ing_h(), view=hitman_malam(5, "Andi", "Budi"), harapan={"tim": {"pemicu": "setuju", "pilihan_rekan": "Budi"}}))
    S.append(dict(nama="444 Chat tim: bot tidak chat bila rekan semuanya bot", cerita="Dodi bot.",
                  ingatan=ing_h(), view=hitman_malam(5, manusia=False), harapan={"aksi": [("hostage", "Eka")], "tim": None}))
    S.append(dict(nama="445 Chat tim: rekan manusia sudah tersingkir", cerita="Dodi manusia sudah mati, jadi tidak ada yang membaca. Engine sudah menyaringnya, dan otak menyaring lagi.",
                  ingatan=ing_h(), view=hitman_malam(5, mati=["Dodi"], can_team_chat=True), harapan={"aksi": [("hostage", "Eka")], "tim": None}))
    S.append(dict(nama="446 Chat tim: bot Spy disandera", cerita="Bot kehilangan aksi dan chat tim.",
                  ingatan=ing_s(), view=spy_malam(5, hostage=True, can_team_chat=False), harapan={"aksi": [("tidak_bisa", None)], "tim": None}))
    S.append(dict(nama="447 Chat tim: room tanpa kanal", cerita="Room satu Hitman: engine tidak memberi kanal.",
                  ingatan=ing_h(), view=view_malam(1, 5, "hitman"), harapan={"aksi": [("hostage", "Eka")], "tim": None}))
    S.append(dict(nama="448 Chat tim: tiga pesan malam ini sudah terkirim", cerita="Batas 3 pesan per malam.",
                  ingatan=_dengan_chat_tim(ing_h(), [("pilih_target", None, True), ("beda", "Andi", True), ("setuju", "Budi", True)]),
                  view=hitman_malam(5, "Eka", "Citra"), harapan={"tim": None}))
    S.append(dict(nama="449 Chat tim: kalimat kosong tidak dihitung", cerita="Dua terkirim dan satu kosong, jadi masih ada jatah.",
                  ingatan=_dengan_chat_tim(ing_h(), [("pilih_target", None, True), ("beda", "Andi", False), ("setuju", "Budi", True)]),
                  view=hitman_malam(5, "Eka", "Citra"), harapan={"tim": {"pemicu": "beda", "pilihan_rekan": "Citra"}}))
    S.append(dict(nama="450 Chat tim: pilihan rekan yang sama hanya ditanggapi sekali", cerita="Bot sudah menanggapi pilihan Citra.",
                  ingatan=_dengan_chat_tim(ing_h(), [("beda", "Citra", True)]), view=hitman_malam(5, "Eka", "Citra"), harapan={"aksi": [("tunggu", None)], "tim": None}))
    S.append(dict(nama="451 Chat tim: tanpa pemicu baru bot diam", cerita="Pilihan bot dan rekan sama, tidak ada yang perlu dikabarkan.",
                  ingatan=ing_h(), view=hitman_malam(5, "Eka", "Eka"), harapan={"aksi": [("tunggu", None)], "tim": None}))
    S.append(dict(nama="452 Chat tim: Guard berulang tetap dikabarkan", cerita="Semalam menjaga Eka dan malam ini menjaga Eka lagi.",
                  ingatan=buat_ingatan(sg, sampai=(2, "night"), peran="spy"), view=spy_malam(5, ronde=2, last_guard="Eka"),
                  harapan={"aksi": [("guard", "Eka")], "tim": {"pemicu": "pilih_target", "target_saya": "Eka"}}))
    return S


# Catatan chat tim buatan pada ronde 1: (pemicu, pilihan rekan, terkirim).
def _dengan_chat_tim(ingatan, catatan):
    view = {"ronde": 1}
    for pemicu, pilihan, terkirim in catatan:
        ingatan.catat_chat_tim(view, {"pemicu": pemicu, "target_saya": "Eka", "pilihan_rekan": pilihan}, terkirim)
    return ingatan


SKENARIO += skenario_malam()

# Skenario Fase 9 (nomor 500–599), di sel sendiri: seri Hostage acak stabil dan klaim pengaku yang terbukti Hitman.
def skenario_fase9():
    S = []
    peek_budi = ch(2, "day", 10, "Dodi", "Aku Stalker, semalam aku peek Budi, dia Hitman.", "offend", ["Budi"])
    bersih_citra = ch(2, "day", 10, "Dodi", "Aku Stalker, semalam aku peek Citra, dia bukan Hitman.", "defend", ["Citra"])
    S.append(dict(nama="500 Tuduhan Peek dari pengaku yang terbukti Hitman diabaikan", cerita="Dodi mengaku Peek Budi sebagai Hitman, lalu Dodi dieksekusi dan terbukti Hitman.",
                  ingatan=buat_ingatan([peek_budi], eksekusi=[(2, "Dodi", True)], sampai=(3, "day")), view=buat_view(3, "day", 30, mati=["Dodi"]),
                  harapan={"tabel": {"Budi": {"klaim_role_bermasalah": 0.0}, "Dodi": {"klaim_role_bermasalah": 1.0}}}))
    S.append(dict(nama="501 Klaim bersih dari pengaku yang terbukti Hitman batal", cerita="Dodi mengaku Peek Citra bersih, lalu Dodi dieksekusi dan terbukti Hitman.",
                  ingatan=buat_ingatan([bersih_citra], eksekusi=[(2, "Dodi", True)], sampai=(3, "day")), view=buat_view(3, "day", 30, mati=["Dodi"]),
                  harapan={"tabel": {"Citra": {"bersih_klaim": 0.0}}}))
    S.append(dict(nama="502 Hitman hasil Peek tidak membuat pengaku lain bentrok", cerita="Stalker bot sudah Peek Dodi sebagai Hitman. Dodi dan Eka sama-sama mengaku Spy, padahal Spy hanya satu.",
                  ingatan=buat_ingatan([ch(2, "day", 10, "Dodi", "Aku Spy."), ch(2, "day", 20, "Eka", "Aku Spy.")], sampai=(2, "day"), peran="stalker", intel=[(1, "Dodi", "hitman")]),
                  view=buat_view(2, "day", 40, peran="stalker"),
                  harapan={"tabel": {"Eka": {"klaim_role_bermasalah": 0.0}, "Dodi": {"klaim_role_bermasalah": 1.0}}, "konteks": {"klaim_bentrok": []}}))
    S.append(dict(nama="503 Pengaku palsu yang sudah mati tetap tidak dipercaya", cerita="Stalker bot tahu Dodi bohong mengaku Stalker. Dodi dieksekusi, perannya tidak diumumkan, dan tuduhan Peeknya ke Budi tetap diabaikan.",
                  ingatan=buat_ingatan([peek_budi], eksekusi=[(2, "Dodi")], sampai=(3, "day"), peran="stalker"), view=buat_view(3, "day", 30, peran="stalker", mati=["Dodi"]),
                  harapan={"tabel": {"Budi": {"klaim_role_bermasalah": 0.0}}}))
    S.append(dict(nama="504 Pengaku hidup yang belum terbukti tetap bentrok", cerita="Pembanding 502 untuk Civilian: bot tidak tahu siapa yang bohong, jadi Dodi dan Eka bentrok.",
                  ingatan=buat_ingatan([ch(2, "day", 10, "Dodi", "Aku Spy."), ch(2, "day", 20, "Eka", "Aku Spy.")], sampai=(2, "day")),
                  view=buat_view(2, "day", 40), harapan={"tabel": {"Eka": {"klaim_role_bermasalah": 0.6}}, "konteks": {"klaim_bentrok": ["Dodi", "Eka"]}}))

    # Seri Hostage: tanpa chat semua warga bernilai sama, jadi pilihan mengikuti seri_acak, bukan nama abjad pertama.
    calon_seri = [p for p in PEMAIN_DEMO if p != BOT_DEMO]
    for ronde in (1, 2):
        pilihan = min(calon_seri, key=lambda p: seri_acak(BOT_DEMO, ronde, p))
        S.append(dict(nama=f"51{ronde - 1} Seri Hostage diacak stabil, ronde {ronde}", cerita=f"Semua warga bernilai sama. Urutan seri_acak menunjuk {pilihan}.",
                      ingatan=buat_ingatan(sampai=(ronde, "night"), peran="hitman"), view=view_malam(ronde, 10, "hitman"),
                      harapan={"aksi": [("hostage", pilihan)]}))
    return S


SKENARIO += skenario_fase9()

# Skenario perbaikan 7 November 2026 (nomor 600–699), di sel sendiri: semua jenis tuduh Hitman dinilai, malam klaim Peek yang
# mungkin, dan klaim Peek (Hitman maupun bersih) yang tidak diulang di ronde yang sama.
def skenario_perbaikan():
    S = []
    peek_budi = [ch(3, "day", 10, "Citra", "Aku Stalker, semalam aku peek Budi, dia Hitman.", "offend", ["Budi"])]
    S.append(dict(nama="600 Korban Gag yang lemah tidak menutup pelintir bukti",
                  cerita="Skenario 154 ditambah korban Gag tim Andi. Serang Andi hanya bernilai 15, pelintir ke kambing hitam Budi 50, jadi Budi yang dituduh.",
                  ingatan=buat_ingatan(peek_budi, sampai=(3, "day"), peran="hitman"),
                  view=buat_view(3, "day", 40, peran="hitman", next_gag=5, korban_gag_tim=["Andi"]),
                  harapan={"chat": [("tuduh", "Budi")], "jenis": "pelintir_bukti"}))
    S.append(dict(nama="601 Nilai tuduh sama: urutan jenis rancangan",
                  cerita="Korban Gag tim juga kambing hitam teratas. Serang korban Gag dan pelintir bukti bernilai sama, jadi serang korban Gag dipilih.",
                  ingatan=buat_ingatan(peek_budi, sampai=(3, "day"), peran="hitman"),
                  view=buat_view(3, "day", 40, peran="hitman", next_gag=5, korban_gag_tim=["Budi"]),
                  harapan={"chat": [("tuduh", "Budi")], "jenis": "serang_korban_gag", "pesan_bukan": ["gag"]}))

    # Klaim Peek: Stalker Peek di malam ronde 1, lalu tiap dua malam (engine: next_peek = ronde + 2).
    suara_nara = {"Andi": "Nara", "Budi": "Nara", "Citra": "Nara"}
    for nomor, ronde, bukti in (("602", 3, "di malam ronde 1 peek Andi, dia Hitman"), ("603", 4, "semalam peek Andi, dia Hitman")):
        peek_nara = [ch(ronde, "day", 10, "Andi", "Aku Stalker, semalam aku peek Nara, dia Hitman.", "offend", ["Nara"])]
        bela = [{"ronde": ronde, "fase": "tribunal", "waktu": jam(ronde, "tribunal", 2), "aksi": "bela_diri", "intent": "defend", "target": "Nara"}]
        S.append(dict(nama=f"{nomor} Klaim Peek palsu di Tribunal ronde {ronde} menyebut malam yang mungkin",
                      cerita=f"Skenario 100 di ronde {ronde}. Stalker asli hanya bisa Peek di malam 1, 3, 5, ..., jadi klaimnya menyebut malam "
                             f"{'ronde 1, bukan semalam' if ronde == 3 else '3 sebagai semalam'}.",
                      ingatan=buat_ingatan(peek_nara, sampai=(ronde, "tribunal"), peran="hitman", aksi_bot=bela),
                      view=buat_view(ronde, "tribunal", 30, peran="hitman", suara=suara_nara),
                      harapan={"chat": [("tuduh", "Andi")], "jenis": "klaim_peek", "role_diakui": "stalker", "bukti_klaim": bukti,
                               **({"pesan_bukan": ["semalam"]} if ronde == 3 else {})}))
    S.append(dict(nama="604 Hasil Peek lama menyebut malam Peek yang sebenarnya",
                  cerita="Stalker Peek Dodi di malam ronde 1 dan baru mengungkapnya di siang ronde 3, jadi kalimatnya tidak berkata semalam.",
                  ingatan=buat_ingatan(sampai=(3, "day"), peran="stalker", intel=[(1, "Dodi", "hitman")]),
                  view=buat_view(3, "day", 30, peran="stalker", next_peek=3),
                  harapan={"chat": [("tuduh", "Dodi")], "jenis": "hasil_peek", "bukti_klaim": "di malam ronde 1 peek Dodi, dia Hitman",
                           "pesan_bukan": ["semalam"]}))

    # Klaim yang sudah diucapkan siang tidak diulang di Tribunal ronde yang sama. Catatan aksi_bot berbentuk catat_aksi_bot.
    ungkap_r2 = [{"ronde": 2, "fase": "day", "waktu": jam(2, "day", 5), "aksi": "tuduh", "intent": "offend", "target": "Dodi",
                  "alasan": ["Aku Stalker, semalam aku peek Dodi: dia Hitman."], "jenis": "hasil_peek", "pemicu": None, "role_diakui": "stalker"}]
    S.append(dict(nama="605 Klaim Peek siang tidak diulang di Tribunal",
                  cerita="Stalker sudah mengungkap Dodi di siang ronde 2. Di Tribunal ronde itu ia tidak mengulang klaim, tetapi menjelaskan vote ke Dodi.",
                  ingatan=buat_ingatan(sampai=(2, "tribunal"), peran="stalker", intel=[(1, "Dodi", "hitman")], aksi_bot=ungkap_r2),
                  view=buat_view(2, "tribunal", 30, peran="stalker", next_peek=3),
                  harapan={"chat": [("tuduh", "Dodi")], "jenis": "jelaskan_vote", "role_diakui": None, "vote": [("vote", "Dodi")]}))
    S.append(dict(nama="606 Klaim Peek diungkap lagi di ronde berikutnya",
                  cerita="Dodi lolos dari Tribunal ronde 2. Siang ronde 3 adalah diskusi baru, jadi Stalker mengungkapnya lagi dengan malam Peek yang benar.",
                  ingatan=buat_ingatan(sampai=(3, "day"), peran="stalker", intel=[(1, "Dodi", "hitman")], aksi_bot=ungkap_r2),
                  view=buat_view(3, "day", 30, peran="stalker", next_peek=3),
                  harapan={"chat": [("tuduh", "Dodi")], "jenis": "hasil_peek", "bukti_klaim": "di malam ronde 1 peek Dodi, dia Hitman"}))
    bela_klaim = [{"ronde": 3, "fase": "day", "waktu": jam(3, "day", 20), "aksi": "bela_orang", "intent": "defend", "target": "Citra",
                   "alasan": ["Aku Stalker, aku sudah peek Citra: dia bukan Hitman."], "jenis": "peek_bersih", "pemicu": None, "role_diakui": "stalker"}]
    S.append(dict(nama="607 Klaim Peek bersih siang tidak diulang di Tribunal",
                  cerita="Stalker sudah mengklaim Peek bersih Citra di siang ronde 3. Di Tribunal Citra masih terancam, jadi Stalker membelanya lagi tanpa mengulang klaim.",
                  ingatan=buat_ingatan([ch(3, "day", d, p, "Citra aneh.", "offend", ["Citra"]) for d, p in ((10, "Andi"), (15, "Budi"))],
                                       sampai=(3, "tribunal"), peran="stalker", intel=[(2, "Citra", "civilian")], aksi_bot=bela_klaim),
                  view=buat_view(3, "tribunal", 30, peran="stalker", next_peek=4, suara={"Andi": "Citra", "Budi": "Citra"}),
                  harapan={"chat": [("bela_orang", "Citra")], "jenis": "yakin_bersih", "role_diakui": None, "pesan_bukan": ["peek"]}))
    return S


SKENARIO += skenario_perbaikan()

# Membandingkan keputusan dengan harapan skenario; hasilnya daftar pelanggaran.
def cek_harapan(hasil, harapan):
    rc, rv, ra, urutan = hasil["rencana_chat"], hasil["rencana_vote"], hasil["rencana_aksi"], hasil["urutan_tersangka"]

    def cocok(rencana, pilihan):
        return any(rencana["aksi"] == aksi and (target is None or rencana["target"] == target)
                   for aksi, target in pilihan)

    gagal = []
    if "chat" in harapan and not cocok(rc, harapan["chat"]):
        gagal.append(f"chat {rc['aksi']}→{rc['target']}, harapan {harapan['chat']}")
    if "chat_bukan" in harapan and cocok(rc, harapan["chat_bukan"]):
        gagal.append(f"chat {rc['aksi']}→{rc['target']} seharusnya tidak dipilih")
    for kunci in ("jenis", "role_diakui", "bukti_klaim", "relasi_tambahan", "pemicu"):
        if kunci in harapan and rc.get(kunci) != harapan[kunci]:
            gagal.append(f"{kunci} {rc.get(kunci)}, harapan {harapan[kunci]}")
    if rc.get("jenis") in harapan.get("jenis_bukan", []):
        gagal.append(f"jenis {rc.get('jenis')} seharusnya tidak dipilih")
    for teks in harapan.get("pesan_bukan", []):
        if teks in hasil["npc_decision"]["message"].casefold():
            gagal.append(f"pesan memuat '{teks}'")
    for kunci, nilai in harapan.get("paket", {}).items():
        if (rc.get("paket") or {}).get(kunci) != nilai:
            gagal.append(f"paket {kunci} = {(rc.get('paket') or {}).get(kunci)}, harapan {nilai}")
    for teks in harapan.get("paket_bukan", []):
        if teks in json.dumps(rc.get("paket"), ensure_ascii=False).casefold():
            gagal.append(f"paket memuat '{teks}'")
    if "vote" in harapan and not cocok(rv, harapan["vote"]):
        gagal.append(f"vote {rv['aksi']}→{rv['target']}, harapan {harapan['vote']}")
    if "vote_pindah" in harapan and bool(hasil["npc_decision"].get("pindah")) != harapan["vote_pindah"]:
        gagal.append(f"pindah {hasil['npc_decision'].get('pindah')}, harapan {harapan['vote_pindah']}")
    if "vote_paksa" in harapan and bool(rv.get("paksa")) != harapan["vote_paksa"]:
        gagal.append(f"vote paksa {rv.get('paksa')}, harapan {harapan['vote_paksa']}")
    if "vote_bukan" in harapan and rv["target"] in harapan["vote_bukan"]:
        gagal.append(f"vote ke {rv['target']} seharusnya dihindari")
    if "aksi" in harapan and not cocok(ra, harapan["aksi"]):
        gagal.append(f"aksi {ra['aksi']}→{ra['target']}, harapan {harapan['aksi']}")
    if "pindah" in harapan and bool(ra.get("pindah")) != harapan["pindah"]:
        gagal.append(f"pindah {ra.get('pindah')}, harapan {harapan['pindah']}")
    if "tim" in harapan:
        tim = hasil["nlg_tim"]
        if (tim is None) != (harapan["tim"] is None):
            gagal.append(f"nlg_tim {tim}, harapan {harapan['tim']}")
        gagal += [f"nlg_tim {kunci} = {tim.get(kunci)}, harapan {nilai}" for kunci, nilai in (harapan["tim"] or {}).items()
                  if tim is not None and tim.get(kunci) != nilai]
    if "aksi_bukan" in harapan and ra["target"] in harapan["aksi_bukan"]:
        gagal.append(f"aksi ke {ra['target']} seharusnya dihindari")
    if "tersangka" in harapan and urutan[:1] != [harapan["tersangka"]]:
        gagal.append(f"tersangka teratas {urutan[:1]}, harapan {harapan['tersangka']}")
    if "dua_teratas" in harapan and set(urutan[:2]) != set(harapan["dua_teratas"]):
        gagal.append(f"dua teratas {urutan[:2]}, harapan {harapan['dua_teratas']}")
    for sumber in ("tabel", "fitur_hitman"):
        for pemain, kolom in harapan.get(sumber, {}).items():
            baris = baris_pemain(hasil[sumber], pemain)
            gagal += [f"{sumber} {pemain}.{k} = {float(baris[k]):.4f}, harapan {v:.4f}" for k, v in kolom.items()
                      if abs(float(baris[k]) - v) > 1e-9]
    for pemain in harapan.get("bukan_fitur_hitman", []):
        if pemain in set(hasil["fitur_hitman"]["pemain"]):
            gagal.append(f"{pemain} seharusnya tidak ada di fitur_hitman")
    for sumber in ("konteks", "pengetahuan"):
        for kunci, nilai in harapan.get(sumber, {}).items():
            if hasil[sumber][kunci] != nilai:
                gagal.append(f"{sumber} {kunci} = {hasil[sumber][kunci]}, harapan {nilai}")
    if "warga_terdesak_min" in harapan and hasil["konteks"]["warga_terdesak"] < harapan["warga_terdesak_min"]:
        gagal.append(f"warga_terdesak {hasil['konteks']['warga_terdesak']:.2f} < {harapan['warga_terdesak_min']}")
    # Nilai tiap target di jejak aksi: 0–100 bila memakai sistem fuzzy, 0–1 bila tanpa sistem.
    for target, nilai in harapan.get("nilai_aksi", {}).items():
        ada = hasil["jejak_aksi"][hasil["jejak_aksi"]["target"] == target]["prioritas"].tolist()
        if not ada or abs(ada[0] - nilai) > 1e-3:
            gagal.append(f"nilai aksi {target} = {ada}, harapan {nilai}")
    if harapan.get("chat_tanpa_nilai") and (rc["skor"] is not None or "prioritas" in hasil["jejak_chat"]):
        gagal.append(f"chat {rc['aksi']} seharusnya tanpa nilai, skor {rc['skor']}")
    for teks in harapan.get("alasan_bukan", []):
        if any(teks in a for rencana in (rc, rv, ra) for a in rencana["alasan"]):
            gagal.append(f"alasan menyebut '{teks}'")
    for rekan in harapan.get("rekan_aman", []):
        # Rekan Syndicate tidak pernah dituduh, di-vote, disandera/di-Gag, atau masuk urutan kambing hitam.
        if (rc["intent"] == "offend" and rc["target"] == rekan) or rekan in (rv["target"], ra["target"]) \
                or rekan in urutan:
            gagal.append(f"rekan Syndicate {rekan} ikut ditarget")
    return gagal
# fmt: on


class SkenarioFuzzyTests(unittest.TestCase):
    def test_jumlah_skenario_sama_dengan_notebook(self):
        self.assertEqual(len(SKENARIO), 328)
        self.assertEqual(len({s["nama"] for s in SKENARIO}), 328)

    def test_semua_skenario_lulus(self):
        for s in SKENARIO:
            with self.subTest(s["nama"]):
                self.assertEqual(cek_harapan(putuskan(s["ingatan"], s["view"]), s["harapan"]), [], s["cerita"])

    # Seri acak tidak selalu jatuh ke nama abjad pertama, dan hasilnya sama setiap kali dihitung.
    def test_seri_acak_stabil_dan_tidak_selalu_abjad(self):
        urut_seri = [min(PEMAIN_DEMO[1:], key=lambda p: seri_acak(BOT_DEMO, r, p)) for r in range(1, 9)]
        self.assertGreater(len(set(urut_seri)), 1)
        self.assertEqual(urut_seri, [min(PEMAIN_DEMO[1:], key=lambda p: seri_acak(BOT_DEMO, r, p)) for r in range(1, 9)])

    # Kalimat kembar dari uji main 7 November 2026: klaim Peek siang tidak terulang persis di Tribunal ronde yang sama, juga lewat
    # templat NLG yang menaruh kalimat mirip di belakang (semua varian hasil_peek saling mirip, jadi dulu varian sama terpilih lagi).
    def test_klaim_peek_tidak_kembar_siang_lalu_tribunal(self):
        intel, konteks = [(1, "Dodi", "hitman")], {"roster": PEMAIN_DEMO, "chat_terbaru": []}
        siang, view_siang = buat_ingatan(sampai=(2, "day"), peran="stalker", intel=intel), buat_view(2, "day", 30, peran="stalker", next_peek=3)
        hasil_siang = putuskan(siang, view_siang)
        teks_siang = tulis_pesan(hasil_siang["nlg"], konteks, None, "gaul")["teks"]
        siang.catat_aksi_bot(view_siang, hasil_siang["rencana_chat"])
        tribunal = buat_ingatan(sampai=(2, "tribunal"), peran="stalker", intel=intel, aksi_bot=siang.aksi_bot)
        hasil_tribunal = putuskan(tribunal, buat_view(2, "tribunal", 30, peran="stalker", next_peek=3))
        teks_tribunal = tulis_pesan(hasil_tribunal["nlg"], konteks, None, "gaul", hindari=(teks_siang,))["teks"]
        self.assertEqual(hasil_siang["rencana_chat"]["jenis"], "hasil_peek")
        self.assertNotEqual(hasil_tribunal["rencana_chat"]["jenis"], "hasil_peek")
        self.assertNotEqual(teks_tribunal, teks_siang)
