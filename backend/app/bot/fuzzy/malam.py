"""[FUZZY 2] Dua fungsi fuzzy Aksi Malam: prioritas 0–100 satu kandidat Gag (Hitman) atau Peek (Stalker).

File ini hanya berisi fungsinya. fuzzy_controller.keputusan_aksi memanggilnya lewat nama sistem kandidat; Hostage dan
Guard tidak memakai fuzzy (nilainya dari calon_hostage dan calon_guard).

Isi berurutan
1. gag
2. intip (Peek)
"""

from app.bot.fuzzy.mesin import hitung, sistem_fuzzy

# ===== 1. GAG =====

# Membungkam warga yang sedang menggalang suara dan memang berbahaya bagi Hitman.
# Alur: 1 ancaman_sekarang dan ancaman jadi rendah/sedang/tinggi -> 2 cek tabel aturan -> 3 centroid -> 4 angka 0–100
ATURAN_GAG = [                        # baris = ancaman_sekarang, kolom = ancaman (rendah, sedang, tinggi)
    ["rendah", "rendah", "rendah"],   # ancaman_sekarang rendah
    ["rendah", "sedang", "tinggi"],   # ancaman_sekarang sedang
    ["sedang", "tinggi", "tinggi"],   # ancaman_sekarang tinggi
]

@sistem_fuzzy(ATURAN_GAG, "Membungkam penggalang suara yang memang berbahaya bagi Hitman.")
def gag(ancaman_sekarang, ancaman):
    return hitung("gag", ancaman_sekarang, ancaman)

# ===== 2. INTIP (PEEK) =====

# Memeriksa tersangka terkuat; pemain yang infonya masih minim menambah nilai Peek.
# Alur: 1 kecurigaan dan kurang_info jadi rendah/sedang/tinggi -> 2 cek tabel aturan -> 3 centroid -> 4 angka 0–100
ATURAN_INTIP = [                      # baris = kecurigaan, kolom = kurang_info (rendah, sedang, tinggi)
    ["rendah", "rendah", "sedang"],   # kecurigaan rendah
    ["sedang", "sedang", "tinggi"],   # kecurigaan sedang
    ["tinggi", "tinggi", "tinggi"],   # kecurigaan tinggi
]

@sistem_fuzzy(ATURAN_INTIP, "Memeriksa tersangka terkuat; info yang minim menambah nilai Peek.")
def intip(kecurigaan, kurang_info):
    return hitung("intip", kecurigaan, kurang_info)
