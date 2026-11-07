"""Pemahaman chat untuk bot: IndoBERT membaca intent lalu target, aturan nama menambah target neutral.

Satu NLU dipakai bersama semua bot (NLUBersama): bacaan tiap chat disimpan di memo karena hasilnya sama untuk semua
bot, dan inferensi model diserialkan supaya aman antar-thread. NLU tidak tahu soal fuzzy maupun socket; yang
memanggilnya adalah bot_controller.py dan pencatat NLU pertandingan.

Alurnya
1. Saat otak dimuat, folder_model mencari folder dua model IndoBERT, lalu NLUIndoBERT membukanya dan NLUBersama
   membungkusnya dengan memo
2. Tiap chat baru di ingatan bot dibaca baca_chat_baru, satu per satu lewat anotasi_chat:
   2.1 Model 1 (NLUIndoBERT.intent): nama pemain diganti nama yang dikenal model (varian_nama_intent), tiga varian
       dirata-ratakan
   2.2 Model 2 (NLUIndoBERT.target): satu teks pasangan per kandidat (buat_teks_pasangan) dengan 12 chat terakhir
       sebagai konteks
   2.3 Pesan neutral: pemain yang disebut namanya (pemain_disebut) menjadi target neutral
3. Pencatat NLU (baca_chat) membaca chat pertandingan sekali, menyimpannya sebagai konteks chat berikutnya, dan
   memberi ringkasan bacaan untuk checker dan riwayat chat panel
"""

from __future__ import annotations

import copy
import json
import logging
import re
import threading
import time
from collections import OrderedDict
from functools import lru_cache
from pathlib import Path

from app.config.settings import BACKEND_DIR, PROJECT_DIR

logger = logging.getLogger("shadow_heist.npc_brain")

# Chat sebelumnya yang ikut dibaca Model 2 sebagai konteks.
KONTEKS_MAKS = 12
# Lokasi bawaan model IndoBERT: artifacts backend, lalu folder skripsi di sebelah repo Games.
FOLDER_MODEL = {
    "intent": ("intent", "models/notebook_standalone/intent_classifier_transformer"),
    "target": ("target", "models/target_classifier/target_classifier_transformer"),
}
# Token pengganti nama pemain di teks pasangan Model 2 (sama dengan dataset nlu_target).
TOKEN_KANDIDAT = "KANDIDAT_X"
TOKEN_PENGIRIM = "PENGIRIM_X"
TOKEN_PEMAIN = "PEMAIN_X"
TOKEN_TIDAK_DIKETAHUI = "TIDAK_DIKETAHUI"
# Kata ganti dan istilah game tidak pernah dianggap nama pemain.
KATA_GANTI = {
    "aku", "saya", "gw", "gue", "gua", "dia", "kamu", "kau", "lu", "lo", "elu",
    "anda", "mereka", "kalian", "kita", "kami", "semua", "si",
}  # fmt: skip
ISTILAH_GAME = {"hitman", "spy", "stalker", "civilian", "hostage", "gag", "order", "guard", "peek", "vote"}
AKHIRAN_NAMA = ("nya", "lah", "kah", "pun", "mu", "ku")


# Mengenali potongan nama (Dika untuk Andika) atau nama berakhiran (Budinya, Andyy); hasil disimpan agar cepat.
@lru_cache(maxsize=None)
def _nama_cocok(word, name):
    w, n = word.casefold(), name.casefold()
    if len(w) < 3:
        return False
    if w in n:
        return True
    sisa = w[len(n):] if w.startswith(n) else None
    return sisa is not None and (sisa in AKHIRAN_NAMA or set(sisa) == {n[-1]})


# Mengganti nama pemain dan panggilannya dengan token peran agar model tidak menghafal nama.
def samarkan_nama(text, daftar_pemain, kandidat, pengirim, common_words):
    lowered = {name.casefold(): name for name in daftar_pemain}

    def token_for(name):
        if name == kandidat:
            return TOKEN_KANDIDAT
        return TOKEN_PENGIRIM if name == pengirim else TOKEN_PEMAIN

    def replace(match):
        word = match.group(0)
        key = word.casefold()
        if key in lowered:
            return token_for(lowered[key])
        if key in KATA_GANTI or key in ISTILAH_GAME or key in common_words:
            return word
        matches = [name for name in daftar_pemain if _nama_cocok(word, name)]
        return token_for(matches[0]) if len(matches) == 1 else word

    return re.sub(r"\w+", replace, text)


NAMA_KANONIK = (
    ("Raka", "Lala", "Sari", "Naya", "Dito", "Kiki", "Fajar", "Tio", "Bima", "Wawan"),
    ("Dito", "Kiki", "Fajar", "Tio", "Bima", "Wawan", "Raka", "Lala", "Sari", "Naya"),
    ("Bima", "Wawan", "Raka", "Lala", "Sari", "Naya", "Dito", "Kiki", "Fajar", "Tio"),
)


# Varian teks untuk Model 1: nama pemain dan panggilannya diganti nama yang dikenal model, dengan aturan
# pencocokan yang sama seperti samarkan_nama. Tanpa nama pemain, teks dipakai apa adanya.
def varian_nama_intent(text, daftar_pemain, common_words):
    lowered = {name.casefold(): name for name in daftar_pemain}

    def pemain(word):
        key = word.casefold()
        if key in lowered:
            return lowered[key]
        if key in KATA_GANTI or key in ISTILAH_GAME or key in common_words:
            return None
        matches = [name for name in daftar_pemain if _nama_cocok(word, name)]
        return matches[0] if len(matches) == 1 else None

    urutan = {}
    for word in re.findall(r"\w+", text):
        nama = pemain(word)
        if nama is not None:
            urutan.setdefault(nama, len(urutan))
    if not urutan:
        return [text]

    def ganti(set_nama):
        def replace(match):
            nama = pemain(match.group(0))
            return match.group(0) if nama is None else set_nama[urutan[nama] % len(set_nama)]
        return re.sub(r"\w+", replace, text)

    return [ganti(set_nama) for set_nama in NAMA_KANONIK]


# Menyusun satu teks pasangan (pesan, kandidat) dari pesan utama, konteks, dan roster.
def buat_teks_pasangan(pengirim, teks_chat, chat_sebelumnya, daftar_pemain, kandidat, common_words, label_intent=None):

    def peran(name):
        if name == "tidak_diketahui":
            return TOKEN_TIDAK_DIKETAHUI
        if name == kandidat:
            return TOKEN_KANDIDAT
        return TOKEN_PENGIRIM if name == pengirim else TOKEN_PEMAIN

    # Konteks terbaru ditulis lebih dulu agar yang terpotong adalah pesan paling lama.
    bagian = []
    for pesan in reversed(chat_sebelumnya):
        relasi = ", ".join(f"{t['relasi']} {peran(t['pemain'])}" for t in pesan["target"])
        anotasi = f"{pesan['label_intent']}: {relasi}" if relasi else pesan["label_intent"]
        teks = samarkan_nama(pesan["teks_chat"], daftar_pemain, kandidat, pengirim, common_words)
        bagian.append(f"{peran(pesan['pengirim'])}: {teks} [{anotasi}]")

    sekarang = samarkan_nama(teks_chat, daftar_pemain, kandidat, pengirim, common_words)
    konteks = " | ".join(bagian) if bagian else "tidak ada"
    awal = f"intent {label_intent} || " if label_intent else ""
    return f"{awal}pesan sekarang {peran(pengirim)}: {sekarang} || konteks: {konteks}"


class NLUIndoBERT:
    """Model 1 (intent) dan Model 2 (target) IndoBERT tersimpan; hanya inferensi, tanpa training atau unduhan."""

    def __init__(self, intent_dir, target_dir, device="cpu"):
        import torch
        from transformers import AutoModelForSequenceClassification, AutoTokenizer

        self.torch = torch
        self.device = torch.device(device)
        self.intent_tokenizer = AutoTokenizer.from_pretrained(intent_dir, local_files_only=True)
        self.intent_model = AutoModelForSequenceClassification.from_pretrained(
            intent_dir, local_files_only=True).to(self.device).eval()
        self.target_tokenizer = AutoTokenizer.from_pretrained(target_dir, local_files_only=True)
        self.target_model = AutoModelForSequenceClassification.from_pretrained(
            target_dir, local_files_only=True).to(self.device).eval()
        builder = json.loads((Path(target_dir) / "pair_builder.json").read_text(encoding="utf-8"))
        self.common_words = frozenset(builder["common_words"])
        # Ambang aturan minimal satu target yang dipilih dari validation saat training nlu_target.
        path_ambang = Path(target_dir) / "ambang_target.json"
        self.ambang = (float(json.loads(path_ambang.read_text(encoding="utf-8")).get("transformer", 0.0))
                       if path_ambang.is_file() else 0.0)

    # Probabilitas kelas untuk sekumpulan teks.
    def _probabilitas(self, tokenizer, model, texts, max_length):
        encoded = tokenizer(texts, return_tensors="pt", truncation=True, padding=True, max_length=max_length)
        encoded = {name: value.to(self.device) for name, value in encoded.items()}
        with self.torch.inference_mode():
            return self.torch.softmax(model(**encoded).logits, dim=-1).cpu().numpy()

    # Model 1: label intent dan confidence 0–1. Dengan roster, nama pemain diganti nama yang dikenal model
    # (varian_nama_intent) dan probabilitas ketiga varian dirata-ratakan.
    def intent(self, teks, daftar_pemain=()):
        config = self.intent_model.config
        varian = varian_nama_intent(teks, list(daftar_pemain), self.common_words) if daftar_pemain else [teks]
        probs = self._probabilitas(self.intent_tokenizer, self.intent_model, varian,
                                   getattr(config, "nlu_max_length", 128)).mean(axis=0)
        index = int(probs.argmax())
        label = {"offense": "offend", "defense": "defend"}.get(config.id2label[index], config.id2label[index])
        return label, float(probs[index])

    # Model 2: relasi setiap pemain roster terhadap pesan ini: offend/defend (dituduh/dibela) atau neutral (diajak
    # bicara atau dibicarakan). Sama dengan gabung_target di nlu_target: pesan neutral boleh tanpa target, dan aturan
    # minimal satu target serta "tidak_diketahui" hanya untuk offend/defend.
    def target(self, pengirim, teks, konteks, daftar_pemain, label_intent):
        config = self.target_model.config
        labels = [config.id2label[i] for i in range(len(config.id2label))]
        if label_intent == "neutral" and "neutral" not in labels:
            return []  # model target lama belum mengenal relasi neutral
        texts = [buat_teks_pasangan(pengirim, teks, konteks, daftar_pemain, kandidat, self.common_words, label_intent)
                 for kandidat in daftar_pemain]
        probs = self._probabilitas(self.target_tokenizer, self.target_model, texts,
                                   getattr(config, "nlu_max_length", 512))
        hasil = []
        for kandidat, baris in zip(daftar_pemain, probs):
            relasi = labels[int(baris.argmax())]
            if relasi != "tidak_ada":
                hasil.append({"pemain": kandidat, "relasi": relasi, "prob": float(baris.max())})
        if label_intent == "neutral":
            # Target pesan neutral selalu berelasi neutral (aturan dataset nlu_target); tanpa target = untuk semua.
            return [t for t in hasil if t["relasi"] == "neutral"]
        # Aturan minimal satu target (hanya offend/defend): sama dengan evaluasi di nlu_target.
        if not hasil and self.ambang > 0 and label_intent in labels:
            kolom = labels.index(label_intent)
            terbaik = int(probs[:, kolom].argmax())
            if probs[terbaik, kolom] >= self.ambang:
                hasil.append({"pemain": daftar_pemain[terbaik], "relasi": label_intent, "prob": float(probs[terbaik, kolom])})
        return hasil or [{"pemain": "tidak_diketahui", "relasi": label_intent, "prob": None}]


class NLUBersama:
    """Satu NLU untuk semua bot: hasil disimpan (memo) dan inferensi model diserialkan."""

    def __init__(self, nlu, sumber, maks=4096):
        self.nlu, self.sumber, self.maks = nlu, sumber, maks
        self.ambang = getattr(nlu, "ambang", 0.0)
        # Kata umum (pair_builder.json) untuk aturan nama di anotasi_chat: tidak pernah dianggap nama pemain.
        self.common_words = getattr(nlu, "common_words", frozenset())
        self._memo = OrderedDict()
        self._lock = threading.Lock()

    # Ambil dari memo atau hitung sekali; salinan dikembalikan agar ingatan bot tidak saling berbagi objek.
    # Alur: 1 kunci belum ada: hitung lalu simpan, buang yang paling lama bila memo penuh -> 2 tandai baru dipakai
    #       -> 3 kembalikan salinan
    def _ingat(self, kunci, hitung):
        with self._lock:
            if kunci not in self._memo:
                self._memo[kunci] = hitung()
                if len(self._memo) > self.maks:
                    self._memo.popitem(last=False)
            self._memo.move_to_end(kunci)
            return copy.deepcopy(self._memo[kunci])

    # Model 1 lewat memo. Roster ikut menjadi kunci, karena IndoBERT mengganti nama pemain sebelum membaca intent.
    def intent(self, teks, daftar_pemain=()):
        daftar = tuple(daftar_pemain)
        return self._ingat(("intent", teks, daftar), lambda: self.nlu.intent(teks, daftar))

    # Model 2 lewat memo. Konteks chat sebelumnya ikut menjadi kunci, karena teks pasangan memuatnya.
    def target(self, pengirim, teks, konteks, daftar_pemain, label_intent):
        kunci = (
            "target", pengirim, teks, json.dumps(konteks, sort_keys=True, ensure_ascii=False),
            tuple(daftar_pemain), label_intent,
        )  # fmt: skip
        return self._ingat(
            kunci, lambda: self.nlu.target(pengirim, teks, konteks, daftar_pemain, label_intent)
        )


# Folder model pertama yang ada: pengaturan eksplisit, artifacts backend, lalu folder skripsi. None bila tidak ada.
def folder_model(nilai, jenis) -> Path | None:
    if nilai and not Path(nilai).is_dir():
        # Salah ketik path di .env tidak boleh lolos diam-diam ke model lain.
        logger.warning("Folder model %s dari pengaturan tidak ditemukan: %s", jenis, nilai)
    nama_artifact, relatif = FOLDER_MODEL[jenis]
    kandidat = [
        nilai,
        BACKEND_DIR / "artifacts" / "indobert" / nama_artifact,
        PROJECT_DIR.parent / "training" / "prethesis" / "ai_2_dataset_baru" / relatif,
    ]
    return next((Path(p) for p in kandidat if p and Path(p).is_dir()), None)


# Aturan nama, sumber kedua target neutral: pemain roster yang disebut nama atau panggilannya di teks. Pencocokan sama
# dengan samarkan_nama: nama persis, atau panggilan/akhiran (_nama_cocok) yang cocok dengan tepat satu pemain; kata
# ganti, istilah game, dan kata umum (common_words) tidak pernah dianggap nama. Pengirim tidak dihitung.
# Masukan : teks, daftar_pemain (roster), pengirim, common_words (pair_builder.json Model 2; kosong bila tidak ada).
# Keluaran: daftar nama pemain yang disebut, urut kemunculan pertama.
# Dipakai oleh: anotasi_chat (hanya untuk pesan neutral, jadi aturan ini tidak pernah membuat target offend/defend).
def pemain_disebut(teks, daftar_pemain, pengirim, common_words):
    lowered = {name.casefold(): name for name in daftar_pemain}
    disebut = []
    for word in re.findall(r"\w+", teks):
        key = word.casefold()
        if key in lowered:
            nama = lowered[key]
        elif key in KATA_GANTI or key in ISTILAH_GAME or key in common_words:
            continue
        else:
            matches = [name for name in daftar_pemain if _nama_cocok(word, name)]
            if len(matches) != 1:
                continue
            nama = matches[0]
        if nama != pengirim and nama not in disebut:
            disebut.append(nama)
    return disebut


# Persepsi: membaca satu chat dengan IndoBERT, Model 1 (intent) lalu Model 2 (target per pemain roster). Pesan neutral
# juga mendapat target neutral dari aturan nama (pemain_disebut); target dari kedua sumber digabung per pemain.
# Masukan : nlu = NLUIndoBERT (atau pembungkus dengan intent/target yang sama); chat = {id, ronde, fase, waktu,
#           pengirim, teks}; riwayat = chat sebelumnya yang sudah beranotasi (12 terakhir menjadi konteks Model 2);
#           daftar_pemain = roster.
# Keluaran: chat yang sama + intent, conf_intent (0–1), dan target [{pemain, relasi, prob, sumber}].
#           sumber = ["indobert"], ["nama"], atau keduanya. Hanya relasi offend/defend yang menjadi bukti (relasi_chat);
#           target neutral menandai pemain yang diajak bicara (konteks "penanya").
# Dipakai oleh: baca_chat_baru (setiap chat baru di ingatan bot) dan baca_chat (pencatat NLU pertandingan).
def anotasi_chat(nlu, chat, riwayat, daftar_pemain):
    intent, confidence = nlu.intent(chat["teks"], daftar_pemain)
    konteks = [{
        "pengirim": c["pengirim"], "teks_chat": c["teks"], "label_intent": c.get("intent") or "neutral",
        "target": [{"pemain": t["pemain"], "relasi": t["relasi"]} for t in c.get("target", [])],
    } for c in riwayat[-KONTEKS_MAKS:]]
    sumber_model = getattr(nlu, "sumber", "indobert")  # pembungkus NLU cadangan di backend menamai sumbernya sendiri
    target = [{**t, "sumber": [sumber_model]}
              for t in nlu.target(chat["pengirim"], chat["teks"], konteks, daftar_pemain, intent)]
    if intent == "neutral":
        for nama in pemain_disebut(chat["teks"], daftar_pemain, chat["pengirim"], getattr(nlu, "common_words", ())):
            sama = next((t for t in target if t["pemain"] == nama), None)
            if sama is None:
                target.append({"pemain": nama, "relasi": "neutral", "prob": None, "sumber": ["nama"]})
            else:
                sama["sumber"].append("nama")
    return {**chat, "intent": intent, "conf_intent": confidence, "target": target}


# Bacakan chat baru di ingatan satu bot, mulai indeks `dari`, berurutan: tiap chat memakai chat sebelumnya yang sudah
# terbaca sebagai konteks, sama seperti saat bacaan dulu dilakukan di dalam Ingatan.sinkron_snapshot. Tanpa NLU, chat
# dibiarkan tanpa bacaan. Bila NLU gagal di tengah, chat yang belum terbaca dikeluarkan lagi dari ingatan supaya
# dibaca ulang di langkah berikutnya.
# Alur: 1 tiap chat baru: anotasi_chat dengan chat sebelumnya -> 2 ganti catatan chat dengan hasil bacaannya
#                         \> 1.2 NLU gagal: keluarkan chat yang belum terbaca, lalu teruskan galatnya
def baca_chat_baru(nlu, ingatan, roster, dari):
    if nlu is None:
        return
    for i in range(dari, len(ingatan.chat)):
        try:
            ingatan.chat[i] = anotasi_chat(nlu, ingatan.chat[i], ingatan.chat[:i], roster)
        except Exception:
            for chat in ingatan.chat[i:]:
                ingatan._id_chat.discard(chat["id"])
            del ingatan.chat[i:]
            raise


# Target NLU menjadi teks pendek untuk panel, mis. "NOX: offend (0.91)".
def teks_target(target):
    return [
        f"{t['pemain']}: {t['relasi']}"
        + (f" ({t['prob']:.2f})" if t.get("prob") is not None else "")
        for t in target or []
    ]


# Pencatat NLU: baca satu chat pertandingan seperti ingatan bot membacanya, dengan `riwayat` (milik pemanggil, urut
# kronologis) sebagai konteks. Bacaannya sama dengan bacaan bot dan masuk memo NLU, jadi bot tidak menghitung ulang.
# Target neutral (pemain yang diajak bicara) ikut dengan asalnya: IndoBERT dan/atau aturan nama.
# Hasil: bacaan beserta konteks (maks KONTEKS_MAKS chat sebelumnya) dan roster, untuk riwayat panel dan ekspor format
# dataset (target sebagai {pemain, relasi}).
# Alur: 1 salin konteks sebelum chat ini -> 2 anotasi_chat -> 3 chat masuk riwayat (maks 50) -> 4 susun ringkasan
def baca_chat(nlu, riwayat, pengirim, teks, roster):
    mulai = time.perf_counter()
    konteks = [
        {"pengirim": c["pengirim"], "teks": c["teks"], "intent": c.get("intent"),
         "target": [{"pemain": t["pemain"], "relasi": t["relasi"]} for t in c.get("target", [])]}
        for c in riwayat[-KONTEKS_MAKS:]
    ]  # fmt: skip
    chat = anotasi_chat(nlu, {"pengirim": pengirim, "teks": teks}, riwayat, list(roster))
    riwayat.append(chat)
    del riwayat[:-50]
    return {"intent": chat["intent"], "confidence": round(chat["conf_intent"], 3),
            "target": [{"pemain": t["pemain"], "relasi": t["relasi"],
                        "prob": None if t.get("prob") is None else round(t["prob"], 3),
                        "sumber": list(t.get("sumber", []))}
                       for t in chat["target"]],
            "konteks": konteks, "daftar_pemain": list(roster),
            "sumber": nlu.sumber, "ms": round((time.perf_counter() - mulai) * 1000, 1)}  # fmt: skip
