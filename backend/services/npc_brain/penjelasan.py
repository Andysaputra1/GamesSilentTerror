"""Penjelasan keputusan bot untuk panel admin: hasil putuskan() → JSON ringkas yang mudah dibaca.

Isi: identitas bot, parameter masukan (konteks, pengetahuan, tersangka), penalaran sesuai metode
(Fuzzy Mamdani, Utility AI/IAUS, Behavior Tree), dan keputusan chat/vote/aksi. Dihitung di thread
keputusan (BrainRuntime.langkah) lalu disimpan di trace checker.

Penjelasan memuat role bot dan kecurigaannya, jadi hanya untuk panel (require_panel) dan tidak
pernah dikirim ke pemain. Fungsi publik tidak pernah melempar error ke game: bagian yang gagal
diganti catatan, dan ukurannya dibatasi BATAS_BYTE.
"""

from __future__ import annotations

import copy
import json
import math
from numbers import Integral, Real

VERSI = 1
BATAS_BYTE = 12_000  # ukuran maksimal satu penjelasan (JSON UTF-8)
MAKS_BARIS = 5  # baris per tabel
MAKS_ATURAN = 5  # aturan fuzzy yang ditampilkan per sistem
MAKS_JALUR_BT = 30  # node Behavior Tree per keputusan
MAKS_DAFTAR = 12  # isi daftar (nama, alasan)
MAKS_TEKS = 240  # karakter per teks

# Kolom tabel tersangka: bukti bersama semua metode, lalu nilai antara khas tiap metode.
KOLOM_BUKTI = ["kecurigaan", "tekanan", "dukungan", "inkonsistensi", "pengalihan", "dituduh_korban",
               "dorong_salah_eksekusi", "serang_bersih", "klaim", "p_sandera", "diam"]  # fmt: skip
KOLOM_METODE = {
    "fuzzy": ["sosial", "perilaku", "jejak", "pribadi", "ucapan", "bukti_keras"],
    "utility": ["kecurigaan_mentah"],
    "bt": ["poin", "bendera", "bobot_bukti"],
}
KOLOM_HITMAN = ["pemain", "ancaman", "kambing_hitam", "menuduh_saya", "pengaruh", "klaim_peran",
                "kecurigaan_publik", "dukungan_suara", "p_sandera", "tidak_dijaga", "ancaman_sekarang",
                "ancaman_langsung", "ancaman_peran", "poin_ancaman", "bendera_ancaman"]  # fmt: skip
KOLOM_LINDUNG = [
    "pemain",
    "terancam",
    "kepercayaan",
    "menuduh_tersangka",
    "klaim_stalker",
    "pengaruh",
]

# Nama sistem fuzzy / pertimbangan utility untuk aksi rahasia (aksi engine → nama di notebook).
SISTEM_AKSI = {"hostage": "sandera", "guard": "lindung", "peek": "intip", "gag": "gag"}

# Ambang tiap keputusan: (nama konstanta di modul notebook, arti). Nilainya dibaca dari modul.
AMBANG_CHAT = {
    "fuzzy": [("AMBANG_CHAT", "prioritas minimal agar bot chat")],
    "utility": [("UTILITAS_TUNGGU", "utilitas diam; chat dikirim bila lebih besar")],
    "bt": [("POIN_KUAT", "poin tersangka kuat"), ("POIN_TERSANGKA", "poin tersangka"),
           ("SELISIH_UNGGUL", "selisih bobot bukti agar satu nama unggul")],
}  # fmt: skip
AMBANG_AKSI = {
    "fuzzy": [("AMBANG_GAG", "prioritas minimal Gag (aksi lain memilih kandidat terbaik)")],
    "utility": [
        ("AMBANG_GAG_UTILITAS", "utilitas minimal Gag (aksi lain memilih kandidat terbaik)")
    ],
}
AMBANG_VOTE = {
    "fuzzy": [("VOTE_LANGSUNG", "kesiapan ≥ nilai ini: vote langsung"),
              ("AMBANG_VOTE", "kesiapan ≥ nilai ini: vote setelah separuh Tribunal"),
              ("VOTE_TUNGGU_FRAKSI", "porsi Tribunal sebelum vote biasa dikunci")],
    "utility": [("UTILITAS_VOTE_LANGSUNG", "utilitas ≥ nilai ini: vote langsung"),
                ("VOTE_TUNGGU_FRAKSI", "porsi Tribunal sebelum vote biasa dikunci")],
    "bt": [("POIN_KUAT", "poin tersangka kuat (vote langsung)"),
           ("POIN_TERSANGKA", "poin tersangka (vote setelah separuh Tribunal)"),
           ("URGENSI_KRITIS", "urgensi kesempatan terakhir"),
           ("VOTE_TUNGGU_FRAKSI", "porsi Tribunal sebelum vote biasa dikunci")],
}  # fmt: skip
AMBANG_VOTE_HITMAN = [
    ("VOTE_TUNGGU_FRAKSI", "Hitman menunggu arah suara sampai porsi ini, kecuali terdesak")
]


# ---------------------------------------------------------------- nilai JSON
# Nilai numpy/pandas/set → tipe JSON; angka dibulatkan, NaN menjadi None, teks dan daftar dibatasi.
def _nilai(x, kedalaman=0):
    if x is None or isinstance(x, bool):
        return x
    if type(x).__name__ == "bool_":  # numpy.bool_
        return bool(x)
    if isinstance(x, Integral):
        return int(x)
    if isinstance(x, Real):
        x = float(x)
        return round(x, 3) if math.isfinite(x) else None
    if isinstance(x, str):
        return x if len(x) <= MAKS_TEKS else x[: MAKS_TEKS - 1] + "…"
    if kedalaman >= 3:
        return _nilai(str(x))
    if isinstance(x, dict):
        return {str(k): _nilai(v, kedalaman + 1) for k, v in list(x.items())[: MAKS_DAFTAR * 2]}
    if isinstance(x, (set, frozenset)):
        x = sorted(x, key=str)
    if isinstance(x, (list, tuple)):
        return [_nilai(v, kedalaman + 1) for v in list(x)[:MAKS_DAFTAR]]
    if hasattr(x, "to_dict"):  # pandas Series
        return _nilai(x.to_dict(), kedalaman)
    return _nilai(str(x))


def _angka(x):
    try:
        x = float(x)
    except (TypeError, ValueError):
        return None
    return x if math.isfinite(x) else None


def _fmt(x, desimal=2):
    x = _angka(x)
    return "—" if x is None else f"{x:.{desimal}f}"


# Dict pertimbangan/input → teks ringkas "nama=0.62 · nama=1.00" untuk sel tabel.
def _ringkas_dict(d):
    if not isinstance(d, dict):
        return _nilai(d)
    return " · ".join(f"{k}={_fmt(v)}" for k, v in d.items())


def _kosong(df):
    return df is None or not hasattr(df, "columns") or getattr(df, "empty", True)


def _baris(df):
    return [] if _kosong(df) else df.to_dict("records")


# DataFrame → {"kolom", "baris"} berisi kolom yang tersedia saja (toleran kolom hilang).
def _tabel(rows, kolom, n=MAKS_BARIS):
    rows = list(rows)[:n]
    ada = [k for k in kolom if any(k in r for r in rows)]
    if not rows or not ada:
        return None
    return {"kolom": ada, "baris": [[_nilai(_sel(r.get(k))) for k in ada] for r in rows]}


def _sel(x):
    return _ringkas_dict(x) if isinstance(x, dict) else x


# ---------------------------------------------------------------- bagian umum
def _identitas(bot, view):
    saya = (view or {}).get("saya") or {}
    return {
        "nama": saya.get("nama") or getattr(bot, "nama", None),
        "role": saya.get("role") or getattr(bot, "peran", None),
        "metode": getattr(bot, "metode", None),
        "persona": getattr(bot, "persona", None),
        "ronde": _nilai((view or {}).get("ronde")),
        "fase": (view or {}).get("fase"),
        "langkah": _nilai(getattr(bot, "langkah", None)),
        "boleh_chat": _nilai(saya.get("can_chat")),
        "boleh_vote": _nilai(saya.get("can_vote")),
        "kemampuan": saya.get("ability"),
        "boleh_aksi": _nilai(saya.get("can_act")),
    }


def _pengetahuan(pengetahuan, bot):
    hasil = _nilai(dict(pengetahuan or {}))
    hasil.pop("peran", None)  # sudah ada di identitas
    intel = getattr(getattr(bot, "ingatan", None), "intel", None)
    if intel:  # hasil Peek milik bot sendiri
        hasil["intel"] = [
            f"ronde {x.get('ronde')}: {x.get('pemain')} = {x.get('peran')}"
            for x in intel[:MAKS_DAFTAR]
        ]
    return hasil


# Urutan tersangka: urutan metode untuk warga; Hitman melihat citra publik (paling dicurigai dulu).
def _urut_tersangka(hasil, peran):
    rows = [r for r in _baris(hasil.get("tabel")) if r.get("kandidat", True)]
    if peran == "hitman" or not hasil.get("urutan_tersangka"):
        return sorted(
            rows, key=lambda r: (-(_angka(r.get("kecurigaan")) or 0.0), str(r.get("pemain")))
        )
    posisi = {nama: i for i, nama in enumerate(hasil["urutan_tersangka"])}
    return sorted(rows, key=lambda r: posisi.get(r.get("pemain"), len(posisi)))


def _tersangka(hasil, metode, peran):
    rows = _urut_tersangka(hasil, peran)
    tabel = _tabel(rows, ["pemain", *KOLOM_BUKTI, *KOLOM_METODE.get(metode, []), "fakta"])
    if tabel is None:
        return None
    tabel["judul"] = (
        "Citra publik (cara warga melihat meja)" if peran == "hitman" else "Tersangka teratas"
    )
    tabel["rincian"] = [
        {"pemain": r.get("pemain"),
         "penuduh": _nilai((r.get("rincian") or {}).get("penuduh", [])),
         "pembela": _nilai((r.get("rincian") or {}).get("pembela", [])),
         "diserang": _nilai((r.get("rincian") or {}).get("diserang", [])),
         "bersih_klaim": _nilai(r.get("bersih_klaim"))}
        for r in rows[:3]
    ]  # fmt: skip
    return tabel


# Tabel khusus role: ancaman bagi Hitman, kebutuhan Guard bagi Spy.
def _khusus_peran(hasil, peran):
    if peran == "hitman":
        rows = sorted(_baris(hasil.get("fitur_hitman")),
                      key=lambda r: (-(_angka(r.get("ancaman")) or 0.0), str(r.get("pemain"))))  # fmt: skip
        tabel = _tabel(rows, KOLOM_HITMAN)
        judul = "Ancaman bagi Hitman dan calon kambing hitam"
    elif peran == "spy":
        rows = sorted(_baris(hasil.get("lindung")),
                      key=lambda r: (-(_angka(r.get("terancam")) or 0.0), str(r.get("pemain"))))  # fmt: skip
        tabel = _tabel(rows, KOLOM_LINDUNG)
        judul = "Calon yang perlu di-Guard"
    else:
        return None
    if tabel is not None:
        tabel["judul"] = judul
    return tabel


def _rencana(rencana, *kunci):
    rencana = rencana or {}
    hasil = {k: _nilai(rencana.get(k)) for k in kunci if k in rencana}
    hasil["alasan"] = _nilai(list(rencana.get("alasan") or [])[:3])
    return hasil


def _keputusan(hasil):
    return {
        "chat": _rencana(
            hasil.get("rencana_chat"), "kirim", "aksi", "intent", "target", "klaim", "skor"
        ),
        "vote": _rencana(hasil.get("rencana_vote"), "aksi", "target", "skor"),
        "aksi": _rencana(hasil.get("rencana_aksi"), "aksi", "target", "skor"),
    }


# ---------------------------------------------------------------- penalaran per metode
def _sistem_fuzzy(modul, aksi, peran):
    semua = getattr(modul, "SEMUA_SISTEM", {})
    calon = ([f"h_{aksi}"] if peran == "hitman" else []) + [SISTEM_AKSI.get(aksi, aksi), aksi]
    return next((s for s in calon if s in semua), None)


# Satu sistem Mamdani: derajat keanggotaan input, aturan yang menyala, dan keluaran defuzzifikasi.
def _detail_fuzzy(modul, sistem, nilai_input, keluaran):
    spesifikasi = getattr(modul, "SEMUA_SISTEM", {}).get(sistem)
    if spesifikasi is None:
        return None
    a, b = spesifikasi["input"]
    x, y = _angka(nilai_input.get(a)), _angka(nilai_input.get(b))
    if x is None or y is None:
        return {"nama": sistem, "arti": spesifikasi.get("arti"), "keluaran": _nilai(keluaran),
                "catatan": "Nilai input tidak tercatat."}  # fmt: skip
    derajat = getattr(modul, "keanggotaan", None)
    aktif = getattr(modul, "aturan_aktif", None)
    aturan = _baris(aktif(sistem, x, y)) if aktif else []
    return {
        "nama": sistem,
        "arti": spesifikasi.get("arti"),
        "input": [{"nama": n, "nilai": _nilai(v), "derajat": _nilai(derajat(v)) if derajat else None}
                  for n, v in ((a, x), (b, y))],  # fmt: skip
        "aturan": [
            [r.get("jika"), r.get("maka"), _nilai(r.get("kekuatan"))] for r in aturan[:MAKS_ATURAN]
        ],
        "keluaran": _nilai(keluaran),
    }


# Ambang yang dipakai metode: [nama konstanta notebook, nilai, arti].
def _ambang(modul, daftar):
    return [
        [nama, _nilai(getattr(modul, nama)), arti] for nama, arti in daftar if hasattr(modul, nama)
    ]


def _cocok(r, rencana):
    return r.get("aksi") == rencana.get("aksi") and r.get("target") == rencana.get("target")


# Keputusan dari fakta pasti (hasil Peek) tidak dinalar metode.
def _blok_fakta(jejak, judul):
    rows = _baris(jejak)
    if rows and "sumber" in rows[0]:
        return {
            "judul": judul,
            "jenis": "fakta",
            "hasil": f"Fakta pasti ({rows[0]['sumber']}); tanpa inferensi metode.",
        }
    return None


def _narasi_rencana(rencana, kosong="Tidak ada keputusan."):
    rencana = rencana or {}
    alasan = (rencana.get("alasan") or [None])[0]
    aksi, target = rencana.get("aksi"), rencana.get("target")
    if not aksi:
        return kosong
    if aksi in ("tunggu", "abstain", "tidak_bisa"):
        return f"{aksi.replace('_', ' ').capitalize()}: {alasan}" if alasan else aksi
    return f"{aksi}{f' → {target}' if target else ''}"


# Chat dan aksi rahasia: kandidat dinilai metode, lalu yang terbaik dibandingkan ambang.
def _blok_kandidat(modul, metode, jejak, rencana, peran, judul, ambang):
    fakta = _blok_fakta(jejak, judul)
    if fakta:
        return fakta
    rows = _baris(jejak)
    blok = {"judul": judul, "jenis": metode, "hasil": _narasi_rencana(rencana)}
    if rows and ambang:
        blok["ambang"] = _ambang(modul, ambang)
    if metode == "bt":
        return {**blok, **_jalur_bt(rows)}
    if not rows:
        return blok
    diam = bool(rencana) and rencana.get("aksi") in ("tunggu", "tidak_bisa")
    if diam:
        # Rencana diam: yang dijelaskan kandidat terbaik yang kalah dari ambang, bukan baris "tunggu"
        # pembanding (utility menambahkan baris itu dengan utilitas diam).
        pesaing = [r for r in rows if r.get("aksi") != "tunggu"] or rows
        terpilih = max(pesaing, key=lambda r: _angka(_skor(r)) or 0.0)
    else:
        terpilih = next((r for r in rows if _cocok(r, rencana or {})), None) or rows[0]
    if metode == "fuzzy":
        blok["kandidat"] = _tabel(rows, ["aksi", "target", "prioritas", "input"])
        sistem = _sistem_fuzzy(modul, terpilih.get("aksi"), peran)
        detail = (
            _detail_fuzzy(modul, sistem, terpilih.get("input") or {}, terpilih.get("prioritas"))
            if sistem
            else None
        )
        blok["sistem"] = [detail] if detail else []
    else:
        bobot = getattr(modul, "PERTIMBANGAN", {})
        for r in rows:
            sistem = SISTEM_AKSI.get(r.get("aksi"), r.get("aksi"))
            nama = f"h_{sistem}" if peran == "hitman" and f"h_{sistem}" in bobot else sistem
            r["bobot"] = bobot[nama][0] if nama in bobot else None
        blok["kandidat"] = _tabel(rows, ["aksi", "target", "bobot", "pertimbangan", "utilitas"])
    skor = _skor(terpilih)
    if diam and skor is not None:
        pembanding = next((r for r in rows if r.get("aksi") == "tunggu"), None)
        batas = f" ≤ utilitas diam {_fmt(_skor(pembanding))}" if pembanding else ""
        blok["hasil"] += f" (kandidat terbaik {terpilih.get('aksi')} = {_fmt(skor)}{batas})"
    elif skor is not None:
        blok["hasil"] += f" (nilai {_fmt(skor)})"
    return blok


# Skor kandidat: prioritas (fuzzy) atau utilitas (utility AI).
def _skor(r):
    return r.get("prioritas", r.get("utilitas")) if r else None


# Jalur Behavior Tree: setiap node yang dievaluasi beserta statusnya, sampai keputusan.
def _jalur_bt(rows):
    if not rows or "node" not in rows[0]:
        return {}
    jalur = rows[-MAKS_JALUR_BT:]
    return {
        "status_akar": rows[0].get("status_akar"),
        "jalur": {"kolom": ["node", "jenis", "status"],
                  "baris": [[r.get("node"), r.get("jenis"), r.get("status")] for r in jalur]},
        "cabang": next((r.get("node") for r in reversed(rows) if r.get("jenis") == "aksi"), None),
    }  # fmt: skip


# Vote warga metode fuzzy: keyakinan_vote(kecurigaan, keunggulan) → kesiapan_vote(keyakinan, urgensi).
def _vote_fuzzy(modul, rows):
    if not rows or "kesiapan" not in rows[0]:
        return {}
    r = rows[0]
    keyakinan = _angka(r.get("keyakinan"))
    sistem = [
        _detail_fuzzy(modul, "keyakinan_vote", r, None if keyakinan is None else keyakinan * 100),
        _detail_fuzzy(modul, "kesiapan_vote", r, r.get("kesiapan")),
    ]
    return {
        "kandidat": _tabel(rows, ["kandidat", "kecurigaan", "keunggulan", "keyakinan", "urgensi", "kesiapan",
                                  "porsi_tribunal"]),
        "sistem": [s for s in sistem if s],
    }  # fmt: skip


def _blok_vote(modul, metode, jejak, rencana, peran):
    judul = "Vote Tribunal"
    fakta = _blok_fakta(jejak, judul)
    if fakta:
        return fakta
    rows = _baris(jejak)
    blok = {"judul": judul, "jenis": metode, "hasil": _narasi_rencana(rencana)}
    if rencana and rencana.get("aksi") == "vote" and rencana.get("skor") is not None:
        blok["hasil"] += f" (skor {_fmt(rencana['skor'])})"
    hitman = bool(rows) and "kambing_hitam" in rows[0]
    if hitman:
        # Hitman: vote ke kambing hitam (logika bersama, nilainya dari metode masing-masing).
        blok["kandidat"] = _tabel(
            rows, ["pemain", "kambing_hitam", "kecurigaan_publik", "dukungan_suara"]
        )
        baris = next((r for r in rows if r.get("pemain") == (rencana or {}).get("target")), None)
        if metode == "fuzzy" and baris is not None:
            keluaran = (_angka(baris.get("kambing_hitam")) or 0.0) * 100
            detail = _detail_fuzzy(modul, "kambing", baris, keluaran)
            blok["sistem"] = [detail] if detail else []
        elif metode != "fuzzy":
            blok["catatan"] = (
                "Vote Hitman memakai logika bersama semua metode (kambing hitam terbaik); "
                "nilai kambing_hitam di tabel dihitung metode ini."
            )
    elif metode == "fuzzy":
        blok.update(_vote_fuzzy(modul, rows))
    elif metode == "utility":
        blok["kandidat"] = _tabel(rows, ["pilihan", "kecurigaan", "bukan sandera", "dukungan suara",
                                         "keunggulan", "utilitas"])  # fmt: skip
    elif metode == "bt":
        blok.update(_jalur_bt(rows))
    if blok.get("kandidat") is None:
        blok.pop("kandidat", None)
    if rows:
        blok["ambang"] = _ambang(
            modul, AMBANG_VOTE_HITMAN if hitman else AMBANG_VOTE.get(metode, [])
        )
    alasan = " ".join((rencana or {}).get("alasan") or [])
    if alasan.startswith("Abstain membiarkan"):
        blok["catatan"] = (
            "Metode memilih abstain, lalu diganti vote ke tersangka teratas (PAKSA_VOTE_BUKTI_LEMAH)."
        )
    return blok


# Mengapa tersangka teratas dicurigai: hierarki Mamdani, komponen noisy-OR, atau bendera merah BT.
def _blok_kecurigaan(modul, metode, hasil, peran):
    if peran == "hitman":
        return None
    rows = _urut_tersangka(hasil, peran)
    if not rows:
        return None
    r = rows[0]
    blok = {"judul": f"Kecurigaan tersangka teratas: {r.get('pemain')}", "jenis": metode,
            "hasil": f"kecurigaan akhir {_fmt(r.get('kecurigaan'))}"}  # fmt: skip
    if r.get("fakta"):
        blok["hasil"] += f" ({r['fakta']})"
    if metode == "fuzzy":
        hierarki = getattr(modul, "HIERARKI", [])
        blok["hierarki"] = {
            "kolom": ["sistem", "input 1", "nilai 1", "input 2", "nilai 2", "keluaran"],
            "baris": [[s, x, _nilai(r.get(x)), y, _nilai(r.get(y)),
                       _nilai(r.get("kecurigaan_mentah") if s == "kecurigaan" else r.get(s))]
                      for s, x, y in hierarki],
        }  # fmt: skip
        mentah = _angka(r.get("kecurigaan_mentah"))
        detail = _detail_fuzzy(modul, "kecurigaan", r, None if mentah is None else mentah * 100)
        blok["sistem"] = [detail] if detail else []
        blok["catatan"] = (
            "Keluaran sistem dibagi 100; kecurigaan akhir = kecurigaan_mentah × (1 − p_sandera)."
        )
    elif metode == "utility":
        bobot = getattr(modul, "BOBOT_BUKTI", {})
        blok["komponen"] = {
            "kolom": ["bukti", "nilai", "bobot", "kontribusi"],
            "baris": [
                [k, _nilai(r.get(k)), _nilai(b), _nilai(r.get(f"u_{k}"))] for k, b in bobot.items()
            ],
        }
        blok["catatan"] = (
            "Noisy-OR: kecurigaan_mentah = 1 − Π(1 − kontribusi); akhir = mentah × (1 − p_sandera)."
        )
    elif metode == "bt":
        bendera = []
        for nama, fungsi, ambang, poin in getattr(modul, "BENDERA", []):
            try:
                nilai = _angka(fungsi(r))
            except Exception:  # kolom hilang: bendera tidak bisa dinilai
                nilai = None
            bendera.append(
                [nama, _nilai(nilai), ambang, poin, bool(nilai is not None and nilai >= ambang)]
            )
        blok["bendera"] = {
            "kolom": ["bendera", "nilai", "ambang", "poin", "aktif"],
            "baris": bendera,
        }
        blok["catatan"] = f"Total poin {_nilai(r.get('poin'))}; kecurigaan = poin / 5 (maks 1)."
    return blok


def _penalaran(modul, metode, hasil, peran):
    return {
        "chat": _blok_kandidat(modul, metode, hasil.get("jejak_chat"), hasil.get("rencana_chat"), peran,
                               "Chat", AMBANG_CHAT.get(metode, [])),
        "vote": _blok_vote(modul, metode, hasil.get("jejak_vote"), hasil.get("rencana_vote"), peran),
        "aksi": _blok_kandidat(modul, metode, hasil.get("jejak_aksi"), hasil.get("rencana_aksi"), peran,
                               "Aksi rahasia", AMBANG_AKSI.get(metode, [])),
        "kecurigaan": _blok_kecurigaan(modul, metode, hasil, peran),
    }  # fmt: skip


# ---------------------------------------------------------------- batas ukuran
def ukuran(data):
    return len(json.dumps(data, ensure_ascii=False, separators=(",", ":")).encode("utf-8"))


# Potong tabel/aturan secara rekursif: baris tabel dan daftar aturan menjadi n, jalur BT menjadi m terakhir.
def _pangkas(obj, n, m):
    if isinstance(obj, dict):
        if isinstance(obj.get("baris"), list):
            obj["baris"] = (
                obj["baris"][-m:]
                if obj.get("kolom") == ["node", "jenis", "status"]
                else obj["baris"][:n]
            )
        if isinstance(obj.get("aturan"), list):
            obj["aturan"] = obj["aturan"][:n]
        for nilai in obj.values():
            _pangkas(nilai, n, m)
    elif isinstance(obj, list):
        for nilai in obj:
            _pangkas(nilai, n, m)


# Pastikan penjelasan ≤ BATAS_BYTE: pangkas bertahap, lalu sisakan identitas, keputusan, dan narasi.
def batasi(penjelasan):
    if ukuran(penjelasan) <= BATAS_BYTE:
        return penjelasan
    catatan = penjelasan.setdefault("catatan", [])
    _pangkas(penjelasan, 3, 12)
    catatan.append("Tabel dan aturan dipangkas agar trace tetap kecil.")
    if ukuran(penjelasan) <= BATAS_BYTE:
        return penjelasan
    for kunci in ("khusus_peran", "tersangka", "pengetahuan", "konteks"):
        penjelasan[kunci] = None
        if ukuran(penjelasan) <= BATAS_BYTE:
            catatan.append("Sebagian parameter dibuang karena terlalu besar.")
            return penjelasan
    penalaran = penjelasan.get("penalaran") or {}
    penjelasan["penalaran"] = {k: ({"judul": v.get("judul"), "jenis": v.get("jenis"), "hasil": v.get("hasil")}
                                   if isinstance(v, dict) else None) for k, v in penalaran.items()}  # fmt: skip
    catatan.append("Detail penalaran dibuang; hanya ringkasan yang disimpan.")
    if ukuran(penjelasan) > BATAS_BYTE:
        return _minimal(
            penjelasan.get("bot"), ["Penjelasan terlalu besar; hanya identitas yang disimpan."]
        )
    return penjelasan


def _minimal(bot, catatan):
    return {"versi": VERSI, "bot": bot if isinstance(bot, dict) else {}, "catatan": catatan}


# ---------------------------------------------------------------- API publik
def jelaskan(bot, modul, view, hasil):
    """Ringkas hasil putuskan() satu langkah bot; tidak pernah melempar error ke game."""
    try:
        identitas = _identitas(bot, view)
    except Exception as error:
        return _minimal({}, [f"Identitas bot tidak terbaca ({type(error).__name__})."])
    try:
        hasil = hasil if isinstance(hasil, dict) else {}
        metode, peran = identitas["metode"], identitas["role"]
        penjelasan = {"versi": VERSI, "bot": identitas, "catatan": []}
        bagian = {
            "keputusan": lambda: _keputusan(hasil),
            "konteks": lambda: _nilai(dict(hasil.get("konteks") or {})),
            "pengetahuan": lambda: _pengetahuan(hasil.get("pengetahuan"), bot),
            "tersangka": lambda: _tersangka(hasil, metode, peran),
            "khusus_peran": lambda: _khusus_peran(hasil, peran),
            "penalaran": lambda: _penalaran(modul, metode, hasil, peran),
        }
        for nama, buat in bagian.items():
            try:
                penjelasan[nama] = buat()
            except Exception as error:  # satu bagian gagal tidak menghapus bagian lain
                penjelasan[nama] = None
                penjelasan["catatan"].append(
                    f"Bagian {nama} gagal dibuat ({type(error).__name__})."
                )
        return batasi(penjelasan)
    except Exception as error:
        return _minimal(identitas, [f"Penjelasan gagal dibuat ({type(error).__name__})."])


# Ringkasan NLG untuk tab panel: kalimat akhir, asal kalimat, penulis LLM, dan hasil validasi IndoBERT.
def _nlg(tulisan, rencana, ditunda):
    rencana = rencana or {}
    if tulisan:
        nlu = tulisan.get("nlu") or {}
        llm = [p for p in tulisan.get("percobaan") or [] if p.get("sumber") == "llm"]
        return {
            "status": "terkirim",
            "teks": _nilai(tulisan.get("teks")),
            "sumber": tulisan.get("sumber"),
            "penulis": tulisan.get("penulis"),  # jalur LLM (None = templat)
            "persona": tulisan.get("persona"),
            "lolos_aturan": _nilai(tulisan.get("lolos_aturan")),
            "lolos_nlu": _nilai(tulisan.get("lolos_nlu")),
            "pelanggaran": _nilai(tulisan.get("pelanggaran") or []),
            "nlu": {k: _nilai(nlu.get(k)) for k in ("intent_prediksi", "confidence", "target_prediksi",
                                                     "cocok_intent", "cocok_target") if k in nlu} or None,
            "percobaan_llm": [_nilai(p.get("status")) for p in llm][:3],
            "percobaan_templat": sum(p.get("sumber") == "templat" for p in tulisan.get("percobaan") or []),
            "detik": _nilai(tulisan.get("detik")),
        }  # fmt: skip
    if rencana.get("kirim") and ditunda:
        return {
            "status": "ditunda",
            "keterangan": "Bot lain sedang bicara (lantai bicara); rencana diputuskan ulang di langkah berikutnya.",
        }
    if rencana.get("kirim"):
        return {
            "status": "tidak terkirim",
            "keterangan": "Fase berganti atau bot tidak lagi boleh chat saat kalimat selesai ditulis.",
        }
    return {"status": "tidak ada chat", "keterangan": _nilai((rencana.get("alasan") or [None])[0])}


def lengkapi(penjelasan, npc, rencana, tulisan, penolakan, ditunda=False):
    """Tambahkan hasil engine dan NLG (setelah kalimat ditulis) ke penjelasan langkah; aman dari error."""
    try:
        if not isinstance(penjelasan, dict):
            return None
        hasil = copy.deepcopy(penjelasan)
        hasil["engine"] = {"action": (npc or {}).get("action"), "target": (npc or {}).get("target"),
                           "ditolak": _nilai(penolakan)}  # fmt: skip
        hasil["nlg"] = _nlg(tulisan, rencana, ditunda)
        return batasi(hasil)
    except Exception as error:
        return _minimal(
            (penjelasan or {}).get("bot"),
            [f"Penjelasan gagal dilengkapi ({type(error).__name__})."],
        )


# Ringkasan kecil untuk daftar jejak panel; penjelasan lengkap diambil saat jejak dibuka.
def ringkas(penjelasan):
    if not isinstance(penjelasan, dict):
        return None
    bot = penjelasan.get("bot") or {}
    keputusan = penjelasan.get("keputusan") or {}
    chat, vote, aksi = (keputusan.get(k) or {} for k in ("chat", "vote", "aksi"))
    baris = []
    if chat.get("kirim"):
        target = f" → {chat['target']}" if chat.get("target") else ""
        baris.append(f"chat {chat.get('aksi')}{target}")
    if vote.get("aksi") == "vote":
        baris.append(f"vote → {vote.get('target')}")
    if aksi.get("aksi") in SISTEM_AKSI:
        baris.append(f"{aksi.get('aksi')} → {aksi.get('target')}")
    return {
        "bot": {
            k: bot.get(k) for k in ("nama", "role", "metode", "persona", "ronde", "fase", "langkah")
        },
        "keputusan": baris,
        "nlg": (penjelasan.get("nlg") or {}).get("status"),
        "ditolak": (penjelasan.get("engine") or {}).get("ditolak"),
    }
