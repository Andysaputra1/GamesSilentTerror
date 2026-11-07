"""Pengujian payload, pemeriksa aturan, templat per jenis, dan prompt npc_nlg, tanpa LLM dan tanpa IndoBERT.

Dipindah dari notebook skripsi (sel pengujian payload dan templat). Kasus bawaan satu per kelompok templat ikut disalin.
Di notebook, rencana juga dimuat dari hasil_npc/nlg_fuzzy.jsonl hasil simulasi; di sini hanya kasus bawaan, jadi
pengujian yang memeriksa semua rencana berjalan di kasus bawaan saja.
"""

import re
import unittest

from app.bot.nlg import (
    MAKSUD_AKSI,
    PERSONA,
    VARIASI,
    buat_prompt,
    fakta_disalin,
    kalimat_templat,
    kelompok_varian,
    klaim_diri,
    nilai_kalimat,
    periksa_aturan,
    tulis_pesan,
)

# fmt: off
PEMAIN_DEMO = ["Nara", "Andi", "Budi", "Citra", "Dodi", "Eka"]
CHAT_DEMO = [
    {"pengirim": "Andi", "teks": "Semalam siapa yang kena?", "intent": "neutral", "target": []},
    {"pengirim": "Budi", "teks": "Aku curiga Citra, dari tadi ngalihin terus.", "intent": "offend",
     "target": [{"pemain": "Citra", "relasi": "offend"}]},
    {"pengirim": "Citra", "teks": "Kok aku? Justru Nara yang aneh.", "intent": "offend",
     "target": [{"pemain": "Nara", "relasi": "offend"}]},
    {"pengirim": "Andi", "teks": "Nara, menurutmu siapa?", "intent": "neutral",
     "target": [{"pemain": "Nara", "relasi": "neutral"}]},
]


# Payload seperti keluaran siapkan_nlg (tanpa role asli); rencana jawab membawa penanya dan paket.
def payload(aksi, intent, target, bukti, role=None, bukti_klaim=None, relasi=(), pembicara="Nara", penanya=None, jenis=None, paket=None):
    return {"pembicara": pembicara, "aksi": aksi, "jenis": jenis, "intent": intent, "target": target, "role_diakui": role,
            "bukti_klaim": bukti_klaim, "relasi_tambahan": list(relasi), "bukti": list(bukti),
            **({"penanya": penanya} if penanya else {}), **({"paket": paket} if paket else {})}


def kasus(nama, peran, p):
    return {"sumber": nama, "metode": "bawaan", "peran": peran, "ronde": 2, "fase": "day",
            "roster": PEMAIN_DEMO, "chat_terbaru": CHAT_DEMO, "payload": p}


# Bentuk yang sama dengan paket_jawab di npc_fuzzy.
def paket_jawab_demo(pertanyaan, penanya="Andi", tersangka=None, pendapat=None, tindakan=(), kondisi="ragu", chat_saya=0):
    return {"pertanyaan": pertanyaan, "penanya": penanya, "kondisi": kondisi, "tersangka": tersangka, "pendapat_pemain": pendapat or {},
            "tindakan_sebelumnya": list(tindakan), "jawaban_role": "aku orang baik", "chat_saya_ronde_ini": chat_saya}


DIRI = [{"pemain": "Nara", "relasi": "defend"}]
BAHAYA = "Kalau salah vote kita bisa kalah."
TERSANGKA_CITRA = {"nama": "Citra", "alasan": ["Citra ikut mendorong eksekusi Dodi (ronde 1), padahal game berlanjut jadi Dodi bukan Hitman."]}
# Satu kasus per kelompok templat, supaya semua jenis teruji walaupun notebook NPC belum dijalankan. Nomor B22 adalah rencana D29 di
# uji model: Spy membuka role dengan bukti jaga, yang dulu selalu jatuh ke templat karena pemeriksa tidak mengenal klaim Spy.
KASUS_BAWAAN = [
    kasus("B01 hasil Peek", "stalker", payload("tuduh", "offend", "Budi", ["Aku Stalker, semalam aku peek Budi: dia Hitman."], "stalker", "semalam peek Budi, dia Hitman", jenis="hasil_peek")),
    kasus("B02 bela diri", "civilian", payload("bela_diri", "defend", "Nara", ["Aku bukan Hitman; tuduhan ke aku belum punya bukti."], jenis="tanpa_bukti")),
    kasus("B03 jawab menuduh", "spy", payload("jawab", "offend", "Citra", TERSANGKA_CITRA["alasan"], penanya="Andi",
                                               paket=paket_jawab_demo("Nara, menurutmu siapa?", tersangka=TERSANGKA_CITRA, kondisi="agak yakin"))),
    kasus("B04 jawab netral", "civilian", payload("jawab", "neutral", None, [], penanya="Andi", paket=paket_jawab_demo("Nara, menurutmu siapa?"))),
    kasus("B05 bela orang", "civilian", payload("bela_orang", "defend", "Andi", ["Belum ada bukti kuat kalau Andi Hitman."], jenis="belum_ada_bukti")),
    kasus("B06 peek bersih", "stalker", payload("bela_orang", "defend", "Eka", ["Aku Stalker, aku sudah peek Eka: dia bukan Hitman."], "stalker", "sudah peek Eka, dia bukan Hitman", jenis="peek_bersih")),
    kasus("B07 tuduh", "civilian", payload("tuduh", "offend", "Citra", ["Eka sempat menuduh Citra, lalu Eka disandera (malam ronde 2)."], jenis="alasan_curiga")),
    kasus("B08 klaim palsu Hitman", "hitman", payload("tuduh", "offend", "Andi", ["Aku Stalker, semalam aku peek Andi, dia Hitman."], "stalker", "semalam peek Andi, dia Hitman", jenis="klaim_peek")),
    kasus("B10 pemain diam", "spy", payload("tanya_info", "neutral", "Eka", ["Eka belum bicara di ronde ini."], jenis="pemain_diam")),
    kasus("B11 tanya info", "civilian", payload("tanya_info", "neutral", None, [], jenis="pertanyaan_umum")),
    kasus("B12 tanya info + konflik klaim", "stalker", payload("tanya_info", "neutral", None, ["Andi dan Citra mengaku role yang sama."], jenis="klaim_bentrok")),
    kasus("B13 Hitman menuduh kambing hitam", "hitman", payload("tuduh", "offend", "Budi", ["3 pemain menuduh atau vote Budi."], jenis="pelintir_bukti")),
    kasus("B14 Hitman bela diri", "hitman", payload("bela_diri", "defend", "Nara", ["Aku bukan Hitman; tuduhan ke aku belum punya bukti."], jenis="tanpa_bukti")),
    kasus("B15 pancingan saat hening", "civilian", payload("tanya_info", "neutral", None, ["Kok sepi ya, belum ada yang cerita."], jenis="ruangan_hening")),
    # Dipanggil lewat "kamu" (target neutral dari IndoBERT) dengan pertanyaan tentang aksi malam: jawaban tetap netral
    # dan tidak boleh mengaku role atau aksi.
    dict(kasus("B16 jawab panggilan 'kamu'", "spy", payload("jawab", "neutral", None, [], penanya="Dodi", paket=paket_jawab_demo("Terus kamu semalam Guard siapa?", "Dodi"))),
         chat_terbaru=CHAT_DEMO[:3] + [{"pengirim": "Dodi", "teks": "Terus kamu semalam Guard siapa?", "intent": "neutral",
                                        "target": [{"pemain": "Nara", "relasi": "neutral"}]}]),
    kasus("B17 bela diri tunjuk orang", "civilian", payload("bela_diri", "offend", "Citra", ["Aku bukan Hitman, yang lebih mencurigakan justru Citra.", "2 pemain menuduh atau vote Citra."], relasi=DIRI, jenis="tunjuk_orang")),
    kasus("B18 bela diri terlalu awal", "civilian", payload("bela_diri", "defend", "Nara", ["Jangan vote aku, masih terlalu awal, buktinya belum ada."], jenis="terlalu_awal")),
    kasus("B19 bela diri bahaya salah vote", "civilian", payload("bela_diri", "defend", "Nara", [f"Jangan vote aku, {BAHAYA.lower()}"], jenis="bahaya_salah_vote")),
    kasus("B20 buka role Civilian palsu", "hitman", payload("bela_diri", "defend", "Nara", ["Jangan vote aku, aku cuma Civilian."], "civilian", jenis="buka_role")),
    kasus("B21 buka role Spy tanpa bukti", "spy", payload("bela_diri", "defend", "Nara", ["Jangan vote aku, aku Spy."], "spy", jenis="buka_role")),
    kasus("B22 buka role Spy + bukti jaga", "spy", payload("bela_diri", "defend", "Nara", ["Jangan vote aku, aku Spy, aku semalam jaga Budi."], "spy", "semalam jaga Budi", jenis="role_bukti_aksi")),
    kasus("B23 Spy palsu Hitman", "hitman", payload("bela_diri", "defend", "Nara", ["Jangan vote aku, aku Spy, aku semalam jaga Eka."], "spy", "semalam jaga Eka", jenis="role_bukti_aksi")),
    kasus("B24 buka role Stalker, Peek bersih", "stalker", payload("bela_diri", "defend", "Nara", ["Jangan vote aku dan Budi, aku Stalker, aku semalam peek Budi, dia bukan Hitman."], "stalker", "semalam peek Budi, dia bukan Hitman",
                                                                   [{"pemain": "Budi", "relasi": "defend"}], jenis="role_bukti_aksi")),
    kasus("B25 buka role Stalker, Peek Hitman", "stalker", payload("bela_diri", "defend", "Nara", ["Aku bukan Hitman, justru Budi yang Hitman. Aku Stalker, aku kemarin peek Budi, dia Hitman."], "stalker", "kemarin peek Budi, dia Hitman",
                                                                   [{"pemain": "Budi", "relasi": "offend"}], jenis="role_bukti_aksi")),
    kasus("B26 tunjuk orang saat kritis", "civilian", payload("bela_diri", "offend", "Citra", ["Aku bukan Hitman, yang lebih mencurigakan justru Citra.", BAHAYA], relasi=DIRI, jenis="tunjuk_orang_bahaya")),
    kasus("B27 yakin bersih", "spy", payload("bela_orang", "defend", "Budi", ["Aku yakin Budi bukan Hitman."], jenis="yakin_bersih")),
    kasus("B28 diklaim bersih", "civilian", payload("bela_orang", "defend", "Budi", ["Eka yang ngaku Stalker bilang Budi bersih."], jenis="diklaim_bersih")),
    kasus("B29 bela orang terlalu awal", "civilian", payload("bela_orang", "defend", "Budi", ["Jangan vote Budi dulu, masih terlalu awal."], jenis="terlalu_awal")),
    kasus("B30 ada pembela", "civilian", payload("bela_orang", "defend", "Budi", ["Tuduhan ke Budi masih pendapat, ada yang membela juga."], jenis="ada_pembela")),
    kasus("B31 ada pembela saat kritis", "civilian", payload("bela_orang", "defend", "Budi", ["Tuduhan ke Budi masih pendapat, ada yang membela juga.", BAHAYA], jenis="ada_pembela_bahaya")),
    kasus("B32 belum ada bukti saat kritis", "civilian", payload("bela_orang", "defend", "Budi", ["Belum ada bukti kuat kalau Budi Hitman.", BAHAYA], jenis="belum_ada_bukti_bahaya")),
    kasus("B33 serang korban Gag", "hitman", payload("tuduh", "offend", "Citra", ["Citra dari tadi diam aja."], jenis="serang_korban_gag")),
    kasus("B34 balik tuduh", "hitman", payload("tuduh", "offend", "Andi", ["Andi nuduh aku tanpa bukti."], relasi=DIRI, jenis="balik_tuduh")),
    kasus("B35 ajak pindah", "civilian", payload("tuduh", "offend", "Budi", ["Ucapan dan vote Budi tidak konsisten."], jenis="ajak_pindah")),
    kasus("B36 ajak menyatukan", "civilian", payload("tuduh", "offend", "Budi", ["Ucapan dan vote Budi tidak konsisten."], jenis="ajak_menyatukan")),
    kasus("B37 jelaskan vote", "civilian", payload("tuduh", "offend", "Budi", ["Ucapan dan vote Budi tidak konsisten."], jenis="jelaskan_vote")),
    kasus("B38 gali tersangka", "civilian", payload("tanya_info", "neutral", "Budi", ["Budi menjawab tuduhan dengan mengalihkan ke pemain lain."], jenis="gali_tersangka")),
    # Peek yang bukan malam terakhir disebut nomor rondenya, bukan "semalam" (npc_fuzzy waktu_peek).
    kasus("B39 hasil Peek malam lama", "stalker", payload("tuduh", "offend", "Budi", ["Aku Stalker, di malam ronde 1 aku peek Budi: dia Hitman."], "stalker", "di malam ronde 1 peek Budi, dia Hitman", jenis="hasil_peek")),
    kasus("B40 klaim palsu malam lama", "hitman", payload("tuduh", "offend", "Andi", ["Aku Stalker, di malam ronde 1 aku peek Andi, dia Hitman."], "stalker", "di malam ronde 1 peek Andi, dia Hitman", jenis="klaim_peek")),
]

class PenulisPalsu:
    """Penulis tiruan untuk pengujian: mengembalikan jawaban yang disiapkan, tanpa API."""

    def __init__(self, jawaban):
        self.jawaban, self.aktif, self.jalur, self.model, self.dipanggil = list(jawaban), True, "palsu", "palsu", []

    def tulis(self, sistem, pesan):
        self.dipanggil.append((sistem, pesan))
        return (self.jawaban.pop(0), "ok") if self.jawaban else (None, "habis")

# Konteks NLG dari satu baris rencana (di game: dari ingatan bot dan snapshot).
def konteks_dari(r):
    return {"roster": r["roster"], "chat_terbaru": r["chat_terbaru"]}


RENCANA = list(KASUS_BAWAAN)
evaluasi_rencana = RENCANA
kasus_uji = {r["sumber"][:3]: r for r in KASUS_BAWAAN}
# fmt: on


class PayloadTemplatTests(unittest.TestCase):
    def test_payload_pemeriksa_templat_dan_prompt(self):
        # fmt: off
        # Pengujian payload, pemeriksa aturan, templat per jenis, dan prompt, di sel sendiri.
        konteks_demo = {"roster": PEMAIN_DEMO, "chat_terbaru": CHAT_DEMO}

        # Setiap kelompok punya maksud, minimal 3 varian, dan satu kasus. Kunci aksi lama sudah hilang.
        assert set(MAKSUD_AKSI) == set(VARIASI)
        assert {kelompok_varian(r["payload"]) for r in KASUS_BAWAAN} == set(VARIASI)
        assert not {"ungkap", "klaim_palsu", "info_sandera", "ajak_bicara", "tuduh", "bela_orang", "bela_diri"} & (set(VARIASI) | set(MAKSUD_AKSI))
        assert not {"klaim"} & {k for r in KASUS_BAWAAN for k in r["payload"]}

        # Semua varian tiap kelompok lolos aturan di ketiga persona, bukan hanya varian pertama.
        for r in KASUS_BAWAAN:
            for persona_uji in PERSONA:
                for teks_uji in kalimat_templat(r["payload"], persona_uji):
                    assert not nilai_kalimat(teks_uji, r["payload"], konteks_dari(r))["pelanggaran"], (r["sumber"], persona_uji, teks_uji)

        # Role yang diakui benar-benar muncul di kalimat, supaya kalimat game sama dengan templat simulasi.
        for r in KASUS_BAWAAN:
            role_uji = r["payload"].get("role_diakui")
            if role_uji:
                assert all(role_uji in teks_uji.casefold() for teks_uji in kalimat_templat(r["payload"], "santai")), r["sumber"]
            else:
                assert not klaim_diri(" ".join(kalimat_templat(r["payload"], "gaul")).casefold()), r["sumber"]

        # Rencana D29: Spy membuka role dengan bukti jaga. Kalimat itu lolos, dan penyimpangan dari rencana tetap ditolak.
        d29 = kasus_uji["B22"]["payload"]
        h = tulis_pesan(d29, konteks_demo, PenulisPalsu(["Jangan vote aku, aku Spy, semalam aku jaga Budi."]), "santai")
        assert h["sumber"] == "llm", h
        for teks_uji, aturan in [("Jangan vote aku, aku Stalker.", "klaim_salah"), ("Jangan vote aku, aku Spy, semalam aku sandera Budi.", "aksi_sendiri"),
                                 ("Jangan vote aku, aku Spy, semalam aku peek Budi.", "aksi_sendiri"), ("Jangan vote aku, aku Spy, semalam aku jaga Citra.", "nama_lain")]:
            assert aturan in periksa_aturan(teks_uji, d29, PEMAIN_DEMO), teks_uji
        tanpa_rencana = {**d29, "role_diakui": None, "bukti_klaim": None, "bukti": []}
        assert {"klaim_tak_direncanakan", "aksi_sendiri"} <= set(periksa_aturan("Jangan vote aku, aku Spy, semalam aku jaga Budi.", tanpa_rencana, PEMAIN_DEMO))
        assert "aksi_sendiri" in periksa_aturan("Jangan vote aku, aku Spy, semalam aku jaga Budi.", kasus_uji["B21"]["payload"], PEMAIN_DEMO)

        # klaim_diri hanya boleh sama dengan role_diakui, termasuk Civilian, Hitman yang mengaku Spy, dan bentuk yang dibaca bot lain.
        assert klaim_diri("gw cuma civilian") == {"civilian"} and klaim_diri("stalker nih gw") == {"stalker"} and klaim_diri("role saya spy") == {"spy"}
        assert klaim_diri("dia bilang aku spy") == set() and klaim_diri("aku warga") == set() and klaim_diri("kata hasil peek eka dia bersih") == {"stalker"}
        assert "klaim_tak_direncanakan" in periksa_aturan("Jangan vote aku, aku cuma Civilian.", kasus_uji["B02"]["payload"], PEMAIN_DEMO)
        assert not periksa_aturan("Jangan vote aku, aku cuma Civilian.", kasus_uji["B20"]["payload"], PEMAIN_DEMO)
        assert not periksa_aturan("Jangan vote aku, aku Spy, semalam aku jaga Eka.", kasus_uji["B23"]["payload"], PEMAIN_DEMO)
        assert "klaim_salah" in periksa_aturan("Jangan vote aku, aku Hitman.", kasus_uji["B20"]["payload"], PEMAIN_DEMO)

        # Nama: bukti, bukti_klaim, relasi_tambahan, paket jawab, dan chat yang menyangkut target boleh; nama lain tetap ditolak.
        b07 = kasus_uji["B07"]["payload"]
        assert not periksa_aturan("Citra aneh, Eka nuduh dia lalu Eka disandera.", b07, PEMAIN_DEMO)
        assert not periksa_aturan("Jangan vote aku, aku Spy, aku jaga Budi semalam.", d29, PEMAIN_DEMO)
        assert not periksa_aturan("Jangan vote aku dan Budi, aku Stalker, aku semalam peek dia.", kasus_uji["B24"]["payload"], PEMAIN_DEMO)
        p_alih = payload("tuduh", "offend", "Andi", ["Andi menjawab tuduhan dengan mengalihkan ke pemain lain."], jenis="alasan_curiga")
        k_alih = {"roster": PEMAIN_DEMO, "chat_terbaru": [{"pengirim": "Budi", "teks": "Andi aneh.", "intent": "offend", "target": [{"pemain": "Andi", "relasi": "offend"}]},
                                                          {"pengirim": "Andi", "teks": "Justru Citra yang aneh.", "intent": "offend", "target": [{"pemain": "Citra", "relasi": "offend"}]}]}
        kalimat_alih = "Andi mencurigakan banget sih, pas dituduh Budi bukannya ngejelasin diri malah langsung balik nuduh orang lain."
        assert not nilai_kalimat(kalimat_alih, p_alih, k_alih)["pelanggaran"]
        assert "<pemicu>\nBudi: Andi aneh.\nAndi: Justru Citra yang aneh." in buat_prompt(p_alih, k_alih, "santai")[1]
        assert not nilai_kalimat("Andi aneh, tadi malah nuduh Citra.", p_alih, k_alih)["pelanggaran"]
        assert "nama_lain" in nilai_kalimat(kalimat_alih.replace("Budi", "Dodi"), p_alih, k_alih)["pelanggaran"]

        # Tersangka baru tetap ditolak walau namanya boleh disebut.
        assert "tuduh_lain" in nilai_kalimat("Andi aneh, dan aku curiga sama Budi juga.", p_alih, k_alih)["pelanggaran"]
        assert "tuduh_lain" in nilai_kalimat("Andi aneh, Budi juga mencurigakan.", p_alih, k_alih)["pelanggaran"]
        assert "tuduh_lain" in nilai_kalimat("Andi aneh, ayo vote Citra.", p_alih, k_alih)["pelanggaran"]
        assert "tuduh_lain" in periksa_aturan("Aku curiga sama Budi.", kasus_uji["B04"]["payload"], PEMAIN_DEMO)
        assert "tuduh_lain" not in periksa_aturan("Jangan vote aku dan Budi, Budi bukan Hitman.", kasus_uji["B24"]["payload"], PEMAIN_DEMO)
        assert "tuduh_lain" not in periksa_aturan("Eka bilang Citra Hitman, aku curiga Citra.", b07, PEMAIN_DEMO)

        # Bela orang: sesama pembela target di chat boleh disebut (rencana F10 uji model). Nama di luar data dan tersangka baru tetap ditolak.
        b30 = kasus_uji["B30"]["payload"]
        k_bela = {"roster": PEMAIN_DEMO, "chat_terbaru": [
            {"pengirim": "Andi", "teks": "Budi aneh.", "intent": "offend", "target": [{"pemain": "Budi", "relasi": "offend"}]},
            {"pengirim": "Dodi", "teks": "Budi bukan Hitman.", "intent": "defend", "target": [{"pemain": "Budi", "relasi": "defend"}]}]}
        assert not nilai_kalimat("Aku sih setuju Dodi, jangan buru-buru vote Budi dulu.", b30, k_bela)["pelanggaran"]
        assert "nama_lain" in nilai_kalimat("Aku sih setuju Eka, jangan buru-buru vote Budi dulu.", b30, k_bela)["pelanggaran"]
        assert "tuduh_lain" in nilai_kalimat("Jangan vote Budi dulu, Dodi justru yang mencurigakan.", b30, k_bela)["pelanggaran"]
        assert "nama_lain" in nilai_kalimat("Aku setuju Dodi, Budi bukan Hitman.", kasus_uji["B07"]["payload"], k_bela)["pelanggaran"]

        # jawab: tersangka tidak wajib disebut, nama paket boleh, tersangka di paket boleh dituduh, dan tersangka karangan ditolak.
        b03 = kasus_uji["B03"]["payload"]
        assert not periksa_aturan("Aku orang baik kok.", b03, PEMAIN_DEMO)
        assert not periksa_aturan("Aku curiga sama Citra, dia ikut mendorong eksekusi Dodi.", b03, PEMAIN_DEMO)
        assert {"nama_lain", "tuduh_lain"} <= set(periksa_aturan("Aku curiga sama Eka.", b03, PEMAIN_DEMO))
        pendapat_p = payload("jawab", "neutral", None, [], penanya="Andi", paket=paket_jawab_demo("Nara, Budi gimana?", pendapat={"Budi": {"sikap": "curiga", "alasan": "Ucapan dan vote Budi tidak konsisten."}}))
        assert not periksa_aturan("Budi aneh sih, aku curiga sama Budi.", pendapat_p, PEMAIN_DEMO)

        # jawab: nama di paket hanya dipakai sesuai perannya (rencana F18 uji model). Target vote boleh dituduh dan dijelaskan, tetapi tidak
        # boleh dibela. Pembelaan hanya untuk diri sendiri, nama yang dipercaya di paket, atau nama yang memang dibela kalimat data.
        p_peran = payload("jawab", "neutral", None, [], penanya="Andi", paket=paket_jawab_demo(
            "Nara, gimana penjelasanmu?", pendapat={"Budi": {"sikap": "percaya", "alasan": "Aku yakin Budi bukan Hitman."}},
            tindakan=[{"tindakan": "vote", "ronde": 2, "target": "Dodi", "alasan": ["Ucapan dan vote Dodi tidak konsisten."]},
                      {"tindakan": "bela", "ronde": 2, "target": "Eka", "alasan": []}]))
        assert "bela_lain" in periksa_aturan("Aku nggak nuduh siapa pun, tapi aku yakin Dodi bukan Hitman.", p_peran, PEMAIN_DEMO)
        assert "bela_lain" in periksa_aturan("Jangan buru-buru vote Dodi.", p_peran, PEMAIN_DEMO)
        assert "bela_lain" in periksa_aturan("Citra bukan Hitman kok.", p_peran, PEMAIN_DEMO)
        assert not periksa_aturan("Aku vote Dodi soalnya ucapan dan vote dia nggak konsisten.", p_peran, PEMAIN_DEMO)
        assert not periksa_aturan("Budi bukan Hitman, dan aku tadi belain Eka.", p_peran, PEMAIN_DEMO)
        assert not periksa_aturan("Kalau Dodi bukan Hitman, kenapa dia diam?", p_peran, PEMAIN_DEMO)
        assert "tuduh_lain" in periksa_aturan("Aku curiga sama Budi.", p_peran, PEMAIN_DEMO)
        # Kalimat data yang memang membela seseorang boleh diulang, walau orang itu target vote ("jadi Dodi bukan Hitman").
        b03_dodi = {**b03, "paket": {**b03["paket"], "tindakan_sebelumnya": [{"tindakan": "vote", "ronde": 1, "target": "Dodi", "alasan": []}]}}
        assert not periksa_aturan("Aku curiga sama Citra, dia ikut mendorong eksekusi Dodi, padahal Dodi bukan Hitman.", b03_dodi, PEMAIN_DEMO)

        # Kalimat khusus: serang korban Gag tanpa kata Gag, dan diklaim bersih tanpa bentuk yang dibaca sebagai klaim Stalker.
        b33 = kasus_uji["B33"]["payload"]
        assert "kata_dilarang" in periksa_aturan("Citra kayaknya kena Gag, curiga.", b33, PEMAIN_DEMO)
        assert not re.search(r"\bgag\b", " ".join(VARIASI["tuduh/serang_korban_gag"] + [MAKSUD_AKSI["tuduh/alasan_curiga"]]).casefold())
        assert "kata_dilarang" not in periksa_aturan("Citra kayaknya kena Gag, curiga.", kasus_uji["B07"]["payload"], PEMAIN_DEMO)
        for pola in VARIASI["bela_orang/diklaim_bersih"]:
            assert not re.search(r"\baku\b|\bhasil\s+peek", pola.casefold()), pola
        assert "klaim_tak_direncanakan" in periksa_aturan("Hasil peek Eka, Budi bersih.", kasus_uji["B28"]["payload"], PEMAIN_DEMO)

        # Varian yang baru terdengar tetap dicoba bila varian baru gugur aturan.
        p_panjang = payload("tuduh", "offend", "Budi", ["Budi " + "aneh sekali dari tadi " * 12], jenis="alasan_curiga")
        sudah = ["Aku curiga sama Budi.", "Menurutku Budi patut dicurigai."]
        h = tulis_pesan(p_panjang, konteks_demo, None, "santai", hindari=sudah)
        assert h["sumber"] == "templat" and h["teks"] in sudah, h

        # Prompt jawab: arahan ikut, dan hanya data yang relevan dengan pertanyaan yang dikirim.
        paket_lengkap = dict(tersangka=TERSANGKA_CITRA, kondisi="agak yakin", pendapat={"Budi": {"sikap": "percaya", "alasan": "Belum ada bukti kuat kalau Budi Hitman."}},
                             tindakan=[{"tindakan": "vote", "ronde": 1, "target": "Dodi", "alasan": ["Ucapan dan vote Dodi tidak konsisten."]}])
        def prompt_jawab(tanya, persona="santai", **ubah):
            isi = {**paket_lengkap, **ubah}
            p = payload("jawab", "offend", "Citra", TERSANGKA_CITRA["alasan"], penanya="Andi", paket=paket_jawab_demo(tanya, **isi))
            konteks = {"roster": PEMAIN_DEMO, "chat_terbaru": [{"pengirim": "Andi", "teks": tanya, "intent": "neutral", "target": [{"pemain": "Nara", "relasi": "neutral"}]}]}
            return buat_prompt(p, konteks, persona)
        sistem_j, pesan_j = prompt_jawab("Nara, kamu role apa?")
        assert "Jawab hanya yang ditanyakan" in sistem_j and "aku orang baik" in sistem_j and "Jangan mengarang tersangka" in sistem_j and "Tanpa angka" in sistem_j
        assert "aku orang baik" in pesan_j and "Dodi" not in pesan_j and "Citra" not in pesan_j and "Budi" not in pesan_j
        _, pesan_j = prompt_jawab("Nara, kenapa kamu vote Dodi?")
        assert "Di ronde 1 aku vote Dodi." in pesan_j and "Tersangkaku" not in pesan_j and "orang baik" not in pesan_j
        _, pesan_j = prompt_jawab("Nara, Budi gimana?")
        assert "Soal Budi: aku percaya." in pesan_j and "Tersangkaku" not in pesan_j and "Dodi" not in pesan_j
        _, pesan_j = prompt_jawab("Nara, menurutmu siapa?", pendapat={}, tindakan=[])
        assert "Tersangkaku: Citra (aku agak yakin)." in pesan_j and "orang baik" not in pesan_j
        _, pesan_j = prompt_jawab("Nara, menurutmu siapa?", pendapat={}, tindakan=[], tersangka=None)
        assert "Aku belum punya tersangka." in pesan_j and "Citra" not in pesan_j.split("</rencana>")[0]
        _, pesan_j = prompt_jawab("Menurut kamu siapa yang paling aneh?", pendapat={}, tindakan=[])
        assert "Tersangkaku: Citra" in pesan_j and "orang baik" not in pesan_j
        _, pesan_j = prompt_jawab("Nara, kamu sebenarnya siapa?", pendapat={}, tindakan=[])
        assert "aku orang baik" in pesan_j and "Tersangkaku" not in pesan_j
        _, pesan_j = prompt_jawab("Nara, kok diam aja?", pendapat={}, tindakan=[], chat_saya=2)
        assert "Aku sudah bicara di ronde ini." in pesan_j and "Tersangkaku" not in pesan_j
        sistem_g, pesan_g = prompt_jawab("Nara, menurut lu siapa?", "gaul", pendapat={}, tindakan=[])
        assert "Tersangka gw: Citra (gw agak yakin)." in pesan_g and "\"aku\"" in sistem_g
        sistem_g, _ = prompt_jawab("Nara, kamu role apa?", "gaul")
        assert '"gw orang baik"' in sistem_g
        # Permintaan penjelasan juga mengirim tindakan sebelumnya, bukan tersangka (rencana F17 dan F18 uji model). Tanpa tindakan, data biasa.
        for tanya in ("Nara, gimana penjelasanmu?", "Nara, jelasin dong", "Nara, kenapa kamu vote Dodi?", "Nara, kok milih Dodi?",
                      "Nara, tadi maksudmu gimana?", "Nara, coba cerita versimu dong."):
            _, pesan_j = prompt_jawab(tanya, pendapat={})
            assert "Di ronde 1 aku vote Dodi." in pesan_j and "Tersangkaku" not in pesan_j, tanya
        _, pesan_j = prompt_jawab("Nara, gimana penjelasanmu?", pendapat={}, tindakan=[])
        assert "Tersangkaku: Citra" in pesan_j and "Di ronde" not in pesan_j

        # Prompt: role_diakui menentukan aturan klaim, kata ganti persona tegas, dan fakta sudah memakai kata ganti persona.
        assert "Rencana ini memang mengaku Spy" in buat_prompt(d29, konteks_demo, "santai")[0]
        assert "aku semalam jaga Budi" in buat_prompt(d29, konteks_demo, "santai")[1]
        assert "gw semalam jaga Budi" in buat_prompt(d29, konteks_demo, "gaul")[1]
        assert "Jangan mengaku role apa pun selain 'warga'" in buat_prompt(b07, konteks_demo, "santai")[0]
        sistem_g, pesan_g = buat_prompt(kasus_uji["B34"]["payload"], konteks_demo, "gaul")
        assert 'sebut dirimu "gw" dan lawan bicara "lu"' in sistem_g and '"aku"' in sistem_g and '"saya"' in sistem_g and "Andi nuduh gw tanpa bukti." in pesan_g
        sistem_k, _ = buat_prompt(b07, konteks_demo, "kalem")
        assert 'sebut dirimu "saya" dan lawan bicara "kamu"' in sistem_k and '"gw"' in sistem_k and '"aku"' in sistem_k
        assert "menuduh atau vote" in sistem_k

        # gali tersangka tidak lagi memakai maksud pemain diam.
        _, pesan_g = buat_prompt(kasus_uji["B38"]["payload"], konteks_demo, "santai")
        assert "yang belum bicara" not in pesan_g and "Jangan bilang Budi diam" in pesan_g
        assert "yang belum bicara" in buat_prompt(kasus_uji["B10"]["payload"], konteks_demo, "santai")[1]

        # Prompt chat publik tidak pernah memuat role asli: role hanya tampil lewat role_diakui di rencana, dan Hitman tidak pernah mengaku Hitman.
        assert not {"peran", "role", "tim"} & {k for r in RENCANA for k in r["payload"]}
        for r in evaluasi_rencana:
            sistem_r, pesan_r = buat_prompt(r["payload"], konteks_dari(r), "santai")
            role_uji = r["payload"].get("role_diakui")
            assert ("Rencana ini memang mengaku" in sistem_r) == bool(role_uji), r["sumber"]
            assert "mengaku Hitman" not in sistem_r + pesan_r, r["sumber"]
            assert "rekan tim" not in sistem_r + pesan_r, r["sumber"]

        # Salinan fakta (aturan 5 prompt; rencana F07 dan F31 uji model): kalimat LLM yang menyalin fakta panjang hampir utuh ditulis ulang
        # sekali. Bila percobaan ulang gagal, salinan itu tetap dipakai, karena templat juga memuat fakta apa adanya.
        p_salin = payload("tuduh", "offend", "Budi", ["Budi ikut mendorong eksekusi Dodi (ronde 2), padahal jumlah Hitman tidak berkurang jadi Dodi bukan Hitman."],
                          jenis="alasan_curiga")
        salinan = "Aku curiga Budi, dia ikut mendorong eksekusi Dodi padahal jumlah Hitman gak berkurang, jadi Dodi bukan Hitman."
        parafrase = "Aku curiga sama Budi, dia yang ngedorong Dodi dieksekusi, padahal Dodi ternyata warga."
        palsu = PenulisPalsu([salinan, parafrase])
        h = tulis_pesan(p_salin, konteks_demo, palsu, "santai")
        assert h["percobaan"][0]["salin_fakta"] and "salin_fakta" in palsu.dipanggil[1][1] and (h["sumber"], h["teks"]) == ("llm", parafrase), h
        for kedua in (salinan, "Aku bot."):
            h = tulis_pesan(p_salin, konteks_demo, PenulisPalsu([salinan, kedua]), "santai")
            assert (h["sumber"], h["teks"], h["pelanggaran"]) == ("llm", salinan, []), h
        # Dua fakta pendek yang disalin berurutan juga terhitung. Satu fakta pendek dan klaim role tidak, karena wajar diucapkan apa adanya.
        assert fakta_disalin("Aku bukan Hitman, yang lebih mencurigakan justru Citra. Kalau salah vote kita bisa kalah.", kasus_uji["B26"]["payload"], "santai")
        assert not fakta_disalin("Jangan vote aku, masih terlalu awal, buktinya belum ada.", kasus_uji["B18"]["payload"], "santai")
        assert not fakta_disalin("Jangan vote aku dan Budi, aku Stalker, aku semalam peek Budi, dia bukan Hitman.", kasus_uji["B24"]["payload"], "santai")
        # fmt: on
