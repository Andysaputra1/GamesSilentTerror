"""Game SQL functions. Related writes share a transaction supplied by the service."""

from sqlalchemy import text
from sqlalchemy.orm import Session


# QUERY UPSERT: pastikan ruangan ada tanpa menggandakan kode, lalu kembalikan ID ruangan.
def ensure_room(database: Session, room_code: str) -> int:
    database.execute(text("""
        INSERT INTO game_sessions (room_code, phase) VALUES (:room_code, 'day')
        ON DUPLICATE KEY UPDATE id = id
    """), {"room_code": room_code})
    return int(database.execute(text(
        "SELECT id FROM game_sessions WHERE room_code = :room_code"
    ), {"room_code": room_code}).scalar_one())


# QUERY UPSERT: pastikan pemain tercatat sekali dalam ruangan, lalu kembalikan ID pemain.
def ensure_player(database: Session, room_id: int, username: str) -> int:
    params = {"room_id": room_id, "username": username}
    database.execute(text("""
        INSERT INTO players (game_session_id, username, display_name, role, status)
        VALUES (:room_id, :username, :username, 'civilian', 'active')
        ON DUPLICATE KEY UPDATE id = id
    """), params)
    return int(database.execute(text("""
        SELECT id FROM players WHERE game_session_id = :room_id AND username = :username
    """), params).scalar_one())


# QUERY UPDATE: simpan agresivitas dan skor kecurigaan pemain; transaksi diatur service.
def update_player_scores(database: Session, player_id: int, aggressiveness: int, suspicion_score: float):
    return database.execute(text("""
        UPDATE players SET aggressiveness = :aggressiveness, suspicion_score = :score
        WHERE id = :player_id
    """), {"player_id": player_id, "aggressiveness": aggressiveness, "score": round(suspicion_score, 2)}).rowcount


# QUERY UPDATE: ubah status pemain berdasarkan ID dan kembalikan jumlah baris terpengaruh.
def update_player_status(database: Session, player_id: int, status: str):
    return database.execute(text("UPDATE players SET status = :status WHERE id = :player_id"),
                            {"player_id": player_id, "status": status}).rowcount


# QUERY INSERT: simpan pesan pemain beserta intent/skor dan kembalikan ID pesan.
def insert_message(database: Session, *, room_id: int, player_id: int, username: str,
                   message: str, intent: str | None, suspicion_score: float) -> int:
    sql = text("""
        INSERT INTO chat_messages
            (game_session_id, player_id, sender_name, message, intent, suspicion_score)
        VALUES (:room_id, :player_id, :username, :message, :intent, :score)
    """)
    return int(database.execute(sql, {
        "room_id": room_id, "player_id": player_id, "username": username,
        "message": message, "intent": intent, "score": round(suspicion_score, 2),
    }).lastrowid)


# QUERY INSERT: simpan hasil SVM, fuzzy, dan balasan LLM yang terkait dengan satu pesan.
def insert_analysis(database: Session, *, message_id: int, intent: str, aggressiveness: int,
                    suspicion_score: float, suspicion_status: str, llm_response: str):
    sql = text("""
        INSERT INTO ai_analyses
            (chat_message_id, intent, aggressiveness, suspicion_score, suspicion_status, llm_response)
        VALUES (:message_id, :intent, :aggressiveness, :score, :status, :response)
    """)
    return database.execute(sql, {
        "message_id": message_id, "intent": intent, "aggressiveness": aggressiveness,
        "score": round(suspicion_score, 2), "status": suspicion_status, "response": llm_response,
    }).lastrowid


# QUERY UPDATE: ubah fase ruangan yang ditunjuk ID; tidak menjalankan engine ronde.
def set_phase(database: Session, room_id: int, phase: str):
    return database.execute(text("UPDATE game_sessions SET phase = :phase WHERE id = :room_id"),
                            {"room_id": room_id, "phase": phase}).rowcount


def set_message_context(database, message_id, *, sender_kind, context, reply_to_id=None):
    database.execute(text("""
        UPDATE chat_messages SET sender_kind=:sender_kind, match_id=:match_id,
            round_number=:round_number, phase=:phase, reply_to_id=:reply_to_id
        WHERE id=:id
    """), dict(id=message_id, sender_kind=sender_kind, match_id=context.get("match_id"),
        round_number=context.get("round_number"), phase=context.get("phase"), reply_to_id=reply_to_id))
