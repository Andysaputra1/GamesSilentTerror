"""Survei akhir pertandingan: pertanyaan, skala, dan arti skala diatur dari database/panel."""

from __future__ import annotations

import logging
import re
import threading
import time

from sqlalchemy.exc import IntegrityError

from app.models import survey_queries as queries
from app.module.persistence_service import PersistenceError, PersistenceService
from app.module.room_service import room_service

logger = logging.getLogger("shadow_heist.survey")

JENIS = {"stars", "scale", "choice", "text"}
# Jenis pertanyaan yang dijawab dengan angka pada skala.
JENIS_BERSKALA = {"stars", "scale"}
NILAI_SKALA_MAKS = 10
PANJANG_TEKS = 1000
# Pemain yang sudah keluar room tetap bisa mengirim survei selama ini (hanya di memori).
BERLAKU_SELESAI_DETIK = 30 * 60
KODE_DUPLIKAT_MYSQL = 1062
PESAN_SUDAH_DIKIRIM = "Survei untuk pertandingan ini sudah dikirim. Terima kasih!"
KOLOM_PUBLIK = (
    "id",
    "code",
    "prompt",
    "kind",
    "scale_min",
    "scale_max",
    "label_min",
    "label_max",
    "options",
    "required",
)


class SurveyAlreadySubmitted(ValueError):
    """Satu akun hanya mengirim survei sekali untuk satu pertandingan."""


# Buang spasi berlebih dari teks yang diketik admin atau pemain.
def _rapikan_spasi(nilai) -> str:
    return " ".join(str(nilai).split())


# Bagian pertanyaan yang boleh dilihat pemain dan disalin ke setiap jawaban.
def public_question(pertanyaan: dict) -> dict:
    return {kolom: pertanyaan[kolom] for kolom in KOLOM_PUBLIK}


# VALIDASI PANEL: bentuk pertanyaan harus konsisten dengan jenis jawabannya.
def validate_question(data: dict) -> dict:
    # INPUT: kode, teks, dan jenis yang sudah dirapikan
    kode = str(data.get("code", "")).strip().lower()
    teks_pertanyaan = _rapikan_spasi(data.get("prompt", ""))
    jenis = data.get("kind")

    # PROSES: pemeriksaan pertama yang gagal menentukan pesan error yang dilihat admin
    if not re.fullmatch(r"[a-z0-9_]{2,40}", kode):
        raise ValueError("Kode pertanyaan 2–40 karakter: huruf kecil, angka, atau garis bawah.")
    if not 3 <= len(teks_pertanyaan) <= 300:
        raise ValueError("Teks pertanyaan harus 3–300 karakter.")
    if jenis not in JENIS:
        raise ValueError("Jenis pertanyaan harus stars, scale, choice, atau text.")
    try:
        skala_minimum = int(data.get("scale_min", 1))
        skala_maksimum = int(data.get("scale_max", 6))
        urutan = int(data.get("position", 0))
    except (TypeError, ValueError) as error:
        raise ValueError("Skala dan urutan harus berupa angka bulat.") from error
    if jenis == "stars" and skala_minimum != 1:
        raise ValueError("Pertanyaan bintang selalu dimulai dari 1.")
    if jenis in JENIS_BERSKALA and not 0 <= skala_minimum < skala_maksimum <= NILAI_SKALA_MAKS:
        raise ValueError(f"Skala harus 0 ≤ minimum < maksimum ≤ {NILAI_SKALA_MAKS}.")
    label_skala = {}
    for kolom_label in ("label_min", "label_max"):
        label = data.get(kolom_label)
        label = _rapikan_spasi(label) if label not in (None, "") else None
        if label is not None and len(label) > 80:
            raise ValueError("Label arti skala maksimal 80 karakter.")
        label_skala[kolom_label] = label
    pilihan = []
    if jenis == "choice":
        pilihan = [_rapikan_spasi(item) for item in (data.get("options") or [])]
        if not 2 <= len(pilihan) <= 8 or len(set(pilihan)) != len(pilihan):
            raise ValueError("Pilihan ganda membutuhkan 2–8 pilihan berbeda.")
        if any(not 1 <= len(item) <= 80 for item in pilihan):
            raise ValueError("Setiap pilihan 1–80 karakter.")
    if not -1000 <= urutan <= 1000:
        raise ValueError("Urutan harus antara -1000 dan 1000.")

    # OUTPUT: data siap simpan; jenis tanpa skala memakai skala bawaan 1–6
    return {
        "code": kode,
        "prompt": teks_pertanyaan,
        "kind": jenis,
        "scale_min": skala_minimum if jenis in JENIS_BERSKALA else 1,
        "scale_max": skala_maksimum if jenis in JENIS_BERSKALA else 6,
        **label_skala,
        "options": pilihan,
        "required": bool(data.get("required", True)),
        "active": bool(data.get("active", True)),
        "position": urutan,
    }


# VALIDASI PEMAIN: setiap jawaban cocok dengan pertanyaan aktif; pertanyaan wajib harus dijawab.
def validate_answers(pertanyaan_aktif: dict[int, dict], daftar_jawaban: list[dict]) -> list[tuple]:
    # INPUT: jawaban per pertanyaan; setiap pertanyaan aktif hanya boleh dijawab sekali
    jawaban_per_pertanyaan = {}
    for jawaban in daftar_jawaban:
        id_pertanyaan = jawaban.get("question_id")
        if id_pertanyaan not in pertanyaan_aktif:
            raise ValueError("Pertanyaan survei tidak dikenal atau sudah tidak aktif.")
        if id_pertanyaan in jawaban_per_pertanyaan:
            raise ValueError("Setiap pertanyaan hanya boleh dijawab sekali.")
        jawaban_per_pertanyaan[id_pertanyaan] = jawaban

    # PROSES: periksa jawaban menurut jenis pertanyaan; yang opsional dan kosong dilewati
    baris_jawaban = []
    for pertanyaan in pertanyaan_aktif.values():
        jawaban = jawaban_per_pertanyaan.get(pertanyaan["id"], {})
        nilai, teks = jawaban.get("value"), jawaban.get("text")
        if pertanyaan["kind"] in JENIS_BERSKALA:
            if nilai is None:
                if pertanyaan["required"]:
                    raise ValueError(f"Jawab pertanyaan: {pertanyaan['prompt']}")
                continue
            if isinstance(nilai, bool) or not isinstance(nilai, int):
                raise ValueError("Nilai skala harus berupa angka bulat.")
            if not pertanyaan["scale_min"] <= nilai <= pertanyaan["scale_max"]:
                raise ValueError(
                    f"Nilai untuk '{pertanyaan['prompt']}' harus "
                    f"{pertanyaan['scale_min']}–{pertanyaan['scale_max']}."
                )
            baris_jawaban.append((pertanyaan, nilai, None))
        else:
            teks = _rapikan_spasi(teks or "")
            if not teks:
                if pertanyaan["required"]:
                    raise ValueError(f"Jawab pertanyaan: {pertanyaan['prompt']}")
                continue
            if pertanyaan["kind"] == "choice" and teks not in pertanyaan["options"]:
                raise ValueError(f"Pilihan untuk '{pertanyaan['prompt']}' tidak tersedia.")
            if len(teks) > PANJANG_TEKS:
                raise ValueError(f"Jawaban teks maksimal {PANJANG_TEKS} karakter.")
            baris_jawaban.append((pertanyaan, None, teks))

    # OUTPUT: tiap baris berisi (pertanyaan, nilai angka, teks)
    return baris_jawaban


class SurveyService:
    def __init__(self):
        # Registri pertandingan selesai: match_id → room, batas berlaku, dan konteks tiap pemain manusia.
        self._selesai: dict[str, dict] = {}
        self._kunci = threading.Lock()

    # Role, kubu, dan hasil setiap peserta manusia pertandingan yang sudah selesai.
    @staticmethod
    def _ambil_peserta_manusia(pertandingan) -> dict[str, dict]:
        peserta = {}
        for pemain in pertandingan.players.values():
            if not pemain.bot:
                hasil = pertandingan.result(pemain.name)
                peserta[pemain.name] = {
                    "role": pemain.role,
                    "team": hasil["team"],
                    "outcome": hasil["outcome"],
                }
        return peserta

    # Baris arsip peserta (tabel match_participants) untuk room yang pertandingannya baru selesai.
    def baris_peserta(self, room) -> list[dict]:
        return [
            {"match_id": room.match.id, "room_code": room.code, "username": nama, **data_peserta}
            for nama, data_peserta in self._ambil_peserta_manusia(room.match).items()
        ]

    # Simpan peserta ke arsip (dipanggil di thread latar oleh RoomService saat pertandingan selesai).
    # Gagal simpan (mis. migrasi V10 belum dijalankan) hanya dicatat: survei tetap jalan lewat memori.
    def catat_peserta(self, daftar_peserta: list[dict]) -> None:
        try:
            PersistenceService._run(
                lambda database: queries.record_participants(database, daftar_peserta)
            )
        except PersistenceError:
            logger.warning("Peserta pertandingan tidak tersimpan (migrasi V10?).")

    # Dipanggil saat anggota keluar dari room pertandingan yang sudah selesai: survei tetap bisa dikirim
    # sesudahnya walau room sudah dibersihkan (cadangan memori bila arsip peserta belum tersedia).
    def ingat_pertandingan(self, room):
        pertandingan = room.match
        if not pertandingan or not pertandingan.winner:
            return
        peserta = self._ambil_peserta_manusia(pertandingan)
        with self._kunci:
            self._buang_pertandingan_kedaluwarsa()
            self._selesai[pertandingan.id] = {
                "room_code": room.code,
                "pemain": peserta,
                "sampai": time.monotonic() + BERLAKU_SELESAI_DETIK,
            }

    # Keluarkan pertandingan yang masa berlakunya sudah lewat dari registri memori.
    def _buang_pertandingan_kedaluwarsa(self):
        waktu_sekarang = time.monotonic()
        id_kedaluwarsa = [
            id_pertandingan
            for id_pertandingan, data in self._selesai.items()
            if data["sampai"] <= waktu_sekarang
        ]
        for id_pertandingan in id_kedaluwarsa:
            del self._selesai[id_pertandingan]

    # KONTEKS: survei hanya untuk manusia peserta pertandingan yang sudah selesai.
    def _context(self, kode_room, username, id_pertandingan=None):
        kode_rapi = kode_room.strip().upper()
        with room_service.lock:
            room_hidup = room_service.rooms.get(kode_rapi)
            if room_hidup is None or username not in room_hidup.members:
                # Sudah keluar room (mungkin room sudah dibersihkan). Cari dulu di registri memori:
                # pertandingan selesai terbaru di room itu yang diikuti akun ini.
                with self._kunci:
                    self._buang_pertandingan_kedaluwarsa()
                    cocok = [
                        (id_selesai, data)
                        for id_selesai, data in self._selesai.items()
                        if data["room_code"] == kode_rapi
                        and username in data["pemain"]
                        and id_pertandingan in (None, id_selesai)
                    ]
                if cocok:
                    id_terbaru, data_terbaru = cocok[-1]
                    return {
                        "match_id": id_terbaru,
                        "room_code": data_terbaru["room_code"],
                        **data_terbaru["pemain"][username],
                    }
                # Lalu arsip peserta di database: berlaku juga setelah server dinyalakan ulang.
                try:
                    konteks_arsip = PersistenceService._run(
                        lambda database: queries.participant(
                            database, kode_rapi, username, id_pertandingan
                        )
                    )
                except PersistenceError:
                    konteks_arsip = None
                if konteks_arsip is not None:
                    return konteks_arsip

            # Masih anggota room, atau konteks tidak ditemukan: baca pertandingan di room.
            # Room yang hilang atau akun bukan anggota ditolak dengan pesan standar room_service.
            room = room_service.get(kode_room, username)
            pertandingan = room.match
            if not pertandingan or not pertandingan.winner:
                raise ValueError("Survei tersedia setelah pertandingan selesai.")
            if id_pertandingan is not None and pertandingan.id != id_pertandingan:
                raise ValueError("Pertandingan sudah berganti. Perbarui halaman.")
            pemain = pertandingan.players.get(username)
            if not pemain or pemain.bot:
                raise ValueError("Survei hanya untuk pemain manusia di pertandingan ini.")
            hasil = pertandingan.result(username)
            return {
                "match_id": pertandingan.id,
                "room_code": room.code,
                "role": pemain.role,
                "team": hasil["team"],
                "outcome": hasil["outcome"],
            }

    # PENGINGAT MAIN: pertandingan selesai yang surveinya belum dijawab akun ini (terbaru dulu). Kosong bila
    # tidak ada pertanyaan aktif atau arsip peserta belum tersedia (migrasi V10).
    def pending(self, username) -> list[dict]:
        def ambil_survei_tertunda(database):
            if not queries.list_questions(database):
                return []
            return queries.pending_surveys(database, username)

        try:
            survei_tertunda = PersistenceService._run(ambil_survei_tertunda)
        except PersistenceError:
            return []
        return [
            {**survei, "finished_at": survei["finished_at"].isoformat()}
            for survei in survei_tertunda
        ]

    # STATUS: pertanyaan aktif dan apakah akun sudah mengirim survei pertandingan ini.
    def status(self, kode_room, username, id_pertandingan=None):
        konteks = self._context(kode_room, username, id_pertandingan)

        def ambil_pertanyaan_dan_jumlah_jawaban(database):
            return (
                queries.list_questions(database),
                queries.count_answers(database, konteks["match_id"], username),
            )

        pertanyaan_aktif, jumlah_jawaban = PersistenceService._run(
            ambil_pertanyaan_dan_jumlah_jawaban
        )
        return {
            "match_id": konteks["match_id"],
            "submitted": jumlah_jawaban > 0,
            "questions": [public_question(pertanyaan) for pertanyaan in pertanyaan_aktif],
        }

    # KIRIM: validasi terhadap pertanyaan aktif, simpan semua jawaban dalam satu transaksi.
    def submit(self, kode_room, username, id_pertandingan, daftar_jawaban):
        konteks = self._context(kode_room, username, id_pertandingan)

        def simpan_jawaban(database):
            if queries.count_answers(database, konteks["match_id"], username):
                raise SurveyAlreadySubmitted(PESAN_SUDAH_DIKIRIM)
            pertanyaan_aktif = {
                pertanyaan["id"]: pertanyaan for pertanyaan in queries.list_questions(database)
            }
            baris_jawaban = validate_answers(pertanyaan_aktif, daftar_jawaban)
            for pertanyaan, nilai, teks in baris_jawaban:
                queries.insert_answer(
                    database,
                    {
                        **konteks,
                        "username": username,
                        "question_id": pertanyaan["id"],
                        "question_snapshot": public_question(pertanyaan),
                        "value_number": nilai,
                        "value_text": teks,
                    },
                )
            return len(baris_jawaban)

        try:
            return {"submitted": True, "answers": PersistenceService._run(simpan_jawaban)}
        except PersistenceError as error:
            # Kiriman bersamaan melanggar UNIQUE (uq_survey_answer): sama dengan "sudah dikirim".
            penyebab = error.__cause__
            if isinstance(penyebab, IntegrityError) and (
                getattr(penyebab.orig, "args", (None,))[:1] == (KODE_DUPLIKAT_MYSQL,)
            ):
                raise SurveyAlreadySubmitted(PESAN_SUDAH_DIKIRIM) from error
            raise

    # PANEL: tambah pertanyaan; kode harus unik.
    def create_question(self, data):
        pertanyaan = validate_question(data)

        def simpan_pertanyaan_baru(database):
            tersimpan = queries.list_questions(database, active_only=False)
            if any(item["code"] == pertanyaan["code"] for item in tersimpan):
                raise ValueError("Kode pertanyaan sudah dipakai.")
            return queries.insert_question(database, pertanyaan)

        return {"id": PersistenceService._run(simpan_pertanyaan_baru), **pertanyaan}

    # PANEL: ubah pertanyaan; jawaban lama tetap memakai salinan pertanyaan saat dijawab.
    def update_question(self, id_pertanyaan, data):
        pertanyaan = validate_question(data)

        def simpan_perubahan(database):
            tersimpan = queries.list_questions(database, active_only=False)
            if not any(item["id"] == id_pertanyaan for item in tersimpan):
                raise LookupError("Pertanyaan tidak ditemukan.")
            if any(
                item["code"] == pertanyaan["code"] and item["id"] != id_pertanyaan
                for item in tersimpan
            ):
                raise ValueError("Kode pertanyaan sudah dipakai.")
            queries.update_question(database, id_pertanyaan, pertanyaan)

        PersistenceService._run(simpan_perubahan)
        return {"id": id_pertanyaan, **pertanyaan}

    # PANEL: hapus permanen semua jawaban dan arsip peserta; pertanyaan tetap ada.
    def clear_responses(self):
        jumlah_terhapus = PersistenceService._run(queries.clear_responses)
        logger.warning("Panel menghapus %s jawaban survei.", jumlah_terhapus)
        return {"deleted": jumlah_terhapus}

    # PANEL: hapus pertanyaan yang belum punya jawaban. Yang masih punya ditolak, karena pemain yang
    # jawabannya habis terhapus akan diminta mengisi lagi survei pertandingan lamanya.
    def delete_question(self, id_pertanyaan):
        def hapus_bila_belum_dijawab(database):
            tersimpan = queries.list_questions(database, active_only=False)
            if not any(item["id"] == id_pertanyaan for item in tersimpan):
                raise LookupError("Pertanyaan tidak ditemukan.")
            if queries.count_question_answers(database, id_pertanyaan):
                raise ValueError("Pertanyaan ini masih punya jawaban. Bersihkan jawaban dulu.")
            queries.delete_question(database, id_pertanyaan)

        PersistenceService._run(hapus_bila_belum_dijawab)

    # PANEL: ringkasan jawaban per pertanyaan dan per metode bot.
    def summary(self):
        def ambil_pertanyaan_dan_ringkasan(database):
            return queries.list_questions(database, active_only=False), queries.summary(database)

        semua_pertanyaan, ringkasan = PersistenceService._run(ambil_pertanyaan_dan_ringkasan)
        return {"questions": semua_pertanyaan, **ringkasan}

    # PANEL: baris CSV untuk analisis penelitian.
    def export_rows(self):
        return PersistenceService._run(queries.export_rows)

    # NPC: catat metode dan persona bot pertandingan (gagal simpan tidak menghentikan game).
    def record_match_bots(self, daftar_bot):
        def simpan_daftar_bot(database):
            for bot in daftar_bot:
                queries.record_match_bot(database, bot)

        PersistenceService._run(simpan_daftar_bot)


survey_service = SurveyService()
