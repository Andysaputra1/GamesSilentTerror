"""Pengelolaan akun oleh admin; arsip permainan tidak diubah ketika akun dihapus."""

from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from config.settings import settings
from models import auth_queries

from services.auth_service import auth_service
from services.password_service import hash_password
from services.room_service import room_service


class UserNotFound(ValueError):
    """ID akun sudah tidak tersedia."""


# Admin membuat akun password biasa tanpa menerbitkan sesi login atas nama pemain.
def create_user(username, display_name, password):
    reserved = {"nox", "echo", "veil", "raven", "ash", "dusk", "admin", "administrator", "user1"}
    reserved.update(name.strip().casefold() for name in settings.admin_usernames.split(","))
    reserved.update(name.strip().casefold() for name in settings.history_admin_usernames.split(","))
    if username.casefold() in reserved:
        raise ValueError("Username tersebut tidak tersedia.")
    encoded = hash_password(password)

    # Constraint unik menangani dua admin yang membuat username sama secara bersamaan.
    def operation(database):
        try:
            user_id = auth_queries.create_account(
                database, username=username, display_name=display_name, password_hash=encoded
            )
        except IntegrityError as error:
            raise ValueError("Username sudah digunakan.") from error
        return account_for_management(database, user_id)

    return auth_service._transaction(operation)


# Baca akun terkini di dalam transaksi; password hanya dipakai menentukan metode login.
def account_for_management(database, user_id):
    row = (
        database.execute(
            text("""
            SELECT u.id, u.username, u.display_name,
                   CASE WHEN i.google_subject IS NOT NULL OR u.password_hash = 'google_only'
                        THEN 'google' ELSE 'password' END AS login_method
            FROM user_accounts u LEFT JOIN account_identities i ON i.user_id = u.id
            WHERE u.id = :user_id
        """),
            {"user_id": user_id},
        )
        .mappings()
        .one_or_none()
    )
    if row is None:
        raise UserNotFound("Akun tidak ditemukan atau sudah dihapus.")
    return dict(row)


# Daftar akun berhalaman tidak pernah mengirim hash password, token, atau Google subject.
def list_users(after_id=0, search=""):
    def read(database):
        rows = (
            database.execute(
                text("""
                SELECT u.id, u.username, u.display_name, u.is_active,
                       CASE WHEN i.google_subject IS NOT NULL OR u.password_hash = 'google_only'
                            THEN 'google' ELSE 'password' END AS login_method
                FROM user_accounts u LEFT JOIN account_identities i ON i.user_id = u.id
                WHERE u.id > :after_id AND (u.username LIKE :search OR u.display_name LIKE :search)
                ORDER BY u.id LIMIT 51
            """),
                {"after_id": after_id, "search": "%" + search + "%"},
            )
            .mappings()
            .all()
        )
        return {
            "users": [dict(row) for row in rows[:50]],
            "has_more": len(rows) > 50,
            "next_after_id": rows[min(len(rows), 50) - 1]["id"] if rows else after_id,
        }

    return auth_service._transaction(read)


# Ganti hash dan cabut semua sesi secara atomik; akun Google tidak memiliki password aplikasi.
def reset_password(user_id, password):
    def operation(database):
        account = account_for_management(database, user_id)
        if account["login_method"] == "google":
            raise ValueError("Akun Google tidak dapat diubah password-nya di aplikasi ini.")
        database.execute(
            text("UPDATE user_accounts SET password_hash = :password WHERE id = :id"),
            {"id": user_id, "password": hash_password(password)},
        )
        database.execute(text("DELETE FROM auth_sessions WHERE user_id = :id"), {"id": user_id})

    auth_service._transaction(operation)


# Hapus hanya data autentikasi; jangan DELETE players, chat_messages, ai_analyses, atau checker_traces.
def delete_user(user_id, confirm_username):
    def operation(database):
        account = account_for_management(database, user_id)
        if account["username"] != confirm_username:
            raise ValueError("Konfirmasi username tidak cocok. Perbarui daftar akun dan coba lagi.")
        if room_service.current(account["username"]):
            raise ValueError(
                "User masih berada di ruangan. Minta user keluar dahulu sebelum menghapus akun."
            )
        database.execute(text("DELETE FROM auth_sessions WHERE user_id = :id"), {"id": user_id})
        database.execute(
            text("DELETE FROM account_identities WHERE user_id = :id"), {"id": user_id}
        )
        database.execute(text("DELETE FROM user_accounts WHERE id = :id"), {"id": user_id})

    with room_service.lock:
        auth_service._transaction(operation)
