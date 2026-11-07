"""Jejak debug live yang dibatasi ukurannya. Tanpa rahasia; restart menghapus riwayat ini."""

from collections import Counter, deque
from copy import deepcopy
from datetime import datetime, timezone
from uuid import uuid4

# Room terbaru yang jejaknya disimpan di memori. Jejak room lama tetap ada di tabel checker_traces.
MAKS_ROOM_LIVE = 50


# Jejak kosong tanpa didaftarkan ke room (simulasi panel memakai bentuk yang sama).
def jejak_baru(code, sender, message):
    return {
        "id": uuid4().hex,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "room_code": code,
        "sender": sender,
        "message": message,
        "stage": "received",
        "intent": None,
        "provider": None,
        "model": None,
        "output": None,
        "error": None,
        "message_id": None,
    }


class CheckerService:
    # CONSTRUCTOR: siapkan tempat jejak debugging sementara, terpisah menurut kode ruangan.
    def __init__(self):
        self.rooms = {}

    # METHOD TRACE: buat jejak pesan baru; 100 jejak terbaru per ruangan, MAKS_ROOM_LIVE ruangan terbaru.
    def begin(self, code, sender, message):
        jejak = jejak_baru(code, sender, message)
        jejak_room = self.rooms.pop(code, None) or deque(maxlen=100)
        self.rooms[code] = jejak_room  # dipindah ke paling baru (dict menjaga urutan masuk)
        jejak_room.appendleft(jejak)
        while len(self.rooms) > MAKS_ROOM_LIVE:
            del self.rooms[next(iter(self.rooms))]
        return jejak

    # METHOD READ-ONLY: kembalikan salinan mendalam riwayat supaya pemanggil tidak mengubah trace internal.
    # `penjelasan` (role dan penalaran bot) hanya disertakan untuk panel admin yang memintanya; tanpa itu,
    # penjelasan yang besar tidak ikut disalin (daftar jejak di-refresh tiap 5 detik).
    def list(self, code, penjelasan=False):
        jejak_room = list(self.rooms.get(code, []))
        if penjelasan:
            return deepcopy(jejak_room)
        return [
            deepcopy({kunci: isi for kunci, isi in jejak.items() if kunci != "penjelasan"})
            for jejak in jejak_room
        ]

    # Satu jejak lengkap (dengan penjelasan) dari buffer live; None jika sudah tidak ada.
    def cari(self, code, trace_id):
        ditemukan = next(
            (jejak for jejak in self.rooms.get(code, []) if jejak.get("id") == trace_id), None
        )
        return deepcopy(ditemukan) if ditemukan is not None else None

    # RINGKASAN ROOM (panel): status pertandingan, komposisi role, dan identitas setiap bot.
    # Bot diambil dari pertandingan live, lalu dari penjelasan di jejak, lalu tabel match_bots (arsip).
    def ringkasan_room(self, code, traces=()):
        from app.bot.bot_controller import brain_runtime
        from app.services.room_service import room_service

        ringkasan = {"kode": code, "status": "arsip", "fase": None, "ronde": None,
                     "pemenang": None, "komposisi": None, "manusia": None, "bot": [], "sumber_bot": None}  # fmt: skip

        # Sumber 1: pertandingan live.
        with room_service.lock:
            room = room_service.rooms.get(code)
            pertandingan = room.match if room else None
            if room is not None and pertandingan is None:
                ringkasan["status"] = "lobby"
            if pertandingan is not None:
                semua_peserta = pertandingan.players.values()
                ringkasan.update(
                    status="selesai" if pertandingan.winner else "live",
                    fase=pertandingan.phase, ronde=pertandingan.round, pemenang=pertandingan.winner,
                    komposisi=dict(Counter(peserta.role for peserta in semua_peserta)),
                    manusia=sum(not peserta.bot for peserta in semua_peserta),
                )  # fmt: skip
                for peserta in sorted(semua_peserta, key=lambda peserta: peserta.name):
                    if not peserta.bot:
                        continue
                    otak = brain_runtime.otak_bot(pertandingan.id, peserta.name)
                    if not peserta.alive:
                        status = "dieksekusi"
                    elif peserta.hostage:
                        status = "disandera"
                    else:
                        status = "dibungkam" if peserta.gagged else "aktif"
                    ringkasan["bot"].append({
                        "nama": peserta.name, "role": peserta.role, "status": status,
                        "metode": getattr(otak, "metode", None), "persona": getattr(otak, "persona", None),
                    })  # fmt: skip
                ringkasan["sumber_bot"] = "live"

        # Sumber 2: jejak terbaru (ringkasan penjelasan, atau provider "otak:<metode>" pada jejak lama).
        if not ringkasan["bot"]:
            bot_per_nama = {}
            for jejak in traces:  # terbaru lebih dulu
                identitas = (jejak.get("ringkas") or jejak.get("penjelasan") or {}).get("bot") or {}
                provider, model = jejak.get("provider") or "", jejak.get("model") or ""
                nama = identitas.get("nama") or (
                    jejak.get("sender") if provider.startswith("otak:") else None
                )
                if not nama or nama in bot_per_nama:
                    continue
                bot_per_nama[nama] = {
                    "nama": nama, "role": identitas.get("role"), "status": None,
                    "metode": identitas.get("metode") or provider.removeprefix("otak:") or None,
                    "persona": identitas.get("persona") or model.removeprefix("persona:") or None,
                }  # fmt: skip
            ringkasan["bot"] = sorted(bot_per_nama.values(), key=lambda bot: bot["nama"])
            ringkasan["sumber_bot"] = "jejak" if ringkasan["bot"] else None

        # Sumber 3: arsip tabel match_bots.
        if not ringkasan["bot"]:
            ringkasan["bot"] = _bot_arsip(code)
            ringkasan["sumber_bot"] = "match_bots" if ringkasan["bot"] else None
        return ringkasan


# Arsip metode/persona/role bot pertandingan terakhir room (migrasi V7); gagal → daftar kosong.
def _bot_arsip(code):
    from app.config.database import PersistenceError, jalankan_transaksi
    from app.models import survey_queries

    try:
        daftar_baris = jalankan_transaksi(
            lambda database: survey_queries.latest_match_bots(database, code)
        )
    except PersistenceError:
        return []
    id_pertandingan_terakhir = daftar_baris[0]["match_id"] if daftar_baris else None
    return [
        {"nama": baris["bot_name"], "role": baris["role"], "status": None, "metode": baris["method"],
         "persona": baris["persona"]}
        for baris in sorted(daftar_baris, key=lambda baris: baris["bot_name"])
        if baris["match_id"] == id_pertandingan_terakhir
    ]  # fmt: skip


checker_service = CheckerService()
