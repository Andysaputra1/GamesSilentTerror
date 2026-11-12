"""BAHAN otak bot: Ingatan satu bot, lalu chat, vote, dan fakta dibaca menjadi angka bukti 0–1 per pemain.

Tidak ada fuzzy di sini. fuzzy_controller.putuskan membaca keluaran file ini (tabel bukti, konteks, pengetahuan pasti,
fitur Spy dan Hitman) lalu memanggil fungsi fuzzy di bot/fuzzy/. File ini tidak mengimpor file bot lain.

Isi berurutan
1. Waktu fase dan komposisi role
2. Ingatan: catatan pengamatan satu bot; sinkron_snapshot mencatat snapshot privat bot dan memberi view
3. Membaca chat, vote, klaim role, dan status lawan: pola teks, relasi chat, dugaan Hostage/Gag, klaim role, memihak
   Hitman, pengaruh
4. Bukti per pemain, konteks permainan, dan fakta pasti: hitung_bukti (dengan _konteks_permainan) dan
   pengetahuan_peran
5. Bahan per role sesudah kecurigaan dinilai: fitur_lindung (Spy, bahan Guard) dan fitur_hitman (bahan ancaman dan
   kambing hitam)
"""

import math
import re
from collections import Counter, defaultdict
from dataclasses import dataclass, field

import numpy as np
import pandas as pd

# ===== 1. WAKTU FASE DAN KOMPOSISI ROLE =====

# Urutan fase dalam satu ronde, untuk mengurutkan chat dan tindakan.
URUTAN_FASE = {"day": 0, "tribunal": 1, "night": 2}

# Waktu tambahan Tribunal saat suara seri (detik), sama dengan engine.
TAMBAHAN_TRIBUNAL = 30

TAMBAHAN_TRIBUNAL_CEPAT = 10

# Sisa malam (detik) saat pilihan bot dikunci, untuk mode standar dan cepat.
KUNCI_BOT_DETIK = {"standar": 15, "cepat": 10}

# Fase sesudah (ronde, fase) menurut engine: siang ronde 1 langsung malam; malam → siang ronde berikutnya.
def fase_berikut(ronde, fase):
    if fase == "day":
        return ronde, "night" if ronde == 1 else "tribunal"
    if fase == "tribunal":
        return ronde, "night"
    return ronde + 1, "day"

# Durasi fase sama persis dengan match_engine.phase_durations di backend.
def durasi_fase(jumlah_peserta, cepat=False):
    if cepat:
        return {"day": math.ceil(jumlah_peserta * 10 / 3), "night": math.ceil(jumlah_peserta * 2.5),
                "tribunal": math.ceil(jumlah_peserta * 2.5)}
    return {"day": jumlah_peserta * 20, "night": jumlah_peserta * 5, "tribunal": math.ceil(jumlah_peserta * 7.5) + 30}

# Waktu mulai dan selesai sebuah fase menurut catatan bot; None jika fase belum pernah terlihat.
def jendela_fase(ingatan, view, ronde, fase):
    mulai = ingatan.mulai_fase.get((ronde, fase))
    if mulai is None:
        return None, None
    berikut = fase_berikut(ronde, fase)
    return mulai, ingatan.mulai_fase.get(berikut, mulai + view["durasi"][fase])

# Bot terkunci saat sisa malam ≤ KUNCI_BOT_DETIK.
def bot_terkunci(cepat, deadline, waktu):
    return deadline - waktu <= KUNCI_BOT_DETIK["cepat" if cepat else "standar"]

# Porsi fase sekarang yang sudah berjalan (0–1).
def waktu_berjalan(ingatan, view):
    mulai, _ = jendela_fase(ingatan, view, view["ronde"], view["fase"])
    if mulai is None or view["fase"] not in view["durasi"]:
        return 0.0
    return float(np.clip((view["waktu"] - mulai) / view["durasi"][view["fase"]], 0, 1))

# Komposisi role pertandingan; view tanpa komposisi dianggap satu Hitman, satu Spy, dan satu Stalker.
def komposisi(view):
    return view.get("komposisi") or {"hitman": 1, "spy": 1, "stalker": 1, "civilian": max(1, len(view["pemain"]) - 3)}

# ===== 2. INGATAN: catatan pengamatan satu bot =====

# Role yang dikenal otak bot.
PERAN = ("civilian", "spy", "stalker", "hitman")

@dataclass
class Ingatan:
    """Memori pengamatan milik satu bot, untuk role apa pun.

    Dibuat sekali per bot per pertandingan: Ingatan(nama_bot, cepat=...). Diisi sinkron_snapshot setiap langkah, serta
    catat_aksi_bot/catat_vote_bot setelah game menerima tindakan bot; dibaca semua tahap putuskan.
    """

    nama_bot: str
    cepat: bool = False
    jumlah_awal: int | None = None
    peran: str | None = None
    chat: list = field(default_factory=list)
    vote: list = field(default_factory=list)
    eksekusi: list = field(default_factory=list)
    keluar: list = field(default_factory=list)
    mulai_fase: dict = field(default_factory=dict)
    aksi_bot: list = field(default_factory=list)
    vote_bot: list = field(default_factory=list)
    gag_bot: set = field(default_factory=set)
    intel: list = field(default_factory=list)
    # Status internal pencatatan: chat yang sudah dicatat, vote terkunci, Tribunal berjalan, roster dan Hitman terakhir.
    _id_chat: set = field(default_factory=set)
    _vote_terkunci: set = field(default_factory=set)
    _tribunal_berjalan: int | None = None
    _suara_berjalan: dict = field(default_factory=dict)
    _hidup_terakhir: set | None = None
    _hitman_tersisa: int | None = None
    # Chat tim: hitungan dan id terakhir saja, supaya isinya tidak pernah tersimpan di ingatan.
    _chat_tim: dict = field(default_factory=lambda: {"jumlah": 0, "id_terakhir": None})
    # Ronde yang saat terkuncinya sudah lewat, dan pemicu chat tim bot yang sudah dikerjakan, tanpa isi kalimat.
    _ronde_terkunci: set = field(default_factory=set)
    chat_tim_bot: list = field(default_factory=list)

    # Chat dengan id sama hanya dicatat sekali (polling atau reconnect bisa mengirim ulang).
    def catat_chat(self, chat):
        if chat["id"] in self._id_chat:
            return False
        self._id_chat.add(chat["id"])
        self.chat.append(chat)
        return True

    # Vote final: satu pemilih satu suara per ronde, sama seperti engine.
    def catat_vote(self, ronde, pemilih, target):
        if (ronde, pemilih) not in self._vote_terkunci:
            self._vote_terkunci.add((ronde, pemilih))
            self.vote.append({"ronde": ronde, "pemilih": pemilih, "target": target})

    # hitman: True/False bila role korban bisa disimpulkan dari pengumuman jumlah Hitman, None bila tidak.
    def catat_eksekusi(self, ronde, pemain, hitman=None):
        self.eksekusi.append({"ronde": ronde, "pemain": pemain, "hitman": hitman})

    # Pemain yang keluar di tengah pertandingan (tanda left): tersingkir seperti korban eksekusi, tetapi bukan hasil
    # suara Tribunal, jadi tidak pernah menjadi bukti "mendorong eksekusi warga". hitman sama artinya dengan eksekusi.
    def catat_keluar(self, ronde, pemain, hitman=None):
        self.keluar.append({"ronde": ronde, "pemain": pemain, "hitman": hitman})

    # Dipanggil game setelah chat bot benar-benar terkirim.
    def catat_aksi_bot(self, view, rencana):
        self.aksi_bot.append({
            "ronde": view["ronde"], "fase": view["fase"], "waktu": view["waktu"],
            "aksi": rencana["aksi"], "intent": rencana["intent"], "target": rencana["target"],
            "alasan": list(rencana["alasan"]), "jenis": rencana.get("jenis"), "pemicu": rencana.get("pemicu"),
            "role_diakui": rencana.get("role_diakui"),
        })

    # Dipanggil game setelah vote bot diterima engine. Satu catatan per ronde: suara yang pindah mengganti catatan lama.
    def catat_vote_bot(self, view, rencana):
        catatan = {"ronde": view["ronde"], "target": rencana["target"], "alasan": list(rencana["alasan"]),
                   "dinilai_ulang": bool(rencana.get("pindah")), **({"paksa": True} if rencana.get("paksa") else {})}
        lama = next((v for v in self.vote_bot if v["ronde"] == view["ronde"]), None)
        if lama is None:
            self.vote_bot.append(catatan)
        else:
            lama.pop("paksa", None)
            lama.update(catatan, dinilai_ulang=True)

    # Dipanggil game sesudah rencana chat tim dikerjakan, juga bila kalimatnya kosong. Isi kalimat tidak pernah disimpan.
    def catat_chat_tim(self, view, rencana, terkirim):
        self.chat_tim_bot.append({"ronde": view["ronde"], "pemicu": rencana["pemicu"], "target_saya": rencana["target_saya"],
                                  "pilihan_rekan": rencana["pilihan_rekan"], "terkirim": terkirim})

    # Ingatan: mengubah snapshot backend menjadi view keputusan sambil mencatat pengamatan baru.
    # Menerima snapshot = Match.snapshot(nama_bot) {round, phase, deadline, players, messages, tribunal_votes, me};
    #   waktu_terima = detik saat snapshot diterima. Chat baru dicatat tanpa intent dan target; bacaannya diisi
    #   nlu.baca_chat_baru sesudah fungsi ini, berurutan sesuai catatan.
    # Hasilnya view = {ronde, fase, waktu, deadline, durasi, pemain, suara_tribunal, komposisi, hitman_tersisa,
    #   tribunal_tambahan, saya};
    #   pemain = [{nama, hidup, sandera}], sandera = ronde malam korban Hostage (diumumkan server) atau None.
    # Dipanggil oleh game sebelum putuskan(ingatan, view); ingatan yang diperbarui dibaca semua tahap berikutnya.
    # Alur: 1 periksa pemilik dan role -> 2 kunci vote Tribunal yang sudah lewat -> 3 catat eksekusi dan pemain
    #       keluar -> 4 awal fase, Gag, hasil Peek, aksi rekan, chat tim -> 5 chat baru masuk ingatan -> 6 saat
    #       terkunci malam -> 7 susun view
    def sinkron_snapshot(self, snapshot, waktu_terima):
        me = snapshot["me"]
        if me["name"] != self.nama_bot:
            raise ValueError("Snapshot bukan milik bot ini.")
        if me["role"] not in PERAN:
            raise ValueError(f"Role tidak dikenal: {me['role']}")
        self.peran = me["role"]
        ronde, fase = snapshot["round"], snapshot["phase"]
        pemain = [{"nama": p["name"], "hidup": bool(p["alive"]),
                   "sandera": p.get("hostage_round", ronde) if p.get("hostage") else None} for p in snapshot["players"]]
        if self.jumlah_awal is None:
            self.jumlah_awal = len(pemain)
        durasi = durasi_fase(self.jumlah_awal, self.cepat)
        tribunal_tambahan = bool(snapshot.get("tribunal_extra"))

        # Server mengosongkan vote setelah Tribunal; vote terakhir yang terlihat dikunci saat fase berganti.
        if self._tribunal_berjalan is not None and (ronde, fase) != (self._tribunal_berjalan, "tribunal"):
            for pemilih, target in self._suara_berjalan.items():
                self.catat_vote(self._tribunal_berjalan, pemilih, target)
            self._tribunal_berjalan, self._suara_berjalan = None, {}
        suara = {}
        if fase == "tribunal":
            suara = {pemilih: baris["target"] for baris in snapshot["tribunal_votes"] for pemilih in baris["voters"]}
            self._tribunal_berjalan, self._suara_berjalan = ronde, dict(suara)

        # Pemain hanya bisa mati karena eksekusi Tribunal atau keluar dari permainan (tanda left di roster), jadi
        # perubahan roster menandai eksekusi; pemain yang keluar dicatat terpisah, bukan sebagai korban Tribunal.
        hidup = {p["nama"] for p in pemain if p["hidup"]}
        keluar = {p["name"] for p in snapshot["players"] if p.get("left")}
        if self._hidup_terakhir is None:  # bot baru bergabung: ronde eksekusi sebelumnya tidak diketahui
            mati, ronde_tribunal, ronde_keluar = sorted(p["nama"] for p in pemain if not p["hidup"]), None, None
        else:
            mati, ronde_tribunal = sorted(self._hidup_terakhir - hidup), (ronde - 1 if fase == "day" else ronde)
            ronde_keluar = ronde
        # Room ≥ 2 Hitman: engine mengumumkan Hitman yang masih hidup (juga setelah pemain keluar). Jumlah tetap →
        # korban warga; turun sebanyak korban → korban Hitman; selain itu (beberapa pemain tersingkir sekaligus) role
        # korban tidak disimpulkan.
        tersisa = snapshot.get("hitman_remaining")
        sebelum = self._hitman_tersisa
        if sebelum is None:  # belum ada pengumuman: mulai dari komposisi awal
            sebelum = (snapshot.get("composition") or {}).get("hitman")
        hitman = None
        if tersisa is not None and sebelum is not None and mati:
            hitman = {0: False, len(mati): True}.get(sebelum - tersisa)
        for nama in mati:
            if nama in keluar:
                self.catat_keluar(ronde_keluar, nama, hitman)
            else:
                self.catat_eksekusi(ronde_tribunal, nama, hitman)
        self._hidup_terakhir, self._hitman_tersisa = hidup, tersisa

        if fase in URUTAN_FASE and (ronde, fase) not in self.mulai_fase:
            # Saat waktu tambahan seri, deadline sudah mundur sebanyak tambahan itu.
            tambahan = 0
            if tribunal_tambahan:
                tambahan = TAMBAHAN_TRIBUNAL_CEPAT if self.cepat else TAMBAHAN_TRIBUNAL
            self.mulai_fase[(ronde, fase)] = min(waktu_terima, snapshot["deadline"] - durasi[fase] - tambahan)
        if me["gagged"]:
            self.gag_bot.add(ronde)

        # Hasil Peek dan pilihan Hostage rekan hanya ada di snapshot privat bot.
        self.intel = [{"ronde": x["round"], "pemain": x["name"], "peran": x["role"]} for x in me.get("intel", [])]
        aksi_rekan = [{"pemain": a["name"], "target": a["target"]} for a in me.get("ally_actions", [])]

        # Chat tim hanya masuk view: di ingatan.chat ia akan terbaca sebagai bukti publik.
        chat_tim = [{"id": m["id"], "pengirim": m["sender"], "teks": m["message"]} for m in me.get("team_messages", [])]
        if chat_tim:
            self._chat_tim = {"jumlah": len(chat_tim), "id_terakhir": chat_tim[-1]["id"]}

        # Waktu chat dari server. Fase chat tetap dari snapshot: chat yang baru terlihat saat malam/selesai dikirim di
        # akhir fase publik sebelumnya, yaitu siang di ronde 1 dan Tribunal di ronde berikutnya.
        fase_chat = fase if fase in ("day", "tribunal") else ("day" if ronde == 1 else "tribunal")
        for pesan in snapshot["messages"]:
            if pesan["id"] in self._id_chat:
                continue
            chat = {"id": pesan["id"], "ronde": ronde, "fase": fase_chat, "waktu": pesan.get("time", waktu_terima),
                    "pengirim": pesan["sender"], "teks": pesan["message"]}
            self.catat_chat(chat)

        # Langkah pertama sesudah batas kunci adalah saat terkunci, satu-satunya kesempatan bot mengikuti rekan manusia.
        terkunci = fase == "night" and bot_terkunci(self.cepat, snapshot["deadline"], waktu_terima)
        saat_terkunci = terkunci and ronde not in self._ronde_terkunci
        if terkunci:
            self._ronde_terkunci.add(ronde)

        return {
            "ronde": ronde, "fase": fase, "waktu": waktu_terima, "deadline": snapshot["deadline"],
            "durasi": durasi, "pemain": pemain, "suara_tribunal": suara, "komposisi": snapshot.get("composition"),
            "hitman_tersisa": tersisa, "tribunal_tambahan": tribunal_tambahan,
            "saya": {"nama": me["name"], "role": me["role"], "can_chat": me["can_chat"], "can_vote": me["can_vote"],
                     "can_cancel_vote": bool(me.get("can_cancel_vote")), "ability": me.get("ability"),
                     "can_act": bool(me.get("can_act")), "can_cancel_action": bool(me.get("can_cancel_action")),
                     "last_guard": me.get("last_guard"), "rekan": list(me.get("allies", [])), "aksi_rekan": aksi_rekan,
                     "rekan_spy": list(me.get("spy_allies", [])),
                     "aksi_rekan_spy": [{"pemain": a["name"], "target": a["target"]} for a in me.get("spy_actions", [])],
                     "korban_gag_tim": list(me.get("ally_gags", [])), "rekan_manusia": list(me.get("team_humans", [])),
                     "chat_tim": chat_tim, "can_team_chat": bool(me.get("can_team_chat")),
                     # Pilihan malam bot sekarang (hanya terisi saat malam), untuk pindah target.
                     "aksi_malam": (me.get("action") or {}).get("target"), "terkunci": terkunci, "saat_terkunci": saat_terkunci,
                     # Hasil Hostage tim tiap malam dari server (hanya Hitman): berhasil, atau gagal karena Guard.
                     "hasil_sandera": [{"ronde": h["round"], "pemain": h["name"], "berhasil": h["success"]}
                                       for h in me.get("syndicate_hostages", [])]},
        }

# ===== 3. MEMBACA CHAT, VOTE, KLAIM ROLE, DAN STATUS LAWAN =====

# Keyakinan intent minimal agar chat terbaca jelas; offend/defend di bawahnya tidak menjadi bukti.
MIN_CONF_INTENT = 0.60

# Peluruhan bukti per ronde: biasa, dan keras untuk jejak yang lebih pasti (klaim, korban, eksekusi).
PELURUHAN = 0.70

PELURUHAN_KERAS = 0.90

POLA_GAG = r"\b(?:di-?gag|kena\s+gag|dibungkam|di-?mute|kena\s+mute)\b"

POLA_PEEK = r"\b(?:peek|ngepeek|intip|ngintip|cek\s+role)\b"

_SAYA = r"\b(?:aku|saya|gw|gue|gua)\s+"

_KATA_SAYA = r"(?:aku|saya|gw|gue|gua)\b"

_PENGHUBUNG = r"(?:(?:ini|itu|adalah|yang|tuh|sih|cuma|cuman|hanya)\s+)*"

_WAKTU = r"(?:sudah\s+|udah\s+|tadi\s+|semalam\s+)?"

POLA_KLAIM = {
    "stalker": (rf"{_SAYA}{_PENGHUBUNG}stalker\b|\bstalker\s+nih\s+{_KATA_SAYA}"
                rf"|{_SAYA}{_WAKTU}(?:peek|ngepeek|intip|ngintip)\b"
                r"|\bhasil\s+peek"),
    "spy": (rf"{_SAYA}{_PENGHUBUNG}spy\b|\bspy\s+nih\s+{_KATA_SAYA}"
            rf"|{_SAYA}{_WAKTU}(?:guard\b|jaga(?:in)?\s+(?!jarak\b)\w)"),
    "civilian": rf"{_SAYA}{_PENGHUBUNG}civilian\b|\bcivilian\s+nih\s+{_KATA_SAYA}",
}

POLA_TANYA = r"\?|^\s*(?:siapa|kenapa|gimana|bagaimana|menurut|apa|kok)\b"

# Faktor peluruhan: bukti dari ronde lama bernilai lebih kecil.
def _luruh(ronde, R, faktor):
    return faktor ** max(0, R - ronde)

# Chat ingatan dalam urutan kronologis: ronde, fase, waktu, lalu id (id dari engine diawali nomor urut).
def _chat_urut(ingatan):
    return sorted(ingatan.chat, key=lambda c: (c["ronde"], URUTAN_FASE[c["fase"]], c["waktu"], c["id"]))

# Vote yang sudah terkunci ditambah suara Tribunal yang sedang berjalan.
def _semua_vote(ingatan, view):
    return list(ingatan.vote) + [{"ronde": view["ronde"], "pemilih": v, "target": t}
                                 for v, t in view["suara_tribunal"].items()]

# Chat bot sendiri pada fase yang sedang berjalan (untuk jatah, jeda, dan bela diri).
def _aksi_fase(ingatan, view):
    return [a for a in ingatan.aksi_bot if (a["ronde"], a["fase"]) == (view["ronde"], view["fase"])]

# Pasangan (pemain, relasi) dari chat yang cukup jelas untuk dijadikan bukti.
def relasi_chat(chat, roster):
    if chat.get("intent") not in {"offend", "defend"} or (chat.get("conf_intent") or 0.0) < MIN_CONF_INTENT:
        return []
    return [(t["pemain"], t["relasi"]) for t in chat.get("target", [])
            if t["pemain"] in roster and t["relasi"] in {"offend", "defend"}]

# Hitman yang sudah terbukti: korban eksekusi atau pemain keluar yang diumumkan Hitman. Sudut pandang pribadi warga juga
# memakai hasil Peek. Sudut pandang publik Hitman tidak memakai rekan, supaya rekannya tidak terbaca dari tabel publik.
def _terbukti_hitman(ingatan, publik=False):
    terbukti = {e["pemain"] for e in ingatan.eksekusi + ingatan.keluar if e.get("hitman") is True}
    if not publik:
        terbukti |= {x["pemain"] for x in ingatan.intel if x["peran"] == "hitman"}
    return terbukti

# Dugaan korban Gag: peluang dasar, jeda diam minimal (porsi siang), dan pesan pemain lain sesudahnya.
P_GAG_DASAR = 0.70

GAG_JEDA_FRAKSI = 0.30

GAG_MIN_PESAN_LAIN = 2

# Status lawan yang memengaruhi bukti: korban Hostage dari pengumuman server (pasti), korban Gag diduga dari jejak publik.
# Menerima ingatan, view (pemain[].sandera), pengamat = nama bot (sudut pandang pribadi) atau None (sudut pandang publik).
# Hasilnya (p_sandera {pemain: 0 atau 1}, p_gag {pemain: 0–1}, korban [{korban, jenis, ronde, p, batas_waktu}]).
# Dipanggil oleh hitung_bukti (kolom p_sandera, p_gag, dan penuduh_dibungkam).
# Alur: 1 Hostage: 1 untuk korban yang diumumkan -> 2 tiap siang yang sudah selesai: Gag milik bot sendiri pasti,
#       selain itu calon korban = pemain aktif yang berhenti bicara, tetap vote, dan diam saat Tribunal -> 3 satu Gag
#       per ronde: calon terkuat tetap, sisanya diturunkan
def dugaan_status(ingatan, view, pengamat):
    R, fase = view["ronde"], view["fase"]
    hidup = [p["nama"] for p in view["pemain"] if p["hidup"]]

    # Hostage: diumumkan server saat malam selesai, jadi pasti 1 untuk korban dan 0 untuk pemain lain (juga yang diam).
    sandera = {p["nama"]: p["sandera"] for p in view["pemain"] if p["hidup"] and p.get("sandera")}
    p_sandera = {q: 1.0 if q in sandera else 0.0 for q in hidup}
    korban = [{"korban": q, "jenis": "sandera", "ronde": sandera[q], "p": 1.0, "batas_waktu": None}
              for q in sorted(sandera) if q != pengamat]

    # Gag: aktif di siang, berhenti di tengah siang, diam saat Tribunal, tetapi tetap vote.
    p_gag = {q: 0.0 for q in hidup}
    gag_kuat = {}
    for r in range(1, R + 1):
        if r == R and fase == "day":
            break  # siang ini belum selesai
        mulai, selesai = jendela_fase(ingatan, view, r, "day")
        if mulai is None:
            continue
        if pengamat is not None and r in ingatan.gag_bot:
            # Bot tahu pasti dirinya di-Gag; satu Gag per ronde berarti pemain lain tidak di-Gag.
            korban.append({"korban": pengamat, "jenis": "gag", "ronde": r, "p": 1.0, "batas_waktu": selesai})
            gag_kuat[r] = 1.0
            continue
        if pengamat is not None and (r - 1) in ingatan.gag_bot:
            continue  # cooldown Gag: tidak mungkin dua ronde berturut-turut
        faktor = 0.5 if gag_kuat.get(r - 1, 0.0) >= 0.6 else 1.0  # ronde lalu kemungkinan Gag: cooldown
        pemilih = {v["pemilih"] for v in ingatan.vote if v["ronde"] == r}
        if r == R:
            pemilih |= set(view["suara_tribunal"])
        chat_hari = [c for c in ingatan.chat if c["ronde"] == r and c["fase"] == "day"]
        bicara_tribunal = {c["pengirim"] for c in ingatan.chat if c["ronde"] == r and c["fase"] == "tribunal"}
        calon_r = []
        for q in hidup:
            if q == pengamat or q not in pemilih or q in bicara_tribunal:
                continue
            waktu_q = [c["waktu"] for c in chat_hari if c["pengirim"] == q]
            if len(waktu_q) < 2:
                continue  # korban Gag biasanya pemain yang sedang aktif bicara
            akhir = max(waktu_q)
            lain_sesudah = sum(1 for c in chat_hari if c["pengirim"] != q and c["waktu"] > akhir)
            jeda = (selesai - akhir) / view["durasi"]["day"]
            if lain_sesudah < GAG_MIN_PESAN_LAIN or jeda < GAG_JEDA_FRAKSI:
                continue
            peluang = P_GAG_DASAR * min(1.0, jeda / 0.5)
            # Mengaku kena Gag pada ronde berikutnya memperkuat dugaan.
            if any(re.search(POLA_GAG, c["teks"], re.I) for c in ingatan.chat
                   if c["pengirim"] == q and c["ronde"] == r + 1):
                peluang = min(0.9, peluang + 0.2)
            calon_r.append((peluang, q, akhir))
        calon_r.sort(key=lambda x: (-x[0], x[1]))
        for urutan, (peluang, q, akhir) in enumerate(calon_r):
            # Hanya satu Gag per ronde: calon selain yang terkuat diturunkan.
            peluang = peluang * faktor * (1.0 if urutan == 0 else 0.5)
            p_gag[q] = max(p_gag[q], peluang)
            korban.append({"korban": q, "jenis": "gag", "ronde": r, "p": peluang, "batas_waktu": akhir})
        gag_kuat[r] = calon_r[0][0] * faktor if calon_r else 0.0
    return p_sandera, p_gag, korban

# Klaim role dari teks. Yang menjadi bukti: bentrok, kebohongan pasti, tuduhan atau klaim bersih lewat Peek, dan klaim bersih
# yang terbukti salah. Klaim Civilian hanya dikenali, bukan bukti bentrok, karena Civilian bisa banyak.
# Bentrok = pengaku lebih banyak dari jumlah role itu (Stalker selalu satu; Spy bisa dua di room besar).
# Alur: 1 pengaku tiap role dari teks -> 2 bentrok: pengaku hidup melebihi jumlah role -> 3 pembohong pasti (terbukti
#       Hitman, atau mengaku role milik bot) -> 4 klaim Peek yang bohong ke bot atau membersihkan Hitman -> 5 tuduhan
#       dan klaim bersih lewat Peek yang dipercaya -> 6 kalimat rincian
def _klaim_peran(relasi, hidup, pengamat, R, peran_bot=None, komposisi_peran=None, rekan_spy=(), terbukti_hitman=()):
    batas = {"stalker": 1, "spy": (komposisi_peran or {}).get("spy", 1)}
    pengaku = defaultdict(set)
    for chat, _ in relasi:
        if chat["pengirim"] == pengamat:
            continue
        for peran, pola in POLA_KLAIM.items():
            if re.search(pola, chat["teks"], re.I):
                pengaku[peran].add(chat["pengirim"])

    # Pengaku yang terbukti Hitman lewat fakta (eksekusi, keluar, atau hasil Peek bot) pasti bohong, juga sesudah ia mati, jadi
    # klaimnya tidak dihitung dan tidak membuat pengaku lain tampak bentrok.
    terbukti = set().union(*pengaku.values()) & set(terbukti_hitman)
    konflik, rincian = {}, {}
    for peran, jumlah_role in batas.items():
        aktif = sorted(o for o in pengaku[peran] if o in hidup and o not in terbukti)
        if len(aktif) > jumlah_role:
            jumlah = "satu" if jumlah_role == 1 else str(jumlah_role)
            for o in aktif:
                konflik[o] = 0.6
                lawan = ", ".join(x for x in aktif if x != o)
                rincian[o] = f"{o} dan {lawan} sama-sama mengaku {peran.capitalize()}, padahal role itu hanya {jumlah}."

    # Stalker/Spy tahu pasti: orang lain yang mengaku role miliknya berbohong, selain rekan Spy di room 2 Spy. Kebohongan itu tetap
    # berlaku sesudah pengakunya mati, supaya klaim lamanya tidak dipercaya lagi.
    pembohong = set(terbukti)
    if peran_bot in batas:
        pembohong |= set(pengaku[peran_bot]) - set(rekan_spy)

    # Hanya pengaku Stalker yang menyebut peek: (pengaku, ronde, target, relasi).
    peek = [(chat["pengirim"], chat["ronde"], target, rel) for chat, pasangan in relasi
            if chat["pengirim"] in pengaku["stalker"] and re.search(POLA_PEEK, chat["teks"], re.I)
            for target, rel in pasangan if target != chat["pengirim"]]
    bohong_peek = {s for s, _, t, rel in peek if rel == "offend" and pengamat is not None and t == pengamat}
    klaim_salah = {}
    for s, _, t, rel in peek:
        if rel == "defend" and t in terbukti_hitman:
            klaim_salah.setdefault(s, t)
            rincian[s] = f"{s} mengaku peek {t} bersih, padahal {t} terbukti Hitman."

    # Klaim dari pengaku yang pasti bohong diabaikan. Tuduhan lewat Peek bernilai tetap, dan pengaku yang bentrok tidak
    # dihitung. Klaim bersih tetap meluruh, dan batal bila klaim pengaku itu terbukti salah.
    tuduhan_peek, bersih_peek = {}, defaultdict(dict)
    for s, ronde, target, rel in peek:
        if s in pembohong or s in bohong_peek:
            continue
        if rel == "offend" and s not in konflik:
            tuduhan_peek[target] = 0.8
            rincian.setdefault(target, f"{s} mengaku peek {target} sebagai Hitman.")
        elif rel == "defend" and s not in klaim_salah:
            bersih_peek[target][s] = (0.4 if s in konflik else 0.8) * _luruh(ronde, R, PELURUHAN_KERAS)

    for o in pembohong:
        rincian[o] = (f"{o} terbukti Hitman, jadi klaim role-nya tidak bisa dipercaya." if o in terbukti
                      else f"Klaim {peran_bot.capitalize()} dari {o} tidak bisa dipercaya.")
    for s in bohong_peek:
        rincian[s] = f"{s} mengaku peek dan menyebut aku Hitman, padahal aku tahu itu bohong."
    return {"pengaku": pengaku, "konflik": konflik, "pembohong": pembohong, "tuduhan_peek": tuduhan_peek,
            "bersih_peek": bersih_peek, "bohong_peek": bohong_peek, "klaim_salah": set(klaim_salah), "rincian": rincian}

# Memihak Hitman: pemain yang pernah membela orang yang kini terbukti Hitman. Pembelaan sesudah klaim bersih pengaku
# Stalker lain bernilai rendah, karena pemain itu mungkin sekadar ikut percaya pada klaim palsu.
# Hasilnya {pemain: (nilai terbesar, orang yang dibela)}.
# Alur: 1 tiap pembelaan ke pemain yang kini terbukti Hitman -> 2 bobot rendah bila pengaku Stalker lain sudah
#       mengklaimnya bersih -> 3 simpan nilai terbesar per pemain
def _memihak_hitman(relasi, klaim, terbukti_hitman, R):
    hasil, sudah_diklaim = {}, defaultdict(set)
    for chat, pasangan in relasi:
        p = chat["pengirim"]
        klaim_sendiri = p in klaim["klaim_salah"] and re.search(POLA_PEEK, chat["teks"], re.I)
        for x, rel in pasangan:
            if rel != "defend" or x == p or x not in terbukti_hitman:
                continue
            bobot = 0.3 if sudah_diklaim[x] - {p} and not klaim_sendiri else 0.8
            nilai = bobot * _luruh(chat["ronde"], R, PELURUHAN_KERAS)
            if nilai > hasil.get(p, (0.0, None))[0]:
                hasil[p] = (nilai, x)
            if klaim_sendiri:
                sudah_diklaim[x].add(p)
    return hasil

# Pengaruh: berapa pemain lain ikut menuduh (lewat chat sesudahnya atau vote) target yang sama setelah p menuduh,
# pada ronde yang sama; dijumlah per pemain lalu dinormalkan ke 0–1.
# Alur: 1 tiap tuduhan p: hitung pengikut lewat chat sesudahnya atau vote, ronde sama -> 2 jumlahkan per pemain -> 3 bagi
#       jumlah pemain hidup − 2, paling besar 1
def _pengaruh(relasi, votes, hidup, R):
    nilai = {}
    for i, (chat, pasangan) in enumerate(relasi):
        p = chat["pengirim"]
        for x, rel in pasangan:
            if rel != "offend" or x == p:
                continue
            pengikut = {d["pengirim"] for d, pasangan_d in relasi[i + 1:]
                        if d["ronde"] == chat["ronde"] and (x, "offend") in pasangan_d and d["pengirim"] not in (p, x)}
            pengikut |= {v["pemilih"] for v in votes
                         if v["ronde"] == chat["ronde"] and v["target"] == x and v["pemilih"] not in (p, x)}
            kunci = (p, x, chat["ronde"])
            nilai[kunci] = max(nilai.get(kunci, 0.0), len(pengikut) * _luruh(chat["ronde"], R, PELURUHAN))
    per_pemain = defaultdict(float)
    for (p, _, _), v in nilai.items():
        per_pemain[p] += v
    skala = max(1, len(hidup) - 2)
    return {p: min(1.0, v / skala) for p, v in per_pemain.items()}

# ===== 4. BUKTI PER PEMAIN, KONTEKS PERMAINAN, DAN FAKTA PASTI =====

# Chat ronde ini dianggap ramai (chat_sepi = 0) mulai sekian pesan pemain lain.
MIN_PESAN_INFO = 4

# Ruangan hening: tidak ada chat selama porsi fase ini, paling sedikit HENING_MIN_DETIK.
HENING_FRAKSI = 0.20

HENING_MIN_DETIK = 15

# Hitman yang masih hidup. Hitman tahu pasti (dirinya + rekan hidup). Warga membaca pengumuman engine
# (room ≥ 2 Hitman); tanpa pengumuman, hanya Hitman hasil Peek yang sudah dieksekusi yang dikurangi.
def hitman_hidup(ingatan, view):
    hidup = {p["nama"] for p in view["pemain"] if p["hidup"]}
    if view["saya"]["role"] == "hitman":
        return 1 + sum(r in hidup for r in view["saya"].get("rekan", []))
    if view.get("hitman_tersisa") is not None:
        return view["hitman_tersisa"]
    tertangkap = {x["pemain"] for x in ingatan.intel if x["peran"] == "hitman"} - hidup
    return max(1, komposisi(view)["hitman"] - len(tertangkap))

# Konteks permainan dari sudut pandang bot: posisi Syndicate, suasana chat, panggilan ke bot, dan suara Tribunal.
# Hasilnya dibaca izin_chat, calon_chat, dan keputusan vote lewat ctx["konteks"].
# Menerima ingatan, view, publik, serta chats, relasi, klaim, dan p_sandera yang sudah dihitung hitung_bukti.
# Hasilnya dict 13 nilai (tabel D di bagian Parameter): warga_terdesak, waktu_berjalan, chat_membingungkan, chat_sepi,
#   ruangan_hening, ada_pertanyaan_baru, sudah_diajak, sudah_disuarakan, klaim_bentrok, bot_dituduh_baru, penanya,
#   porsi_suara, jumlah_suara.
# Dipanggil oleh hitung_bukti.
# Alur: 1 warga bebas dan warga_terdesak -> 2 chat ronde ini: membingungkan, sepi, klaim bentrok -> 3 sejak chat
#       terakhir bot: penuduh baru, penanya, pertanyaan baru -> 4 sudah diajak, gema, ruangan hening -> 5 porsi suara
#       Tribunal
def _konteks_permainan(ingatan, view, publik, chats, relasi, klaim, p_sandera):
    bot, R = view["saya"]["nama"], view["ronde"]
    roster = [p["nama"] for p in view["pemain"]]
    hidup = [p["nama"] for p in view["pemain"] if p["hidup"]]
    # Warga bebas = pemain hidup − Hitman hidup − korban Hostage yang diumumkan (rekan Hitman tidak pernah disandera).
    # Syndicate menang saat warga bebas ≤ Hitman hidup, jadi warga_terdesak dihitung dari selisihnya.
    rekan = set(view["saya"].get("rekan", [])) if not publik else set()
    lain = [q for q in hidup if q != bot and q not in rekan]
    jumlah_hitman_hidup = hitman_hidup(ingatan, view)
    warga_bebas = len(hidup) - jumlah_hitman_hidup - sum(p_sandera.get(q, 0.0) for q in lain)
    ronde_ini = [c for c in chats if c["ronde"] == R and c["fase"] in ("day", "tribunal") and c["pengirim"] != bot]
    tidak_jelas = [c for c in ronde_ini if (c.get("conf_intent") or 0.0) < MIN_CONF_INTENT
                   or (c.get("intent") in ("offend", "defend") and not relasi_chat(c, roster))]
    # Pengaku bentrok yang bot belum tahu siapa yang bohong.
    klaim_bentrok = sorted(set(klaim["konflik"]) - klaim["pembohong"])
    chat_membingungkan = len(tidak_jelas) / max(1, len(ronde_ini))
    if klaim_bentrok:
        chat_membingungkan = max(chat_membingungkan, 0.8)
    aksi_fase = _aksi_fase(ingatan, view)
    waktu_bot = max((a["waktu"] for a in aksi_fase), default=-math.inf)
    sudah_bela = any(a["aksi"] == "bela_diri" for a in aksi_fase)
    fase_ini = [(c, pasangan) for c, pasangan in relasi
                if (c["ronde"], c["fase"]) == (R, view["fase"]) and c["waktu"] > waktu_bot and c["pengirim"] != bot]
    penuduh_baru = {c["pengirim"] for c, pasangan in fase_ini if (bot, "offend") in pasangan}
    if view["fase"] == "tribunal" and not sudah_bela:
        penuduh_baru |= {pemilih for pemilih, target in view["suara_tribunal"].items() if target == bot}
    # Penanya: pengirim chat neutral terbaru yang menyebut bot, sesudah chat terakhir bot (jadi belum dijawab). Menyebut =
    # bot menjadi target neutral (IndoBERT atau aturan nama di anotasi_chat) atau namanya tertulis. Sengaja tanpa pola
    # pertanyaan: kalimat yang menyebut bot layak ditanggapi, walau bot jadi bisa membalas sapaan atau komentar biasa.
    pola_nama = rf"(?<!\w){re.escape(bot)}(?!\w)"
    penanya = next((c["pengirim"] for c, _ in reversed(fase_ini)
                    if c.get("intent") in (None, "neutral")
                    and (any((t["pemain"], t["relasi"]) == (bot, "neutral") for t in c.get("target", []))
                         or re.search(pola_nama, c["teks"], re.I))), None)
    # Pertanyaan pemain lain sejak chat terakhir bot: bot tidak mengulang pertanyaan umum atau
    # ajakan bicara ke pemain yang sama (beberapa bot bertanya serentak terasa seperti mesin).
    tanya_lain = [c for c, _ in fase_ini if re.search(POLA_TANYA, c["teks"], re.I)]
    ada_pertanyaan_baru = any(c.get("intent") in (None, "neutral") for c in tanya_lain)
    # Ajakan bicara dihitung per ronde (sama dengan "diam"): pemain yang sudah diajak siang tidak diajak lagi
    # saat Tribunal.
    tanya_ronde = [c for c in ronde_ini if re.search(POLA_TANYA, c["teks"], re.I)]
    sudah_diajak = sorted({p for c in tanya_ronde for p in roster
                           if p != bot and re.search(rf"(?<!\w){re.escape(p)}(?!\w)", c["teks"], re.I)})
    # Gema: pemain lain yang sudah menuduh/membela p di fase ini (seluruh fase, bukan sejak chat bot),
    # agar bot tidak menjadi suara ketiga yang mengulang hal sama. Bela diri tidak dihitung.
    gema = {"offend": defaultdict(set), "defend": defaultdict(set)}
    for c, pasangan in relasi:
        if (c["ronde"], c["fase"]) == (R, view["fase"]) and c["pengirim"] != bot:
            for p, rel in pasangan:
                if p != c["pengirim"]:
                    gema[rel][p].add(c["pengirim"])
    # Hening: tidak ada chat dari siapa pun (termasuk bot sendiri) di fase ini selama ambang waktu tertentu.
    ruangan_hening = False
    if view["fase"] in ("day", "tribunal"):
        mulai_fase, _ = jendela_fase(ingatan, view, R, view["fase"])
        if mulai_fase is not None:
            terakhir = max([c["waktu"] for c in chats if (c["ronde"], c["fase"]) == (R, view["fase"])] + [mulai_fase])
            ambang_hening = max(HENING_MIN_DETIK, HENING_FRAKSI * view["durasi"][view["fase"]])
            ruangan_hening = view["waktu"] - terakhir >= ambang_hening
    suara = Counter(view["suara_tribunal"].values())
    total_suara = sum(suara.values())
    return {
        # Satu Hitman: sama dengan (6 − warga_bebas) ÷ 4; k Hitman: diukur dari selisih warga bebas − k.
        "warga_terdesak": float(np.clip((5 - (warga_bebas - jumlah_hitman_hidup)) / 4, 0, 1)),
        "chat_membingungkan": chat_membingungkan,
        "chat_sepi": 1 - min(1.0, len(ronde_ini) / MIN_PESAN_INFO),
        "bot_dituduh_baru": sorted(penuduh_baru),
        "penanya": penanya,
        "ada_pertanyaan_baru": ada_pertanyaan_baru,
        "sudah_diajak": sudah_diajak,
        "ruangan_hening": bool(ruangan_hening),
        "sudah_disuarakan": {rel: {p: len(s) for p, s in sorted(gema[rel].items())} for rel in ("offend", "defend")},
        "porsi_suara": {t: n / total_suara for t, n in suara.items()} if total_suara else {},
        "jumlah_suara": total_suara,
        "waktu_berjalan": waktu_berjalan(ingatan, view),
        "klaim_bentrok": klaim_bentrok,
    }

# Pemain diam: nilai diam penuh sesudah porsi siang ini berlalu tanpa ia bicara.
DIAM_FRAKSI = 0.35

# Bukti per pemain dan konteks permainan, dihitung ulang dari ingatan setiap langkah. Tabelnya lalu dinilai pohon fuzzy
# kecurigaan (fuzzy_controller.nilai_kecurigaan), dan menjadi bahan fitur Hitman/Spy serta kandidat tindakan.
# Menerima ingatan, view; publik=True = sudut pandang pengamat netral tanpa pengetahuan pribadi (dipakai Hitman).
# Hasilnya (tabel, konteks). tabel = DataFrame satu baris per pemain: bukti 0–1 (tekanan, dukungan, klaim_role_bermasalah, p_sandera,
#   ...), penanda kandidat, dan rincian kalimat alasan. konteks = dict dari _konteks_permainan.
# Dipanggil oleh fuzzy_controller.putuskan (tabel pribadi; Hitman juga tabel publik).
# Alur: 1 status Hostage dan Gag (dugaan_status) -> 2 relasi chat, klaim role, pengaruh vote -> 3 bukti tiap
#       pemain -> 4 konteks permainan (_konteks_permainan)
def hitung_bukti(ingatan, view, publik=False):
    bot, R, peran_bot = view["saya"]["nama"], view["ronde"], view["saya"]["role"]
    pengamat = None if publik else bot
    roster = [p["nama"] for p in view["pemain"]]
    hidup = [p["nama"] for p in view["pemain"] if p["hidup"]]
    jumlah_hitman = komposisi(view)["hitman"]
    p_sandera, p_gag, korban = dugaan_status(ingatan, view, pengamat)
    chats = _chat_urut(ingatan)
    relasi = [(c, relasi_chat(c, roster)) for c in chats]
    votes = _semua_vote(ingatan, view)
    terbukti_hitman = _terbukti_hitman(ingatan, publik)
    rekan_spy = [] if publik else view["saya"].get("rekan_spy", [])
    klaim = _klaim_peran(relasi, hidup, pengamat, R, None if publik else peran_bot, komposisi(view), rekan_spy, terbukti_hitman)
    memihak = _memihak_hitman(relasi, klaim, terbukti_hitman, R)
    # Pemain yang pasti bersih menurut bot warga: dirinya sendiri, hasil Peek bukan Hitman, dan rekan Spy.
    bersih_pasti, hitman_peek = set(), set()
    if not publik and peran_bot != "hitman":
        bersih_pasti = {bot, *rekan_spy} | {x["pemain"] for x in ingatan.intel if x["peran"] != "hitman"}
        hitman_peek = {x["pemain"] for x in ingatan.intel if x["peran"] == "hitman"}
    # Hitman yang diketahui bot: hasil Peek (warga) atau rekan Syndicate (Hitman). Berlaku juga untuk sudut pandang
    # publik Hitman, agar Hitman tidak pernah menyebut eksekusi rekannya sebagai eksekusi yang salah.
    hitman_diketahui = hitman_peek | (set(view["saya"].get("rekan", [])) if peran_bot == "hitman" else set())
    # Eksekusi yang tidak mengakhiri game: korbannya pasti warga jika Hitman hanya satu, atau jika pengumuman
    # jumlah Hitman tidak berkurang. Tanpa kepastian itu, bukti dibobot peluang korban bukan Hitman ≈ 1 − k/(N − 1).
    bobot_eksekusi = 1.0 if jumlah_hitman == 1 else max(0.0, 1 - jumlah_hitman / max(1, len(roster) - 1))
    # Klaim bersih palsu dari Hitman bisa membersihkan rekannya bila Hitman lebih dari satu: bobotnya dipotong.
    bobot_klaim_bersih = 1.0 if jumlah_hitman == 1 else 0.5

    # Yang tersingkir atau disandera tidak bisa lagi mengeksekusi, jadi tuduhannya bukan tekanan. Tuduhan korban Hostage
    # tetap menjadi bukti lewat penuduh_dibungkam.
    bersuara = [q for q in hidup if not p_sandera[q]]

    baris = []
    for p in roster:
        sumber = max(1, len([q for q in bersuara if q not in (p, pengamat)]))

        # Tekanan dan dukungan: satu pemain dihitung sekali (nilai terbarunya), baik lewat chat maupun vote.
        penuduh, pembela = {}, {}
        for chat, pasangan in relasi:
            s = chat["pengirim"]
            if s in (p, pengamat) or s not in bersuara:
                continue
            for target, rel in pasangan:
                if target == p:
                    kumpulan = penuduh if rel == "offend" else pembela
                    kumpulan[s] = max(kumpulan.get(s, 0.0), _luruh(chat["ronde"], R, PELURUHAN))
        for v in votes:
            if v["target"] == p and v["pemilih"] not in (p, pengamat) and v["pemilih"] in bersuara:
                penuduh[v["pemilih"]] = max(penuduh.get(v["pemilih"], 0.0), _luruh(v["ronde"], R, PELURUHAN))
        for s, bobot in klaim["bersih_peek"].get(p, {}).items():
            if s in bersuara:
                pembela[s] = max(pembela.get(s, 0.0), bobot)

        # Plin-plan: berganti sikap ke target yang sama, atau vote tidak sejalan dengan ucapan.
        sikap = [(chat["ronde"], target, rel) for chat, pasangan in relasi if chat["pengirim"] == p
                 for target, rel in pasangan if target != p]
        skor_ink, terakhir = 0.0, {}
        for ronde, target, rel in sikap:
            if target in terakhir and terakhir[target][1] != rel and ronde - terakhir[target][0] <= 1:
                skor_ink += _luruh(ronde, R, PELURUHAN)
            terakhir[target] = (ronde, rel)
        for v in votes:
            if v["pemilih"] != p:
                continue
            dituduh = {t for r, t, rel in sikap if r == v["ronde"] and rel == "offend"}
            dibela = {t for r, t, rel in sikap if r == v["ronde"] and rel == "defend"}
            if v["target"] in dibela:
                skor_ink += _luruh(v["ronde"], R, PELURUHAN)
            elif dituduh and v["target"] not in dituduh:
                skor_ink += 0.5 * _luruh(v["ronde"], R, PELURUHAN)

        # Alihkan tuduhan: balasan pertama p sesudah dituduh, di fase yang sama. Menuduh siapa pun = 1, membela diri sekaligus
        # menuduh = 0,5, hanya membela = 0. Chat tanpa relasi dilewati, dan tuduhan yang tidak dibalas tidak masuk pembagi.
        # Kunci id balasan: satu balasan yang menjawab beberapa tuduhan dihitung sekali.
        respon = {}
        for i, (chat, pasangan) in enumerate(relasi):
            if chat["pengirim"] == p or (p, "offend") not in pasangan:
                continue
            for berikut, pasangan_berikut in relasi[i + 1:]:
                if (berikut["ronde"], berikut["fase"]) != (chat["ronde"], chat["fase"]):
                    break
                if berikut["pengirim"] != p or not pasangan_berikut:
                    continue
                menuduh = any(rel == "offend" and t != p for t, rel in pasangan_berikut)
                bobot = (0.5 if (p, "defend") in pasangan_berikut else 1.0) if menuduh else 0.0
                respon[berikut["id"]] = bobot * _luruh(berikut["ronde"], R, PELURUHAN)
                break

        # Menyerang pemain yang pasti bersih: bot warga tahu tuduhan/vote seperti itu pasti keliru. Dua langkah per ronde:
        # nilai lama meluruh, lalu ditambah serangan ronde itu dan dipotong di 1.
        serang, diserang, tambahan = 0.0, set(), defaultdict(float)
        if bersih_pasti and p not in bersih_pasti:
            for c, pasangan in relasi:
                sasaran = {t for t, rel in pasangan if rel == "offend" and t in bersih_pasti}
                if c["pengirim"] == p and sasaran:
                    tambahan[c["ronde"]] += 0.5
                    diserang |= sasaran
            for v in votes:
                if v["pemilih"] == p and v["target"] in bersih_pasti:
                    tambahan[v["ronde"]] += 1.0
                    diserang.add(v["target"])
            for r in range(1, R + 1):
                serang = min(1.0, serang * PELURUHAN + tambahan[r])
            if p in klaim["bohong_peek"]:
                serang = 1.0
                diserang.add(bot)

        # Penuduh dibungkam: penuduh p kemudian di-Gag atau disandera (Hitman membungkam ancamannya).
        nilai_korban, rinci_korban = 0.0, None
        for k in korban:
            v, n = k["korban"], k["ronde"]
            if v == p:
                continue
            bobot = 0.0
            if v == pengamat:
                for a in ingatan.aksi_bot:
                    if a["intent"] == "offend" and a["target"] == p and a["ronde"] in (n, n - 1):
                        bobot = max(bobot, 1.0 if a["ronde"] == n else 0.6)
            else:
                for chat, pasangan in relasi:
                    if chat["pengirim"] != v or (p, "offend") not in pasangan:
                        continue
                    if k["batas_waktu"] is not None and chat["ronde"] == n and chat["waktu"] > k["batas_waktu"]:
                        continue
                    if chat["ronde"] == n:
                        bobot = max(bobot, 1.0)
                    elif chat["ronde"] == n - 1:
                        bobot = max(bobot, 0.6)
                # Vote terakhir korban sebelum dibungkam: Tribunal ronde n (sebelum malam Hostage n) atau n − 1 (Gag).
                ronde_vote = n if k["jenis"] == "sandera" else n - 1
                if any(x["pemilih"] == v and x["target"] == p and x["ronde"] == ronde_vote for x in ingatan.vote):
                    bobot = max(bobot, 0.6)
            nilai = k["p"] * bobot * _luruh(n, R, PELURUHAN_KERAS)
            if nilai > nilai_korban:
                nilai_korban, rinci_korban = nilai, k

        # Mendorong eksekusi warga: eksekusi yang tidak mengakhiri game berarti korbannya (kemungkinan) bukan Hitman.
        # Korban yang diketahui Hitman tidak pernah dihitung, karena mendorong eksekusinya bukan kesalahan.
        nilai_eks, rinci_eks = 0.0, None
        if view["fase"] != "finished":
            for e in ingatan.eksekusi:
                x, r = e["pemain"], e["ronde"]
                if x is None or r is None or x == p or e.get("hitman") is True or x in hitman_diketahui:
                    continue
                # Sebab korban pasti warga (untuk kalimat alasan); None = tidak pasti, bukti dibobot peluangnya.
                sebab = ("jumlah Hitman tidak berkurang" if e.get("hitman") is False
                         else "game berlanjut" if jumlah_hitman == 1
                         else "aku yakin" if x in bersih_pasti
                         else None)
                bobot_x = 1.0 if sebab else bobot_eksekusi
                # Ikut arus mayoritas kurang bermakna daripada menjadi segelintir pendorong eksekusi.
                pemilih_r = [v for v in ingatan.vote if v["ronde"] == r]
                pendorong = [v["pemilih"] for v in pemilih_r if v["target"] == x]
                bobot = 0.5 * (1 - (len(pendorong) - 1) / max(1, len(pemilih_r))) if p in pendorong else 0.0
                penuduh_x = [c["pengirim"] for c, pasangan in relasi
                             if c["ronde"] == r and (x, "offend") in pasangan and c["pengirim"] != x]
                if p in penuduh_x:
                    bobot += 0.3
                if penuduh_x and penuduh_x[0] == p:
                    bobot += 0.2
                nilai = min(1.0, bobot) * bobot_x * _luruh(r, R, PELURUHAN_KERAS)
                if nilai > nilai_eks:
                    nilai_eks, rinci_eks = nilai, {**e, "sebab": sebab}

        nilai_memihak, dibela_hitman = memihak.get(p, (0.0, None))
        nilai_klaim = max(klaim["konflik"].get(p, 0.0), klaim["tuduhan_peek"].get(p, 0.0),
                          0.8 if p in klaim["klaim_salah"] else 0.0,
                          1.0 if p in klaim["bohong_peek"] or p in klaim["pembohong"] else 0.0)
        n_info = (sum(1 for c, pasangan in relasi
                      if pasangan and (c["pengirim"] == p or any(t == p for t, _ in pasangan)))
                  + sum(1 for v in votes if p in (v["pemilih"], v["target"])))

        # Diam: hanya untuk mengajak bicara pemain yang belum bicara sama sekali di ronde ini (siang + Tribunal).
        # Dihitung per ronde agar pemain yang sudah bicara siang tadi tidak disebut "belum cerita" saat Tribunal.
        diam = 0.0
        if view["fase"] in ("day", "tribunal") and p in hidup and p != pengamat:
            mulai, _ = jendela_fase(ingatan, view, R, "day")
            if mulai is None:  # bot bergabung setelah siang: pakai awal fase sekarang
                mulai, _ = jendela_fase(ingatan, view, R, view["fase"])
            sudah_bicara = any(c["pengirim"] == p and c["ronde"] == R and c["fase"] in ("day", "tribunal")
                               for c in chats)
            if mulai is not None and not sudah_bicara:
                skala = DIAM_FRAKSI * view["durasi"]["day"]
                diam = float(np.clip((view["waktu"] - mulai) / skala, 0, 1))

        baris.append({
            "pemain": p, "hidup": p in hidup, "bot": p == bot, "kandidat": p in hidup and p != pengamat,
            "tekanan": min(1.0, sum(penuduh.values()) / sumber),
            "dukungan": min(1.0, sum(pembela.values()) / sumber),
            "plin_plan": min(1.0, skor_ink / 2),
            "alihkan_tuduhan": sum(respon.values()) / max(1, len(respon)),
            "menuduh_orang_baik": serang,
            "penuduh_dibungkam": nilai_korban,
            "ikut_salah_eksekusi": nilai_eks,
            "memihak_hitman": nilai_memihak,
            "klaim_role_bermasalah": nilai_klaim,
            "p_sandera": p_sandera.get(p, 0.0),
            "p_gag": p_gag.get(p, 0.0),
            "volume_info": 1 - math.exp(-n_info / 4),
            "diam": diam,
            # Total bukti mentah: pemutus seri agar bukti lemah tetap berpengaruh. Bobot 2 kedua dipakai jejak_kedua, yaitu
            # nilai terbesar ikut_salah_eksekusi dan memihak_hitman.
            "bukti_total": (2 * nilai_korban + 2 * max(nilai_eks, nilai_memihak) + 2 * nilai_klaim + serang
                            + min(1.0, sum(penuduh.values()) / sumber) * (1 - min(1.0, sum(pembela.values()) / sumber))
                            + sum(respon.values()) / max(1, len(respon)) + min(1.0, skor_ink / 2)),
            "n_penuduh": len(penuduh),
            "n_pembela": len(pembela),
            # Bobot klaim bersih dari pengaku Stalker (0,8; 0,4 bila bentrok; separuhnya bila Hitman lebih dari satu);
            # dipakai terapkan_pengetahuan.
            "bersih_klaim": bobot_klaim_bersih * max(klaim["bersih_peek"].get(p, {}).values(), default=0.0),
            "rincian": {"penuduh": sorted(penuduh), "pembela": sorted(pembela), "korban": rinci_korban,
                        "eksekusi": rinci_eks, "memihak": dibela_hitman, "klaim": klaim["rincian"].get(p),
                        "diserang": sorted(diserang),
                        "pengaku_bersih": max(sorted(klaim["bersih_peek"].get(p, {})), key=klaim["bersih_peek"].get(p, {}).get, default=None)},
        })
    tabel = pd.DataFrame(baris)
    return tabel, _konteks_permainan(ingatan, view, publik, chats, relasi, klaim, p_sandera)

# Pengetahuan pasti: fakta yang hanya diketahui bot dari role-nya sendiri (hasil Peek, rekan, hasil Hostage Syndicate).
# Hasilnya dibaca terapkan_pengetahuan, fitur Hitman, kandidat tindakan, serta chat_pasti/vote_pasti lewat ctx.
# Menerima ingatan (intel, eksekusi, keluar), view (role, rekan, rekan_spy, hasil_sandera, komposisi, fase).
# Hasilnya dict {hitman_diketahui, pasti_orang_baik, rekan, gagal_sandera}.
# Dipanggil oleh fuzzy_controller.putuskan.
# Alur: 1 hasil Peek: pasti baik atau Hitman -> 2 korban eksekusi dan pemain keluar menurut pengumuman -> 3 semua Hitman
#       sudah diketahui: sisanya pasti baik -> 4 rekan Hitman dan Hostage gagal per target
def pengetahuan_peran(ingatan, view):
    peran, bot = view["saya"]["role"], view["saya"]["nama"]
    roster = [p["nama"] for p in view["pemain"]]
    jumlah = komposisi(view)
    pasti_orang_baik = set() if peran == "hitman" else {bot, *view["saya"].get("rekan_spy", [])}
    hitman_diketahui = []
    for x in ingatan.intel:
        if x["peran"] != "hitman":
            pasti_orang_baik.add(x["pemain"])
        elif x["pemain"] not in hitman_diketahui:
            hitman_diketahui.append(x["pemain"])
    # Korban eksekusi dan pemain yang keluar: room 1 Hitman → warga bila game berlanjut; room ≥ 2 Hitman → menurut
    # pengumuman jumlah Hitman.
    for e in ingatan.eksekusi + ingatan.keluar:
        if not e["pemain"] or view["fase"] == "finished":
            continue
        if e.get("hitman") is True and e["pemain"] not in hitman_diketahui:
            hitman_diketahui.append(e["pemain"])
        elif jumlah["hitman"] == 1 or e.get("hitman") is False:
            pasti_orang_baik.add(e["pemain"])
    if hitman_diketahui and len(hitman_diketahui) >= jumlah["hitman"]:
        pasti_orang_baik |= set(roster) - set(hitman_diketahui)  # semua Hitman sudah diketahui
    rekan = set(view["saya"].get("rekan", [])) if peran == "hitman" else set()

    # Hostage gagal per target sepanjang pertandingan, dari hasil pasti server (me.syndicate_hostages, hanya Hitman). Tidak harus
    # berturut-turut, supaya Hitman tidak berputar di antara dua target yang terus dijaga: {target: jumlah malam}.
    gagal_sandera = dict(Counter(h["pemain"] for h in view["saya"].get("hasil_sandera", []) if not h["berhasil"]))
    return {"hitman_diketahui": hitman_diketahui, "pasti_orang_baik": pasti_orang_baik, "rekan": rekan,
            "gagal_sandera": gagal_sandera}

# ===== 5. BAHAN PER ROLE SESUDAH KECURIGAAN: fitur Spy dan fitur Hitman =====

# Fitur Spy: seberapa mungkin tiap pemain diincar Hitman, dari sudut pandang warga. Hasilnya (ctx["lindung"]) menjadi
# bahan kandidat Guard di calon_aksi.
# Menerima ingatan, view, tabel = bukti pribadi berisi kecurigaan (sesudah terapkan_pengetahuan).
# Hasilnya DataFrame per pemain hidup {menuduh_tersangka, mengaku_stalker, pengaruh, terancam}.
# Dipanggil oleh fuzzy_controller.putuskan (role Spy).
# Alur: 1 relasi chat, vote, klaim, dan pengaruh dari sudut pandang bot -> 2 tiap pemain hidup: menuduh tersangka kuat,
#       mengaku Stalker, pengaruh -> 3 terancam = nilai terbesar ketiganya
def fitur_lindung(ingatan, view, tabel):
    bot, R = view["saya"]["nama"], view["ronde"]
    roster = [p["nama"] for p in view["pemain"]]
    hidup = [p["nama"] for p in view["pemain"] if p["hidup"]]
    kec = dict(zip(tabel["pemain"], tabel["kecurigaan"]))
    chats = _chat_urut(ingatan)
    relasi = [(c, relasi_chat(c, roster)) for c in chats]
    votes = _semua_vote(ingatan, view)
    klaim = _klaim_peran(relasi, hidup, bot, R, view["saya"]["role"], komposisi(view), view["saya"].get("rekan_spy", []),
                         _terbukti_hitman(ingatan))
    pengaruh = _pengaruh(relasi, votes, hidup, R)
    baris = []
    for p in hidup:
        dari_chat = sum(kec.get(x, 0.0) * _luruh(c["ronde"], R, PELURUHAN) for c, pasangan in relasi
                        if c["pengirim"] == p for x, rel in pasangan if rel == "offend" and x != p)
        dari_vote = sum(kec.get(v["target"], 0.0) * _luruh(v["ronde"], R, PELURUHAN) for v in votes
                        if v["pemilih"] == p and v["target"] != p)
        # Tuduhan bot sendiri juga tercatat di aksi_bot; diambil yang terbesar agar tidak terhitung dua kali.
        dari_aksi = (sum(kec.get(a["target"], 0.0) * _luruh(a["ronde"], R, PELURUHAN) for a in ingatan.aksi_bot
                         if a["intent"] == "offend" and a["target"] not in (None, bot)) if p == bot else 0)
        menuduh_tersangka = min(1.0, max(dari_chat, dari_aksi) + dari_vote)
        stalker = p in klaim["pengaku"]["stalker"] and p not in klaim["pembohong"]
        mengaku_stalker = (0.5 if p in klaim["konflik"] else 0.9) if stalker else 0.0
        nilai_pengaruh = pengaruh.get(p, 0.0)
        baris.append({"pemain": p, "menuduh_tersangka": menuduh_tersangka, "mengaku_stalker": mengaku_stalker,
                      "pengaruh": nilai_pengaruh,
                      "terancam": min(1.0, max(menuduh_tersangka, mengaku_stalker, 0.8 * nilai_pengaruh))})
    return pd.DataFrame(baris)

# Kolom tabel fitur_hitman; tabel tanpa warga tetap memakai kolom ini.
KOLOM_HITMAN = ["pemain", "menuduh_tim", "pengaruh", "mengaku_role_penting", "kecurigaan_publik", "kredibilitas",
                "dukungan_suara", "ancaman_sekarang", "bicara_ronde_ini", "jejak_tuduhan"]

# Fitur Hitman: ancaman tiap warga dan citra publiknya, serta risiko diri sendiri. Rekan Syndicate dan korban Hostage tidak
# pernah menjadi target, jadi tidak masuk tabel ini (tidak dituduh, tidak di-vote sebagai kambing hitam, tidak disandera/di-Gag).
# Tabelnya lalu dinilai fuzzy ancaman dan kambing (fuzzy_controller.nilai_ancaman) dan menjadi bahan kandidat chat, vote,
# dan aksi Hitman.
# Menerima ingatan, view, publik = tabel publik yang sudah dinilai nilai_kecurigaan, pengetahuan, konteks.
# Hasilnya (DataFrame kolom KOLOM_HITMAN, satu baris per warga hidup yang bebas; diri {risiko_saya, suara_saya, korban_gag_tim}).
# Dipanggil oleh fuzzy_controller.putuskan (role Hitman).
# Alur: 1 relasi chat, vote, klaim, dan pengaruh dari sudut pandang publik -> 2 tiap warga bebas: tuduhan ke Syndicate,
#       jejak bila dibungkam, klaim role penting, citra publik -> 3 risiko dan porsi suara bot sendiri
def fitur_hitman(ingatan, view, publik, pengetahuan, konteks):
    bot, R = view["saya"]["nama"], view["ronde"]
    roster = [p["nama"] for p in view["pemain"]]
    hidup = [p["nama"] for p in view["pemain"] if p["hidup"]]
    chats = _chat_urut(ingatan)
    relasi = [(c, relasi_chat(c, roster)) for c in chats]
    votes = _semua_vote(ingatan, view)
    klaim = _klaim_peran(relasi, hidup, None, R, komposisi_peran=komposisi(view),
                         terbukti_hitman=_terbukti_hitman(ingatan, publik=True))
    pengaruh = _pengaruh(relasi, votes, hidup, R)
    pub = publik.set_index("pemain")
    rekan = pengetahuan["rekan"]
    sandera = {p["nama"] for p in view["pemain"] if p.get("sandera")}

    # Bobot tuduhan ke Syndicate: penuh ke bot, separuh ke rekan. Chat bernilai separuh vote.
    def ke_tim(target):
        return 1.0 if target == bot else 0.5 if target in rekan else 0.0

    baris = []
    for p in hidup:
        if p == bot or p in rekan or p in sandera:
            continue
        chat_p = [(c["ronde"], t) for c, pasangan in relasi if c["pengirim"] == p
                  for t, rel in pasangan if rel == "offend" and t != p]
        # Pasangan (ronde, bobot) setiap tuduhan p ke Syndicate, lewat chat atau vote.
        tuduhan = [(r, 0.5 * ke_tim(t)) for r, t in chat_p] + [(v["ronde"], ke_tim(v["target"])) for v in votes
                                                               if v["pemilih"] == p]
        menuduh = sum(bobot * _luruh(r, R, PELURUHAN) for r, bobot in tuduhan)
        sekarang = sum(bobot for r, bobot in tuduhan if r == R)
        # Jejak bila p dibungkam: makin sedikit orang yang p tuduh, makin jelas siapa yang diuntungkan.
        jejak_tuduhan = 0.0
        for r, bobot in ((R, 1.0), (R - 1, 0.6)):
            dituduh = {t for ronde, t in chat_p if ronde == r}
            if any(ke_tim(t) for t in dituduh):
                jejak_tuduhan = max(jejak_tuduhan, bobot / len(dituduh))
        mengaku_role_penting = 0.0
        if p in klaim["pengaku"]["stalker"]:
            mengaku_role_penting = 0.7 if p in klaim["konflik"] else 1.0
        elif p in klaim["pengaku"]["spy"]:
            mengaku_role_penting = 0.5
        bicara = any(c["pengirim"] == p and (c["ronde"], c["fase"]) == (R, view["fase"]) for c in chats)
        kec = float(pub.loc[p, "kecurigaan"])
        baris.append({
            "pemain": p, "menuduh_tim": min(1.0, menuduh), "pengaruh": pengaruh.get(p, 0.0),
            "mengaku_role_penting": mengaku_role_penting, "kecurigaan_publik": kec, "kredibilitas": 1 - kec,
            "dukungan_suara": konteks["porsi_suara"].get(p, 0.0),
            "ancaman_sekarang": min(1.0, sekarang + (0.5 * mengaku_role_penting if bicara else 0.0)),
            "bicara_ronde_ini": bicara,
            "jejak_tuduhan": jejak_tuduhan,
        })
    diri = {"risiko_saya": float(pub.loc[bot, "kecurigaan"]), "suara_saya": konteks["porsi_suara"].get(bot, 0.0),
            "korban_gag_tim": list(view["saya"].get("korban_gag_tim", []))}
    return pd.DataFrame(baris, columns=KOLOM_HITMAN), diri
