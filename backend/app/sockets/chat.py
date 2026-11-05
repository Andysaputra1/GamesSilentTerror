"""
Menerima event Socket.IO dari browser pemain, lalu mengirim hasilnya ke room.

Alurnya
1. Saat berkas ini diimpor, event connect, disconnect, send_chat didaftarkan ke sio
2. connect: Cek token login dan room, catat socket ini milik siapa, masuk kanal room
3. send_chat: Cek pesan dan identitas, cek boleh chat atau tidak, simpan ke MySQL, kirim ke room, IndoBERT membaca pesan
4. disconnect: Hapus catatan socket (keanggotaan lobby dan data MySQL tetap)

Chat bot tidak lewat send_chat. Bot hanya memakai emit_room di server.py untuk mengirim pesannya ke room.
"""

from __future__ import annotations

import logging
from time import perf_counter
from typing import Any

import socketio
from app.services.room_service import room_service
from app.services.checker_service import checker_service
from app.services.activity_service import activity
from app.services.ai_diagnostics import measure
from app.module.npc_service import catat_nlu

from app.services.auth_service import SessionValidationError, auth_service
from app.module.persistence_service import PersistenceError, PersistenceService
from app.sockets.server import emit_room, sio, sockets, verifikasi_socket

logger = logging.getLogger("shadow_heist.socket")


# Jalan saat browser menyambung: mengecek siapa yang masuk dan ke room mana, sebelum sambungan boleh menerima chat.
# auth = data dari browser (token, room_code). environ tidak dipakai, tapi wajib ada karena Socket.IO mengirimnya.
async def connect(sid: str, environ: dict[str, Any], auth: Any = None) -> None:
    token = str(auth.get("token", "")) if isinstance(auth, dict) else ""
    try:
        akun = auth_service.check_user_by_token(token)
    except (SessionValidationError, PersistenceError) as error:
        raise socketio.exceptions.ConnectionRefusedError("Login diperlukan.") from error
    try:
        kode_room = str(auth.get("room_code", ""))
        room_service.get(kode_room, akun.username)
    except ValueError as error:
        logger.info("Koneksi Socket ditolak untuk %s: %s", sid, error)
        raise socketio.exceptions.ConnectionRefusedError("Ruangan tidak valid.") from error

    kode_room = kode_room.strip().upper()
    # Token ikut dicatat karena dicek ulang tiap chat, jadi pemain yang sudah logout tidak bisa terus chat lewat sambungan lama.
    sockets[sid] = {"username": akun.username, "token": token, "room": kode_room}
    await sio.enter_room(sid, kode_room)
    logger.info("Pemain terkoneksi ke Socket: %s", sid)


# Jalan saat browser terputus: hanya menghapus catatan sambungan.
# Keanggotaan room tetap, jadi pemain yang memuat ulang halaman bisa kembali ke room yang sama.
async def disconnect(sid: str) -> None:
    sockets.pop(sid, None)
    logger.info("Pemain keluar dari Socket: %s", sid)


# Jalan saat pemain mengirim chat, lewat 5 tahap di bawah. Fungsi ini tidak membalas pesan.
# Jejak = catatan tahap dan durasi satu pesan, yang tampil di panel checker.
# IndoBERT membaca pesan sekali di tahap 5; hasilnya masuk memo NLU, jadi langkah bot berikutnya tidak menghitung ulang.
async def send_chat(sid: str, data: dict[str, Any]) -> None:
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
            await sio.emit("system_alert", {"msg": str(error)}, to=sid)
            return

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
            await sio.emit("system_alert", {"msg": "Chat terkunci untukmu pada fase ini."}, to=sid)
            return
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
            await sio.emit("system_alert", {"msg": str(error)}, to=sid)
            return
        except PersistenceError as error:
            jejak.update(stage="persistence_error", error=str(error))
            await sio.emit("system_alert", {"msg": str(error)}, to=sid)
            return
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


sio.on("connect", connect)
sio.on("disconnect", disconnect)
sio.on("send_chat", send_chat)
