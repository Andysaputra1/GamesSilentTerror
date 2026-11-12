"""[FUZZY 2] Enam fungsi fuzzy Sesi Diskusi: prioritas 0–100 satu kandidat chat dari dua input 0–1.

File ini hanya berisi fungsinya. fuzzy_controller.keputusan_chat memanggilnya lewat nama sistem kandidat (kunci
"sistem", bawaannya nama aksi), lalu prioritas tertinggi dikirim bila mencapai AMBANG_CHAT. bela_diri dan jawab tidak
dinilai fuzzy.

Isi berurutan
1. Chat warga: tuduh, bela_orang, ajak_bicara, tanya_info (bela_orang, ajak_bicara, dan tanya_info juga dipakai Hitman)
2. Chat Hitman: h_tuduh, klaim_palsu
"""

from app.bot.fuzzy.mesin import hitung, sistem_fuzzy

# ===== 1. CHAT WARGA =====

# Menuduh tersangka teratas: kecurigaannya jelas dan namanya unggul dari tersangka kedua.
# Alur: 1 kecurigaan dan keunggulan jadi rendah/sedang/tinggi -> 2 cek tabel aturan -> 3 centroid -> 4 angka 0–100
ATURAN_TUDUH = [                      # baris = kecurigaan, kolom = keunggulan (rendah, sedang, tinggi)
    ["rendah", "rendah", "rendah"],   # kecurigaan rendah
    ["rendah", "sedang", "sedang"],   # kecurigaan sedang
    ["sedang", "tinggi", "tinggi"],   # kecurigaan tinggi
]

@sistem_fuzzy(ATURAN_TUDUH, "Menuduh jika kecurigaan jelas dan satu nama unggul.")
def tuduh(kecurigaan, keunggulan):
    return hitung("tuduh", kecurigaan, keunggulan)

# Membela pemain yang sedang ditekan, hanya bila ia sangat dipercaya (pasti bersih atau korban Hostage). Hitman
# memakainya untuk rekan Syndicate yang masih dipercaya publik.
# Alur: 1 tekanan dan kepercayaan jadi rendah/sedang/tinggi -> 2 cek tabel aturan -> 3 centroid -> 4 angka 0–100
ATURAN_BELA_ORANG = [                 # baris = tekanan, kolom = kepercayaan (rendah, sedang, tinggi)
    ["rendah", "rendah", "rendah"],   # tekanan rendah
    ["rendah", "rendah", "tinggi"],   # tekanan sedang
    ["rendah", "sedang", "tinggi"],   # tekanan tinggi
]

@sistem_fuzzy(ATURAN_BELA_ORANG, "Membela hanya pemain yang sangat dipercaya (pasti bersih atau korban Hostage); "
                                 "Hitman memakainya untuk rekan Syndicate yang masih dipercaya publik.")
def bela_orang(tekanan, kepercayaan):
    return hitung("bela_orang", tekanan, kepercayaan)

# Mengajak bicara pemain yang diam, terutama yang juga agak dicurigai.
# Alur: 1 diam dan kecurigaan jadi rendah/sedang/tinggi -> 2 cek tabel aturan -> 3 centroid -> 4 angka 0–100
ATURAN_AJAK_BICARA = [                # baris = diam, kolom = kecurigaan (rendah, sedang, tinggi)
    ["rendah", "rendah", "rendah"],   # diam rendah
    ["rendah", "rendah", "sedang"],   # diam sedang
    ["rendah", "sedang", "sedang"],   # diam tinggi
]

@sistem_fuzzy(ATURAN_AJAK_BICARA, "Mengajak bicara pemain diam yang juga agak dicurigai.")
def ajak_bicara(diam, kecurigaan):
    return hitung("ajak_bicara", diam, kecurigaan)

# Bertanya ke semua pemain saat chat membingungkan atau sepi.
# Alur: 1 chat_membingungkan dan chat_sepi jadi rendah/sedang/tinggi -> 2 cek tabel aturan -> 3 centroid -> 4 angka 0–100
ATURAN_TANYA_INFO = [                 # baris = chat_membingungkan, kolom = chat_sepi (rendah, sedang, tinggi)
    ["rendah", "rendah", "sedang"],   # chat_membingungkan rendah
    ["rendah", "sedang", "sedang"],   # chat_membingungkan sedang
    ["sedang", "sedang", "tinggi"],   # chat_membingungkan tinggi
]

@sistem_fuzzy(ATURAN_TANYA_INFO, "Bertanya saat chat membingungkan atau sepi.")
def tanya_info(chat_membingungkan, chat_sepi):
    return hitung("tanya_info", chat_membingungkan, chat_sepi)

# ===== 2. CHAT HITMAN =====

# Hitman menuduh kambing hitam; makin perlu saat Hitman sendiri mulai dicurigai.
# Alur: 1 kambing_hitam dan risiko_saya jadi rendah/sedang/tinggi -> 2 cek tabel aturan -> 3 centroid -> 4 angka 0–100
ATURAN_H_TUDUH = [                    # baris = kambing_hitam, kolom = risiko_saya (rendah, sedang, tinggi)
    ["rendah", "rendah", "sedang"],   # kambing_hitam rendah
    ["rendah", "sedang", "tinggi"],   # kambing_hitam sedang
    ["sedang", "tinggi", "tinggi"],   # kambing_hitam tinggi
]

@sistem_fuzzy(ATURAN_H_TUDUH, "Menuduh kambing hitam; lebih perlu saat Hitman mulai dicurigai.")
def h_tuduh(kambing_hitam, risiko_saya):
    return hitung("h_tuduh", kambing_hitam, risiko_saya)

# Klaim Peek palsu, langkah terakhir Hitman saat sangat dicurigai dan suara Tribunal mengarah kepadanya.
# Alur: 1 risiko_saya dan suara_saya jadi rendah/sedang/tinggi -> 2 cek tabel aturan -> 3 centroid -> 4 angka 0–100
ATURAN_KLAIM_PALSU = [                # baris = risiko_saya, kolom = suara_saya (rendah, sedang, tinggi)
    ["rendah", "rendah", "rendah"],   # risiko_saya rendah
    ["rendah", "rendah", "sedang"],   # risiko_saya sedang
    ["rendah", "sedang", "tinggi"],   # risiko_saya tinggi
]

@sistem_fuzzy(ATURAN_KLAIM_PALSU, "Langkah terakhir saat Hitman sangat dicurigai dan suara mengarah kepadanya.")
def klaim_palsu(risiko_saya, suara_saya):
    return hitung("klaim_palsu", risiko_saya, suara_saya)
