"""SQL akun. Nilai selalu lewat parameter terikat; commit/rollback diatur pemanggil."""

from datetime import datetime, timezone
from sqlalchemy import text
from sqlalchemy.orm import Session


# Ubah hanya nama tampilan akun terautentikasi; username dan sesi tetap menggunakan identitas lama.
def update_display_name(database: Session, user_id: int, display_name: str):
    database.execute(
        text("UPDATE user_accounts SET display_name = :name WHERE id = :user_id"),
        {"name": display_name, "user_id": user_id},
    )


# Username berubah berdasarkan ID akun tetap, sehingga email Google dan token tetap menunjuk akun sama.
def update_username(database: Session, user_id: int, username: str):
    database.execute(
        text("UPDATE user_accounts SET username = :username WHERE id = :user_id"),
        {"username": username, "user_id": user_id},
    )


# Ubah skin pilihan pengguna berdasarkan ID akun.
def update_skin(database: Session, user_id: int, skin_id: str):
    database.execute(
        text("UPDATE user_accounts SET skin_id = :skin_id WHERE id = :user_id"),
        {"skin_id": skin_id, "user_id": user_id},
    )


# Tambah akun baru saja; constraint unik mencegah menimpa akun yang sudah ada.
def create_account(database: Session, *, username: str, display_name: str, password_hash: str):
    return database.execute(
        text("""
        INSERT INTO user_accounts (username, display_name, password_hash)
        VALUES (:username, :display_name, :password_hash)
    """),
        {"username": username, "display_name": display_name, "password_hash": password_hash},
    ).lastrowid


# Skin dan nama tampilan beberapa akun sekaligus; akun yang tidak ditemukan tidak ikut terbaca.
def account_profiles(database: Session, daftar_username: list[str]):
    penanda_sql = ", ".join([f":u{urutan}" for urutan in range(len(daftar_username))])
    nilai_sql = {f"u{urutan}": username for urutan, username in enumerate(daftar_username)}
    perintah_sql = text(f"""
                SELECT username, skin_id, display_name FROM user_accounts
                WHERE username IN ({penanda_sql})
            """)
    return database.execute(perintah_sql, nilai_sql)


# Cari satu akun berdasarkan username; hasil bisa kosong.
def account_by_username(database: Session, username: str):
    sql = text("""
        SELECT id, username, display_name, password_hash, is_active, skin_id
        FROM user_accounts WHERE username = :username
    """)
    return database.execute(sql, {"username": username}).mappings().one_or_none()


# Simpan hash token dan waktu kedaluwarsa sesi; commit diatur oleh service pemanggil.
# Semua jalur login lewat sini, jadi sesi kedaluwarsa ikut dibersihkan di sini.
def create_session(database: Session, *, user_id: int, token_hash: str, expires_at: datetime):
    # shortcut: DELETE dan INSERT satu transaksi, jadi dua login bersamaan saat tidak ada sesi aktif bisa
    # deadlock dan satu login gagal 503. Pindahkan ke transaksi sendiri kalau itu pernah terjadi.
    database.execute(
        text("DELETE FROM auth_sessions WHERE expires_at <= :now"),
        {"now": datetime.now(timezone.utc).replace(tzinfo=None)},
    )
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


# Mencari akun pemilik token: hash cocok, sesi belum kedaluwarsa, dan akun masih aktif.
# Hasilnya satu baris atau None, karena token_hash unik.
def account_by_token(database: Session, token_hash: str, waktu_sekarang: datetime):
    sql = text("""
        SELECT u.id, u.username, u.display_name, u.skin_id
        FROM user_accounts u JOIN auth_sessions s ON s.user_id = u.id
        WHERE s.token_hash = :token_hash AND s.expires_at > :now AND u.is_active = 1
    """)
    return (
        database.execute(sql, {"token_hash": token_hash, "now": waktu_sekarang})
        .mappings()
        .one_or_none()
    )


# Hapus sesi berdasarkan hash token untuk logout; kembalikan jumlah baris yang terhapus.
def delete_session(database: Session, token_hash: str):
    sql = text("DELETE FROM auth_sessions WHERE token_hash = :token_hash")
    return database.execute(sql, {"token_hash": token_hash}).rowcount


# Cabut semua sesi satu akun.
def delete_user_sessions(database: Session, user_id: int):
    database.execute(text("DELETE FROM auth_sessions WHERE user_id = :id"), {"id": user_id})


# Satu akun untuk panel; kolom password hanya dipakai menentukan metode login.
def account_for_management(database: Session, user_id: int):
    return (
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


# Satu halaman akun untuk panel. LIMIT 51 = satu baris lebih dari isi halaman, untuk tahu masih ada halaman berikutnya.
def accounts_for_management(database: Session, after_id: int, search: str):
    return (
        database.execute(
            text("""
                SELECT u.id, u.username, u.display_name,
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


# Ganti hash password satu akun.
def update_password_hash(database: Session, user_id: int, password_hash: str):
    database.execute(
        text("UPDATE user_accounts SET password_hash = :password WHERE id = :id"),
        {"id": user_id, "password": password_hash},
    )


# Hapus identitas login satu akun; arsip permainan tidak ikut terhapus.
def delete_identity(database: Session, user_id: int):
    database.execute(text("DELETE FROM account_identities WHERE user_id = :id"), {"id": user_id})


# Hapus baris akun.
def delete_account(database: Session, user_id: int):
    database.execute(text("DELETE FROM user_accounts WHERE id = :id"), {"id": user_id})


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
def account_by_google_subject(database, google_subject):
    return (
        database.execute(
            text("""
        SELECT u.id, u.username, u.display_name, u.is_active, u.skin_id
        FROM user_accounts u JOIN account_identities i ON i.user_id = u.id
        WHERE i.google_subject = :subject
    """),
            {"subject": google_subject},
        )
        .mappings()
        .one_or_none()
    )


# Pilih pencarian username atau email sesuai isian login.
def account_by_login(database, username_atau_email):
    # Username lama tetap bekerja; username pendaftaran tidak mengandung @.
    if "@" not in username_atau_email:
        return account_by_username(database, username_atau_email)
    return (
        database.execute(
            text("""
        SELECT u.id, u.username, u.display_name, u.password_hash, u.is_active, u.skin_id
        FROM user_accounts u JOIN account_identities i ON i.user_id = u.id
        WHERE i.email = :email
    """),
            {"email": username_atau_email.lower()},
        )
        .mappings()
        .one_or_none()
    )
