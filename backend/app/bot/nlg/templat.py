"""[TEMPLAT] Kalimat siap pakai tanpa LLM: persona, varian kalimat per jenis aksi, dan pemilih varian.

Dipakai main controller (nlg_controller.tulis_pesan) saat LLM mati, gagal, atau kalimatnya ditolak dua kali, dan oleh
chat tim malam (kalimat_tim). kalimat_templat mencoba varian yang belum terdengar lebih dulu, lalu yang paling lama
tidak terdengar; pembandingnya bentuk_dasar (huruf kecil, tanpa tanda baca, kata ganti diseragamkan).
"""

import hashlib
import json
import re
from difflib import SequenceMatcher

MIRIP_MAKS = 0.75

PERSONA = {
    "santai": {"deskripsi": "santai dan ramah, memakai aku/kamu, sesekali 'sih', 'deh', atau 'nih'",
               "aku": "aku", "kamu": "kamu"},
    "gaul": {"deskripsi": "gaul ala anak Jakarta, memakai gw/lu, kalimat pendek", "aku": "gw", "kamu": "lu"},
    "kalem": {"deskripsi": "tenang dan sopan, kalimat lengkap, memakai saya/kamu", "aku": "saya", "kamu": "kamu"},
}

# Persona bergiliran untuk bot dalam satu room; tanpa daftar, persona tetap dari hash nama.
def persona_bot(nama, daftar_bot=None):
    urutan = list(PERSONA)
    if daftar_bot:
        return urutan[sorted(daftar_bot).index(nama) % len(urutan)]
    return urutan[int(hashlib.sha256(nama.encode("utf-8")).hexdigest(), 16) % len(urutan)]

# Mengganti kata ganti templat sesuai persona; huruf kapital di awal kata dipertahankan.
def ubah_kata_ganti(teks, persona):
    gaya = PERSONA[persona]

    def ganti(kata_baru):
        return lambda m: kata_baru[:1].upper() + kata_baru[1:] if m.group(0)[0].isupper() else kata_baru

    # Akhiran -ku/-mu pada kata umum ("menurutku", "pendapatmu") dipisah bila persona tidak memakai aku/kamu.
    if gaya["aku"] != "aku":
        teks = re.sub(r"\b([Mm]enurut|[Pp]endapat|[Kk]ecurigaan|[Ss]uara|[Pp]ilihan|[Tt]ersangka)ku\b", lambda m: f"{m.group(1)} {gaya['aku']}", teks)
    if gaya["kamu"] != "kamu":
        teks = re.sub(r"\b([Mm]enurut|[Pp]endapat|[Pp]enjelasan|[Mm]aksud|[Vv]ersi|[Pp]ilihan)mu\b", lambda m: f"{m.group(1)} {gaya['kamu']}", teks)
    teks = re.sub(r"\b[Aa]ku\b", ganti(gaya["aku"]), teks)
    return re.sub(r"\b[Kk]amu\b", ganti(gaya["kamu"]), teks)

VARIASI = {
    # Selain tunjuk orang, kalimat bela diri wajib memuat sangkalan atau penolakan vote, supaya labelnya defend.
    "bela_diri/tanpa_bukti": [
        "Aku bukan Hitman, tuduhan ke aku belum ada buktinya.",
        "Kok aku? Aku bukan Hitman, tuduhan itu nggak ada buktinya.",
        "Kok aku sih? Aku warga, bukan Hitman.",
        "Aku bukan Hitman kok, jangan asal nuduh.",
    ],
    "bela_diri/terlalu_awal": [
        "Jangan vote aku, masih terlalu awal, buktinya belum ada.",
        "Jangan vote aku dulu, ini masih terlalu awal.",
        "Jangan buru-buru vote aku, buktinya belum ada.",
        "Aku bukan Hitman, masih terlalu awal buat vote aku.",
    ],
    "bela_diri/bahaya_salah_vote": [
        "Jangan vote aku, kalau salah vote kita bisa kalah.",
        "Jangan vote aku, aku bukan Hitman. Kalau salah vote kita bisa kalah.",
        "Aku bukan Hitman, jangan vote aku. Salah vote sekali lagi kita bisa kalah.",
    ],
    "bela_diri/buka_role": [
        "Jangan vote aku, aku {r}.",
        "Aku {r}, jangan vote aku.",
        "Aku bukan Hitman, aku {r}. Jangan vote aku.",
        "Jangan vote aku dong, aku ini {r}.",
    ],
    # Nama di bukti Guard adalah saksi, jadi tidak dibela dan tidak dituduh.
    "bela_diri/role_bukti_aksi": [
        "Jangan vote aku, aku {r}, {k}.",
        "Aku {r}, {k}. Jangan vote aku.",
        "Jangan vote aku, aku {r}. {K}.",
        "Aku bukan Hitman, aku {r}. {K}.",
    ],
    # Hasil Peek menyebut orang itu langsung. Tanpa "jangan vote aku dan X", IndoBERT tidak membaca X sebagai dibela.
    "bela_diri/role_bukti_aksi_bersih": [
        "Jangan vote aku dan {x}, aku {r}, {k}.",
        "Jangan vote aku dan {x}, aku {r}. {K}.",
        "Aku {r}, jangan vote aku dan {x}. {K}.",
    ],
    "bela_diri/role_bukti_aksi_hitman": [
        "Aku bukan Hitman, justru {x} yang Hitman. Aku {r}, {k}.",
        "Jangan vote aku, aku bukan Hitman, justru {x}. Aku {r}, {k}.",
        "Aku bukan Hitman, yang Hitman itu {x}. Aku {r}, {k}.",
    ],
    # Target bela diri jenis tunjuk orang adalah orang lain, jadi kalimatnya wajib menyebut orang itu.
    "bela_diri/tunjuk_orang": [
        "Aku bukan Hitman, justru {t} yang lebih mencurigakan.",
        "Aku bukan Hitman, yang lebih mencurigakan justru {t}.",
        "Aku bukan Hitman, justru {t} yang lebih aneh.",
        "Aku bukan Hitman, yang lebih aneh itu {t}. {b2}",
    ],
    "bela_diri/tunjuk_orang_bahaya": [
        "Aku bukan Hitman, yang lebih mencurigakan justru {t}. Kalau salah vote kita bisa kalah.",
        "Aku bukan Hitman, justru {t} yang lebih aneh. Kalau salah vote kita bisa kalah.",
        "Jangan salah vote, aku bukan Hitman, justru {t} yang aneh.",
    ],
    "jawab/target": [
        "Kalau aku sih paling curiga sama {t}. {b1}",
        "Aku condong curiga ke {t}. {b1}",
        "Kalau aku sih paling curiga sama {t}.",
        "Aku condong curiga ke {t}.",
    ],
    # Jawaban netral untuk pertanyaan langsung apa pun; pertanyaan balik ditujukan ke semua (tanpa nama), agar tidak
    # memanggil satu pemain dan memicu balas-membalas. Diuji IndoBERT pada empat konteks pertanyaan langsung.
    "jawab/netral": [
        "Aku belum yakin siapa-siapa. Kalian curiga siapa?",
        "Jujur aku masih bingung. Ada yang punya petunjuk?",
        "Aku belum punya tersangka kuat. Menurut kalian gimana?",
        "Belum ada yang bisa aku pastikan, aku masih nyimak. Kalian gimana?",
        "Aku belum punya info yang bisa dipegang. Kalian sendiri gimana?",
    ],
    "bela_orang/peek_bersih": [
        "Aku {r}, {k}. Jangan vote {t}.",
        "Jangan vote {t}, aku {r}, {k}.",
        "Percaya deh, aku {r}. {K}.",
    ],
    "bela_orang/yakin_bersih": [
        "Aku yakin {t} bukan Hitman.",
        "{t} bukan Hitman, aku yakin.",
        "Jangan vote {t}, aku yakin dia bukan Hitman.",
        "Percaya deh, {t} bukan Hitman.",
    ],
    # Tanpa bentuk "aku ..." dan "hasil peek", karena POLA_KLAIM milik bot lain akan membaca pembicaranya sebagai pengaku Stalker.
    "bela_orang/diklaim_bersih": [
        "{b1}",
        "{b1} Jangan vote {t}.",
        "Jangan vote {t} dulu. {b1}",
        "Jangan vote {t} dulu, ada yang bilang dia bersih.",
    ],
    # "Masih terlalu awal buat nuduh X" terbaca menuduh X; penolakan vote di depan terbaca membela.
    "bela_orang/terlalu_awal": [
        "Jangan vote {t} dulu, masih terlalu awal.",
        "Jangan vote {t} sekarang, ini masih terlalu awal.",
        "Jangan buru-buru vote {t}, ini masih terlalu awal.",
    ],
    "bela_orang/ada_pembela": [
        "Jangan vote {t} dulu, ada yang membela dia juga.",
        "{t} belum tentu Hitman, ada yang membela dia juga.",
        "Jangan buru-buru vote {t}, masih ada yang membela dia.",
        "Tuduhan ke {t} masih pendapat, ada yang membela juga.",
    ],
    "bela_orang/ada_pembela_bahaya": [
        "Jangan vote {t} dulu, ada yang membela dia juga. Kalau salah vote kita bisa kalah.",
        "{t} belum tentu Hitman, ada yang membela dia juga. Kalau salah vote kita bisa kalah.",
        "Jangan buru-buru vote {t}, masih ada yang membela dia. Kalau salah vote kita bisa kalah.",
    ],
    "bela_orang/belum_ada_bukti": [
        "Belum ada bukti kuat kalau {t} Hitman.",
        "Jangan vote {t} dulu, belum ada bukti kuat dia Hitman.",
        "{t} belum tentu Hitman, buktinya belum kuat.",
    ],
    "bela_orang/belum_ada_bukti_bahaya": [
        "Belum ada bukti kuat kalau {t} Hitman. Kalau salah vote kita bisa kalah.",
        "Jangan vote {t} dulu, belum ada bukti kuat dia Hitman. Kalau salah vote kita bisa kalah.",
        "{t} belum tentu Hitman, buktinya belum kuat. Kalau salah vote kita bisa kalah.",
    ],
    "tuduh/hasil_peek": [
        "Aku {r}, {k}. Ayo vote {t}!",
        "Aku buka role, aku {r}: {k}. Vote {t} sekarang!",
        "Jujur aku {r}, {k}. Jadi vote {t}.",
    ],
    "tuduh/klaim_peek": [
        "Aku {r}, {k}.",
        "Oke aku buka role, aku {r}, {k}.",
        "Aku {r}, {k}, jangan sampai lolos.",
    ],
    # Kalimat "aku curiga" selalu di depan fakta. Bentuk lain, misalnya "X patut dicurigai. X pernah membela Y", terbaca membela X.
    # Varian tanpa {b1} dipakai bila rencana tidak membawa kalimat bukti, misalnya kambing hitam yang hanya didukung suara.
    "tuduh/alasan_curiga": [
        "Aku makin curiga sama {t}. {b1}",
        "Aku curiga sama {t}. {b1}",
        "Coba perhatikan {t}, aku curiga. {b1}",
        "Aku curiga sama {t}.",
        "Menurutku {t} patut dicurigai.",
    ],
    # Warga tidak tahu siapa korban Gag, jadi kalimatnya hanya soal diam.
    "tuduh/serang_korban_gag": [
        "{t} dari tadi diam aja, curiga.",
        "{t} kok diam aja dari tadi, aku curiga.",
        "Aku curiga sama {t}, dari tadi nggak ada suaranya.",
        "{t} mendadak diam, mencurigakan.",
    ],
    # "X nuduh aku, justru dia aneh" terbaca menuduh pembicara, jadi nama penuduh diletakkan sesudah sangkalan.
    "tuduh/balik_tuduh": [
        "Aku bukan Hitman, justru {t} yang aneh, dia nuduh aku tanpa bukti.",
        "Aku bukan Hitman, justru {t} yang mencurigakan, nuduh aku tanpa bukti.",
        "Aku bukan Hitman, justru {t} yang aneh karena nuduh aku tanpa bukti.",
        "Aku bukan Hitman, yang aneh justru {t}, dia nuduh aku tanpa bukti.",
    ],
    "tuduh/ajak_pindah": [
        "Seri nih, pindah ke {t} aja.",
        "Suaranya seri, mending vote {t} aja.",
        "Masih seri, ayo vote {t} aja.",
        "Biar nggak seri, vote {t} aja.",
    ],
    "tuduh/ajak_menyatukan": [
        "Vote {t} aja, suara kita jangan pecah.",
        "Suara kita jangan pecah, ke {t} aja.",
        "Jangan pecah suara, vote {t} aja.",
        "Ayo satukan suara ke {t}.",
    ],
    # Kata vote diikuti fakta mudah terbaca terbalik, jadi hanya satu varian yang membawa fakta.
    "tuduh/jelaskan_vote": [
        "Aku pilih vote {t}. {b1}",
        "Aku vote {t}, soalnya aku curiga sama dia.",
        "Aku curiga sama {t}, jadi aku vote dia.",
        "Aku vote {t}, aku curiga sama dia.",
    ],
    # "X kok diam?" terbaca menuduh; ajakan bicara ditulis sebagai pertanyaan pendapat.
    "tanya_info/pemain_diam": [
        "{t}, pendapatmu gimana? Dari tadi belum kedengaran.",
        "{t}, menurutmu gimana? Ayo ikut cerita.",
        "{t}, ayo ikut diskusi. Kamu curiga siapa?",
    ],
    # Tanpa bukti di kalimat, karena fakta yang memberatkan membuat pertanyaan terbaca menuduh.
    "tanya_info/gali_tersangka": [
        "{t}, gimana penjelasanmu?",
        "{t}, coba jelasin dong, menurutmu gimana?",
        "{t}, coba cerita versimu dong.",
        "{t}, tadi maksudmu gimana?",
        "{t}, boleh jelasin maksudmu tadi?",
    ],
    "tanya_info/klaim_bentrok": [
        "{b1} Gimana nih?",
        "{b1} Menurut kalian gimana?",
        "{b1} Ada yang bisa jelasin?",
    ],
    "tanya_info/ruangan_hening": [
        "{b1} Ada yang punya info lain?",
        "{b1} Menurut kalian gimana?",
        "{b1} Ayo cerita dong.",
        "{b1} Ada yang mau mulai?",
    ],
    "tanya_info/pertanyaan_umum": [
        "Ada yang punya info atau curiga sama seseorang? Ceritain alasannya ya.",
        "Siapa yang punya petunjuk? Jangan asal vote.",
        "Ayo cerita, kalian curiga siapa dan kenapa?",
    ],
}

# Varian tambahan per persona untuk kelompok yang paling sering diucapkan berulang oleh bot yang sama, terutama bela diri di
# Tribunal: rencana yang sama bisa datang sampai sepuluh kali dalam satu fase. Ditulis langsung dengan kata ganti persona,
# bentuknya sengaja berbeda dari varian bersama, dan dipilih dari bacaan IndoBERT di ketiga persona seperti varian di atas.
# Bela diri tetap memuat "bukan Hitman", dan bela orang tetap memuat penolakan vote di depan nama, supaya labelnya sama.
VARIASI_PERSONA = {
    "bela_diri/tanpa_bukti": {
        "santai": [
            "Aku bukan Hitman, sumpah. Nuduh tanpa bukti gitu cuma bikin kita salah pilih.",
            "Lho kok aku? Aku bukan Hitman, buktinya mana coba?",
            "Aku bukan Hitman kok. Tuduhannya cuma tebakan, belum ada bukti apa-apa.",
            "Beneran deh, aku bukan Hitman. Jangan nuduh orang tanpa bukti ya.",
            "Aku bukan Hitman, dan sampai sekarang nggak ada bukti yang nunjuk ke aku.",
            "Santai dulu, aku bukan Hitman. Tuduhan ke aku itu nggak ada dasarnya.",
            "Aku ngerti kalian curiga, tapi aku bukan Hitman. Buktinya belum ada sama sekali.",
            "Aku bukan Hitman, nggak ada satu pun bukti soal itu.",
        ],
        "gaul": [
            "Gw bukan Hitman, sumpah. Nuduh tanpa bukti gitu malah bikin kita salah pilih.",
            "Lah kok gw? Gw bukan Hitman, buktinya mana?",
            "Gw bukan Hitman, bro. Tuduhan lu cuma tebakan, gak ada buktinya.",
            "Serius, gw bukan Hitman. Jangan asal nuduh tanpa bukti dong.",
            "Gw bukan Hitman, dan sampe sekarang gak ada bukti yang ngarah ke gw.",
            "Santai dulu, gw bukan Hitman. Tuduhan ke gw tuh gak ada dasarnya.",
            "Gw ngerti kalian curiga, tapi gw bukan Hitman. Buktinya belum ada sama sekali.",
            "Gw bukan Hitman, gak ada bukti satu pun soal itu.",
        ],
        "kalem": [
            "Saya bukan Hitman. Menuduh tanpa bukti hanya akan membuat kita salah pilih.",
            "Mengapa saya? Saya bukan Hitman, dan belum ada bukti yang menunjukkan sebaliknya.",
            "Saya bukan Hitman. Tuduhan itu masih dugaan, belum ada buktinya.",
            "Saya mohon jangan menuduh tanpa bukti, karena saya bukan Hitman.",
            "Saya bukan Hitman, dan sampai sekarang tidak ada bukti yang mengarah ke saya.",
            "Tenang dulu, saya bukan Hitman. Tuduhan kepada saya belum punya dasar.",
            "Saya mengerti kalian curiga, tetapi saya bukan Hitman. Buktinya belum ada sama sekali.",
            "Saya bukan Hitman, tidak ada satu pun bukti soal itu.",
        ],
    },
    "bela_diri/bahaya_salah_vote": {
        "santai": [
            "Tolong jangan vote aku ya, sekali salah pilih kita bisa kalah.",
            "Aku bukan Hitman, jadi jangan vote aku. Kita nggak punya ruang buat salah vote.",
        ],
        "gaul": [
            "Plis jangan vote gw, sekali salah pilih kita langsung kalah.",
            "Gw bukan Hitman, jangan vote gw. Kita gak bisa salah vote lagi sekarang.",
        ],
        "kalem": [
            "Mohon jangan vote saya, karena satu salah pilih bisa membuat kita kalah.",
            "Saya bukan Hitman, jadi jangan vote saya. Kita tidak punya ruang untuk salah vote.",
        ],
    },
    "bela_diri/tunjuk_orang": {
        "santai": [
            "Aku bukan Hitman kok, malah {t} yang dari tadi aneh.",
            "Aku bukan Hitman, beneran. Yang patut dicurigai itu {t}, bukan aku.",
            "Aku bukan Hitman lho, yang aneh malah {t}.",
            "Aku bukan Hitman, aku malah curiga sama {t}.",
            "Sumpah, aku bukan Hitman. Justru {t} yang dari tadi mencurigakan.",
        ],
        "gaul": [
            "Gw bukan Hitman, yang aneh tuh malah {t}.",
            "Gw bukan Hitman, gw malah curiga sama {t}.",
            "Gw bukan Hitman kok, malah {t} yang dari tadi aneh banget.",
            "Gw bukan Hitman, mending curigain {t} aja.",
            "Gw bukan Hitman. Yang lebih mencurigakan tuh {t}, bukan gw.",
        ],
        "kalem": [
            "Saya tegaskan saya bukan Hitman, justru sikap {t} yang lebih mencurigakan.",
            "Mohon dipertimbangkan, saya bukan Hitman. Yang lebih mencurigakan adalah {t}.",
            "Saya bukan Hitman, saya justru curiga kepada {t}.",
            "Saya bukan Hitman, dan menurut saya yang lebih aneh adalah {t}.",
            "Saya bukan Hitman. Kalau boleh jujur, justru {t} yang lebih patut dicurigai.",
        ],
    },
    "bela_diri/tunjuk_orang_bahaya": {
        "santai": [
            "Kita nggak boleh salah vote sekarang, bisa kalah. Aku bukan Hitman, yang patut dicurigai itu {t}.",
            "Aku bukan Hitman kok, beneran. {t} malah yang aneh dari tadi, jangan sampai suara kita salah sasaran.",
            "Tolong jangan salah pilih ya, taruhannya kita kalah. Aku bukan Hitman, coba curigai {t} aja.",
            "Aku bukan Hitman, jadi jangan buang suara ke aku. {t} lebih pantas dicurigai, salah vote bisa fatal.",
            "Ini genting lho, satu salah vote bisa bikin kalah. Aku bukan Hitman, sementara {t} justru mencurigakan.",
            "Aku bukan Hitman, justru aku curiga sama {t}. Hati-hati, salah vote bisa bikin kita kalah.",
            "Aku bukan Hitman lho. Justru {t} yang mencurigakan, jangan sampai kita kalah gara-gara salah vote.",
        ],
        "gaul": [
            "Gw bukan Hitman, serius. Mending curigain {t}, salah vote dikit aja kita bisa kalah.",
            "Gw bukan Hitman, jadi jangan buang suara ke gw. {t} lebih layak dicurigain, salah vote bisa fatal.",
            "Gw bukan Hitman, sumpah, justru {t} yang mencurigakan. Salah vote sekarang kita bisa kalah.",
            "Gw bukan Hitman, yang aneh tuh malah {t}. Jangan sampe kita salah vote terus kalah.",
            "Hati-hati, salah vote bisa bikin kalah. Gw bukan Hitman, justru {t} yang lebih aneh.",
            "Gw bukan Hitman. Yang lebih mencurigakan tuh {t}, jangan sampe kita kalah gara-gara salah vote.",
            "Gw bukan Hitman kok, malah {t} yang dari tadi aneh banget. Salah vote sekarang bahaya.",
        ],
        "kalem": [
            "Mohon hati-hati, salah vote bisa membuat kita kalah. Saya bukan Hitman, justru {t} yang patut dicurigai.",
            "Saya tegaskan saya bukan Hitman. Sikap {t} justru lebih mencurigakan, jadi mari jangan sampai salah vote.",
            "Saya bukan Hitman, jadi jangan sia-siakan suara untuk saya. Yang lebih mencurigakan adalah {t}, dan salah vote bisa membuat kita kalah.",
            "Saya bukan Hitman, sungguh. Kecurigaan saya ke {t}, dan saya khawatir kita kalah kalau salah vote.",
            "Satu salah vote bisa membuat kita kalah. Saya bukan Hitman, dan menurut saya yang lebih mencurigakan adalah {t}.",
            "Saya bukan Hitman. Justru {t} yang menurut saya lebih mencurigakan, dan kita tidak boleh salah vote sekarang.",
            "Saya bukan Hitman, saya justru curiga kepada {t}. Mohon hati-hati, salah vote bisa membuat kita kalah.",
        ],
    },
    "bela_orang/terlalu_awal": {
        "santai": [
            "Jangan vote {t} dulu deh, kita belum tahu banyak.",
            "Jangan vote {t} dulu ya, kita baru mulai dan belum ada petunjuk.",
        ],
        "gaul": [
            "Jangan vote {t} dulu, masih kepagian, bro.",
            "Jangan vote {t} dulu, info kita masih dikit banget.",
        ],
        "kalem": [
            "Sebaiknya jangan vote {t} dulu, kita belum punya cukup informasi.",
            "Mohon tahan dulu, jangan vote {t}. Masih terlalu dini untuk memutuskan.",
        ],
    },
    "bela_orang/ada_pembela": {
        "santai": [
            "Tunggu dulu, jangan vote {t}. Tuduhannya masih pendapat, dan ada yang belain dia juga.",
            "Jangan buru-buru vote {t} ya, masih ada yang belain dia. Tuduhannya juga baru sebatas pendapat.",
            "Masih ada yang membela {t}, jadi jangan vote dia dulu deh.",
        ],
        "gaul": [
            "Tahan dulu, jangan vote {t}. Tuduhannya masih opini, ada yang belain dia juga.",
            "Jangan main vote {t} dulu lah, masih ada yang belain dia.",
            "Jangan vote {t} dulu, bro. Tuduhannya cuma opini, masih ada yang belain dia.",
        ],
        "kalem": [
            "Mohon jangan buru-buru vote {t}. Tuduhan kepadanya masih pendapat, dan ada yang membelanya.",
            "Sebaiknya kita jangan vote {t} dulu, karena masih ada yang membela dia.",
            "Jangan vote {t} dulu, tuduhan kepadanya belum kuat dan masih ada pembelanya.",
        ],
    },
    "bela_orang/ada_pembela_bahaya": {
        "santai": [
            "Jangan vote {t} dulu ya, masih ada yang belain dia. Salah vote sekarang bisa bikin kita kalah.",
            "Jangan buru-buru vote {t}, ada yang membela dia. Kita nggak boleh salah vote sekarang.",
        ],
        "gaul": [
            "Jangan vote {t} dulu, masih ada yang belain. Salah vote sekarang kita bisa kalah.",
            "Jangan main vote {t}, dia masih dibelain orang. Salah dikit aja kita kalah.",
        ],
        "kalem": [
            "Mohon jangan vote {t} dulu, masih ada yang membelanya. Salah vote sekarang bisa membuat kita kalah.",
            "Sebaiknya jangan buru-buru vote {t}, karena masih ada yang membela dan salah vote bisa berakibat kalah.",
        ],
    },
    # Nama penuduh tetap sesudah sangkalan, seperti varian bersama balik_tuduh.
    "tuduh/balik_tuduh": {
        "santai": [
            "Aku bukan Hitman, dan yang bikin curiga malah {t}, nuduh aku tanpa dasar.",
            "Lho, aku bukan Hitman. {t} justru yang aneh, nuduh aku tanpa bukti apa-apa.",
        ],
        "gaul": [
            "Gw bukan Hitman, yang aneh malah {t}, asal nuduh gw doang.",
            "Gw bukan Hitman, bro. Justru {t} yang aneh, nuduh gw tanpa bukti gitu.",
        ],
        "kalem": [
            "Saya bukan Hitman, dan sikap {t} yang menuduh saya tanpa bukti justru mencurigakan.",
            "Saya tegaskan saya bukan Hitman. Yang lebih aneh adalah {t}, menuduh saya tanpa dasar.",
        ],
    },
    "tanya_info/ruangan_hening": {
        "santai": [
            "Sepi banget nih dari tadi. Ada yang mau mulai cerita?",
            "Kok pada hening sih? Ayo dong, siapa yang punya cerita?",
        ],
        "gaul": [
            "Sepi amat nih. Ada yang mau buka obrolan?",
            "Pada ke mana nih, kok sepi? Ayo ngobrol.",
        ],
        "kalem": [
            "Suasananya sepi sekali. Ada yang ingin memulai cerita?",
            "Belum ada yang bercerita sejak tadi. Silakan, siapa yang mau berbagi?",
        ],
    },
    "tanya_info/pertanyaan_umum": {
        "santai": [
            "Kalian curiga sama siapa nih? Ceritain dong alasannya.",
            "Yuk tukar pikiran, siapa yang menurut kalian paling patut dicurigai dan kenapa?",
            "Aku pengen dengar pendapat kalian, siapa yang kalian curigai dan apa alasannya?",
        ],
        "gaul": [
            "Ada yang punya clue? Siapa yang kalian curigain, kasih alasannya juga dong.",
            "Ayo share, siapa yang menurut kalian paling patut dicurigain, terus kenapa?",
            "Gw pengen denger dari kalian, siapa yang kalian curigain dan alasannya apa?",
        ],
        "kalem": [
            "Siapa yang kalian curigai sejauh ini? Mohon sertakan alasannya.",
            "Saya ingin mendengar pendapat kalian, siapa yang paling patut dicurigai dan mengapa?",
            "Mari kita berbagi pendapat, siapa yang kalian curigai dan apa alasannya?",
        ],
    },
}

TEMPLAT_TIM = {
    "hitman": {
        "pilih_target": ["Aku incar {t}. {b1}", "Malam ini aku pilih {t}. {b1}", "Malam ini aku pilih {t}.",
                         "Aku mau sandera {t} malam ini. {b1}", "Menurutku {t} dulu malam ini."],
        "setuju": ["Oke, {r} juga bagus.", "Boleh, {r} juga masuk akal.", "Sip, {r} juga oke.",
                   "Aku setuju, {r} boleh juga.", "{r} juga pilihan bagus kok."],
        "beda": ["Aku lebih pilih {t}. {b1}", "Menurutku {t} lebih pas. {b1}", "Aku lebih pilih {t}.",
                 "Kalau aku sih {t} dulu. {b1}", "Gimana kalau {t} aja?"],
        "ikut_manusia": ["Oke, aku ikut {r}.", "Sip, aku ikut pilihanmu, {r} aja.", "Ya udah, aku ikut {r}.",
                         "Aku ikut kamu aja, kita ke {r}.", "Oke, {r} aja malam ini."],
    },
    "spy": {
        "pilih_target": ["Aku jaga {t}. {b1}", "Malam ini aku jaga {t}. {b1}", "Malam ini aku jaga {t}.",
                         "Aku yang jaga {t} ya.", "Giliran aku jaga {t} malam ini."],
        "pindah_sama": ["{r} sudah kamu jaga, aku jaga {t}.", "Kamu sudah jaga {r}, jadi aku jaga {t}.",
                        "{r} udah sama kamu, aku pindah jaga {t}.", "Karena {r} sudah kamu jaga, aku ke {t}.",
                        "Biar nggak sama, {r} buat kamu, aku jaga {t}."],
    },
}

JENIS_BAWAAN = {"bela_diri": "tanpa_bukti", "bela_orang": "belum_ada_bukti", "tuduh": "alasan_curiga", "tanya_info": "pertanyaan_umum"}

# Kelompok varian sesuai aksi dan jenis. jawab tidak punya jenis, dan bentuk kalimat bukti Peek bergantung pada hasilnya.
def kelompok_varian(p):
    if p["aksi"] == "jawab":
        return "jawab/target" if p["target"] else "jawab/netral"
    jenis = p.get("jenis") or ("pemain_diam" if p["aksi"] == "tanya_info" and p["target"] else JENIS_BAWAAN[p["aksi"]])
    if jenis == "pelintir_bukti":
        jenis = "alasan_curiga"
    relasi = {r["relasi"] for r in p.get("relasi_tambahan") or []}
    if jenis == "role_bukti_aksi" and relasi:
        jenis += "_hitman" if "offend" in relasi else "_bersih"
    return f"{p['aksi']}/{jenis}"

# Sebutan role di kalimat; Civilian ditulis "cuma Civilian", karena mengaku warga biasa terdengar lebih wajar begitu.
def sebutan_role(role):
    return f"cuma {role.capitalize()}" if role == "civilian" else role.capitalize()

# Mengisi slot templat; None jika varian butuh data yang tidak ada.
def isi_templat(pola, p):
    bukti, role = list(p["bukti"]), p.get("role_diakui")
    klaim = f"aku {p['bukti_klaim']}" if p.get("bukti_klaim") else None
    relasi = p.get("relasi_tambahan") or []
    isi = {"{b1}": bukti[0] if bukti else None, "{b2}": bukti[1] if len(bukti) > 1 else None, "{t}": p["target"] or "",
           "{r}": sebutan_role(role) if role else None, "{k}": klaim, "{K}": klaim and klaim[0].upper() + klaim[1:],
           "{x}": relasi[0]["pemain"] if relasi else None}
    for slot, nilai in isi.items():
        if slot in pola:
            if nilai is None:
                return None
            pola = pola.replace(slot, nilai)
    return re.sub(r"\s+", " ", pola).strip()

# Urutan dasar varian satu pesan: varian bersama kelompok lalu varian persona, diputar sebanyak sidik sha256 dari pembicara
# dan rencana. Bot atau rencana berbeda mendapat urutan berbeda; masukan yang sama selalu mendapat urutan yang sama.
# Ronde dan fase sengaja tidak ikut: giliran varian untuk rencana yang berulang sudah diatur kalimat_templat dari kalimat
# yang baru terdengar, jadi pilihan varian hanya berubah bila memang ada pengulangan.
def urutan_varian(p, persona="santai"):
    kelompok = kelompok_varian(p)
    daftar = VARIASI[kelompok] + VARIASI_PERSONA.get(kelompok, {}).get(persona, [])
    kunci = json.dumps([p["pembicara"], p["aksi"], p.get("jenis"), p["target"], p["bukti"]], ensure_ascii=False)
    geser = int(hashlib.sha256(kunci.encode("utf-8")).hexdigest(), 16) % len(daftar)
    return daftar[geser:] + daftar[:geser]

KATA_GANTI_DASAR = {"saya": "aku", "gw": "aku", "gue": "aku", "gua": "aku", "lu": "kamu", "lo": "kamu"}

# Bentuk dasar kalimat untuk mendeteksi pengulangan lintas persona ("Gw rasa ..." = "Aku rasa ...").
def bentuk_dasar(teks):
    return " ".join(KATA_GANTI_DASAR.get(k, k) for k in re.findall(r"\w+", teks.casefold()))

# Kemiripan dua kalimat (0–1) pada bentuk dasarnya: nilai terbesar dari rasio urutan huruf dan porsi kata yang sama.
# Rasio urutan menangkap parafrase tipis ("kalian curiga siapa dan kenapa?" vs "kalian curiga siapa aja dan
# alasannya?"); porsi kata menangkap susunan yang dibalik ("jangan vote X, X bukan Hitman" vs "X bukan Hitman, jangan
# vote X").
def kemiripan(a, b):
    x, y = bentuk_dasar(a), bentuk_dasar(b)
    kata_x, kata_y = set(x.split()), set(y.split())
    porsi_kata = len(kata_x & kata_y) / max(1, len(kata_x | kata_y))
    return max(SequenceMatcher(None, x, y).ratio(), porsi_kata)

# Kalimat yang baru terdengar dan paling mirip dengan teks bila kemiripannya ≥ MIRIP_MAKS, selain itu None.
def kalimat_mirip(teks, hindari):
    skor, kalimat = max(((kemiripan(teks, h), h) for h in hindari), default=(0.0, None))
    return kalimat if skor >= MIRIP_MAKS else None

# Kalimat pengaman terakhir: intent dan target rencana tidak pernah berubah.
def kalimat_cadangan(p):
    t = p["target"]
    if p["aksi"] == "bela_diri" and t in (None, p["pembicara"]):
        return "Aku bukan Hitman."
    if not t:
        return "Ada yang punya info?"
    return {"offend": f"Aku curiga sama {t}.", "defend": f"{t} bukan Hitman menurutku.",
            "neutral": f"{t}, pendapatmu gimana?"}[p["intent"]]

# Semua kalimat templat yang mungkin, sudah diberi persona, urut dari yang paling layak dikirim. hindari = kalimat yang baru
# terdengar, dari yang paling lama ke yang paling baru (kalimat bot ini lalu chat terbaru room, siapa pun pengirimnya).
# Kalimat yang persis atau hampir sama dengan salah satunya tetap ikut dicoba, karena mengulang lebih baik daripada mengganti
# maksud rencana, tetapi ditaruh di belakang: yang belum terdengar dulu, lalu yang hanya mirip, lalu yang persis sama. Di
# antara yang sudah terdengar, yang paling lama tidak terdengar didahulukan, jadi varian dipakai bergiliran.
# Alur: 1 isi tiap varian sesuai rencana -> 2 ubah kata ganti persona -> 3 kapan terakhir terdengar kalimat yang persis
#       sama dan yang mirip -> 4 urutkan: belum terdengar, mirip paling lama, persis paling lama -> 5 tanpa varian:
#       kalimat cadangan
def kalimat_templat(p, persona, hindari=()):
    dasar_hindari = [bentuk_dasar(h) for h in hindari]
    calon = {}
    for pola in urutan_varian(p, persona):
        teks = isi_templat(pola, p)
        if teks is None:
            continue
        teks = ubah_kata_ganti(teks, persona)
        if teks in calon:
            continue
        # Letak terakhir di hindari, makin besar makin baru; -1 berarti belum terdengar. Persis dibandingkan pada bentuk
        # dasarnya, jadi "Gw bukan Hitman" dari bot lain sama dengan "Aku bukan Hitman". Kalimat yang persis sama tidak
        # perlu dihitung kemiripannya: dua kalimat dengan letak persis yang sama juga sama bentuk dasarnya.
        dasar = bentuk_dasar(teks)
        persis = max((i for i, h in enumerate(dasar_hindari) if h == dasar), default=-1)
        mirip = persis if persis >= 0 else next(
            (i for i in range(len(hindari) - 1, -1, -1) if kemiripan(teks, hindari[i]) >= MIRIP_MAKS), -1)
        calon[teks] = (persis, mirip, len(calon))
    return sorted(calon, key=calon.get) or [ubah_kata_ganti(kalimat_cadangan(p), persona)]

# Varian templat chat tim yang sudah diberi persona; yang mirip dengan chat tim terakhir diletakkan paling belakang.
def kalimat_tim(p, persona):
    sendiri = p["target_saya"] == p["pembicara"]
    t = "diri sendiri" if sendiri else p["target_saya"]
    alasan = [] if sendiri else p["alasan"]
    daftar = TEMPLAT_TIM[p["tim"]][p["pemicu"]]
    kunci = json.dumps([p["pembicara"], p["pemicu"], p["target_saya"], p["pilihan_rekan"]], ensure_ascii=False)
    geser = int(hashlib.sha256(kunci.encode("utf-8")).hexdigest(), 16) % len(daftar)
    hindari = [m["teks"] for m in p["chat_tim"]]
    baru, ulang = [], []
    for pola in daftar[geser:] + daftar[:geser]:
        if "{b1}" in pola and not alasan:
            continue
        teks = pola.replace("{b1}", alasan[0] if alasan else "").replace("{t}", t or "").replace("{r}", p["pilihan_rekan"] or "")
        teks = ubah_kata_ganti(re.sub(r"\s+", " ", teks).strip(), persona)
        (ulang if kalimat_mirip(teks, hindari) else baru).append(teks)
    return baru + ulang
