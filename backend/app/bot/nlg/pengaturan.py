"""[PANEL] Pengaturan rantai penulis dari panel: jalur, urutan, model, dan status cek tiap jalur.

PenulisNPC menyimpan konfigurasi (KonfigurasiNPC), membangun rantai dengan buat_rantai, mengecek jalur di latar, dan
memberi ringkasan untuk panel. JamPenulis membungkus penulis untuk mencatat lama LLM per kalimat.
"""

import logging
import re
import threading
import time
from dataclasses import dataclass, field
from time import monotonic, perf_counter
from urllib.parse import urlsplit

from app.bot.nlg.penulis import BATAS_CEK_DETIK, BATAS_WAKTU_DETIK, JALUR_PENULIS, buat_rantai
from app.config.settings import POLA_MODEL_OPENROUTER, settings
from app.services.ai_config_service import ai_runtime

logger = logging.getLogger("shadow_heist.npc_brain")



# Nama model di link LLM (Ollama/OpenAI), mis. qwen3:4b-instruct atau qwen3:14b.
POLA_MODEL_TAUTAN = re.compile(
    r"[A-Za-z0-9][A-Za-z0-9._-]*(?:/[A-Za-z0-9._-]+)*(?::[A-Za-z0-9._-]+)?"
)
PENULIS_VALID = {"otomatis", "templat"}


@dataclass
class KonfigurasiNPC:
    penulis: str = "otomatis"
    # Prioritas rantai penulis; jalur yang tidak tercantum dinonaktifkan.
    urutan_penulis: list = field(default_factory=lambda: list(JALUR_PENULIS))
    model_openrouter: str = ""  # kosong = model OpenRouter dari Konfigurasi AI/.env (qwen/qwen3-14b)
    model_tautan: str = ""  # kosong = model Ollama dari Konfigurasi AI/.env (OLLAMA_MODEL)


# Pengganti lapor(tahap) saat tidak ada pemantau. Pemantau tahap: simulasi panel dan alur live Checker.
def tanpa_lapor(tahap):
    pass


class JamPenulis:
    """Penulis yang mencatat total lama panggilan LLM satu kalimat (satu objek per kalimat)."""

    # Bungkus satu penulis untuk satu kalimat; detik = total lama panggilan LLM.
    def __init__(self, penulis, lapor=tanpa_lapor):
        self.penulis, self.detik, self.lapor = penulis, 0.0, lapor

    # Atribut lain (aktif, jalur, terakhir) dibaca langsung dari penulis yang dibungkus.
    def __getattr__(self, nama):
        return getattr(self.penulis, nama)

    # Panggil LLM sambil mencatat lamanya; pemantau (simulasi panel, alur live Checker) diberi tahu tahap llm lalu
    # aturan.
    def tulis(self, sistem, pesan):
        mulai = perf_counter()
        self.lapor("llm")
        try:
            return self.penulis.tulis(sistem, pesan)
        finally:
            self.detik += perf_counter() - mulai
            self.lapor("aturan")  # kalimat diperiksa aturan, lalu ulang LLM atau templat bila ditolak


class PenulisNPC:
    """Rantai penulis kalimat sesuai pengaturan panel: urutan jalur, model, cek tiap jalur, dan status untuk panel.

    Kunci (lock) dipinjam dari BrainRuntime supaya status otak dan status rantai selalu terbaca bersamaan.
    """

    # Konfigurasi awal dari .env; rantai baru dibangun saat otak dimuat (segarkan).
    def __init__(self, lock):
        self.lock = lock
        self.konfigurasi = KonfigurasiNPC(
            settings.npc_writer,
            settings.npc_writer_order.split(",") if settings.npc_writer_order else [],
            settings.npc_openrouter_model,
        )
        self.rantai = None
        self.keterangan = {}  # jalur → alasan tidak masuk rantai (mis. key belum diisi)
        self._kunci_cek = threading.Lock()  # satu cek rantai penulis pada satu waktu
        # Cek yang sedang berjalan atau antre; selama > 0 panel menampilkan "Sedang dicek…".
        self._cek_tertunda = 0
        # Host link LLM dan asalnya (panel/.env) untuk ditampilkan di panel.
        self.alamat_tautan = None
        # Model yang ada di link LLM (hasil cek terakhir), untuk pilihan model di panel.
        self.model_tautan_tersedia = []

    # Bagian penulis di ringkasan otak untuk panel dan layar persiapan, termasuk status tiap jalur tanpa nilai key.
    # Alur: 1 jalur yang menulis kalimat berikutnya -> 2 status tiap jalur: yang aktif sesuai prioritas, lalu yang
    #       dinonaktifkan -> 3 ringkasan konfigurasi dan rantai
    def ringkasan(self):
        with self.lock:
            penulis = self.rantai if self.konfigurasi.penulis != "templat" else None
            # Jalur yang menulis kalimat berikutnya: yang pertama siap (tidak ditolak dan tidak istirahat).
            berikut = penulis.terdepan() if penulis else None
            anggota = {p.jalur: p for p in (penulis.daftar if penulis else [])}
            urutan = self.konfigurasi.urutan_penulis
            rantai_penulis = []
            for jalur in urutan + [j for j in JALUR_PENULIS if j not in urutan]:
                p = anggota.get(jalur)
                if self.konfigurasi.penulis == "templat" or jalur not in urutan:
                    keadaan, status = "nonaktif", "mode templat" if jalur in urutan else "dinonaktifkan"
                elif p is None:
                    keadaan, status = "tidak_ada", self.keterangan.get(jalur, "belum dimuat")
                elif not p.aktif:
                    keadaan, status = "ditolak", p.status
                elif not p.siap():
                    keadaan, status = "istirahat", p.status
                else:
                    keadaan, status = ("dipakai" if p is berikut else "siap"), p.status
                # Penghitung panggilan/token berlaku sejak rantai terakhir dibangun (token cek ikut dihitung).
                rantai_penulis.append({
                    "jalur": jalur, "keadaan": keadaan, "status": status,
                    "model": p.model if p else None, "panggilan": p.panggilan if p else 0,
                    "token_masuk": p.token_masuk if p else 0, "token_keluar": p.token_keluar if p else 0,
                    "alamat": self.alamat_tautan if jalur == "tautan" else None,
                    "hasil_cek": getattr(p, "hasil_cek", None),
                })  # fmt: skip
            return {
                "sedang_cek_penulis": self._cek_tertunda > 0,
                "penulis_diminta": self.konfigurasi.penulis,
                "penulis_aktif": berikut is not None,
                "penulis": berikut.jalur if berikut else "templat",
                "model_penulis": berikut.model if berikut else None,
                "urutan_penulis": list(self.konfigurasi.urutan_penulis),
                "model_openrouter": self.konfigurasi.model_openrouter,
                "model_tautan": self.konfigurasi.model_tautan,
                "model_tautan_bawaan": ai_runtime.current().ollama_model,
                "model_tautan_tersedia": list(self.model_tautan_tersedia),
                "rantai_penulis": rantai_penulis,
            }

    # Hit provider langsung; link juga diuji menghasilkan jawaban setelah penemuan model. Hanya status yang dicatat,
    # tanpa key. Penghitung cek dinaikkan pemanggil (segarkan).
    # Alur: 1 tiap jalur: cek -> 2 link: minta satu jawaban uji -> 3 catat hasil cek -> 4 link: daftar modelnya
    #       (Ollama /api/tags, lalu OpenAI /v1/models) -> 5 selesai: turunkan penghitung cek
    def _cek(self, penulis):
        try:
            with self._kunci_cek:
                hasil = []
                for p in penulis.daftar:
                    mulai = monotonic()
                    p.hasil_cek = {"keadaan": "memeriksa"}
                    status = p.cek()
                    if status == "ok" and p.jalur == "tautan":
                        teks, status = p.tulis("Jawab singkat.", "Balas: ok")
                        if status == "ok" and not (teks or "").strip():
                            status = p.gagal("jawaban pengujian kosong")[1]
                    p.hasil_cek = {
                        "keadaan": "berhasil" if status == "ok" else "gagal",
                        "waktu": time.time(),
                        "durasi_ms": round((monotonic() - mulai) * 1000),
                        "detail": status,
                    }
                    hasil.append((p.jalur, status))
                    if p.jalur == "tautan" and status != "ok":
                        self.model_tautan_tersedia = []
                    elif p.jalur == "tautan":
                        # Daftar model di link memakai klien penulis yang sama (token tunnel ikut); kosong bila link
                        # tidak menjawab.
                        data, _ = p._minta("GET", f"{p.url}/api/tags", batas=BATAS_CEK_DETIK)
                        if isinstance(data, dict) and isinstance(data.get("models"), list):
                            nama = [m.get("name") or m.get("model") for m in data["models"]]
                        else:
                            data, _ = p._minta("GET", f"{p.url}/v1/models", batas=BATAS_CEK_DETIK)
                            ok = isinstance(data, dict) and isinstance(data.get("data"), list)
                            nama = [m.get("id") for m in data["data"]] if ok else []
                        self.model_tautan_tersedia = sorted({n for n in nama if isinstance(n, str) and n})
                logger.info("Cek penulis: %s", "; ".join(f"{j}={h}" for j, h in hasil))
        except Exception:
            logger.exception("Cek rantai penulis gagal.")
        finally:
            with self.lock:
                self._cek_tertunda -= 1

    # Bangun ulang rantai sesuai urutan panel, dengan key OpenRouter dan link LLM (Docker/tunnel) terbaru dari
    # Konfigurasi AI panel, lalu cek semua jalurnya. Jalur tanpa key/link dilewati; mode templat atau semua jalur gagal
    # berarti tanpa rantai (templat). latar=False (cek sinkron) hanya dipakai tes; panel membaca progres lewat polling.
    # Alur: 1 mode templat: tanpa rantai -> 2 baca key, link, model, token dari Konfigurasi AI -> 3 buat_rantai
    #       -> 4 tutup rantai lama sesudah kalimat yang sedang ditulis selesai -> 5 cek rantai baru, di latar atau
    #       langsung
    def segarkan(self, latar=True):
        with self.lock:
            lama, rantai = self.rantai, None
            self.keterangan = {}
            if self.konfigurasi.penulis != "templat":
                config = ai_runtime.current()
                link = (config.ollama_base_url or "").strip() or None
                # Host dan asal link ditampilkan di panel: link bawaan .env (mis. localhost) mudah dikenali.
                self.alamat_tautan = link and {
                    "host": urlsplit(link).netloc,
                    "sumber": "panel" if ai_runtime.diatur_panel("ollama_base_url") else ".env",
                }
                kunci = {
                    "openrouter": config.openrouter_api_key_value,
                    "tautan": link,
                }
                model = {
                    "openrouter": self.konfigurasi.model_openrouter or config.openrouter_model,
                    "tautan": self.konfigurasi.model_tautan or config.ollama_model,
                }
                # Token tanpa spasi; None jika tidak diatur.
                token = config.ollama_tunnel_token
                try:
                    rantai, self.keterangan = buat_rantai(
                        self.konfigurasi.urutan_penulis, kunci, model,
                        token_tautan=(token.get_secret_value().strip() or None) if token else None,
                    )  # fmt: skip
                except Exception:
                    logger.exception("Rantai penulis gagal disiapkan; memakai templat.")
                    rantai = None
            self.rantai = rantai
            if rantai is not None:
                # Dinaikkan sebelum thread cek mulai agar ringkasan langsung "sedang dicek".
                self._cek_tertunda += 1
        if lama is not None:
            # Koneksi rantai lama dilepas setelah kalimat yang mungkin sedang ditulis selesai.
            penutup = threading.Timer(2 * BATAS_WAKTU_DETIK, lama.tutup)
            penutup.daemon = True
            penutup.start()
        if rantai is not None:
            if latar:
                threading.Thread(
                    target=self._cek, args=(rantai,), daemon=True, name="cek-penulis"
                ).start()
            else:
                self._cek(rantai)

    # Ubah penulis/rantai saat server berjalan. Semua nilai divalidasi dulu (atomik). Hasil: True bila rantai perlu
    # dibangun ulang.
    # Alur: 1 validasi semua nilai -> 2 terapkan yang diisi -> 3 bandingkan dengan sebelumnya
    def atur(self, penulis=None, urutan_penulis=None, model_openrouter=None, model_tautan=None):
        if penulis is not None and penulis not in PENULIS_VALID:
            raise ValueError("Penulis kalimat tidak dikenal.")
        if urutan_penulis is not None:
            if not set(urutan_penulis) <= set(JALUR_PENULIS) or len(set(urutan_penulis)) != len(
                urutan_penulis
            ):
                raise ValueError("Urutan penulis berisi jalur yang tidak dikenal atau ganda.")
        if model_openrouter is not None:
            model_openrouter = model_openrouter.strip()
            if model_openrouter and not POLA_MODEL_OPENROUTER.fullmatch(model_openrouter):
                raise ValueError("Model OpenRouter harus berbentuk penyedia/model.")
        if model_tautan is not None:
            model_tautan = model_tautan.strip()
            if model_tautan and (
                len(model_tautan) > 100 or not POLA_MODEL_TAUTAN.fullmatch(model_tautan)
            ):
                raise ValueError("Nama model link LLM tidak valid (contoh: qwen3:4b-instruct).")
        with self.lock:
            k = self.konfigurasi
            sebelum = (k.penulis, list(k.urutan_penulis), k.model_openrouter, k.model_tautan)
            if penulis is not None:
                k.penulis = penulis
            if urutan_penulis is not None:
                k.urutan_penulis = urutan_penulis
            if model_openrouter is not None:
                k.model_openrouter = model_openrouter
            if model_tautan is not None:
                k.model_tautan = model_tautan
            return sebelum != (k.penulis, list(k.urutan_penulis), k.model_openrouter, k.model_tautan)

    # Rantai yang dipakai kalimat berikutnya; None bila mode templat, rantai belum ada, atau pemanggil minta templat.
    def dipakai(self, pakai_llm=True):
        with self.lock:
            return self.rantai if pakai_llm and self.konfigurasi.penulis != "templat" else None

    # Server mati: tutup koneksi rantai yang sedang dipakai.
    def tutup(self):
        if self.rantai is not None:
            self.rantai.tutup()
