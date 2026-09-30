"""Bounded, live debug traces. No secrets; restart clears this diagnostic history."""

from collections import Counter, deque
from copy import deepcopy
from datetime import datetime, timezone
from uuid import uuid4


class CheckerService:
    # CONSTRUCTOR: siapkan tempat jejak debugging sementara, terpisah menurut kode ruangan.
    def __init__(self):
        self.rooms = {}

    # METHOD TRACE: buat jejak pesan baru dan batasi riwayat menjadi 100 pesan terbaru per ruangan.
    def begin(self, code, sender, message):
        trace = {
            "id": uuid4().hex,
            "created_at": datetime.now(timezone.utc).isoformat(),
            "room_code": code,
            "sender": sender,
            "message": message,
            "stage": "received",
            "intent": None,
            "aggressiveness_before": None,
            "intent_weight": None,
            "aggressiveness": None,
            "silence_percentage": 20,
            "suspicion_score": None,
            "suspicion_status": None,
            "provider": None,
            "model": None,
            "prompt": None,
            "output": None,
            "llm_error": None,
            "error": None,
            "message_id": None,
        }
        self.rooms.setdefault(code, deque(maxlen=100)).appendleft(trace)
        return trace

    # METHOD READ-ONLY: kembalikan salinan mendalam riwayat supaya pemanggil tidak mengubah trace internal.
    # `penjelasan` (role dan penalaran bot) hanya disertakan untuk panel admin yang memintanya; tanpa itu,
    # penjelasan yang besar tidak ikut disalin (daftar jejak di-refresh tiap 5 detik).
    def list(self, code, penjelasan=False):
        traces = list(self.rooms.get(code, []))
        if penjelasan:
            return deepcopy(traces)
        return [deepcopy({k: v for k, v in t.items() if k != "penjelasan"}) for t in traces]

    # Satu jejak lengkap (dengan penjelasan) dari buffer live; None jika sudah tidak ada.
    def cari(self, code, trace_id):
        trace = next((t for t in self.rooms.get(code, []) if t.get("id") == trace_id), None)
        return deepcopy(trace) if trace is not None else None

    # RINGKASAN ROOM (panel): status pertandingan, komposisi role, dan identitas setiap bot.
    # Bot diambil dari pertandingan live, lalu dari penjelasan di jejak, lalu tabel match_bots (arsip).
    def ringkasan_room(self, code, traces=()):
        from services.npc_brain.runtime import brain_runtime
        from services.room_service import room_service

        ringkasan = {"kode": code, "status": "arsip", "match_id": None, "fase": None, "ronde": None,
                     "pemenang": None, "komposisi": None, "manusia": None, "bot": [], "sumber_bot": None}  # fmt: skip
        with room_service.lock:
            room = room_service.rooms.get(code)
            match = room.match if room else None
            if room is not None and match is None:
                ringkasan["status"] = "lobby"
            if match is not None:
                ringkasan.update(
                    status="selesai" if match.winner else "live", match_id=match.id,
                    fase=match.phase, ronde=match.round, pemenang=match.winner,
                    komposisi=dict(Counter(p.role for p in match.players.values())),
                    manusia=sum(not p.bot for p in match.players.values()),
                )  # fmt: skip
                for p in sorted(match.players.values(), key=lambda p: p.name):
                    if not p.bot:
                        continue
                    otak = brain_runtime.otak_bot(match.id, p.name)
                    ringkasan["bot"].append({
                        "nama": p.name, "role": p.role, "status": _status_pemain(p),
                        "metode": getattr(otak, "metode", None), "persona": getattr(otak, "persona", None),
                        "langkah": getattr(otak, "langkah", 0),
                    })  # fmt: skip
                ringkasan["sumber_bot"] = "live"
        if not ringkasan["bot"]:
            ringkasan["bot"] = _bot_dari_jejak(traces)
            ringkasan["sumber_bot"] = "jejak" if ringkasan["bot"] else None
        if not ringkasan["bot"]:
            ringkasan["bot"] = _bot_arsip(code)
            ringkasan["sumber_bot"] = "match_bots" if ringkasan["bot"] else None
        return ringkasan


def _status_pemain(player):
    if not player.alive:
        return "dieksekusi"
    if player.hostage:
        return "disandera"
    return "dibungkam" if player.gagged else "aktif"


# Identitas bot dari jejak terbaru (ringkasan penjelasan, atau provider "otak:<metode>" pada jejak lama).
def _bot_dari_jejak(traces):
    bot = {}
    for trace in traces:  # terbaru lebih dulu
        identitas = (trace.get("ringkas") or trace.get("penjelasan") or {}).get("bot") or {}
        provider, model = trace.get("provider") or "", trace.get("model") or ""
        nama = identitas.get("nama") or (
            trace.get("sender") if provider.startswith("otak:") else None
        )
        if not nama or nama in bot:
            continue
        bot[nama] = {
            "nama": nama, "role": identitas.get("role"), "status": None,
            "metode": identitas.get("metode") or provider.removeprefix("otak:") or None,
            "persona": identitas.get("persona") or model.removeprefix("persona:") or None,
            "langkah": identitas.get("langkah"),
        }  # fmt: skip
    return sorted(bot.values(), key=lambda b: b["nama"])


# Arsip metode/persona/role bot pertandingan terakhir room (migrasi V7); gagal → daftar kosong.
def _bot_arsip(code):
    from sqlalchemy import text

    from services.persistence_service import PersistenceError, PersistenceService

    def baca(db):
        return db.execute(
            text("""
            SELECT match_id, bot_name, method, persona, role FROM match_bots
            WHERE room_code=:code ORDER BY created_at DESC, bot_name LIMIT 20
        """),
            {"code": code},
        ).mappings().all()  # fmt: skip

    try:
        rows = PersistenceService._run(baca)
    except PersistenceError:
        return []
    terakhir = rows[0]["match_id"] if rows else None
    return [
        {"nama": r["bot_name"], "role": r["role"], "status": None, "metode": r["method"],
         "persona": r["persona"], "langkah": None}
        for r in sorted(rows, key=lambda r: r["bot_name"]) if r["match_id"] == terakhir
    ]  # fmt: skip


checker_service = CheckerService()
