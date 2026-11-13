"""MAIN CONTROLLER NLG: rencana chat dari fuzzy_controller menjadi kalimat yang dikirim bot.

Kode di sini dan di folder nlg/ adalah sumber logika penulis kalimat di game dan boleh diubah langsung. Notebook skripsi
npc_nlg.ipynb hanya untuk laporan. Patokan perilakunya adalah tests/test_skenario_nlg.py dan sidik di
tests/jejak/sidik.json.

File ini hanya merangkai tahap; isi tiap tahap ada di folder nlg/:
    nlg/prompt.py      [PROMPT]          menyusun perintah untuk LLM
    nlg/penulis.py     [PENULIS LLM]     OpenRouter, lalu tautan ai-docker
    nlg/aturan.py      [PERIKSA ATURAN]  menolak kalimat yang melanggar aturan
    nlg/templat.py     [TEMPLAT]         kalimat siap pakai bila LLM gagal atau ditolak
    nlg/pengaturan.py  [PANEL]           rantai penulis yang diatur panel (dipakai bot_controller)

Alurnya
1. tulis_pesan menerima payload rencana chat dari siapkan_nlg, konteks, penulis, dan persona
2. LLM, bila aktif, paling banyak MAKS_PERCOBAAN_LLM kali:
   2.1 [PROMPT] prompt.buat_prompt menyusun prompt, lalu [PENULIS LLM] penulis.tulis meminta kalimat
   2.2 [PERIKSA ATURAN] nilai_kalimat memeriksa aturan, templat.kalimat_mirip menolak parafrase kalimat yang baru
       terdengar, dan fakta_disalin meminta tulis ulang bila fakta panjang disalin hampir utuh
   2.3 Lolos: kalimat dipakai. Ditolak: alasannya ikut ke percobaan berikutnya. Salinan fakta tetap dipakai bila
       percobaan ulang gagal
3. [TEMPLAT] templat.kalimat_templat dicoba satu per satu, varian pertama yang lolos aturan dipakai. Varian yang belum
   terdengar dicoba lebih dulu, lalu yang paling lama tidak terdengar
4. Cadangan: tidak ada varian yang lolos, varian pertama tetap dipakai
5. tulis_chat_tim menulis paket siapkan_nlg_tim: LLM, lalu templat, tanpa IndoBERT; kalimatnya boleh kosong
"""

from time import perf_counter

from app.bot.nlg import aturan, prompt, templat
from app.bot.nlg.penulis import BATAS_WAKTU_DETIK

# Percobaan LLM paling banyak per kalimat; percobaan kedua membawa alasan penolakan yang pertama.
MAKS_PERCOBAAN_LLM = 2
# Fakta rencana sepanjang ini (kata, dalam bentuk_dasar) atau lebih tidak boleh disalin hampir utuh oleh LLM.
FAKTA_KATA_MIN = 14

# Menilai satu kalimat dengan pemeriksa aturan. Pengirim chat pemicu boleh disapa (mis. "Andi, kenapa nuduh aku?")
# tanpa dianggap menambah nama pemain lain.
def nilai_kalimat(teks, p, konteks):
    langgar = aturan.periksa_aturan(teks, p, konteks["roster"], prompt.pemicu(p, konteks)[1])
    return {"teks": teks, "lolos": not langgar, "pelanggaran": langgar}

# Fakta rencana yang disalin hampir utuh (kemiripan ≥ MIRIP_MAKS), atau None. Hanya fakta panjang dan gabungan fakta yang dihitung,
# karena fakta pendek dan klaim role memang wajar diucapkan apa adanya.
def fakta_disalin(teks, p, persona):
    if p.get("role_diakui"):
        return None
    fakta = prompt.data_jawab(p, persona) if p["aksi"] == "jawab" else p["bukti"]
    calon = [f for f in [*fakta, " ".join(fakta)] if len(templat.bentuk_dasar(f).split()) >= FAKTA_KATA_MIN]
    return next((f for f in calon if templat.kemiripan(teks, f) >= templat.MIRIP_MAKS), None)

# MAIN NLG: rencana chat → kalimat akhir. Selalu mengembalikan kalimat, apa pun yang gagal.
# Menerima p = payload siapkan_nlg, konteks (roster, chat_terbaru, suara_tribunal), penulis (None = templat saja),
# persona, dan hindari (kalimat yang baru terdengar). Dipanggil oleh BrainRuntime.tulis.
# Hasilnya {teks, sumber (llm / templat / templat_cadangan), penulis, lolos_aturan, pelanggaran, persona, percobaan,
#   detik}.
# Alur: 1 [LLM] paling banyak MAKS_PERCOBAAN_LLM kali: [PROMPT] → [PENULIS LLM] → [PERIKSA ATURAN] → mirip → salin
#       fakta -> 2 [TEMPLAT] varian pertama yang lolos aturan -> 3 [CADANGAN] varian pertama
def tulis_pesan(p, konteks, penulis=None, persona="santai", hindari=()):
    mulai, percobaan = perf_counter(), []

    def selesai(nilai, sumber, jalur=None):
        return {"teks": nilai["teks"], "sumber": sumber, "penulis": jalur, "lolos_aturan": not nilai["pelanggaran"],
                "pelanggaran": nilai["pelanggaran"], "persona": persona,
                "percobaan": percobaan, "detik": round(perf_counter() - mulai, 3)}

    # [1. LLM] bila aktif. Kalimat yang hanya menyalin fakta disimpan sebagai cadangan, karena templat juga memuat
    # fakta apa adanya.
    alasan_tolak, salinan = None, None
    for ke in range(1, MAKS_PERCOBAAN_LLM + 1):
        if penulis is None or not penulis.aktif:
            break
        # Percobaan ulang hanya bila percobaan sebelumnya cepat: di game kalimat harus tetap tepat waktu.
        if ke > 1 and perf_counter() - mulai > BATAS_WAKTU_DETIK:
            percobaan.append({"sumber": "llm", "ke": ke, "status": "waktu habis"})
            break
        sistem, pesan = prompt.buat_prompt(p, konteks, persona, alasan_tolak)  # [PROMPT]
        mentah, status = penulis.tulis(sistem, pesan)  # [PENULIS LLM]
        if mentah is None:
            percobaan.append({"sumber": "llm", "ke": ke, "status": status})
            continue
        jalur = getattr(penulis, "terakhir", None) or penulis.jalur  # rantai: jalur yang benar-benar menulis
        nilai = nilai_kalimat(aturan.bersihkan(mentah, p["pembicara"]), p, konteks)  # [PERIKSA ATURAN]
        # Parafrase tipis dari kalimat yang baru terdengar (milik bot sendiri atau pemain lain) ikut ditolak.
        mirip = templat.kalimat_mirip(nilai["teks"], hindari)
        salin = fakta_disalin(nilai["teks"], p, persona) if nilai["lolos"] and mirip is None else None
        percobaan.append({"sumber": "llm", "ke": ke, "penulis": jalur, "status": status, "teks": nilai["teks"],
                          "lolos": nilai["lolos"], "pelanggaran": nilai["pelanggaran"], "mirip": mirip, "salin_fakta": salin})
        if nilai["lolos"] and mirip is None and salin is None:
            return selesai(nilai, "llm", jalur)
        if salin:
            salinan = salinan or (nilai, jalur)
            alasan_tolak = "salin_fakta: fakta rencana disalin hampir utuh; tulis ulang dengan kata-katamu sendiri"
        elif nilai["pelanggaran"]:
            alasan_tolak = ", ".join(nilai["pelanggaran"])
        else:
            alasan_tolak = f'terlalu mirip dengan kalimat yang baru terdengar ("{mirip}"); pakai susunan lain'
    if salinan:
        return selesai(salinan[0], "llm", salinan[1])

    # [2. TEMPLAT] varian bergiliran sesuai persona; yang pertama lolos aturan dipakai.
    dinilai = []
    for teks in templat.kalimat_templat(p, persona, hindari):
        nilai = nilai_kalimat(teks, p, konteks)
        percobaan.append({"sumber": "templat", "teks": teks, "lolos": nilai["lolos"], "pelanggaran": nilai["pelanggaran"]})
        if nilai["lolos"]:
            return selesai(nilai, "templat")
        dinilai.append(nilai)

    # [3. CADANGAN] tidak ada varian yang lolos aturan, jadi varian pertama yang dikirim.
    return selesai(dinilai[0], "templat_cadangan")

# Paket chat tim → kalimat akhir. Tanpa IndoBERT, karena chat tim tidak pernah menjadi bukti; pemeriksa aturan tetap berjalan. Keluaran
# boleh kosong bila LLM menilai tidak perlu membalas. Hasilnya tidak memuat kalimat percobaan, supaya aman bila ikut tercatat.
# Menerima p = paket siapkan_nlg_tim, roster, penulis (None = templat), persona.
# Hasilnya {teks, sumber, penulis, lolos_aturan, pelanggaran, persona, percobaan, detik}; teks "" berarti tidak ada pesan.
# Dipanggil oleh BrainRuntime.tulis_tim → NPCService.
# Alur: 1 LLM paling banyak MAKS_PERCOBAAN_LLM kali -> 2 templat tim yang lolos aturan -> 3 tidak ada
#       yang lolos: kalimat kosong
def tulis_chat_tim(p, roster, penulis=None, persona="santai"):
    mulai, percobaan, rencana = perf_counter(), [], aturan.rencana_periksa_tim(p)
    boleh = {p["pilihan_rekan"], p["target_saya"], *(m["pengirim"] for m in p["chat_tim"])} - {None}

    def selesai(teks, sumber, jalur=None, langgar=()):
        return {"teks": teks, "sumber": sumber, "penulis": jalur, "lolos_aturan": not langgar, "pelanggaran": list(langgar),
                "persona": persona, "percobaan": percobaan, "detik": round(perf_counter() - mulai, 3)}

    # [1. LLM] bila aktif.
    alasan_tolak = None
    for ke in range(1, MAKS_PERCOBAAN_LLM + 1):
        if penulis is None or not penulis.aktif:
            break
        if ke > 1 and perf_counter() - mulai > BATAS_WAKTU_DETIK:
            percobaan.append({"sumber": "llm", "ke": ke, "status": "waktu habis"})
            break
        mentah, status = penulis.tulis(*prompt.buat_prompt_tim(p, persona, alasan_tolak))  # [PROMPT] → [PENULIS LLM]
        if mentah is None:
            percobaan.append({"sumber": "llm", "ke": ke, "status": status})
            continue
        jalur = getattr(penulis, "terakhir", None) or penulis.jalur
        teks = aturan.bersihkan(mentah, p["pembicara"])
        if teks in ("", "-"):
            percobaan.append({"sumber": "llm", "ke": ke, "status": "kosong"})
            return selesai("", "llm_kosong", jalur)
        langgar = aturan.periksa_aturan(teks, rencana, roster, boleh)
        mirip = templat.kalimat_mirip(teks, [m["teks"] for m in p["chat_tim"]])
        percobaan.append({"sumber": "llm", "ke": ke, "status": status, "pelanggaran": langgar, "mirip": bool(mirip)})
        if not langgar and mirip is None:
            return selesai(teks, "llm", jalur)
        alasan_tolak = ", ".join(langgar) if langgar else "terlalu mirip dengan chat tim terakhir; pakai susunan lain"

    # [2. TEMPLAT] templat tim. Bila tidak ada yang lolos, lebih baik tidak mengirim apa pun ke rekan.
    for teks in templat.kalimat_tim(p, persona):
        langgar = aturan.periksa_aturan(teks, rencana, roster, boleh)
        percobaan.append({"sumber": "templat", "pelanggaran": langgar})
        if not langgar:
            return selesai(teks, "templat")
    return selesai("", "kosong")
