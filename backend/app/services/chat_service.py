"""
Aturan chat manusia: dari pesan masuk sampai tersimpan, terkirim ke room, dan terbaca IndoBERT.

Alurnya
1. Cek pesan dan identitas
2. Cek boleh chat atau tidak, lalu batas laju per pemain
3. Simpan ke MySQL
4. Kirim ke room
5. IndoBERT membaca pesan

Pesan yang ditolak di tahap 1-3 menjadi ChatDitolak, dan sockets/chat.py mengirimkannya ke pengirim. Chat bot tidak lewat sini.
Query MySQL (cek token, simpan pesan, arsip jejak) berjalan di thread, jadi event loop tidak ikut menunggu database.
"""

from __future__ import annotations

import asyncio
import logging
from math import ceil
from time import perf_counter
from typing import Any

from app.bot.bot_controller import catat_nlu
from app.middleware.auth_limits import BatasPercobaan
from app.services.activity_service import activity
from app.services.ai_diagnostics import measure
from app.services.checker_service import checker_service
from app.services.persistence_service import PersistenceError, PersistenceService
from app.services.room_service import room_service
from app.sockets.server import emit_room, verifikasi_socket

logger = logging.getLogger("shadow_heist.chat")


class ChatDitolak(Exception):
    """Pesan tidak diproses. Teksnya dikirim ke pengirim sebagai system_alert."""


# Batas laju chat per pemain di satu room. IndoBERT membaca tiap chat ±9 detik di satu thread yang juga dipakai langkah
# bot semua room, jadi chat beruntun membuat langkah bot di mana pun melewati batas 25 detik. Jeda 2 detik menahan
# kiriman dobel dan tempel beruntun; 5 pesan per 20 detik masih cukup untuk membalas beberapa tuduhan sekaligus, tetapi
# rata-ratanya paling cepat satu pesan per 4 detik, jauh di bawah skrip spam.
_jeda_chat = BatasPercobaan(1, 2)
_jendela_chat = BatasPercobaan(5, 20)


# Tolak pesan bila pemain ini mengirim terlalu cepat; selain itu catat kirimannya. Kunci = (kode room, username).
def _cek_batas_chat(kunci):
    tunggu = max(_jeda_chat.sisa_tunggu(kunci), _jendela_chat.sisa_tunggu(kunci))
    if tunggu > 0:
        raise ChatDitolak(f"Chat terlalu cepat. Tunggu {ceil(tunggu)} detik lalu kirim lagi.")
    _jeda_chat.catat(kunci)
    _jendela_chat.catat(kunci)


# TAHAP 3, dijalankan di thread: simpan pesan lalu masukkan ke chat pertandingan. Aksi/skip HTTP bisa berjalan
# bersamaan, jadi lock room tetap dipegang dari cek ulang sampai commit supaya Gag atau fase baru tidak diterobos;
# query yang macet dibatasi batas waktu MySQL (config/database.py). Hasil: (id pesan, pesan untuk siaran).
# Alur: 1 room dan pertandingan masih sama -> 2 fase sama dan masih boleh chat -> 3 simpan ke MySQL
#       -> 4 masuk chat pertandingan
def _simpan_pesan(kode_room, room, pertandingan, token_fase, pengirim, pesan, konteks):
    with room_service.lock:
        room_terkini = room_service.get(kode_room, pengirim)
        if room_terkini is not room or room_terkini.match is not pertandingan:
            raise ValueError("Ruangan sudah berubah. Kirim ulang pada fase yang sesuai.")
        if pertandingan:
            pertandingan.tick()
            if token_fase != (
                pertandingan.id,
                pertandingan.round,
                pertandingan.phase,
            ) or not pertandingan.can_chat(pengirim):
                raise ValueError("Chat terkunci atau fase sudah berubah. Pesan tidak dikirim.")
        id_pesan = PersistenceService(kode_room).record_player_message(
            username=pengirim,
            message=pesan,
            context=konteks,
        )
        if not pertandingan:
            return id_pesan, {"sender": pengirim, "message": pesan}
        return id_pesan, pertandingan.add_message(pengirim, pesan)


# Jalan saat pemain mengirim chat, lewat 5 tahap di bawah. Fungsi ini tidak membalas pesan.
# Jejak = catatan tahap dan durasi satu pesan, yang tampil di panel checker.
# IndoBERT membaca pesan sekali di tahap 5; hasilnya masuk memo NLU, jadi langkah bot berikutnya tidak menghitung ulang.
async def kirim_chat_pemain(sid: str, data: dict[str, Any]) -> None:
    waktu_mulai = perf_counter()
    # Diisi di tahap 2. finally tetap membacanya walau fungsi ini berhenti di tengah jalan.
    jejak = None
    try:
        # TAHAP 1: terima event send_chat; validasi isi pesan dan identitas sesi.
        try:
            if not isinstance(data, dict) or not isinstance(data.get("message"), str):
                raise ValueError("Format pesan tidak valid.")
            pengirim = str(data.get("username", "")).strip()
            pesan = str(data.get("message", "")).strip()
            if not pesan or len(pesan) > 1000:
                raise ValueError("Pesan chat harus berisi 1–1000 karakter.")
            # Socket sudah masuk kanal ruangan saat connect; pemain dicatat di transaksi pesan (tahap 3).
            room = await verifikasi_socket(sid, pengirim)
        except (ValueError, PersistenceError) as error:
            raise ChatDitolak(str(error)) from error

        kode_room = room.code
        # TAHAP 2: engine mengotorisasi pesan sebelum disimpan atau ditampilkan.
        chat_terkunci = False
        with room_service.lock:
            pertandingan = room.match
            if pertandingan:
                # tick dulu: jam baru berdetak tiap 0,5 detik, jadi fase bisa belum terbarui.
                pertandingan.tick()
                chat_terkunci = not pertandingan.can_chat(pengirim)
                # Penanda fase ini; dibandingkan lagi di tahap 3 untuk tahu fase sudah berubah atau belum.
                token_fase = (pertandingan.id, pertandingan.round, pertandingan.phase)
            else:
                token_fase = None
        if chat_terkunci:
            activity.record(
                kode_room,
                "Match.can_chat",
                {"username": pengirim},
                status="rejected",
                result={"allowed": False},
            )
            raise ChatDitolak("Chat terkunci untukmu pada fase ini.")
        # Batas laju dihitung sesudah izin engine dan sebelum MySQL/IndoBERT: pesan yang ditolak engine tidak memakai
        # jatah, pesan yang lolos selalu memakainya.
        _cek_batas_chat((kode_room, pengirim))
        # Jejak debugging pesan (tahap dan durasi) untuk checker di panel.
        jejak = checker_service.begin(kode_room, pengirim, pesan)
        jejak["match_id"] = token_fase[0] if token_fase else None
        activity.record(
            kode_room,
            "chat.send_chat",
            {"username": pengirim, "message": pesan},
            status="received",
            call_id=jejak["id"],
        )

        konteks = (
            {"match_id": token_fase[0], "round_number": token_fase[1], "phase": token_fase[2]}
            if token_fase
            else {"phase": "lobby"}
        )
        try:
            # TAHAP 3: simpan pesan (lihat _simpan_pesan). Jejak diisi di sini, di event loop, sama dengan
            # penulis jejak lain, jadi panel Checker tidak menyalinnya saat sedang diubah.
            with measure(jejak, "persistence_ms"):
                jejak["message_id"], pesan_diterima = await asyncio.to_thread(
                    _simpan_pesan,
                    kode_room,
                    room,
                    pertandingan,
                    token_fase,
                    pengirim,
                    pesan,
                    konteks,
                )
            activity.record(
                kode_room,
                "PersistenceService.record_player_message",
                {"username": pengirim},
                result={"message_id": jejak["message_id"]},
                call_id=jejak["id"],
            )
        except ValueError as error:
            jejak.update(stage="discarded_state_changed", error=str(error))
            raise ChatDitolak(str(error)) from error
        except PersistenceError as error:
            jejak.update(stage="persistence_error", error=str(error))
            raise ChatDitolak(str(error)) from error
        # TAHAP 4: kirim pesan ke semua anggota ruangan.
        with measure(jejak, "broadcast_ms"):
            await emit_room("receive_chat", pesan_diterima, to=kode_room)
        jejak["stage"] = "delivered"
        # TAHAP 5: catat bacaan IndoBERT (intent, target) untuk checker dan riwayat chat panel.
        if pertandingan:
            with measure(jejak, "nlu_ms"):
                jejak["nlu"] = await catat_nlu(
                    pertandingan, pengirim, pesan, jejak["message_id"], room_code=kode_room
                )
    finally:
        if jejak:
            jejak["duration_ms"] = round((perf_counter() - waktu_mulai) * 1000, 2)
            try:
                # Jejak tidak diubah lagi sesudah ini, jadi aman dibaca thread arsip.
                await asyncio.to_thread(PersistenceService(jejak["room_code"]).record_trace, jejak)
            except PersistenceError:
                logger.error("Checker archive could not be saved for room %s", jejak["room_code"])
