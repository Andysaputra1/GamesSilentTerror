"""Arsip MySQL tiruan untuk tes langkah bot.

Bot menyimpan chat lewat room_service (chat_bot) dan menyimpan jejak checker serta bacaan NLU lewat bot_controller.
Satu Mock dipasang di kedua tempat, jadi tes cukup memeriksa satu objek.
"""

from contextlib import contextmanager
from unittest.mock import MagicMock, patch


@contextmanager
def arsip_bot_palsu():
    kelas = MagicMock()
    with (
        patch("app.bot.bot_controller.PersistenceService", kelas),
        patch("app.services.room_service.PersistenceService", kelas),
    ):
        yield kelas
