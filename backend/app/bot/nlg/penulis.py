"""[PENULIS LLM] Pengirim prompt ke model bahasa: OpenRouter dan tautan ai-docker, dirangkai berurutan.

PenulisOpenRouter dan PenulisTautan meminta satu kalimat lewat HTTP. PenulisBerantai mencoba jalur sesuai urutan;
jalur yang gagal diistirahatkan sebentar (JEDA_GAGAL_DETIK, berlipat sampai JEDA_MAKS_DETIK). buat_rantai merakit
rantai dari urutan, kunci, dan model yang diatur panel.
"""

import re
import threading
from time import monotonic

from app.bot.nlg.aturan import buang_pikiran
from app.config.settings import JALUR_PENULIS_NPC

MODEL_OPENROUTER = "qwen/qwen3-14b"

MODEL_TAUTAN = "qwen3:14b"

MAKS_TOKEN_LLM = 1024

BATAS_WAKTU_DETIK = 20

BATAS_CEK_DETIK = 8

JEDA_GAGAL_DETIK = 30

JEDA_MAKS_DETIK = 300

# Jalur rantai penulis yang dikenal game; sama dengan pilihan NPC_WRITER_ORDER di pengaturan.
JALUR_PENULIS = JALUR_PENULIS_NPC

# Kode HTTP → (status, permanen). Permanen: jalur dimatikan sampai dicek ulang; sementara: diistirahatkan.
def status_http(kode):
    if kode in (401, 403):
        return f"key ditolak ({kode})", True
    if kode == 402:
        return "kredit tidak cukup (402)", True
    if kode in (400, 404, 422):
        return f"model atau permintaan ditolak ({kode})", True
    if kode == 429:
        return "rate limit (429)", False
    return (f"error server ({kode})" if kode >= 500 else f"HTTP {kode}"), False

# Qwen3 memakai saklar /no_think di prompt agar langsung menjawab tanpa penalaran panjang.
def pesan_model(pesan, model):
    return pesan + "\n/no_think" if "qwen3" in (model or "").casefold() else pesan

class PenulisDasar:
    """Keadaan bersama semua jalur: aktif/mati, istirahat setelah gagal sementara, dan pemakaian token."""

    def __init__(self, jalur, model):
        self.jalur, self.model = jalur, model
        self.aktif, self.status = True, "belum dicek"
        self.istirahat_sampai, self.gagal_beruntun = 0.0, 0
        self.panggilan, self.token_masuk, self.token_keluar = 0, 0, 0

    # Siap dipakai sekarang: tidak dimatikan dan tidak sedang istirahat.
    def siap(self):
        return self.aktif and monotonic() >= self.istirahat_sampai

    # Gagal permanen mematikan jalur; gagal sementara mengistirahatkannya, makin lama bila beruntun.
    def gagal(self, status, permanen=False):
        self.status = status
        if permanen:
            self.aktif = False
        else:
            self.gagal_beruntun += 1
            jeda = min(JEDA_MAKS_DETIK, JEDA_GAGAL_DETIK * 2 ** (self.gagal_beruntun - 1))
            self.istirahat_sampai = monotonic() + jeda
        return None, status

    # Kode HTTP (int) atau status koneksi (str) → gagal permanen/sementara.
    def gagal_dari(self, hasil):
        return self.gagal(*status_http(hasil)) if isinstance(hasil, int) else self.gagal(hasil)

    def berhasil(self, teks):
        self.status, self.gagal_beruntun, self.istirahat_sampai = "ok", 0, 0.0
        return teks, "ok"

    def catat_token(self, masuk, keluar):
        self.token_masuk += int(masuk or 0)
        self.token_keluar += int(keluar or 0)

    # Satu panggilan → (teks, status). Kegagalan tidak pernah melempar error ke game.
    def tulis(self, sistem, pesan):
        if not self.aktif:
            return None, self.status
        if not self.siap():
            return None, f"istirahat ({self.status})"
        self.panggilan += 1
        try:
            return self._tulis(sistem, pesan)
        except Exception as e:  # respons di luar dugaan tidak boleh menghentikan game
            return self.gagal(f"respons tidak terbaca ({type(e).__name__})")

    # Cek sebelum dipakai; cek ulang juga menghidupkan lagi jalur yang tadinya ditolak.
    def cek(self):
        self.aktif, self.istirahat_sampai, self.gagal_beruntun = True, 0.0, 0
        try:
            hasil = self._cek()
        except Exception as e:
            hasil = self.gagal(f"cek gagal ({type(e).__name__})")[1]
        if hasil == "ok":
            self.status = "siap"
        return hasil

    # Lepas koneksi HTTP milik jalur (dipanggil saat rantai lama diganti).
    def tutup(self):
        klien = getattr(self, "klien", None)
        if klien is not None:
            klien.close()

class PenulisHTTP(PenulisDasar):
    """Dasar jalur HTTP (httpx) untuk OpenRouter dan link LLM sendiri."""

    def __init__(self, jalur, model, header, transport=None):
        import httpx

        super().__init__(jalur, model)
        self.httpx = httpx
        self.klien = httpx.Client(headers=header, timeout=BATAS_WAKTU_DETIK, follow_redirects=False, transport=transport)

    # Satu permintaan → (JSON, "ok") atau (None, kode HTTP / status koneksi).
    def _minta(self, metode, url, batas=BATAS_WAKTU_DETIK, **opsi):
        try:
            r = self.klien.request(metode, url, timeout=batas, **opsi)
        except self.httpx.TimeoutException:
            return None, "timeout"
        except self.httpx.HTTPError:
            return None, "tidak terhubung"
        if r.status_code >= 400:
            return None, r.status_code
        try:
            return r.json(), "ok"
        except ValueError:
            return None, "respons bukan JSON"

    # Chat Completions format OpenAI: dipakai OpenRouter dan server link yang kompatibel OpenAI.
    def _chat_openai(self, url, sistem, pesan, maks_token, **tambahan):
        data, hasil = self._minta("POST", url, json={
            "model": self.model, "max_tokens": maks_token, "stream": False,
            "messages": [{"role": "system", "content": sistem},
                         {"role": "user", "content": pesan_model(pesan, self.model)}], **tambahan})
        if data is None:
            return self.gagal_dari(hasil)
        pakai = data.get("usage") or {}
        self.catat_token(pakai.get("prompt_tokens"), pakai.get("completion_tokens"))
        pilihan = (data.get("choices") or [{}])[0]
        teks = buang_pikiran((pilihan.get("message") or {}).get("content"))
        alasan = pilihan.get("finish_reason")
        if alasan in ("length", "content_filter", "error") or not teks:
            return None, alasan or "kosong"
        return self.berhasil(teks)

class PenulisOpenRouter(PenulisHTTP):
    """Model lewat OpenRouter (Chat Completions). Default: MODEL_OPENROUTER (qwen/qwen3-14b, sama dengan game)."""

    ALAMAT = "https://openrouter.ai/api/v1"

    def __init__(self, api_key, model=None, transport=None):
        super().__init__("openrouter", model or MODEL_OPENROUTER, {"Authorization": f"Bearer {api_key}"}, transport)

    # Qwen3: penalaran dimatikan agar cepat; model lain memakai bawaannya.
    def _tambahan(self):
        return {"reasoning": {"enabled": False}} if "qwen3" in self.model.casefold() else {}

    def _tulis(self, sistem, pesan):
        return self._chat_openai(f"{self.ALAMAT}/chat/completions", sistem, pesan, MAKS_TOKEN_LLM, **self._tambahan())

    # Key lewat /key dan model lewat /models/<model>/endpoints (gratis), lalu satu pesan pendek dengan batas token
    # yang sama seperti saat bermain: saldo yang tidak cukup (402) ketahuan sebelum bot bicara.
    def _cek(self):
        data, hasil = self._minta("GET", f"{self.ALAMAT}/key", batas=BATAS_CEK_DETIK)
        if data is None:
            return self.gagal_dari(hasil)[1]
        sisa = (data.get("data") or {}).get("limit_remaining")
        if sisa is not None and sisa <= 0:
            return self.gagal("kredit key habis", permanen=True)[1]
        model = self.model.split(":")[0]  # varian seperti :free memakai halaman model yang sama
        data, hasil = self._minta("GET", f"{self.ALAMAT}/models/{model}/endpoints", batas=BATAS_CEK_DETIK)
        if hasil == 404:
            return self.gagal(f"model {self.model} tidak ada di OpenRouter", permanen=True)[1]
        if data is None:
            return self.gagal_dari(hasil)[1]
        data, hasil = self._minta("POST", f"{self.ALAMAT}/chat/completions", batas=BATAS_CEK_DETIK, json={
            "model": self.model, "max_tokens": MAKS_TOKEN_LLM, "stream": False,
            "messages": [{"role": "user", "content": pesan_model("Balas: ok", self.model)}], **self._tambahan()})
        if data is None:
            return self.gagal_dari(hasil)[1]
        pakai = data.get("usage") or {}
        self.catat_token(pakai.get("prompt_tokens"), pakai.get("completion_tokens"))
        return "ok"

class PenulisTautan(PenulisHTTP):
    """LLM sendiri lewat link, mis. Ollama di Docker yang dibuka lewat tunnel HTTPS.

    Protokol dikenali saat cek: Ollama (/api/chat) atau server kompatibel OpenAI (/v1/chat/completions).
    """

    def __init__(self, url, model=None, token=None, transport=None):
        header = {"Authorization": f"Bearer {token}"} if token else {}
        super().__init__("tautan", model or MODEL_TAUTAN, header, transport)
        self.url = re.sub(r"/v1/?$", "", url.strip().rstrip("/"))
        self.protokol = None

    # Link menolak (401/403) biasanya karena token atau host header tunnel, bukan key model.
    def gagal_dari(self, hasil):
        if hasil in (401, 403):
            return self.gagal(f"akses link ditolak ({hasil}): periksa token/host header tunnel", permanen=True)
        return super().gagal_dari(hasil)

    # Model yang diminta tidak ada di link: pakai model sekeluarga (mis. qwen3:8b), lalu model pertama.
    def _pilih_model(self, protokol, daftar):
        daftar = [m for m in daftar if m]
        if not daftar:  # model mungkin masih diunduh (ollama-models): dicoba lagi setelah jeda
            return self.gagal("belum ada model di link")[1]
        self.protokol = protokol
        if self.model not in daftar:
            keluarga = [m for m in daftar if m.split(":")[0] == self.model.split(":")[0]]
            self.model = (keluarga or daftar)[0]
        return "ok"

    # Ollama: daftar model /api/tags, atau /api/show bila tunnel hanya meneruskan chat/show; lalu OpenAI /v1/models.
    def _cek(self):
        data, hasil = self._minta("GET", f"{self.url}/api/tags", batas=BATAS_CEK_DETIK)
        if isinstance(data, dict) and isinstance(data.get("models"), list):
            return self._pilih_model("ollama", [m.get("name") or m.get("model") for m in data["models"]])
        if hasil in ("timeout", "tidak terhubung", 401, 403):  # link mati/timeout atau akses ditolak
            return self.gagal_dari(hasil)[1]
        # Jawaban lain (404, 200 tanpa daftar model, bukan JSON): mungkin tunnel terbatas atau server OpenAI.
        if self._minta("POST", f"{self.url}/api/show", batas=BATAS_CEK_DETIK, json={"model": self.model})[0] is not None:
            self.protokol = "ollama"
            return "ok"
        data, _ = self._minta("GET", f"{self.url}/v1/models", batas=BATAS_CEK_DETIK)
        if isinstance(data, dict) and isinstance(data.get("data"), list):
            return self._pilih_model("openai", [m.get("id") for m in data["data"]])
        return self.gagal(f"link belum menjawab sebagai Ollama/OpenAI ({hasil})")[1]

    def _tulis(self, sistem, pesan):
        if self.protokol is None:  # belum dicek: kenali protokol dulu
            self._cek()
            if self.protokol is None:
                return None, self.status
        if self.protokol == "openai":
            return self._chat_openai(f"{self.url}/v1/chat/completions", sistem, pesan, MAKS_TOKEN_LLM)
        data, hasil = self._minta("POST", f"{self.url}/api/chat", json={
            "model": self.model, "stream": False, "think": False, "options": {"num_predict": MAKS_TOKEN_LLM},
            "messages": [{"role": "system", "content": sistem},
                         {"role": "user", "content": pesan_model(pesan, self.model)}]})
        if data is None:
            return self.gagal_dari(hasil)
        self.catat_token(data.get("prompt_eval_count"), data.get("eval_count"))
        teks = buang_pikiran((data.get("message") or {}).get("content"))
        if data.get("done_reason") == "length" or not teks:
            return None, data.get("done_reason") or "kosong"
        return self.berhasil(teks)

class PenulisBerantai:
    """Rantai prioritas: jalur dicoba berurutan, yang mati/istirahat dilewati. Templat tetap cadangan di tulis_pesan."""

    def __init__(self, daftar):
        self.daftar = list(daftar)
        self._lokal = threading.local()  # jalur terakhir per thread (NLG game berjalan di beberapa thread)

    @property
    def aktif(self):
        return any(p.aktif for p in self.daftar)

    # Jalur yang menulis kalimat berikutnya: yang pertama siap (tidak ditolak, tidak istirahat); None bila tidak ada.
    def terdepan(self):
        return next((p for p in self.daftar if p.siap()), None)

    @property
    def jalur(self):
        p = self.terdepan()
        return p.jalur if p else "templat"

    @property
    def model(self):
        p = self.terdepan()
        return p.model if p else None

    @property
    def status(self):
        return "; ".join(f"{p.jalur}: {p.status}" for p in self.daftar)

    # Jalur yang menulis kalimat terakhir di thread ini.
    @property
    def terakhir(self):
        return getattr(self._lokal, "jalur", None)

    @property
    def panggilan(self):
        return sum(p.panggilan for p in self.daftar)

    @property
    def token_masuk(self):
        return sum(p.token_masuk for p in self.daftar)

    @property
    def token_keluar(self):
        return sum(p.token_keluar for p in self.daftar)

    # Semua jalur dicek (gratis atau sangat murah) agar status tiap jalur terlihat.
    def cek(self):
        return [(p.jalur, p.model, p.cek()) for p in self.daftar]

    def tulis(self, sistem, pesan):
        self._lokal.jalur, alasan = None, []
        for p in self.daftar:
            if not p.siap():
                continue
            teks, status = p.tulis(sistem, pesan)
            if teks is not None:
                self._lokal.jalur = p.jalur
                return teks, status
            alasan.append(f"{p.jalur}: {status}")
        return None, "; ".join(alasan) or "semua jalur mati atau istirahat"

    def tutup(self):
        for p in self.daftar:
            p.tutup()

    def laporan(self):
        return [{"jalur": p.jalur, "model": p.model, "aktif": p.aktif, "siap": p.siap(), "status": p.status,
                 "panggilan": p.panggilan, "token_masuk": p.token_masuk, "token_keluar": p.token_keluar}
                for p in self.daftar]

# Rantai dari urutan prioritas dan key/link yang tersedia; jalur tanpa key dilewati dengan keterangan.
def buat_rantai(urutan, kunci, model=None, token_tautan=None):
    anggota, keterangan, model = [], {}, model or {}
    for jalur in dict.fromkeys(urutan):  # duplikat dibuang, prioritas dipertahankan
        if jalur not in JALUR_PENULIS:
            keterangan[jalur] = "jalur tidak dikenal"
        elif not kunci.get(jalur):
            keterangan[jalur] = "link belum diisi" if jalur == "tautan" else "key belum diisi"
        else:
            try:
                if jalur == "openrouter":
                    anggota.append(PenulisOpenRouter(kunci[jalur], model.get(jalur)))
                else:
                    anggota.append(PenulisTautan(kunci[jalur], model.get(jalur), token_tautan))
            except Exception as e:  # mis. paket httpx belum terpasang
                keterangan[jalur] = f"gagal disiapkan ({type(e).__name__})"
    return (PenulisBerantai(anggota) if anggota else None), keterangan
