"""[FUZZY 1] Tujuh fungsi fuzzy kecurigaan dari sudut pandang warga: bukti 0–1 seorang pemain → keluaran 0–100.

File ini hanya berisi fungsinya. Rangkaiannya ada di fuzzy_controller.nilai_kecurigaan: keluaran tiap fungsi dibagi
100 lalu menjadi input fungsi berikutnya, empat sistem bukti → dua gabungan → kecurigaan. Hitman memakai fungsi yang
sama untuk menilai citra publik meja.

Isi berurutan
1. Sistem bukti: sentimen_sosial, perilaku_mencurigakan, jejak, kejanggalan
2. Sistem gabungan: ucapan (bukti lunak), bukti_keras, lalu kecurigaan
"""

from app.bot.fuzzy.mesin import hitung, sistem_fuzzy

# ===== 1. SISTEM BUKTI: empat pasang bukti dari tabel hitung_bukti =====

# Seberapa buruk pandangan meja ke seorang pemain: banyak dituduh menaikkan, banyak dibela menurunkan.
# Alur: 1 tekanan dan dukungan jadi rendah/sedang/tinggi -> 2 cek tabel aturan -> 3 centroid -> 4 angka 0–100
ATURAN_SENTIMEN_SOSIAL = [            # baris = tekanan, kolom = dukungan (rendah, sedang, tinggi)
    ["rendah", "rendah", "rendah"],   # tekanan rendah
    ["sedang", "rendah", "rendah"],   # tekanan sedang
    ["tinggi", "sedang", "sedang"],   # tekanan tinggi
]

@sistem_fuzzy(ATURAN_SENTIMEN_SOSIAL, "Banyak penuduh menaikkan kecurigaan; pembela menurunkannya.")
def sentimen_sosial(tekanan, dukungan):
    return hitung("sentimen_sosial", tekanan, dukungan)

# Seberapa aneh sikap pemain sendiri: berganti sikap dan membalas tuduhan dengan menuduh orang lain saling menguatkan.
# Alur: 1 plin_plan dan alihkan_tuduhan jadi rendah/sedang/tinggi -> 2 cek tabel aturan -> 3 centroid -> 4 angka 0–100
ATURAN_PERILAKU_MENCURIGAKAN = [      # baris = plin_plan, kolom = alihkan_tuduhan (rendah, sedang, tinggi)
    ["rendah", "rendah", "sedang"],   # plin_plan rendah
    ["rendah", "sedang", "tinggi"],   # plin_plan sedang
    ["sedang", "tinggi", "tinggi"],   # plin_plan tinggi
]

@sistem_fuzzy(ATURAN_PERILAKU_MENCURIGAKAN, "Plin-plan dan mengalihkan tuduhan saling menguatkan.")
def perilaku_mencurigakan(plin_plan, alihkan_tuduhan):
    return hitung("perilaku_mencurigakan", plin_plan, alihkan_tuduhan)

# Jejak aksi Hitman di sekitar pemain: penuduhnya dibungkam, atau ia ikut salah eksekusi / memihak Hitman (jejak_kedua).
# Satu jejak yang kuat sudah cukup untuk tinggi.
# Alur: 1 penuduh_dibungkam dan jejak_kedua jadi rendah/sedang/tinggi -> 2 cek tabel aturan -> 3 centroid -> 4 angka 0–100
ATURAN_JEJAK = [                      # baris = penuduh_dibungkam, kolom = jejak_kedua (rendah, sedang, tinggi)
    ["rendah", "sedang", "tinggi"],   # penuduh_dibungkam rendah
    ["sedang", "tinggi", "tinggi"],   # penuduh_dibungkam sedang
    ["tinggi", "tinggi", "tinggi"],   # penuduh_dibungkam tinggi
]

@sistem_fuzzy(ATURAN_JEJAK, "Satu jejak aksi Hitman yang kuat sudah cukup untuk tinggi.")
def jejak(penuduh_dibungkam, jejak_kedua):
    return hitung("jejak", penuduh_dibungkam, jejak_kedua)

# Kejanggalan yang bot tahu pasti: menyerang pemain yang pasti bersih (bisa warga keliru, jadi paling tinggi sedang)
# dan klaim role bermasalah (kuat = tinggi).
# Alur: 1 menuduh_orang_baik dan klaim_role_bermasalah jadi rendah/sedang/tinggi -> 2 cek tabel aturan -> 3 centroid
#       -> 4 angka 0–100
ATURAN_KEJANGGALAN = [                # baris = menuduh_orang_baik, kolom = klaim_role_bermasalah (rendah, sedang, tinggi)
    ["rendah", "sedang", "tinggi"],   # menuduh_orang_baik rendah
    ["sedang", "sedang", "tinggi"],   # menuduh_orang_baik sedang
    ["sedang", "tinggi", "tinggi"],   # menuduh_orang_baik tinggi
]

@sistem_fuzzy(ATURAN_KEJANGGALAN, "Menyerang pemain yang pasti bersih saja = sedang (bisa warga keliru); "
                                  "klaim bermasalah kuat = tinggi.")
def kejanggalan(menuduh_orang_baik, klaim_role_bermasalah):
    return hitung("kejanggalan", menuduh_orang_baik, klaim_role_bermasalah)

# ===== 2. SISTEM GABUNGAN: keluaran sistem bukti (dibagi 100) menjadi input =====

# Bukti lunak: pandangan meja dan sikap pemain digabung.
# Alur: 1 sentimen_sosial dan perilaku_mencurigakan jadi rendah/sedang/tinggi -> 2 cek tabel aturan -> 3 centroid
#       -> 4 angka 0–100
ATURAN_UCAPAN = [                     # baris = sentimen_sosial, kolom = perilaku_mencurigakan (rendah, sedang, tinggi)
    ["rendah", "rendah", "sedang"],   # sentimen_sosial rendah
    ["rendah", "sedang", "tinggi"],   # sentimen_sosial sedang
    ["sedang", "tinggi", "tinggi"],   # sentimen_sosial tinggi
]

@sistem_fuzzy(ATURAN_UCAPAN, "Gabungan bukti lunak.")
def ucapan(sentimen_sosial, perilaku_mencurigakan):
    return hitung("ucapan", sentimen_sosial, perilaku_mencurigakan)

# Bukti keras: jejak aksi Hitman dan kejanggalan pasti digabung; salah satunya kuat sudah tinggi.
# Alur: 1 jejak dan kejanggalan jadi rendah/sedang/tinggi -> 2 cek tabel aturan -> 3 centroid -> 4 angka 0–100
ATURAN_BUKTI_KERAS = [                # baris = jejak, kolom = kejanggalan (rendah, sedang, tinggi)
    ["rendah", "sedang", "tinggi"],   # jejak rendah
    ["sedang", "tinggi", "tinggi"],   # jejak sedang
    ["tinggi", "tinggi", "tinggi"],   # jejak tinggi
]

@sistem_fuzzy(ATURAN_BUKTI_KERAS, "Gabungan bukti keras.")
def bukti_keras(jejak, kejanggalan):
    return hitung("bukti_keras", jejak, kejanggalan)

# Puncak pohon: bukti lunak saja paling tinggi sedang, bukti keras yang tinggi langsung tinggi.
# Alur: 1 ucapan dan bukti_keras jadi rendah/sedang/tinggi -> 2 cek tabel aturan -> 3 centroid -> 4 angka 0–100
ATURAN_KECURIGAAN = [                 # baris = ucapan, kolom = bukti_keras (rendah, sedang, tinggi)
    ["rendah", "sedang", "tinggi"],   # ucapan rendah
    ["sedang", "sedang", "tinggi"],   # ucapan sedang
    ["sedang", "tinggi", "tinggi"],   # ucapan tinggi
]

@sistem_fuzzy(ATURAN_KECURIGAAN, "Bukti lunak saja maksimal sedang; bukti keras tinggi langsung tinggi.")
def kecurigaan(ucapan, bukti_keras):
    return hitung("kecurigaan", ucapan, bukti_keras)
