"""[FUZZY 2] Dua fungsi fuzzy Tribunal warga: keyakinan pada tersangka teratas, lalu kesiapan mengunci vote (0–100).

File ini hanya berisi fungsinya. Rangkaiannya ada di fuzzy_controller.keputusan_vote: keyakinan_vote dibagi 100 lalu
menjadi input kesiapan_vote, dan kesiapan dibandingkan VOTE_LANGSUNG dan AMBANG_VOTE.

Isi berurutan
1. keyakinan_vote
2. kesiapan_vote
"""

from app.bot.fuzzy.mesin import hitung, sistem_fuzzy

# ===== 1. KEYAKINAN VOTE =====

# Seberapa yakin bot memilih tersangka layak teratas: kecurigaannya jelas dan namanya unggul.
# Alur: 1 kecurigaan dan keunggulan jadi rendah/sedang/tinggi -> 2 cek tabel aturan -> 3 centroid -> 4 angka 0–100
ATURAN_KEYAKINAN_VOTE = [             # baris = kecurigaan, kolom = keunggulan (rendah, sedang, tinggi)
    ["rendah", "rendah", "rendah"],   # kecurigaan rendah
    ["rendah", "sedang", "sedang"],   # kecurigaan sedang
    ["sedang", "tinggi", "tinggi"],   # kecurigaan tinggi
]

@sistem_fuzzy(ATURAN_KEYAKINAN_VOTE, "Keyakinan memilih kandidat teratas.")
def keyakinan_vote(kecurigaan, keunggulan):
    return hitung("keyakinan_vote", kecurigaan, keunggulan)

# ===== 2. KESIAPAN VOTE =====

# Seberapa siap bot mengunci vote: keyakinan dinaikkan keadaan warga; makin sedikit warga bebas, makin berani vote.
# Alur: 1 keyakinan dan warga_terdesak jadi rendah/sedang/tinggi -> 2 cek tabel aturan -> 3 centroid -> 4 angka 0–100
ATURAN_KESIAPAN_VOTE = [              # baris = keyakinan, kolom = warga_terdesak (rendah, sedang, tinggi)
    ["rendah", "rendah", "sedang"],   # keyakinan rendah
    ["sedang", "sedang", "tinggi"],   # keyakinan sedang
    ["tinggi", "tinggi", "tinggi"],   # keyakinan tinggi
]

@sistem_fuzzy(ATURAN_KESIAPAN_VOTE, "Makin sedikit warga bebas, makin berani vote.")
def kesiapan_vote(keyakinan, warga_terdesak):
    return hitung("kesiapan_vote", keyakinan, warga_terdesak)
