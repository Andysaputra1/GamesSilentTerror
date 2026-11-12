"""Mesin Fuzzy Mamdani bersama untuk semua fungsi fuzzy otak bot: kurva, satu sistem dua input, centroid, dan cache.

Tiap file lain di folder fuzzy/ berisi fungsi fuzzy saja. Satu sistem = satu fungsi bernama sistem itu, dengan dua
parameter bernama sesuai inputnya (angka 0–1), yang mengembalikan keluaran centroid 0–100 lewat hitung. Tabel aturan
3×3-nya konstanta ATURAN_<NAMA> tepat di atas fungsi, dan dekorator sistem_fuzzy mendaftarkannya ke SEMUA_SISTEM.
File ini tidak mengimpor file bot lain, jadi tidak ada impor melingkar.

Isi berurutan
1. Kurva: tiga tingkat bahasa, titik kurva input (MF_INPUT) dan keluaran (MF_OUTPUT), fungsi keanggotaan
2. Bangun sistem: satu sistem Mamdani dua input dengan 9 aturan
3. Daftar sistem: SEMUA_SISTEM dan SIMULASI, diisi dekorator sistem_fuzzy
4. Hitung: hitung (validasi input lalu cache), _fuzzy_tersimpan (satu run skfuzzy), dan nilai_sistem (panggil fungsi
   sistem menurut namanya)
5. Penjelasan: keanggotaan dan aturan_aktif untuk panel, tidak dipakai saat memutuskan
"""

import inspect
import math
import warnings
from functools import lru_cache

import numpy as np
import pandas as pd
import skfuzzy as fuzz
from skfuzzy import control as ctrl

# scikit-fuzzy memanggil np.maximum dengan argumen ketiga posisional; peringatannya tidak memengaruhi hasil.
warnings.filterwarnings("ignore", category=DeprecationWarning, module=r"skfuzzy(\..*)?")

# ===== 1. KURVA: tingkat rendah/sedang/tinggi untuk input 0–1 dan keluaran 0–100 =====

# Tiga tingkat bahasa untuk semua input dan keluaran, berurutan seperti baris dan kolom tabel ATURAN.
TINGKAT = ["rendah", "sedang", "tinggi"]

# Titik kurva input 0–1: rendah dan tinggi trapesium, sedang segitiga. Derajat ketiganya selalu berjumlah 1.
MF_INPUT = {"rendah": [0.0, 0.0, 0.2, 0.5], "sedang": [0.2, 0.5, 0.8], "tinggi": [0.5, 0.8, 1.0, 1.0]}

# Titik kurva keluaran 0–100: tiga segitiga.
MF_OUTPUT = {"rendah": [0, 15, 30], "sedang": [35, 50, 65], "tinggi": [70, 85, 100]}

# Sumbu input 0–1 (201 titik).
_SEMESTA = np.linspace(0, 1, 201)

# Fungsi keanggotaan dari titik kurva MF_INPUT atau MF_OUTPUT: 4 titik = trapesium, 3 titik = segitiga.
# Menerima semesta = titik sumbu (array) dan titik kurva; hasilnya array derajat 0–1 untuk setiap titik semesta.
def _mf(semesta, titik):
    return fuzz.trapmf(semesta, titik) if len(titik) == 4 else fuzz.trimf(semesta, titik)

# ===== 2. BANGUN SISTEM: satu sistem Mamdani dua input, 9 aturan =====

# Satu sistem Mamdani dua input dengan 9 aturan lengkap (setiap pasangan tingkat input pertama × input kedua).
# Menerima spesifikasi = satu entri SEMUA_SISTEM {input: (nama_a, nama_b), aturan: tabel 3×3, ...}.
# Hasilnya ControlSystemSimulation skfuzzy dengan DAN = min, implikasi = clipping (min), agregasi = max,
#   defuzzifikasi centroid pada semesta 0–100.
# Alur: 1 dua input dan keluaran 0–100 -> 2 kurva rendah/sedang/tinggi -> 3 9 aturan JIKA–MAKA -> 4 simulasi skfuzzy
def _bangun_sistem(spesifikasi):
    nama_a, nama_b = spesifikasi["input"]
    a = ctrl.Antecedent(_SEMESTA, nama_a)
    b = ctrl.Antecedent(_SEMESTA, nama_b)
    keluaran = ctrl.Consequent(np.linspace(0, 100, 201), "keluaran")
    keluaran.defuzzify_method = "centroid"
    for tingkat, titik in MF_INPUT.items():
        a[tingkat] = _mf(a.universe, titik)
        b[tingkat] = _mf(b.universe, titik)
    for tingkat, titik in MF_OUTPUT.items():
        keluaran[tingkat] = _mf(keluaran.universe, titik)
    # Aturan (i, j): JIKA a = TINGKAT[i] DAN b = TINGKAT[j] MAKA keluaran = aturan[i][j]; "&" pada skfuzzy = minimum.
    aturan = [ctrl.Rule(a[x] & b[y], keluaran[spesifikasi["aturan"][i][j]])
              for i, x in enumerate(TINGKAT) for j, y in enumerate(TINGKAT)]
    # Cache internal skfuzzy dikosongkan tiap 10.000 run; hasil tetap disimpan _fuzzy_tersimpan.
    return ctrl.ControlSystemSimulation(ctrl.ControlSystem(aturan), flush_after_run=10000)

# ===== 3. DAFTAR SISTEM: satu daftar untuk mesin, panel, tes, dan pembangun dokumen =====

# Semua sistem yang dikenal mesin, urut seperti didaftarkan: nama → {nama, input, aturan, arti, kelompok, fungsi}.
# input = nama parameter fungsi berurutan, aturan = tabel ATURAN 3×3, kelompok = nama file fungsi (kecurigaan, ancaman,
# diskusi, tribunal, malam), fungsi = fungsi fuzzy itu sendiri. SIMULASI = nama → simulasi skfuzzy yang sudah dibangun.
SEMUA_SISTEM = {}

SIMULASI = {}

# Dekorator yang mendaftarkan satu fungsi fuzzy ke mesin. Nama dan input diambil dari fungsinya sendiri, jadi tabel
# aturan dan arti hanya ditulis sekali. Fungsinya dikembalikan utuh, tanpa pembungkus.
# Alur: 1 nama fungsi dan nama kedua parameternya -> 2 periksa tabel 3×3 -> 3 simpan ke SEMUA_SISTEM -> 4 bangun
#       simulasi sekali
def sistem_fuzzy(aturan, arti):
    def daftarkan(fungsi):
        nama, masukan = fungsi.__name__, tuple(inspect.signature(fungsi).parameters)
        if len(masukan) != 2 or len(aturan) != 3 or any(len(b) != 3 or set(b) - set(TINGKAT) for b in aturan):
            raise ValueError(f"Sistem {nama} harus punya dua input dan tabel aturan 3×3 dari {TINGKAT}.")
        spesifikasi = {"nama": nama, "input": masukan, "aturan": aturan, "arti": arti,
                       "kelompok": fungsi.__module__.rsplit(".", 1)[-1], "fungsi": fungsi}
        SEMUA_SISTEM[nama] = spesifikasi
        SIMULASI[nama] = _bangun_sistem(spesifikasi)
        return fungsi

    return daftarkan

# ===== 4. HITUNG: validasi input, cache, lalu satu run skfuzzy =====

# Satu run skfuzzy, disimpan per (nama, a, b) agar input yang sama tidak dihitung ulang.
# Menerima nama sistem, a dan b = input yang sudah divalidasi dan dibulatkan oleh hitung().
# Hasilnya float 0–100 = centroid himpunan keluaran hasil agregasi.
# Dipanggil oleh hitung (jangan dipanggil langsung karena tanpa validasi input).
# Alur: 1 isi kedua input simulasi -> 2 hitung aturan, agregasi, dan centroid -> 3 ambil keluaran
@lru_cache(maxsize=500_000)
def _fuzzy_tersimpan(nama, a, b):
    simulasi = SIMULASI[nama]
    nama_a, nama_b = SEMUA_SISTEM[nama]["input"]
    simulasi.input[nama_a], simulasi.input[nama_b] = a, b
    simulasi.compute()
    return float(simulasi.output["keluaran"])

# Inferensi Mamdani satu sistem: fuzzifikasi → aturan DAN (min) → agregasi (max) → centroid 0–100. Badan setiap
# fungsi fuzzy hanya memanggil ini dengan namanya sendiri.
# Menerima nama = kunci SEMUA_SISTEM; a, b = input pertama dan kedua sesuai urutan "input" sistem (angka 0–1).
# Hasilnya float 0–100 (nilai tegas). Pemanggil membaginya 100 bila hasilnya menjadi input sistem berikutnya.
# Alur: 1 tiap input: tolak bila di luar 0–1, jepit lalu bulatkan 4 desimal -> 2 hasil dari cache _fuzzy_tersimpan
def hitung(nama, a, b):
    nilai = []
    for x in (a, b):
        x = float(x)
        # Toleransi 1e-9 hanya untuk galat pembulatan; input lain di luar 0–1 adalah kesalahan dan harus berhenti.
        if not math.isfinite(x) or not -1e-9 <= x <= 1 + 1e-9:
            raise ValueError(f"Input sistem {nama} harus angka 0–1, didapat {x}.")
        # Dijepit ke 0–1 lalu dibulatkan 4 desimal: kunci cache yang stabil.
        nilai.append(round(min(1.0, max(0.0, x)), 4))
    return _fuzzy_tersimpan(nama, *nilai)

# Nilai satu sistem yang dipilih lewat namanya: fungsi fuzzy sistem itu dipanggil dengan input dari dict bernama.
# Dipakai saat kandidat sendiri yang menentukan sistemnya (chat, Gag, Peek); dict boleh memuat nilai lain.
def nilai_sistem(nama, masukan):
    spesifikasi = SEMUA_SISTEM[nama]
    a, b = spesifikasi["input"]
    return spesifikasi["fungsi"](masukan[a], masukan[b])

# ===== 5. PENJELASAN: derajat dan aturan yang menyala, untuk panel =====

# Kurva input yang sudah dihitung sekali, untuk fuzzifikasi di keanggotaan.
_KURVA_INPUT = {tingkat: _mf(_SEMESTA, titik) for tingkat, titik in MF_INPUT.items()}

# Fuzzifikasi satu nilai: derajat x pada kurva rendah, sedang, dan tinggi (interpolasi linear seperti skfuzzy).
# Menerima x = angka 0–1. Hasilnya {"rendah": derajat, "sedang": derajat, "tinggi": derajat}; jumlahnya 1.
# Dipanggil oleh aturan_aktif dan penjelasan panel (penjelasan.py).
def keanggotaan(x):
    return {t: float(fuzz.interp_membership(_SEMESTA, kurva, x)) for t, kurva in _KURVA_INPUT.items()}

# Aturan yang menyala untuk satu pasangan input; menjelaskan hasil hitung() dan tidak dipakai saat memutuskan.
# Menerima nama sistem, a dan b (0–1).
# Hasilnya DataFrame {jika, maka, kekuatan}, terkuat dulu. Kekuatan = min(derajat a, derajat b), bukan peluang.
# Dipanggil oleh penjelasan panel (penjelasan.py), serta contoh penalaran dan pengujian cakupan di notebook.
# Alur: 1 derajat kedua input -> 2 kekuatan 9 aturan, yang nol dibuang -> 3 urutkan dari yang terkuat
def aturan_aktif(nama, a, b):
    spesifikasi = SEMUA_SISTEM[nama]
    nama_a, nama_b = spesifikasi["input"]
    derajat_a, derajat_b = keanggotaan(a), keanggotaan(b)
    baris = []
    for i, x in enumerate(TINGKAT):
        for j, y in enumerate(TINGKAT):
            kekuatan = min(derajat_a[x], derajat_b[y])
            if kekuatan > 0:
                baris.append({"jika": f"{nama_a}={x} DAN {nama_b}={y}", "maka": spesifikasi["aturan"][i][j],
                              "kekuatan": kekuatan})
    return pd.DataFrame(baris).sort_values("kekuatan", ascending=False, kind="stable")
