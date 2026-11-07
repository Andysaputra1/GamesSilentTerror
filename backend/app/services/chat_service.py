"""
Aturan chat manusia: dari pesan masuk sampai tersimpan, terkirim ke room, dan terbaca IndoBERT.

Alurnya
1. Cek pesan dan identitas
2. Cek boleh chat atau tidak
3. Simpan ke MySQL
4. Kirim ke room
5. IndoBERT membaca pesan

Pesan yang ditolak di tahap 1-3 menjadi ChatDitolak, dan sockets/chat.py mengirimkannya ke pengirim. Chat bot tidak lewat sini.
"""

from __future__ import annotations

import logging
from time import perf_counter
from typing import Any

from app.bot.bot_controller import catat_nlu
from app.services.activity_service import activity
from app.services.ai_diagnostics import measure
from app.services.checker_service import checker_service
from app.services.persistence_service import PersistenceError, PersistenceService
from app.services.room_service import room_service
from app.sockets.server import emit_room, verifikasi_socket

logger = logging.getLogger("shadow_heist.chat")


class ChatDitolak(Exception):
    """Pesan tidak diproses. Teksnya dikirim ke pengirim sebagai system_alert."""


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
            room = verifikasi_socket(sid, pengirim)
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
        pesan_diterima = {"sender": pengirim, "message": pesan}
        try:
            # TAHAP 3: simpan pesan. Aksi/skip HTTP bisa berjalan bersamaan, jadi periksa ulang dan
            # commit di lock yang sama supaya Gag atau fase baru tidak diterobos.
            with measure(jejak, "persistence_ms"), room_service.lock:
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
                        raise ValueError(
                            "Chat terkunci atau fase sudah berubah. Pesan tidak dikirim."
                        )
                jejak["message_id"] = PersistenceService(kode_room).record_player_message(
                    username=pengirim,
                    message=pesan,
                    context=konteks,
                )
                if pertandingan:
                    pesan_diterima = pertandingan.add_message(pengirim, pesan)
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
                PersistenceService(jejak["room_code"]).record_trace(jejak)
            except PersistenceError:
                logger.error("Checker archive could not be saved for room %s", jejak["room_code"])
