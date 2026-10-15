"""Game SQL functions. Related writes share a transaction supplied by the service."""

from sqlalchemy import text
from sqlalchemy.orm import Session


# QUERY UPSERT: pastikan ruangan ada tanpa menggandakan kode, lalu kembalikan ID ruangan.
def ensure_room(database: Session, room_code: str) -> int:
    database.execute(
        text("""
        INSERT INTO game_sessions (room_code, phase) VALUES (:room_code, 'day')
        ON DUPLICATE KEY UPDATE id = id
    """),
        {"room_code": room_code},
    )
    return int(
        database.execute(
            text("SELECT id FROM game_sessions WHERE room_code = :room_code"),
            {"room_code": room_code},
        ).scalar_one()
    )


# QUERY UPSERT: pastikan pemain tercatat sekali dalam ruangan, lalu kembalikan ID pemain.
def ensure_player(database: Session, room_id: int, username: str) -> int:
    params = {"room_id": room_id, "username": username}
    database.execute(
        text("""
        INSERT INTO players (game_session_id, username, display_name, role, status)
        VALUES (:room_id, :username, :username, 'civilian', 'active')
        ON DUPLICATE KEY UPDATE id = id
    """),
        params,
    )
    return int(
        database.execute(
            text("""
        SELECT id FROM players WHERE game_session_id = :room_id AND username = :username
    """),
            params,
        ).scalar_one()
    )


# QUERY UPDATE: ubah status pemain berdasarkan ID dan kembalikan jumlah baris terpengaruh.
def update_player_status(database: Session, player_id: int, status: str):
    return database.execute(
        text("UPDATE players SET status = :status WHERE id = :player_id"),
        {"player_id": player_id, "status": status},
    ).rowcount


# QUERY INSERT: simpan pesan (pemain atau bot) dan kembalikan ID pesan. Kolom lama intent/suspicion_score
# di chat_messages dibiarkan NULL; analisis SVM/fuzzy per pesan sudah tidak dipakai.
def insert_message(
    database: Session,
    *,
    room_id: int,
    player_id: int | None,
    username: str,
    message: str,
) -> int:
    sql = text("""
        INSERT INTO chat_messages (game_session_id, player_id, sender_name, message)
        VALUES (:room_id, :player_id, :username, :message)
    """)
    return int(
        database.execute(
            sql,
            {
                "room_id": room_id,
                "player_id": player_id,
                "username": username,
                "message": message,
            },
        ).lastrowid
    )


# QUERY UPDATE: ubah fase ruangan yang ditunjuk ID; tidak menjalankan engine ronde.
def set_phase(database: Session, room_id: int, phase: str):
    return database.execute(
        text("UPDATE game_sessions SET phase = :phase WHERE id = :room_id"),
        {"room_id": room_id, "phase": phase},
    ).rowcount


# Lengkapi pesan tersimpan dengan konteks pertandingan, ronde, dan fase.
def set_message_context(database, message_id, *, sender_kind, context, reply_to_id=None):
    database.execute(
        text("""
        UPDATE chat_messages SET sender_kind=:sender_kind, match_id=:match_id,
            round_number=:round_number, phase=:phase, reply_to_id=:reply_to_id
        WHERE id=:id
    """),
        dict(
            id=message_id,
            sender_kind=sender_kind,
            match_id=context.get("match_id"),
            round_number=context.get("round_number"),
            phase=context.get("phase"),
            reply_to_id=reply_to_id,
        ),
    )
