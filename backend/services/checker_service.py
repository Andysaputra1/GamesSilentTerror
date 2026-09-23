"""Bounded, live debug traces. No secrets; restart clears this diagnostic history."""

from collections import deque
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
    def list(self, code):
        return deepcopy(list(self.rooms.get(code, [])))


checker_service = CheckerService()
