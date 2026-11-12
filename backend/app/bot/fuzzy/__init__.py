"""Fungsi fuzzy Mamdani otak bot: satu sistem = satu fungsi, input dua angka 0–1, keluaran centroid 0–100.

Folder ini hanya berisi fungsi fuzzy, tanpa urutan keputusan atau kondisi game. Rangkaian dan pemakaiannya ada di
bot/fuzzy_controller.py. Tiap file fungsi hanya mengimpor mesin.py.

Isi folder
- mesin.py       kurva rendah/sedang/tinggi, bangun sistem, hitung centroid + cache, daftar SEMUA_SISTEM, penjelasan
- kecurigaan.py  [FUZZY 1] 7 sistem warga: sentimen_sosial, perilaku_mencurigakan, jejak, kejanggalan, ucapan,
                 bukti_keras, kecurigaan
- ancaman.py     [FUZZY 1] 4 sistem Hitman: ancaman_langsung, ancaman_peran, ancaman, kambing
- diskusi.py     [FUZZY 2] 6 sistem chat: tuduh, bela_orang, ajak_bicara, tanya_info, h_tuduh, klaim_palsu
- tribunal.py    [FUZZY 2] 2 sistem vote warga: keyakinan_vote, kesiapan_vote
- malam.py       [FUZZY 2] 2 sistem aksi malam: gag, intip

Menambah atau mengubah satu fuzzy
1. Tulis konstanta ATURAN_<NAMA> (3 baris × 3 kolom dari "rendah", "sedang", "tinggi"; baris = input pertama, kolom =
   input kedua) di file kelompoknya, lalu fungsinya tepat di bawahnya:
       @sistem_fuzzy(ATURAN_<NAMA>, "arti satu kalimat untuk panel")
       def <nama>(input_pertama, input_kedua):
           return hitung("<nama>", input_pertama, input_kedua)
   Nama fungsi = nama sistem, nama parameter = nama input (muncul di panel sebagai "input=tingkat").
2. File kelompok baru harus ikut diimpor di bawah ini supaya sistemnya terdaftar.
3. Panggil fungsinya di fuzzy_controller.py. Keluaran 0–100; bagi 100 bila menjadi input fungsi fuzzy lain.

Yang dibaca pemakai lain: SEMUA_SISTEM (penjelasan panel, tes, pembangun dokumen), TAHAP, POHON_KECURIGAAN,
keanggotaan, aturan_aktif, dan nilai_sistem.
"""

# Memuat file fungsi = mendaftarkan sistemnya. Urutan impor ini menjadi urutan SEMUA_SISTEM: [FUZZY 1] lalu [FUZZY 2],
# sesuai urutan sesi.
from app.bot.fuzzy import kecurigaan
from app.bot.fuzzy import ancaman
from app.bot.fuzzy import diskusi
from app.bot.fuzzy import tribunal
from app.bot.fuzzy import malam
from app.bot.fuzzy.mesin import SEMUA_SISTEM, aturan_aktif, hitung, keanggotaan, nilai_sistem

__all__ = ["SEMUA_SISTEM", "TAHAP", "POHON_KECURIGAAN", "ancaman", "aturan_aktif", "diskusi", "hitung", "kecurigaan",
           "keanggotaan", "malam", "nilai_sistem", "tribunal"]

# Tahap otak tiap kelompok sistem (kunci "kelompok" di SEMUA_SISTEM): 1 = [FUZZY 1] menilai pemain, 2 = [FUZZY 2]
# memilih tindakan.
TAHAP = {"kecurigaan": 1, "ancaman": 1, "diskusi": 2, "tribunal": 2, "malam": 2}

# Pohon kecurigaan untuk panel: (sistem, input pertama, input kedua) urut dari sistem bukti sampai puncak, diturunkan
# dari urutan fungsi di kecurigaan.py. fuzzy_controller.nilai_kecurigaan memanggil fungsinya dengan urutan yang sama.
POHON_KECURIGAAN = [(nama, *s["input"]) for nama, s in SEMUA_SISTEM.items() if s["kelompok"] == "kecurigaan"]
