"""Pengelolaan akun oleh admin; arsip permainan tidak diubah ketika akun dihapus."""

from sqlalchemy.exc import IntegrityError
from app.config.settings import settings
from app.models import auth_queries

from app.config.database import jalankan_transaksi
from app.services.password_service import hash_password
from app.services.room_service import BOT_NAMES, room_service


class UserNotFound(ValueError):
    """ID akun sudah tidak tersedia."""


# Satu-satunya daftar username terlarang (NPC dan administrator): dipakai panel, pendaftaran, dan profil.
def validate_username(username):
    reserved = {name.casefold() for name in BOT_NAMES} | {"admin", "administrator", "user1"}
    reserved.update(name.strip().casefold() for name in settings.admin_usernames.split(","))
    reserved.update(name.strip().casefold() for name in settings.history_admin_usernames.split(","))
    if username.casefold() in reserved:
        raise ValueError("Username tersebut tidak tersedia.")


# Buat akun lokal; password disimpan sebagai hash, tidak pernah dikembalikan ke panel.
def create_user(username, display_name, password):
    validate_username(username)
    hash_tersimpan = hash_password(password)

    # Constraint unik menangani dua admin yang membuat username sama secara bersamaan.
    def simpan_akun_baru(database):
        try:
            id_akun_baru = auth_queries.create_account(
                database, username=username, display_name=display_name, password_hash=hash_tersimpan
            )
        except IntegrityError as error:
            raise ValueError("Username sudah digunakan.") from error
        return account_for_management(database, id_akun_baru)

    return jalankan_transaksi(simpan_akun_baru)


# Edit identitas berdasarkan ID; arsip pengirim lama dan identitas Google tetap dipertahankan.
def update_user(user_id, display_name, username=None):
    def simpan_perubahan_profil(database):
        akun = account_for_management(database, user_id)
        username_terpilih = username or akun["username"]
        # Ganti username hanya di luar ruangan; sesi lama akun ini ikut dicabut.
        if username_terpilih != akun["username"]:
            validate_username(username_terpilih)
            if room_service.current(akun["username"]):
                raise ValueError("User harus keluar dari ruangan sebelum username diganti.")
            try:
                auth_queries.update_username(database, user_id, username_terpilih)
            except IntegrityError as error:
                raise ValueError("Username sudah digunakan.") from error
            auth_queries.delete_user_sessions(database, user_id)
        auth_queries.update_display_name(database, user_id, display_name)
        return account_for_management(database, user_id)

    with room_service.lock:
        return jalankan_transaksi(simpan_perubahan_profil)


# Baca akun terkini di dalam transaksi; password hanya dipakai menentukan metode login.
def account_for_management(database, user_id):
    akun = auth_queries.account_for_management(database, user_id)
    if akun is None:
        raise UserNotFound("Akun tidak ditemukan atau sudah dihapus.")
    return dict(akun)


# Daftar akun berhalaman tidak pernah mengirim hash password, token, atau Google subject.
def list_users(after_id=0, search=""):
    def baca_satu_halaman(database):
        baris_akun = auth_queries.accounts_for_management(database, after_id, search)
        # Baris ke-51 hanya penanda masih ada halaman berikutnya; yang dikirim paling banyak 50.
        halaman = baris_akun[:50]
        return {
            "users": [dict(baris) for baris in halaman],
            "has_more": len(baris_akun) > 50,
            "next_after_id": halaman[-1]["id"] if halaman else after_id,
        }

    return jalankan_transaksi(baca_satu_halaman)


# Ganti hash dan cabut semua sesi secara atomik; akun Google tidak memiliki password aplikasi.
def reset_password(user_id, password):
    def simpan_password_baru(database):
        akun = account_for_management(database, user_id)
        if akun["login_method"] == "google":
            raise ValueError("Akun Google tidak dapat diubah password-nya di aplikasi ini.")
        auth_queries.update_password_hash(database, user_id, hash_password(password))
        auth_queries.delete_user_sessions(database, user_id)

    jalankan_transaksi(simpan_password_baru)


# Hapus hanya data autentikasi; jangan DELETE players, chat_messages, ai_analyses, atau checker_traces.
def delete_user(user_id, confirm_username):
    def hapus_data_autentikasi(database):
        akun = account_for_management(database, user_id)
        if akun["username"] != confirm_username:
            raise ValueError("Konfirmasi username tidak cocok. Perbarui daftar akun dan coba lagi.")
        if room_service.current(akun["username"]):
            raise ValueError(
                "User masih berada di ruangan. Minta user keluar dahulu sebelum menghapus akun."
            )
        auth_queries.delete_user_sessions(database, user_id)
        auth_queries.delete_identity(database, user_id)
        auth_queries.delete_account(database, user_id)

    with room_service.lock:
        jalankan_transaksi(hapus_data_autentikasi)
