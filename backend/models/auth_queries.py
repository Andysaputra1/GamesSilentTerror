"""Account SQL. Values are bound parameters; callers own commit/rollback."""

from datetime import datetime
from sqlalchemy import text
from sqlalchemy.orm import Session


# QUERY INSERT: akun baru saja; constraint unik mencegah menimpa akun yang sudah ada.
def create_account(database: Session, *, username: str, display_name: str, password_hash: str):
    return database.execute(
        text("""
        INSERT INTO user_accounts (username, display_name, password_hash)
        VALUES (:username, :display_name, :password_hash)
    """),
        {"username": username, "display_name": display_name, "password_hash": password_hash},
    ).lastrowid


# QUERY SELECT: cari satu akun berdasarkan username dengan parameter SQL terikat; hasil bisa kosong.
def account_by_username(database: Session, username: str):
    sql = text("""
        SELECT id, username, display_name, password_hash, is_active
        FROM user_accounts WHERE username = :username
    """)
    return database.execute(sql, {"username": username}).mappings().one_or_none()


# QUERY INSERT: simpan hash token dan waktu kedaluwarsa sesi; commit diatur oleh service pemanggil.
def create_session(database: Session, *, user_id: int, token_hash: str, expires_at: datetime):
    sql = text("""
        INSERT INTO auth_sessions (user_id, token_hash, expires_at)
        VALUES (:user_id, :token_hash, :expires_at)
    """)
    return database.execute(
        sql,
        {
            "user_id": user_id,
            "token_hash": token_hash,
            "expires_at": expires_at,
        },
    ).lastrowid


# QUERY JOIN: cari akun aktif dengan sesi yang cocok dan belum kedaluwarsa.
def account_for_token(database: Session, token_hash: str, now: datetime):
    sql = text("""
        SELECT u.id, u.username, u.display_name
        FROM user_accounts u JOIN auth_sessions s ON s.user_id = u.id
        WHERE s.token_hash = :token_hash AND s.expires_at > :now AND u.is_active = 1
    """)
    return database.execute(sql, {"token_hash": token_hash, "now": now}).mappings().one_or_none()


# QUERY DELETE: hapus sesi berdasarkan hash token untuk logout; kembalikan jumlah baris yang terhapus.
def delete_session(database: Session, token_hash: str):
    sql = text("DELETE FROM auth_sessions WHERE token_hash = :token_hash")
    return database.execute(sql, {"token_hash": token_hash}).rowcount


# Identitas tambahan dipisahkan supaya akun demo lama tetap kompatibel.
def create_identity(database, user_id, email, google_subject=None):
    database.execute(
        text("""
        INSERT INTO account_identities (user_id, email, google_subject, email_verified)
        VALUES (:id, :email, :subject, :verified)
    """),
        {
            "id": user_id,
            "email": email,
            "subject": google_subject,
            "verified": google_subject is not None,
        },
    )


# Cari akun berdasarkan identitas Google sub, bukan kesamaan email.
def account_by_google_subject(database, subject):
    return (
        database.execute(
            text("""
        SELECT u.id, u.username, u.display_name, u.is_active
        FROM user_accounts u JOIN account_identities i ON i.user_id = u.id
        WHERE i.google_subject = :subject
    """),
            {"subject": subject},
        )
        .mappings()
        .one_or_none()
    )


# Pilih pencarian username atau email sesuai identifier login.
def account_by_login(database, identifier):
    # Username lama tetap bekerja; username pendaftaran tidak mengandung @.
    if "@" not in identifier:
        return account_by_username(database, identifier)
    return (
        database.execute(
            text("""
        SELECT u.id, u.username, u.display_name, u.password_hash, u.is_active
        FROM user_accounts u JOIN account_identities i ON i.user_id = u.id
        WHERE i.email = :email
    """),
            {"email": identifier.lower()},
        )
        .mappings()
        .one_or_none()
    )
