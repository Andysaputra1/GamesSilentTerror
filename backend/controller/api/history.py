"""Read-only durable transcript access, restricted to explicitly configured accounts."""
from pathlib import Path
from fastapi import APIRouter, Depends, HTTPException, Query, Response
from fastapi.responses import FileResponse
from sqlalchemy import text
from config.settings import settings
from controller.middleware.auth import require_authenticated_user
from services.persistence_service import PersistenceService, PersistenceError

router = APIRouter(tags=["chat-history"])
ASSETS = Path(__file__).resolve().parents[2] / "public" / "history"


def require_history_admin(response: Response, user=Depends(require_authenticated_user)):
    response.headers["Cache-Control"] = "no-store"
    allowed = {name.strip() for name in settings.history_admin_usernames.split(",") if name.strip()}
    if user.username not in allowed:
        raise HTTPException(403, "Akun ini tidak memiliki akses riwayat percakapan.")
    return user


@router.get("/history", include_in_schema=False)
def panel_redirect():
    from fastapi.responses import RedirectResponse
    return RedirectResponse("/panel", status_code=307)


@router.get("/history/app.js", include_in_schema=False)
def script():
    return FileResponse(ASSETS / "app.js", headers={"Cache-Control": "no-store"})


@router.get("/api/history/messages")
def messages(room_code: str | None = Query(None, max_length=36),
             match_id: str | None = Query(None, max_length=36),
             after_id: int = Query(0, ge=0), limit: int = Query(100, ge=1, le=500),
             user=Depends(require_history_admin)):
    conditions = ["m.id > :after_id"]
    params = dict(after_id=after_id, limit=limit + 1)
    if room_code:
        conditions.append("s.room_code = :room_code")
        params["room_code"] = room_code
    if match_id:
        conditions.append("m.match_id = :match_id")
        params["match_id"] = match_id
    def read(db):
        rows = db.execute(text("""
            SELECT m.id, s.room_code, m.match_id, m.round_number, m.phase,
                   m.sender_kind, m.sender_name, m.message, m.reply_to_id, m.created_at,
                   m.intent, m.suspicion_score
            FROM chat_messages m LEFT JOIN game_sessions s ON s.id=m.game_session_id
            WHERE """ + " AND ".join(conditions) + " ORDER BY m.id ASC LIMIT :limit"), params)
        return [dict(row) for row in rows.mappings()]
    try:
        rows = PersistenceService._run(read)
    except PersistenceError as error:
        raise HTTPException(503, "Riwayat belum bisa dibaca. Periksa database dan migrasi V5.") from error
    return {"messages": rows[:limit], "has_more": len(rows) > limit,
            "next_after_id": rows[min(len(rows), limit)-1]["id"] if rows else after_id}
