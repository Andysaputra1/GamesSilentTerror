"""[FUZZY 1] Empat fungsi fuzzy dari sudut pandang Hitman: ancaman tiap warga dan kambing hitam → keluaran 0–100.

File ini hanya berisi fungsinya. Rangkaiannya ada di fuzzy_controller.nilai_ancaman: ancaman_langsung dan
ancaman_peran (dibagi 100) menjadi input ancaman; kambing berdiri sendiri. Inputnya dari tabel ingatan.fitur_hitman.

Isi berurutan
1. Ancaman: ancaman_langsung, ancaman_peran, lalu gabungannya ancaman (target Hostage, pemutus seri Gag)
2. Kambing hitam: kambing (target tuduhan dan vote Hitman)
"""

from app.bot.fuzzy.mesin import hitung, sistem_fuzzy

# ===== 1. ANCAMAN: dua sumber bahaya, lalu gabungannya =====

# Bahaya dari tuduhan: warga yang menuduh Syndicate, apalagi bila tuduhannya diikuti pemain lain.
# Alur: 1 menuduh_tim dan pengaruh jadi rendah/sedang/tinggi -> 2 cek tabel aturan -> 3 centroid -> 4 angka 0–100
ATURAN_ANCAMAN_LANGSUNG = [           # baris = menuduh_tim, kolom = pengaruh (rendah, sedang, tinggi)
    ["rendah", "rendah", "sedang"],   # menuduh_tim rendah
    ["sedang", "sedang", "tinggi"],   # menuduh_tim sedang
    ["tinggi", "tinggi", "tinggi"],   # menuduh_tim tinggi
]

@sistem_fuzzy(ATURAN_ANCAMAN_LANGSUNG, "Penuduh Hitman berbahaya, apalagi jika tuduhannya diikuti orang lain.")
def ancaman_langsung(menuduh_tim, pengaruh):
    return hitung("ancaman_langsung", menuduh_tim, pengaruh)

# Bahaya dari peran: pengaku Stalker/Spy, dan warga yang dipercaya meja.
# Alur: 1 mengaku_role_penting dan kredibilitas jadi rendah/sedang/tinggi -> 2 cek tabel aturan -> 3 centroid
#       -> 4 angka 0–100
ATURAN_ANCAMAN_PERAN = [              # baris = mengaku_role_penting, kolom = kredibilitas (rendah, sedang, tinggi)
    ["rendah", "rendah", "sedang"],   # mengaku_role_penting rendah
    ["sedang", "sedang", "tinggi"],   # mengaku_role_penting sedang
    ["tinggi", "tinggi", "tinggi"],   # mengaku_role_penting tinggi
]

@sistem_fuzzy(ATURAN_ANCAMAN_PERAN, "Pengaku Stalker/Spy dan pemain yang dipercaya berbahaya.")
def ancaman_peran(mengaku_role_penting, kredibilitas):
    return hitung("ancaman_peran", mengaku_role_penting, kredibilitas)

# Ancaman gabungan bagi Hitman: salah satu sumber bahaya yang tinggi sudah cukup.
# Alur: 1 ancaman_langsung dan ancaman_peran jadi rendah/sedang/tinggi -> 2 cek tabel aturan -> 3 centroid
#       -> 4 angka 0–100
ATURAN_ANCAMAN = [                    # baris = ancaman_langsung, kolom = ancaman_peran (rendah, sedang, tinggi)
    ["rendah", "sedang", "tinggi"],   # ancaman_langsung rendah
    ["sedang", "tinggi", "tinggi"],   # ancaman_langsung sedang
    ["tinggi", "tinggi", "tinggi"],   # ancaman_langsung tinggi
]

@sistem_fuzzy(ATURAN_ANCAMAN, "Salah satu ancaman tinggi sudah cukup.")
def ancaman(ancaman_langsung, ancaman_peran):
    return hitung("ancaman", ancaman_langsung, ancaman_peran)

# ===== 2. KAMBING HITAM =====

# Kambing hitam terbaik bagi Hitman: warga yang sudah terlihat mencurigakan atau sudah mulai di-vote warga lain.
# Alur: 1 kecurigaan_publik dan dukungan_suara jadi rendah/sedang/tinggi -> 2 cek tabel aturan -> 3 centroid
#       -> 4 angka 0–100
ATURAN_KAMBING = [                    # baris = kecurigaan_publik, kolom = dukungan_suara (rendah, sedang, tinggi)
    ["rendah", "rendah", "sedang"],   # kecurigaan_publik rendah
    ["sedang", "sedang", "tinggi"],   # kecurigaan_publik sedang
    ["tinggi", "tinggi", "tinggi"],   # kecurigaan_publik tinggi
]

@sistem_fuzzy(ATURAN_KAMBING, "Kambing hitam terbaik: sudah terlihat mencurigakan atau sudah mulai di-vote warga.")
def kambing(kecurigaan_publik, dukungan_suara):
    return hitung("kambing", kecurigaan_publik, dukungan_suara)
