"""Jejak debug live yang dibatasi ukurannya. Tanpa rahasia; restart menghapus riwayat ini."""

import itertools
import threading
from collections import Counter, deque
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from contextvars import ContextVar
from copy import deepcopy
from datetime import datetime, timezone
from time import perf_counter
from uuid import uuid4

# Room terbaru yang jejaknya disimpan di memori. Jejak room lama tetap ada di tabel checker_traces.
MAKS_ROOM_LIVE = 50
# Tahap NLG yang dilaporkan thread penulis. Thread LLM yang tertinggal sesudah batas waktu bisa masih melapor saat bot
# sudah mengetik atau menyimpan chat; laporan itu diabaikan supaya tahap tidak mundur.
TAHAP_TULIS = {"nlg", "llm", "aturan"}
TAHAP_SESUDAH_TULIS = {"ketik", "simpan"}
# Tahap tunggu langkah bot → kunci timings jejak (ms). Tahap lain (nlu, logika, penjelasan, nlg, llm, aturan) sudah
# diukur sendiri oleh BrainRuntime.langkah dan waktu_jejak; giliran (cek lantai bicara) dan jejak (menyusun jejak)
# hanya pembatas, lamanya masuk "lainnya" di panel.
KUNCI_TUNGGU = {"antre": "antre_otak_ms", "engine": "engine_ms", "tim": "tim_ms", "antre_nlg": "antre_nlg_ms",
                "ketik": "ketik_ms", "simpan": "simpan_ms"}  # fmt: skip
# Antrean thread di panel: entri paling banyak (entri selesai langsung dibuang) dan panjang pratinjau chat.
MAKS_ANTREAN = 300
PRATINJAU_MAKS = 40
# Label pekerjaan yang sedang dikirim ke eksekutor (room, siapa, kerja, teks), dipasang pemanggil lewat label_antrean.
LABEL_ANTREAN = ContextVar("label_antrean", default=None)


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


class LangkahBerjalan:
    """Satu langkah bot yang sedang berjalan, untuk alur live di panel Checker.

    lapor(tahap) dipanggil dari event loop, thread otak, dan thread NLG, jadi isinya dijaga kunci. Tahap pertama "antre"
    = menunggu thread otak, satu thread untuk semua room yang juga dipakai IndoBERT membaca chat manusia.
    """

    # Langkah mulai di tahap antre thread otak.
    def __init__(self, code, match_id, nama, langkah):
        self.kunci = threading.Lock()
        self.id = uuid4().hex
        self.code, self.match_id, self.nama, self.langkah = code, match_id, nama, langkah
        self.dibuat = datetime.now(timezone.utc).isoformat()
        self.mulai = self.sejak = perf_counter()
        self.tahap = "antre"
        self.lama = {}  # tahap yang sudah lewat → total ms
        self.selesai = False

    # Pindah ke tahap baru dan tambahkan lama tahap sebelumnya. Laporan sesudah langkah selesai, atau laporan NLG dari
    # thread LLM yang tertinggal, diabaikan.
    def lapor(self, tahap):
        with self.kunci:
            if self.selesai or (tahap in TAHAP_TULIS and self.tahap in TAHAP_SESUDAH_TULIS):
                return
            sekarang = perf_counter()
            self.lama[self.tahap] = self.lama.get(self.tahap, 0.0) + (sekarang - self.sejak) * 1000
            self.tahap, self.sejak = tahap, sekarang

    # Lama tiap tahap sampai sekarang (ms, dibulatkan), termasuk tahap yang sedang berjalan.
    def lama_sekarang(self):
        with self.kunci:
            lama = dict(self.lama)
            lama[self.tahap] = lama.get(self.tahap, 0.0) + (perf_counter() - self.sejak) * 1000
        return {tahap: round(ms, 1) for tahap, ms in lama.items()}

    # Lama antre dan jeda langkah ini untuk timings jejak (antre_otak_ms, antre_nlg_ms, ketik_ms, ...).
    def waktu_tunggu(self):
        lama = self.lama_sekarang()
        return {kunci: lama[tahap] for tahap, kunci in KUNCI_TUNGGU.items() if tahap in lama}

    # Keadaan untuk panel: tahap sekarang dan lamanya, total langkah, dan lama tiap tahap yang sudah lewat.
    def lihat(self):
        with self.kunci:
            sekarang = perf_counter()
            return {
                "id": self.id, "match_id": self.match_id, "nama": self.nama, "langkah": self.langkah,
                "dibuat": self.dibuat, "tahap": self.tahap,
                "tahap_ms": round((sekarang - self.sejak) * 1000, 1),
                "total_ms": round((sekarang - self.mulai) * 1000, 1),
                "lama": {tahap: round(ms, 1) for tahap, ms in self.lama.items()},
            }  # fmt: skip


class AntreanThread:
    """Pekerjaan yang sedang menunggu atau dikerjakan di thread otak dan thread penulis, untuk kotak Antrean Checker.

    Kedua eksekutor dipakai bersama semua room, jadi isinya lintas room. Diisi EksekutorTercatat dari event loop
    (masuk) dan thread kerja (mulai), dan dibaca endpoint panel, jadi dijaga kunci.
    """

    # Registri kosong; jumlah thread tiap eksekutor dicatat saat eksekutornya dibuat.
    def __init__(self):
        self.kunci = threading.Lock()
        self.nomor = itertools.count(1)
        self.tugas = {}  # nomor (urut masuk) → entri
        self.thread = {}  # nama antrean → jumlah thread

    # Pekerjaan masuk antrean; entri terlama dibuang bila registri melewati MAKS_ANTREAN. Hasil: nomor entri.
    def masuk(self, antrean, label):
        label = label or {}
        teks = label.get("teks")
        if teks and len(teks) > PRATINJAU_MAKS:
            teks = teks[:PRATINJAU_MAKS].rstrip() + "…"
        with self.kunci:
            nomor = next(self.nomor)
            self.tugas[nomor] = {
                "nomor": nomor, "antrean": antrean, "room": label.get("room"), "siapa": label.get("siapa"),
                "kerja": label.get("kerja") or "pekerjaan tanpa label", "teks": teks,
                "masuk": perf_counter(), "mulai": None,
            }  # fmt: skip
            while len(self.tugas) > MAKS_ANTREAN:
                del self.tugas[next(iter(self.tugas))]
        return nomor

    # Thread kerja mulai mengerjakan entri ini.
    def mulai(self, nomor):
        with self.kunci:
            if nomor in self.tugas:
                self.tugas[nomor]["mulai"] = perf_counter()

    # Pekerjaan selesai, gagal, atau dibatalkan: entri dibuang.
    def keluar(self, nomor):
        with self.kunci:
            self.tugas.pop(nomor, None)

    # Isi tiap antrean untuk panel: yang sedang dikerjakan lebih dulu, lalu yang menunggu sesuai urutan masuk (FIFO
    # ThreadPoolExecutor), dengan lama menunggu dan lama berjalan (ms).
    # Alur: 1 salin entri -> 2 pisahkan berjalan dan menunggu -> 3 urutan dan lama tiap entri
    def lihat(self):
        with self.kunci:
            sekarang = perf_counter()
            semua = [dict(tugas) for tugas in self.tugas.values()]
            thread = dict(self.thread)
        hasil = {nama: {"thread": jumlah, "tugas": []} for nama, jumlah in thread.items()}
        for nama in hasil:
            milik = [tugas for tugas in semua if tugas["antrean"] == nama]
            berjalan = sorted(
                (t for t in milik if t["mulai"] is not None), key=lambda t: t["mulai"]
            )
            menunggu = sorted((t for t in milik if t["mulai"] is None), key=lambda t: t["nomor"])
            for urutan, tugas in enumerate(berjalan + menunggu, start=1):
                dikerjakan = tugas["mulai"] is not None
                hasil[nama]["tugas"].append({
                    "nomor": tugas["nomor"], "urutan": urutan, "room": tugas["room"], "siapa": tugas["siapa"],
                    "kerja": tugas["kerja"], "teks": tugas["teks"],
                    "status": "dikerjakan" if dikerjakan else "menunggu",
                    "menunggu_ms": round(((tugas["mulai"] if dikerjakan else sekarang) - tugas["masuk"]) * 1000, 1),
                    "berjalan_ms": round((sekarang - tugas["mulai"]) * 1000, 1) if dikerjakan else None,
                })  # fmt: skip
        return hasil


antrean_thread = AntreanThread()


class EksekutorTercatat(ThreadPoolExecutor):
    """ThreadPoolExecutor biasa yang mencatat tiap pekerjaan ke antrean_thread: masuk, mulai, dan selesai.

    Hanya mencatat: jumlah thread, urutan antrean (FIFO), hasil, dan error pekerjaan sama dengan ThreadPoolExecutor.
    """

    # Eksekutor bernama (otak/penulis); jumlah threadnya ikut ditampilkan di panel.
    def __init__(self, antrean, max_workers, **opsi):
        super().__init__(max_workers, **opsi)
        self.antrean = antrean
        with antrean_thread.kunci:
            antrean_thread.thread[antrean] = max_workers

    # Kirim pekerjaan dengan label dari label_antrean; entrinya dibuang saat future selesai (juga saat dibatalkan).
    # Alur: 1 entri masuk antrean -> 2 bungkus fn supaya mencatat mulai -> 3 kirim ke ThreadPoolExecutor
    #       -> 4 future selesai: entri keluar
    def submit(self, fn, /, *args, **kwargs):
        nomor = antrean_thread.masuk(self.antrean, LABEL_ANTREAN.get())

        def kerjakan():
            antrean_thread.mulai(nomor)
            return fn(*args, **kwargs)

        try:
            future = super().submit(kerjakan)
        except BaseException:
            antrean_thread.keluar(nomor)
            raise
        future.add_done_callback(lambda _: antrean_thread.keluar(nomor))
        return future


# Pasang label untuk pekerjaan yang dikirim ke eksekutor di dalam blok ini (dibaca saat submit, per task asyncio).
@contextmanager
def label_antrean(room, siapa, kerja, teks=None):
    penanda = LABEL_ANTREAN.set({"room": room, "siapa": siapa, "kerja": kerja, "teks": teks})
    try:
        yield
    finally:
        LABEL_ANTREAN.reset(penanda)


class CheckerService:
    # CONSTRUCTOR: siapkan tempat jejak debugging sementara, terpisah menurut kode ruangan, daftar langkah bot yang
    # sedang berjalan (alur live Checker), dan hasil langkah terakhir tiap bot.
    def __init__(self):
        self.rooms = {}
        self.langkah_berjalan = {}  # kode room → [LangkahBerjalan]
        self.hasil_terakhir = {}  # kode room → {nama bot: hasil langkah terakhir}
        self.kunci_langkah = threading.Lock()

    # Daftarkan langkah bot yang baru mulai; hasilnya dipakai brain_turn untuk melapor tahap.
    def mulai_langkah(self, code, match_id, nama, langkah):
        berjalan = LangkahBerjalan(code, match_id, nama, langkah)
        with self.kunci_langkah:
            self.langkah_berjalan.setdefault(code, []).append(berjalan)
        return berjalan

    # Langkah selesai (juga saat error): tahap berhenti dicatat, langkah keluar dari alur live, dan hasilnya (bertindak,
    # ditolak, ditunda, diam, basi, error) disimpan untuk kolom kondisi bot. Aman dipanggil dua kali.
    # Alur: 1 tutup laporan tahap -> 2 keluar dari daftar berjalan -> 3 simpan hasil terakhir (MAKS_ROOM_LIVE room)
    def selesai_langkah(self, berjalan, hasil=None, error=None):
        with berjalan.kunci:
            berjalan.selesai = True
        with self.kunci_langkah:
            daftar = self.langkah_berjalan.get(berjalan.code, [])
            if berjalan in daftar:
                daftar.remove(berjalan)
            if not daftar:
                self.langkah_berjalan.pop(berjalan.code, None)
            if hasil is None:
                return
            per_bot = self.hasil_terakhir.pop(berjalan.code, None) or {}
            self.hasil_terakhir[berjalan.code] = per_bot  # dipindah ke paling baru
            per_bot[berjalan.nama] = {
                "match_id": berjalan.match_id, "langkah": berjalan.langkah, "hasil": hasil, "error": error,
                "selesai": datetime.now(timezone.utc).isoformat(),
            }  # fmt: skip
            while len(self.hasil_terakhir) > MAKS_ROOM_LIVE:
                del self.hasil_terakhir[next(iter(self.hasil_terakhir))]

    # Hasil langkah terakhir tiap bot di room ini (salinan).
    def hasil_langkah(self, code):
        with self.kunci_langkah:
            return deepcopy(self.hasil_terakhir.get(code, {}))

    # Alur live untuk panel: langkah bot yang sedang berjalan, chat manusia yang belum selesai diproses beserta lama
    # berjalannya sejak jejak dibuat, dan antrean thread otak/penulis (semua room). Dipanggil di event loop (endpoint
    # async), sama dengan pengisi jejak chat.
    # Alur: 1 salin keadaan tiap langkah bot -> 2 chat manusia tanpa duration_ms -> 3 lama berjalan dari created_at
    #       -> 4 antrean thread
    def proses_berjalan(self, code):
        with self.kunci_langkah:
            daftar = list(self.langkah_berjalan.get(code, []))
        sekarang = datetime.now(timezone.utc)
        chat = []
        for jejak in self.rooms.get(code, []):
            if "duration_ms" in jejak or jejak.get("stage") not in ("received", "delivered"):
                continue
            lama = sekarang - datetime.fromisoformat(jejak["created_at"])
            chat.append({**deepcopy(jejak), "berjalan_ms": round(lama.total_seconds() * 1000, 1)})
        return {
            "bot": [berjalan.lihat() for berjalan in daftar],
            "chat": chat,
            "antrean": antrean_thread.lihat(),
        }

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
