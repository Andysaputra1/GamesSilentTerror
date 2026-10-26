"""Kode asli untuk flowchart proses AI di panel Simulasi.

Sumber fungsi/konstanta diambil dari modul yang sedang berjalan (bukan salinan), lalu setiap baris diberi
penanda: parameter (baris def), output (return), komentar, dan baris inti beserta catatan singkat.
Hanya objek di daftar KODE_ALUR yang bisa dibaca; panel tidak dapat meminta modul atau nama lain.
"""

import ast
import importlib
import inspect
from functools import lru_cache
from pathlib import Path

from app.config.settings import BACKEND_DIR

G = "app.module.npc_brain.generated."
RT = "app.module.npc_brain.runtime"

# node flowchart → [(modul, nama bertitik, [(potongan teks baris inti, catatan)])]
KODE_ALUR = {
    "input": [
        ("app.module.simulasi_service", "Simulasi.kirim", [
            ("can_chat(PEMAIN)", "izin chat diperiksa (siang/Tribunal, tidak dibungkam)"),
            ("m.add_message(PEMAIN", "pesan masuk chat pertandingan"),
            ("self._baca(PEMAIN", "langsung dibaca NLU IndoBERT"),
        ]),
        ("app.module.match_engine", "Match.can_chat", []),
        ("app.module.match_engine", "Match.add_message", [("06d", "ID diawali nomor urut agar chat tetap kronologis")]),
    ],
    "nlu_pesan": [
        (RT, "BrainRuntime.baca_chat", [
            ("modul.anotasi_chat(", "fungsi anotasi yang sama dengan ingatan bot"),
            ("riwayat.append(chat)", "chat ini menjadi konteks chat berikutnya"),
        ]),
        (G + "otak_fuzzy", "anotasi_chat", [
            ("nlu.intent(", "Model 1: intent + keyakinan"),
            ("KONTEKS_MAKS", "maksimal 12 chat terakhir sebagai konteks"),
            ("nlu.target(", "Model 2: target, memakai intent dan konteks"),
            ("pemain_disebut(", "pesan neutral: target neutral dari aturan nama (sumber kedua)"),
        ]),
    ],
    "nlu_intent": [
        (G + "nlg", "NLUIndoBERT.intent", [
            ("varian_nama_intent(", "kalimat dibuat 3 varian nama"),
            (".mean(axis=0)", "probabilitas ketiga varian dirata-rata"),
            ("argmax()", "kelas terbesar menjadi intent"),
        ]),
        (G + "nlg", "NLUIndoBERT._probabilitas", [("softmax", "logit model menjadi probabilitas 0–1")]),
        (G + "nlg", "varian_nama_intent", [("NAMA_KANONIK", "nama pemain diganti nama yang dikenal model")]),
    ],
    "nlu_target": [
        (G + "nlg", "NLUIndoBERT.target", [
            ('label_intent == "neutral"', "pesan neutral: hanya relasi neutral (pemain yang diajak bicara), boleh kosong"),
            ("buat_teks_pasangan(", "satu teks pasangan untuk tiap kandidat"),
            ('relasi != "tidak_ada"', "kandidat berelasi offend/defend/neutral menjadi target"),
            ("self.ambang > 0", "aturan minimal satu target (offend/defend)"),
        ]),
        (G + "nlg", "buat_teks_pasangan", [
            ("reversed(chat_sebelumnya)", "konteks terbaru ditulis lebih dulu"),
            ("samarkan_nama(teks_chat", "nama disamarkan menjadi peran (kandidat/pengirim/pemain)"),
        ]),
    ],
    "nlu_memo": [
        (RT, "NLUBersama._ingat", [
            ("if kunci not in self._memo", "dihitung hanya bila belum ada di memo"),
            ("copy.deepcopy", "tiap bot mendapat salinan sendiri"),
        ]),
        (RT, "NLUBersama.intent", [('("intent", teks, daftar)', "kunci memo: teks + daftar pemain")]),
        (RT, "NLUBersama.target", [("json.dumps(konteks", "konteks chat ikut menjadi kunci memo")]),
    ],
    "sinkron": [
        (RT, "BrainRuntime.langkah", [
            ("sinkron_snapshot(", "ingatan diperbarui (NLU chat baru di sini)"),
            ("modul.putuskan(", "logika metode bot"),
            ("jelaskan(bot", "penjelasan untuk panel"),
            ('hasil["waktu"]', "lama tiap tahap dicatat"),
        ]),
        (G + "otak_fuzzy", "Ingatan.sinkron_snapshot", [
            ("self.catat_eksekusi(", "eksekusi Tribunal dicatat"),
            ("self.intel = ", "hasil Peek milik bot sendiri"),
            ("anotasi_chat(nlu, chat", "chat baru dibaca NLU"),
            ("self.catat_chat(chat)", "chat masuk ingatan"),
        ]),
    ],
    "bukti": [
        (G + "otak_fuzzy", "hitung_bukti", [
            ('"tekanan": min(', "tekanan: tuduhan + vote ke pemain ini"),
            ('"dukungan": min(', "dukungan: pembelaan dari pemain lain"),
            ('"inkonsistensi": min(', "berganti sikap atau vote tidak sesuai ucapan"),
            ('"pengalihan": ', "menuduh balik setelah dituduh"),
            ('"diam": diam', "belum bicara di ronde ini"),
        ]),
        (G + "otak_fuzzy", "pengetahuan_peran", []),
    ],
    "fl": [
        (G + "otak_fuzzy", "putuskan", [
            ("hitung_bukti(ingatan, view)", "bukti tiap pemain"),
            ("nilai_kecurigaan(tabel)", "kecurigaan lewat hierarki fuzzy"),
            ("keputusan_chat(ctx)", "pilih chat"),
            ("keputusan_vote(ctx)", "pilih vote"),
            ("keputusan_aksi(ctx)", "pilih aksi rahasia"),
            ('"nlg": siapkan_nlg(', "rencana kalimat untuk NLG"),
        ]),
    ],
    "fl_1": [
        (G + "otak_fuzzy", "MF_INPUT", [("[0.2, 0.5, 0.8]", "titik fungsi keanggotaan tingkat sedang")]),
        (G + "otak_fuzzy", "_mf", [("trapmf", "4 titik = trapesium, 3 titik = segitiga")]),
        (G + "otak_fuzzy", "keanggotaan", [("interp_membership", "derajat x pada tiap tingkat")]),
    ],
    "fl_2": [
        (G + "otak_fuzzy", "_bangun_sistem", [
            ("ctrl.Rule(a[x] & b[y]", "9 aturan JIKA–MAKA; & = DAN (min)"),
            ('defuzzify_method = "centroid"', "defuzzifikasi centroid"),
        ]),
        (G + "otak_fuzzy", "aturan_aktif", [("min(derajat_a[x], derajat_b[y])", "kekuatan aturan = min derajat input")]),
    ],
    "fl_3": [
        (G + "otak_fuzzy", "fuzzy", [("_fuzzy_tersimpan(nama", "hasil disimpan per input (cache)")]),
        (G + "otak_fuzzy", "_fuzzy_tersimpan", [("simulasi.compute()", "skfuzzy: agregasi max lalu centroid")]),
        (G + "otak_fuzzy", "HIERARKI", [('("kecurigaan", "ucapan", "bukti_keras")', "sistem puncak: kecurigaan")]),
        (G + "otak_fuzzy", "nilai_kecurigaan", [
            ("for sistem, x, y in HIERARKI", "sistem dihitung bertingkat"),
            ("fuzzy(sistem, nilai[x], nilai[y]) / 100", "keluaran 0–100 menjadi 0–1"),
            ('(1 - b["p_sandera"])', "dikurangi dugaan sedang disandera"),
        ]),
    ],
    "fl_4": [
        (G + "otak_fuzzy", "keputusan_chat", [
            ('c["skor"] = fuzzy(sistem', "prioritas tiap kandidat chat"),
            ("calon.sort(", "prioritas tertinggi di depan"),
            ("< AMBANG_CHAT", "di bawah ambang: diam"),
        ]),
        (G + "otak_fuzzy", "AMBANG_CHAT", []),
    ],
    "ua": [
        (G + "otak_utility", "putuskan", [
            ("hitung_bukti(ingatan, view)", "bukti tiap pemain (sama dengan fuzzy)"),
            ("nilai_kecurigaan(tabel)", "kecurigaan noisy-OR"),
            ("keputusan_chat(ctx)", "utilitas chat"),
            ("keputusan_vote(ctx)", "utilitas vote"),
            ("keputusan_aksi(ctx)", "utilitas aksi rahasia"),
        ]),
    ],
    "ua_1": [
        (G + "otak_utility", "kurva_linear", [("np.clip", "dibatasi 0–1")]),
        (G + "otak_utility", "kurva_logistik", [("math.exp", "kurva S: nilai kecil diredam")]),
        (G + "otak_utility", "PERTIMBANGAN", []),
    ],
    "ua_2": [
        (G + "otak_utility", "BOBOT_BUKTI", []),
        (G + "otak_utility", "nilai_kecurigaan", [
            ("BOBOT_BUKTI[k] * float(b[k])", "kontribusi tiap bukti"),
            ('komponen["tekanan"] *= 1 - 0.7', "tekanan diredam oleh dukungan"),
            ("1 - float(np.prod(", "noisy-OR: 1 − Π(1 − kontribusi)"),
            ('(1 - b["p_sandera"])', "dikurangi dugaan sedang disandera"),
        ]),
    ],
    "ua_3": [
        (G + "otak_utility", "skor_iaus", [
            ("modifikasi = 1 - 1 / len(nilai)", "faktor kompensasi IAUS"),
            ("skor *= n + (1 - n) * modifikasi * n", "perkalian pertimbangan dengan kompensasi"),
        ]),
        (G + "otak_utility", "_nilai_calon", [
            ('kurva(c["input"])', "pertimbangan lewat kurva"),
            ("skor_iaus(", "utilitas kandidat"),
        ]),
    ],
    "ua_4": [
        (G + "otak_utility", "keputusan_chat", [
            ("_nilai_calon(calon_chat(ctx))", "semua kandidat chat dinilai"),
            ('"utilitas": UTILITAS_TUNGGU', "diam ikut dibandingkan"),
            ("<= UTILITAS_TUNGGU", "tidak lebih berguna dari diam: tunggu"),
        ]),
        (G + "otak_utility", "UTILITAS_TUNGGU", []),
    ],
    "bt": [
        (G + "otak_bt", "putuskan", [
            ("hitung_bukti(ingatan, view)", "bukti tiap pemain (sama dengan fuzzy)"),
            ("nilai_kecurigaan(tabel)", "poin bendera merah"),
            ("keputusan_chat(ctx)", "pohon chat"),
            ("keputusan_vote(ctx)", "pohon vote"),
            ("keputusan_aksi(ctx)", "pohon aksi rahasia"),
        ]),
    ],
    "bt_1": [
        (G + "otak_bt", "BENDERA", []),
        (G + "otak_bt", "nilai_kecurigaan", [
            ("fungsi(b) >= ambang", "bendera aktif bila bukti ≥ ambangnya"),
            ("poin = sum(", "poin bendera dijumlah"),
            ("poin / 5", "kecurigaan = poin / 5"),
        ]),
    ],
    "bt_2": [
        (G + "otak_bt", "_papan", [
            ("urutan_bt(", "urutan tersangka"),
            ("calon_chat(ctx)", "kandidat chat"),
            ('"jejak": []', "jalur node dicatat di sini"),
        ]),
    ],
    "bt_3": [
        (G + "otak_bt", "Selector", [("if status != Status.GAGAL", "berhenti di anak pertama yang tidak gagal")]),
        (G + "otak_bt", "Sequence", [("if status != Status.SUKSES", "berhenti di syarat yang gagal")]),
        (G + "otak_bt", "Kondisi", [('papan["jejak"].append', "dicatat untuk tab Penalaran")]),
        (G + "otak_bt", "POHON_CHAT", [
            ('Sequence("Bela diri"', "dicoba lebih dulu: membela diri"),
            ('Sequence("Tuduh tersangka kuat"', "tersangka ≥ 3 poin"),
            ('Aksi("tunggu", lambda', "cabang terakhir: diam"),
        ]),
        (G + "otak_bt", "keputusan_chat", [(".tick(papan)", "pohon dijalankan dari akar")]),
    ],
    "bt_4": [
        (G + "otak_bt", "Aksi", [('papan["hasil"] = self.fungsi(papan)', "aksi membuat rencana")]),
        (G + "otak_bt", "_a_tuduh", [("rencana_chat(", "rencana tuduh")]),
    ],
    "keputusan": [
        (G + "otak_fuzzy", "rencana_chat", []),
        (G + "otak_fuzzy", "format_npc", [
            ('if rencana_a["aksi"] in AKSI_RAHASIA', "aksi rahasia diutamakan"),
            ('elif rencana_v["aksi"] == "vote"', "lalu vote"),
        ]),
        (G + "otak_fuzzy", "siapkan_nlg", [
            ('if not rencana["kirim"]', "tidak chat: NLG tidak dijalankan"),
            ('"cadangan": templat_pesan(', "kalimat cadangan bila semua gagal"),
        ]),
    ],
    "penjelasan": [
        ("app.module.npc_brain.penjelasan", "jelaskan", [
            ("_penalaran(modul", "penalaran sesuai metode"),
            ("batasi(penjelasan)", "dibatasi 12 KB"),
        ]),
    ],
    "engine": [
        ("app.module.simulasi_service", "Simulasi._langkah", [
            ("m.vote(", "vote ke engine"),
            ("m.act(", "aksi rahasia ke engine"),
            ("except ValueError", "tidak sah: ditolak engine"),
        ]),
        ("app.module.match_engine", "Match.vote", []),
        ("app.module.match_engine", "Match.act", []),
    ],
    "nlg_prompt": [
        (G + "nlg", "buat_prompt", [
            ("aturan_klaim = (", "aturan klaim role"),
            ("Aturan menulis:", "batasan untuk LLM"),
            ("maksud = MAKSUD_AKSI", "maksud rencana"),
            ('konteks["chat_terbaru"][-JUMLAH_CHAT_KONTEKS:]', "chat terbaru sebagai data"),
            ("if alasan_tolak:", "tulis ulang: alasan penolakan ikut dikirim"),
        ]),
    ],
    "nlg_llm": [
        (G + "nlg", "PenulisBerantai.tulis", [
            ("if not p.siap()", "jalur yang sedang istirahat dilewati"),
            ("p.tulis(sistem, pesan)", "panggil LLM jalur ini"),
            ("alasan.append", "gagal: coba jalur berikutnya"),
        ]),
        (RT, "_JamPenulis.tulis", [
            ('self.lapor("llm")', "flowchart: bot sedang di tahap LLM"),
            ("self.detik +=", "lama panggilan LLM dicatat"),
        ]),
    ],
    "nlg_cek": [
        (G + "nlg", "tulis_pesan", [
            ("for ke in range(1, MAKS_PERCOBAAN_LLM + 1)", "maksimal 2 percobaan LLM"),
            ("nilai_kalimat(bersihkan(", "kalimat dibersihkan lalu dinilai"),
            ('alasan_tolak = ", ".join', "alasan ditolak dikirim ke percobaan berikutnya"),
            ("# 2) Templat bervariasi.", "LLM gagal: templat"),
        ]),
        (G + "nlg", "nilai_kalimat", [
            ("periksa_aturan(", "cek aturan"),
            ("validasi_nlu(", "IndoBERT membaca ulang kalimat"),
        ]),
        (G + "nlg", "periksa_aturan", [
            ('"menyebut_ai"', "tidak boleh mengaku AI"),
            ('"klaim_tak_direncanakan"', "tidak boleh mengaku role tanpa rencana"),
            ('"target_hilang"', "target rencana harus disebut"),
        ]),
        (G + "nlg", "validasi_nlu", [
            ("anotasi_chat(nlu, chat", "kalimat dibaca seperti chat pemain"),
            ("cocok_intent = ", "intent harus sama dengan rencana"),
            ("cocok_target = not perlu_target", "target rencana harus terbaca"),
        ]),
    ],
    "nlg_templat": [
        (G + "nlg", "kalimat_templat", [
            ("dasar_hindari = ", "hindari kalimat yang sudah dipakai"),
            ("urutan_varian(p)", "varian sesuai rencana"),
            ("ubah_kata_ganti(teks, persona)", "gaya bahasa persona"),
        ]),
    ],
    "kirim": [
        (RT, "BrainRuntime.catat_chat", [("catat_aksi_bot", "ingatan: bot sudah bicara (jeda antar-chat)")]),
        ("app.module.npc_service", "catat_nlu", [
            ("runtime.baca_chat", "kalimat bot dibaca NLU"),
            ("tandai_dipanggil(", "bot yang dipanggil/dituduh melangkah segera"),
            ("record_nlu", "bacaan disimpan untuk riwayat chat"),
        ]),
    ],
    "simpan": [
        ("app.module.persistence_service", "PersistenceService.record_trace", [
            ("INSERT INTO checker_traces", "jejak untuk checker"),
        ]),
        ("app.module.persistence_service", "PersistenceService.record_nlu", [
            ("UPDATE chat_messages SET nlu", "bacaan NLU untuk riwayat chat"),
        ]),
        (G + "otak_fuzzy", "Ingatan.catat_aksi_bot", []),
    ],
    "output": [
        ("app.module.npc_service", "isi_jejak", [
            ("lengkapi_penjelasan(", "hasil engine dan NLG ditambahkan"),
            ("ringkas=ringkas_penjelasan", "ringkasan untuk item chat"),
        ]),
    ],
}  # fmt: skip


# Sumber satu fungsi/kelas (inspect) atau konstanta modul (ast): (baris, nomor baris awal, berkas, objek).
def _sumber(modul, nama):
    mod = obj = importlib.import_module(modul)
    for bagian in nama.split("."):
        obj = getattr(obj, bagian)
    if callable(obj) and hasattr(obj, "__wrapped__"):
        obj = inspect.unwrap(obj)  # mis. fungsi ber-lru_cache
    if inspect.isfunction(obj) or inspect.isclass(obj) or inspect.ismethod(obj):
        baris, mulai = inspect.getsourcelines(obj)
        return baris, mulai, Path(inspect.getsourcefile(obj)), obj
    berkas = Path(inspect.getsourcefile(mod))
    teks = berkas.read_text(encoding="utf-8").splitlines(keepends=True)
    for simpul in ast.parse("".join(teks)).body:
        target = simpul.targets if isinstance(simpul, ast.Assign) else []
        if any(isinstance(n, ast.Name) and n.id == nama for t in target for n in ast.walk(t)):
            return teks[simpul.lineno - 1 : simpul.end_lineno], simpul.lineno, berkas, None
    raise LookupError(f"{modul}.{nama} tidak ditemukan.")


def _parameter(obj):
    if not callable(obj) or inspect.isclass(obj):
        return []
    return [
        {"nama": p.name, "bawaan": None if p.default is p.empty else repr(p.default)}
        for p in inspect.signature(obj).parameters.values()
        if p.name != "self"
    ]


# Satu potongan kode bertanda. `hilang` = penanda inti yang tidak ditemukan (dijaga test).
def _potongan(modul, nama, inti):
    baris, mulai, berkas, obj = _sumber(modul, nama)
    hasil, hilang = [], []
    for i, teks in enumerate(baris):
        bersih = teks.strip()
        jenis = (
            "param" if i == 0 and obj is not None and not inspect.isclass(obj)
            else "output" if bersih.startswith(("return ", "yield ")) or bersih == "return"
            else "catatan" if bersih.startswith(("#", '"""'))
            else None
        )  # fmt: skip
        hasil.append({"no": mulai + i, "teks": teks.rstrip("\n").rstrip(), "jenis": jenis})
    for potong, catatan in inti:
        b = next((b for b in hasil if potong in b["teks"]), None)
        if b is None:
            hilang.append(potong)
            continue
        b["jenis"] = "inti"
        b["catatan"] = f"{b['catatan']}; {catatan}" if b.get("catatan") else catatan
    try:
        lokasi = berkas.resolve().relative_to(BACKEND_DIR.resolve()).as_posix()
    except ValueError:
        lokasi = berkas.name
    return {
        "nama": f"{modul.rsplit('.', 1)[-1]}.{nama}",
        "berkas": f"backend/{lokasi}",
        "mulai": mulai,
        "akhir": mulai + len(baris) - 1,
        "konstanta": obj is None,
        "parameter": _parameter(obj),
        "baris": hasil,
        "hilang": hilang,
    }


@lru_cache(maxsize=None)
def kode_node(node):
    if node not in KODE_ALUR:
        raise KeyError(node)
    return [_potongan(modul, nama, inti) for modul, nama, inti in KODE_ALUR[node]]
