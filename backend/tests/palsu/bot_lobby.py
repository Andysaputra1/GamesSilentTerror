"""Bantuan tes lobby: mengisi kursi kosong dengan bot lewat jalur yang sama dengan tombol "+ Tambah bot"."""

from app.services.room_service import BOT_MAKS


# Host menekan Tambah bot satu per satu sampai kursi penuh atau BOT_MAKS. Untuk room yang kursi kosongnya paling
# banyak BOT_MAKS, jumlah bot sama dengan saklar bot lama (kapasitas 6 dengan satu manusia: 5 bot).
# Alur: 1 hitung bot yang masih muat -> 2 tekan tambah sebanyak itu -> 3 kembalikan room
def isi_kursi_bot(rooms, code, host):
    room = rooms.get(code, host)
    muat = min(room.capacity - len(room.members), BOT_MAKS) - len(rooms.bot_names(room))
    for _ in range(muat):
        rooms.ubah_bot(code, host, "tambah")
    return room
