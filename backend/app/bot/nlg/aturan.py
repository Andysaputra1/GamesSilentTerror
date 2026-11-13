"""[PERIKSA ATURAN] Penolak kalimat yang melanggar aturan game, untuk kalimat LLM maupun templat.

periksa_aturan menolak kalimat yang terlalu panjang, membocorkan role atau aksi rahasia, menyebut angka/skor,
menuduh atau membela orang yang tidak boleh, atau berisi perintah ke AI. bersihkan membuang sisa jejak berpikir dan
tanda kutip dari jawaban LLM sebelum diperiksa.
"""

import json
import re
from collections import Counter

PANJANG_MAKS = 220

KALIMAT_MAKS = 2

AKHIRAN_NAMA_NLG = ("nya", "lah", "kah", "pun", "mu", "ku")

POLA_AI = r"\b(?:bot|ai|a\.i|npc|chatbot|model bahasa|language model|asisten|assistant|prompt|instruksi|sistem)\b"

POLA_ANGKA = r"\d+[.,]\d+|\d+\s*%|\bpersen\b|\bskor\b|\bprobabilitas\b|\bconfidence\b"

POLA_KLAIM = (r"(?:(\w+)\s+)?\b(?:aku|saya|gw|gue|gua)\s+(?:(?:ini|itu|adalah|yang|tuh|sih|cuma|cuman|hanya|sebenarnya|memang|emang)\s+)*"
              r"(stalker|spy|hitman|civilian)\b")

POLA_KLAIM_AKHIR = r"\b(stalker|spy|hitman|civilian)\s+nih\s+(?:aku|saya|gw|gue|gua)\b"

POLA_ROLE_KU = r"\brole\s*-?\s*(?:ku|aku|saya|gw|gue)\s+(?:adalah\s+|itu\s+)?(stalker|spy|hitman|civilian)\b"

BUKAN_KLAIM = {"menyebut", "nyebut", "sebut", "bilang", "nuduh", "menuduh", "tuduh", "anggap", "menganggap", "kira",
               "mengira", "dikira", "kalau", "kalo", "jika", "seandainya", "misal", "curigai", "mencurigai", "vote"}

POLA_AKSI_SENDIRI = (r"\b(?:aku|saya|gw|gue|gua)\s+(?:(?:sudah|udah|tadi|malam|semalam|kemarin|yang|sempat|habis|abis)\s+){0,2}"
                     r"(peek|ngepeek|intip|ngintip|cek|guard|jaga(?!\s+jarak)|jagain|menjaga|sandera|menyandera|nyandera|gag|nge-?gag|bungkam|membungkam)\b")

POLA_INJEKSI = r"\babaikan\b|\bignore\b|instruksi sebelumnya|system prompt"

# Blok penalaran model (mis. <think>…</think> dari Qwen3) bukan bagian pesan.
def buang_pikiran(teks):
    return re.sub(r"<think>.*?(?:</think>|$)", "", teks or "", flags=re.S).strip()

# Merapikan keluaran LLM: blok penalaran, tanda kutip, markdown, awalan nama, dan spasi.
def bersihkan(teks, pembicara):
    teks = re.sub(r"[*`#]", "", buang_pikiran(teks))
    teks = re.sub(rf"^\s*{re.escape(pembicara)}\s*[:\-–]\s*", "", teks, flags=re.IGNORECASE)
    teks = teks.strip().strip("\"'“”‘’").strip()
    return re.sub(r"\s+", " ", teks)

# Role yang diakui pembicara untuk dirinya sendiri (kutipan tuduhan orang lain tidak dihitung).
def klaim_diri(kecil):
    klaim = {m.group(2) for m in re.finditer(POLA_KLAIM, kecil) if (m.group(1) or "") not in BUKAN_KLAIM}
    klaim |= {m.group(1) for pola in (POLA_ROLE_KU, POLA_KLAIM_AKHIR) for m in re.finditer(pola, kecil)}
    # Bot lain membaca "hasil peek" sebagai pengakuan Stalker, siapa pun yang mengucapkannya.
    return klaim | ({"stalker"} if re.search(r"\bhasil\s+peek", kecil) else set())

# Nama roster yang disebut di teks (boleh berakhiran -nya, -lah, ...). Nama tampilan bisa lebih dari satu kata:
# nama lengkap dihitung, begitu juga kata pertamanya ("Andy" untuk "Andy Saputra") bila tidak dipakai pemain lain.
def nama_disebut(teks, roster):
    akhiran = "|".join(AKHIRAN_NAMA_NLG)
    depan = Counter(nama.split()[0].casefold() for nama in roster if nama.split())

    def ada(kata):
        frasa = r"\s+".join(map(re.escape, kata))
        return re.search(rf"(?<!\w){frasa}(?:{akhiran})?(?!\w)", teks, flags=re.IGNORECASE)

    disebut = set()
    for nama in roster:
        kata = nama.split()
        panggilan = len(kata) > 1 and len(kata[0]) >= 3 and depan[kata[0].casefold()] == 1
        if kata and (ada(kata) or (panggilan and ada(kata[:1]))):
            disebut.add(nama)
    return disebut

AKSI_TIM = {"hitman": {"sandera", "menyandera", "nyandera", "gag", "nge-gag", "ngegag", "bungkam", "membungkam"},
            "spy": {"guard", "jaga", "jagain", "menjaga"}}

AKSI_KLAIM = {"stalker": {"peek", "ngepeek", "intip", "ngintip", "cek"}, "spy": {"guard", "jaga", "jagain", "menjaga"}}

KATA_DILARANG = {"serang_korban_gag": r"\b(?:gag|nge-?gag|di-?gag|bungkam|dibungkam|mute|di-?mute)\b",
                 "chat_tim/spy": r"\b(?:incar|incer|ngincar|ngincer|mengincar|targetkan|menargetkan|serang|nyerang|menyerang|habisi|habisin)\b"}

# Nama yang boleh disebut selain target: pembicara, pengirim pemicu, dan semua nama yang memang ada di data rencana.
def nama_boleh(p, roster, boleh_sebut=()):
    data = [*p["bukti"], p.get("bukti_klaim") or "", json.dumps(p.get("paket") or "", ensure_ascii=False)]
    return ({p["target"], p["pembicara"], p.get("penanya"), *boleh_sebut, *(r["pemain"] for r in p.get("relasi_tambahan") or [])}
            | nama_disebut(" ".join(data), roster))

# Peran nama di paket jawab: (dicurigai, dipercaya). Dicurigai = tersangka, pendapat curiga, dan target vote atau tuduh sebelumnya;
# dipercaya = pendapat percaya dan target bela sebelumnya. Nama lain di paket, misalnya saksi di alasan, hanya boleh disebut.
def peran_paket(p):
    paket = p.get("paket") or {}
    pendapat, tindakan = paket.get("pendapat_pemain") or {}, paket.get("tindakan_sebelumnya") or []
    dicurigai = {(paket.get("tersangka") or {}).get("nama"), *(n for n, d in pendapat.items() if d["sikap"] == "curiga"),
                 *(t["target"] for t in tindakan if t["tindakan"] in ("vote", "tuduh"))}
    dipercaya = {*(n for n, d in pendapat.items() if d["sikap"] == "percaya"), *(t["target"] for t in tindakan if t["tindakan"] == "bela")}
    return dicurigai - {None}, dipercaya

# Nama yang memang boleh dituduh rencana ini: target, relasi tambahan offend, dan nama yang dicurigai di paket jawab.
def nama_boleh_dituduh(p):
    return {p["target"], *(r["pemain"] for r in p.get("relasi_tambahan") or [] if r["relasi"] == "offend"), *peran_paket(p)[0]}

# Apakah kalimat menuduh atau mengajak vote nama ini. Nama yang boleh disebut tetap tidak boleh menjadi tersangka baru.
def menuduh_nama(kecil, nama):
    for bentuk in {nama, nama.split()[0]}:
        n = re.escape(bentuk.casefold())
        if re.search(rf"(?:curiga|mencurigai|nyurigain)\s+(?:(?:sama|ke|dengan|pada|kepada|si)\s+)?{n}(?!\w)"
                     rf"|\b(?:ayo|mending|aku|saya|gw|gue|gua|kita)\s+(?:vote|pilih)\s+{n}(?!\w)"
                     rf"|\bvote\s+{n}\s+(?:aja|saja|sekarang)\b"
                     rf"|(?<!kalau )(?<!kalo )(?<!bilang )(?<!nuduh )(?<!\w){n}\s+(?:(?:itu|yang|juga|sih|tuh|kok|lebih|paling|justru)\s+)*"
                     r"(?:mencurigakan|aneh|hitman)\b", kecil):
            return True
    return False

# Apakah kalimat membela nama ini: "X bukan Hitman", "X bersih", atau "jangan vote X". Pengandaian dan kutipan langsung tidak dihitung.
def membela_nama(kecil, nama):
    for bentuk in {nama, nama.split()[0]}:
        n = re.escape(bentuk.casefold())
        if re.search(rf"(?<!kalau )(?<!kalo )(?<!bilang )(?<!kata )(?<!\w){n}\s+(?:(?:itu|juga|sih|tuh|kok|memang|emang|pasti|jelas)\s+)*"
                     r"(?:bukan\s+hitman|bersih|orang\s+baik)\b"
                     rf"|\b(?:jangan|gak\s+usah|nggak\s+usah|ga\s+usah|tidak\s+usah)\s+(?:(?:buru-buru|asal|dulu)\s+)*"
                     rf"(?:vote|pilih|eksekusi|tuduh|nuduh|curigai)\s+{n}(?!\w)", kecil):
            return True
    return False

# Nama yang boleh dibela jawaban: pembicara, nama yang dipercaya di paket, dan nama yang memang dibela kalimat data (misalnya
# "jadi Dodi bukan Hitman" di alasan tersangka). calon = nama yang disebut kalimat.
def nama_boleh_dibela(p, calon):
    paket = p.get("paket") or {}
    data = " ".join([*p["bukti"], *((paket.get("tersangka") or {}).get("alasan") or []),
                     *(d["alasan"] for d in (paket.get("pendapat_pemain") or {}).values()),
                     *(a for t in paket.get("tindakan_sebelumnya") or [] for a in t["alasan"])]).casefold()
    return {p["pembicara"], p["target"] if p["intent"] == "defend" else None, *peran_paket(p)[1],
            *(n for n in calon if membela_nama(data, n))}

# Daftar pelanggaran aturan; kosong berarti lolos. Aturan sama untuk semua role, karena yang dinilai role yang diakui rencana.
# boleh_sebut = nama dari chat pemicu (penuduh, pemilih, penanya) yang boleh disapa walau bukan target.
def periksa_aturan(teks, p, roster, boleh_sebut=()):
    kecil, langgar = teks.casefold(), []
    if not teks:
        return ["kosong"]
    kalimat = [k for k in re.split(r"(?<=[.!?])\s+", teks) if k]
    if len(teks) > PANJANG_MAKS or len(kalimat) > KALIMAT_MAKS:
        langgar.append("terlalu_panjang")
    if re.search(POLA_AI, kecil):
        langgar.append("menyebut_ai")
    if re.search(POLA_ANGKA, kecil):
        langgar.append("angka_internal")
    klaim = klaim_diri(kecil)
    aksi = {m.group(1) for m in re.finditer(POLA_AKSI_SENDIRI, kecil)}
    tim = p.get("aksi") == "chat_tim"
    # Chat tim hanya sampai ke rekan, jadi role dan aksi tim sendiri boleh disebut. Chat publik tidak pernah memuat tim.
    if tim:
        if klaim - {p["tim"]}:
            langgar.append("klaim_salah")
        if aksi - AKSI_TIM[p["tim"]]:
            langgar.append("aksi_sendiri")
        if re.search(KATA_DILARANG.get(f"chat_tim/{p['tim']}", r"(?!)"), kecil):
            langgar.append("kata_dilarang")
    else:
        role = p.get("role_diakui")
        if klaim and not role:
            langgar.append("klaim_tak_direncanakan")
        elif klaim - {role}:
            langgar.append("klaim_salah")
        if aksi - (AKSI_KLAIM.get(role, set()) if p.get("bukti_klaim") else set()):
            langgar.append("aksi_sendiri")
        if re.search(KATA_DILARANG.get(p.get("jenis"), r"(?!)"), kecil):
            langgar.append("kata_dilarang")
    disebut = nama_disebut(teks, roster)
    # Jawaban hanya menjawab yang ditanyakan, jadi tersangka di paket tidak wajib disebut.
    if p["target"] and p["target"] != p["pembicara"] and p["target"] not in disebut and p["aksi"] != "jawab":
        langgar.append("target_hilang")
    if p["intent"] != "neutral" and disebut - nama_boleh(p, roster, boleh_sebut):
        langgar.append("nama_lain")
    if not tim and any(menuduh_nama(kecil, n) for n in disebut - nama_boleh_dituduh(p) - {p["pembicara"]}):
        langgar.append("tuduh_lain")
    # Jawaban tidak boleh tiba-tiba membela pemain yang dicurigai atau divote bot, maupun pemain yang tidak dipercaya di paket.
    if p["aksi"] == "jawab" and any(membela_nama(kecil, n) for n in disebut - nama_boleh_dibela(p, disebut)):
        langgar.append("bela_lain")
    if re.search(POLA_INJEKSI, kecil):
        langgar.append("injeksi")
    return langgar

# Paket chat tim dalam bentuk yang dibaca periksa_aturan: nama wajib, dan nama yang boleh disebut selain itu.
def rencana_periksa_tim(p):
    sebut = p["pilihan_rekan"] if p["pemicu"] == "setuju" else p["target_saya"]
    return {**p, "intent": "tim", "target": sebut, "bukti": [*p["alasan"], *(m["teks"] for m in p["chat_tim"])]}
