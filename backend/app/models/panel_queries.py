"""SQL panel administrator: sesi, konfigurasi, arsip room, jejak checker, riwayat chat, dan kesiapan skema. Transaksi diatur pemanggil."""

from sqlalchemy import bindparam, text


# Hash token sesi panel bila masih berlaku dan cocok dengan versi kredensial; kosong bila tidak.
def valid_panel_session(database, token_hash, credential_version):
    return database.execute(
        text("""
        SELECT token_hash FROM panel_sessions WHERE token_hash=:token
        AND expires_at > UTC_TIMESTAMP() AND credential_version=:version
    """),
        {"token": token_hash, "version": credential_version},
    ).scalar()


# Simpan hash sesi panel baru. Sesi kedaluwarsa dibersihkan terpisah (delete_expired_panel_sessions).
def create_panel_session(database, token_hash, expires_at, credential_version):
    database.execute(
        text(
            "INSERT INTO panel_sessions(token_hash,expires_at,credential_version) VALUES(:token,:expires,:version)"
        ),
        {
            "token": token_hash,
            "expires": expires_at,
            "version": credential_version,
        },
    )


# Hapus semua sesi panel yang sudah kedaluwarsa. Dijalankan service di transaksi sendiri sesudah login berhasil:
# DELETE rentang lalu INSERT di satu transaksi membuat dua login bersamaan bisa saling mengunci (deadlock).
def delete_expired_panel_sessions(database):
    database.execute(text("DELETE FROM panel_sessions WHERE expires_at <= UTC_TIMESTAMP()"))


# Hapus satu sesi panel berdasarkan hash token.
def delete_panel_session(database, token_hash):
    database.execute(
        text("DELETE FROM panel_sessions WHERE token_hash=:token"), {"token": token_hash}
    )


# Isi baris konfigurasi panel (id=1 provider AI, id=2 otak NPC). for_update mengunci barisnya sampai transaksi selesai.
def panel_configuration(database, row_id, *, for_update=False):
    kunci = " FOR UPDATE" if for_update else ""
    return database.execute(
        text("SELECT config FROM panel_configuration WHERE id=:id" + kunci), {"id": row_id}
    ).scalar()


# Tulis ulang utuh satu baris konfigurasi panel.
def write_panel_configuration(database, row_id, config):
    database.execute(
        text("""
        INSERT INTO panel_configuration(id,config) VALUES(:id,:config)
        ON DUPLICATE KEY UPDATE config=:config
    """),
        {"id": row_id, "config": config},
    )


# Versi dari daftar_versi yang sudah tercatat di schema_migrations.
def recorded_migrations(database, daftar_versi):
    return set(
        database.execute(
            text("SELECT version FROM schema_migrations WHERE version IN :versi").bindparams(
                bindparam("versi", expanding=True)
            ),
            {"versi": list(daftar_versi)},
        ).scalars()
    )


# Daftar room yang pernah tercatat beserta jumlah pesannya.
# LIMIT 201 = satu baris lebih dari isi halaman, untuk tahu masih ada halaman berikutnya.
def archived_rooms(database, after_id):
    return [
        dict(baris)
        for baris in database.execute(
            text("""
        SELECT s.id,s.room_code,s.created_at,COUNT(m.id) AS message_count
        FROM game_sessions s LEFT JOIN chat_messages m ON m.game_session_id=s.id
        WHERE s.id > :after GROUP BY s.id,s.room_code,s.created_at ORDER BY s.id LIMIT 201
    """),
            {"after": after_id},
        ).mappings()
    ]


# Cursor waktu+ID membuat halaman stabil walau ada waktu yang sama. LIMIT 101 = satu baris lebih
# dari isi halaman, untuk tahu masih ada halaman berikutnya.
# Daftar tanpa `penjelasan` (bisa ~10 KB per jejak); detail diambil lewat checker_trace.
def checker_trace_page(database, room_code, before):
    return (
        database.execute(
            text("""
        SELECT JSON_REMOVE(trace,'$.penjelasan') AS trace,
        CONCAT(DATE_FORMAT(created_at,'%Y-%m-%d %H:%i:%s'), '|', id) AS trace_cursor
        FROM checker_traces WHERE room_code=:code
        AND CONCAT(DATE_FORMAT(created_at,'%Y-%m-%d %H:%i:%s'), '|', id) < :before
        ORDER BY created_at DESC,id DESC LIMIT 101
    """),
            {"code": room_code, "before": before or "9999"},
        )
        .mappings()
        .all()
    )


# Satu jejak lengkap beserta penjelasan; kosong bila tidak ada.
def checker_trace(database, trace_id, room_code):
    return database.execute(
        text("SELECT trace FROM checker_traces WHERE id=:id AND room_code=:code"),
        {"id": trace_id, "code": room_code},
    ).scalar()


# Bangun kondisi SQL berparameter yang sama untuk daftar riwayat dan ekspor CSV.
def history_conditions(room_code, start, end, sender_kind="all"):
    daftar_syarat = ["1=1"]
    parameter_sql = {}
    if sender_kind != "all":
        daftar_syarat.append("m.sender_kind=:sender_kind")
        parameter_sql["sender_kind"] = sender_kind
    if room_code:
        daftar_syarat.append("s.room_code=:room")
        parameter_sql["room"] = room_code
    if start:
        daftar_syarat.append("m.created_at >= :start")
        parameter_sql["start"] = start
    if end:
        daftar_syarat.append("m.created_at < :end")
        parameter_sql["end"] = end
    return " AND ".join(daftar_syarat), parameter_sql


# Ambil halaman pesan sesuai filter tanpa memuat seluruh arsip.
def history_page(database, syarat_sql, parameter_sql, *, terbaru_dulu, after_id, before_id):
    parameter_sql = dict(parameter_sql)
    # Halaman berikutnya: "lama" melanjutkan sesudah after_id, "baru" (terbaru dulu) sebelum before_id.
    if terbaru_dulu:
        arah = "DESC"
        if before_id:
            syarat_sql += " AND m.id<:before"
            parameter_sql["before"] = before_id
    else:
        arah = "ASC"
        syarat_sql += " AND m.id>:after"
        parameter_sql["after"] = after_id
    # LIMIT 201 = satu baris lebih dari isi halaman, untuk tahu masih ada halaman berikutnya.
    return [
        dict(baris)
        for baris in database.execute(
            text("""
        SELECT m.id,m.sender_name,m.sender_kind,m.message,m.nlu,m.created_at,m.round_number,m.phase,s.room_code
        FROM chat_messages m LEFT JOIN game_sessions s ON s.id=m.game_session_id
        WHERE """ + syarat_sql + f" ORDER BY m.id {arah} LIMIT 201"),
            parameter_sql,
        ).mappings()
    ]


# ID pesan terbesar saat ini; ekspor CSV berhenti di sini walau ada pesan baru masuk.
def max_message_id(database):
    return database.execute(text("SELECT COALESCE(MAX(id),0) FROM chat_messages")).scalar()


# Satu halaman ekspor CSV; halaman berjalan naik ("lama") atau turun ("baru") dari batas.
def history_export_page(database, syarat_sql, parameter_sql, *, terbaru_dulu, batas, maximum):
    syarat_halaman = " AND m.id<:batas" if terbaru_dulu else " AND m.id>:batas AND m.id<=:maximum"
    return database.execute(
        text(
            """
                SELECT m.id,m.sender_name,m.sender_kind,m.message,m.nlu,m.match_id,s.room_code,m.created_at
                FROM chat_messages m LEFT JOIN game_sessions s ON s.id=m.game_session_id
                WHERE """
            + syarat_sql
            + syarat_halaman
            + f" ORDER BY m.id {'DESC' if terbaru_dulu else 'ASC'} LIMIT 1000"
        ),
        {**parameter_sql, "batas": batas, "maximum": maximum},
    ).all()
