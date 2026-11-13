"""Pengganti IndoBERT di tes: cepat dan tidak butuh file model."""

import re


class NLUPalsu:
    """Intent dari kata kunci; target dari nama pemain yang disebut."""

    ambang = 0.0
    common_words = frozenset()

    def __init__(self, pola_offend=None, pola_defend=None):
        self.pola_offend = pola_offend
        self.pola_defend = pola_defend

    def intent(self, teks, daftar_pemain=()):
        kecil = teks.casefold()
        if self.pola_defend and re.search(self.pola_defend, kecil):
            return "defend", 0.7
        if self.pola_offend and re.search(self.pola_offend, kecil):
            return "offend", 0.7
        return "neutral", 0.7

    def target(self, pengirim, teks, konteks, daftar_pemain, label_intent):
        if label_intent == "neutral":
            return []
        kata = {w.casefold() for w in re.findall(r"\w+", teks)}
        disebut = [p for p in daftar_pemain if p != pengirim and p.casefold() in kata]
        if (
            not disebut
            and label_intent == "defend"
            and re.search(r"\b(aku|saya|gw|gue)\b", teks, re.I)
        ):
            disebut = [pengirim]
        return [{"pemain": p, "relasi": label_intent, "prob": None} for p in disebut] or [
            {"pemain": "tidak_diketahui", "relasi": label_intent, "prob": None}
        ]
