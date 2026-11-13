"""Menjalankan event socket tanpa server asli: sio tiruan, room tiruan, dan catatan sambungan sendiri."""

from contextlib import contextmanager, nullcontext
from unittest.mock import AsyncMock, Mock, patch

from app.sockets import server


# Token palsu berisi username, jadi tes cukup menulis username sebagai tokennya.
def akun_dari_token(token):
    return Mock(username=token)


# Tiruan dipasang pada satu sio yang dipakai bersama chat.py dan server.py.
# cek_token=None memakai check_user_by_token asli, untuk tes yang menggagalkan query di bawahnya.
@contextmanager
def socket_palsu(rooms, sambungan, cek_token=akun_dari_token):
    tiruan = Mock(emit=AsyncMock(), enter_room=AsyncMock(), leave_room=AsyncMock())
    with (
        patch.multiple(
            server.sio,
            emit=tiruan.emit,
            enter_room=tiruan.enter_room,
            leave_room=tiruan.leave_room,
        ),
        patch.dict(server.sockets, sambungan, clear=True),
        patch("app.sockets.server.room_service", rooms),
        patch("app.sockets.chat.room_service", rooms),
        patch("app.services.chat_service.room_service", rooms),
        (
            patch.object(server.auth_service, "check_user_by_token", side_effect=cek_token)
            if cek_token
            else nullcontext()
        ),
    ):
        yield tiruan
