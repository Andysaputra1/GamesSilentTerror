"""Logika panel administrator: sesi admin, konfigurasi AI dan NPC, arsip room, jejak checker, dan riwayat chat.

Berkas ini tidak mengenal HTTP. Controller menerjemahkan exception di sini menjadi status dan pesan.
"""

import base64
import csv
from datetime import datetime, date, time, timedelta, timezone
import hashlib
import hmac
import io
import ipaddress
import json
import re
import secrets
import socket
from tempfile import SpooledTemporaryFile
from urllib.parse import urlsplit

from app.config.database import PersistenceError, jalankan_transaksi
from app.config.settings import settings
from app.models import panel_queries
from app.bot.bot_controller import brain_runtime
from app.bot.nlg import POLA_MODEL_TAUTAN
from app.services.activity_service import activity
from app.services.ai_config_service import ai_runtime, simpan_konfigurasi_ai
from app.services.checker_service import checker_service
from app.services.npc_config_service import save_npc_configuration
from app.services.password_service import verify_password
from app.services.room_service import room_service

PESAN_PANEL = "Database panel belum siap. Periksa koneksi dan migrasi V5/V6."


class PanelBelumSiap(RuntimeError):
    """Password administrator di server belum disiapkan atau tidak valid."""


class LoginPanelGagal(RuntimeError):
    """Username atau password administrator salah."""


class AlamatTunnelDitolak(ValueError):
    """URL tunnel kosong, tidak aman, atau tidak mengarah ke alamat publik."""


class FilterRiwayatSalah(ValueError):
    """Rentang tanggal riwayat chat tidak bisa dipakai."""


# Transaksi panel memakai satu pesan gagal, yang diteruskan controller sebagai HTTP 503.
def transaction(operasi):
    return jalankan_transaksi(operasi, PESAN_PANEL)


# Buat sidik kredensial agar pergantian username/password membatalkan sesi lama.
def credential_version():
    hash_password = (
        settings.panel_password_hash.get_secret_value() if settings.panel_password_hash else ""
    )
    return hashlib.sha256((settings.panel_username + hash_password).encode()).hexdigest()


# Hash token panel sebelum pencarian atau penyimpanan di database.
def digest(token):
    return hashlib.sha256(token.encode()).hexdigest()


# Kolom JSON dari database bisa berupa teks atau sudah menjadi objek.
def _baca_kolom_json(nilai):
    return json.loads(nilai) if isinstance(nilai, str) else nilai


# Validasi hash token, kedaluwarsa, dan versi kredensial panel.
def sesi_berlaku(token):
    return bool(
        transaction(
            lambda database: panel_queries.valid_panel_session(
                database, digest(token), credential_version()
            )
        )
    )


# Periksa kredensial admin lalu simpan sesi panel berumur delapan jam. Hasil: token sesi.
def login(username, password):
    if not settings.panel_password_hash:
        raise PanelBelumSiap("Password administrator belum disiapkan di server.")
    try:
        hash_password = base64.b64decode(
            settings.panel_password_hash.get_secret_value(), validate=True
        ).decode()
    except (ValueError, UnicodeError) as error:
        raise PanelBelumSiap("Konfigurasi login panel tidak valid.") from error
    # Password selalu dihitung lebih dulu agar lama proses tidak membocorkan benar-salahnya username.
    password_cocok = verify_password(password, hash_password)
    if (
        not hmac.compare_digest(username.encode(), settings.panel_username.encode())
        or not password_cocok
    ):
        raise LoginPanelGagal("Username atau password salah.")
    token_sesi = secrets.token_urlsafe(32)
    waktu_kedaluwarsa = datetime.now(timezone.utc).replace(tzinfo=None) + timedelta(hours=8)
    transaction(
        lambda database: panel_queries.create_panel_session(
            database, digest(token_sesi), waktu_kedaluwarsa, credential_version()
        )
    )
    return token_sesi


# Hapus sesi panel terautentikasi dari database.
def logout(token):
    transaction(lambda database: panel_queries.delete_panel_session(database, digest(token)))


# Skema siap bila migrasi V5 dan V6 sudah tercatat; database gagal dianggap belum siap.
def skema_siap():
    try:
        return jalankan_transaksi(panel_queries.count_required_migrations) == 2
    except PersistenceError:
        return False


# Model yang disiapkan ai-docker (jalankan.bat): 4B cepat, 14B lebih pintar tetapi lebih lambat.
MODEL_LOKAL = ("qwen3:4b-instruct", "qwen3:14b")


# Susun konfigurasi publik dan status kunci tanpa membocorkan isi rahasia.
def config_view():
    config = ai_runtime.current()
    return {
        "provider": config.ai_provider,
        "endpoint": config.ollama_base_url,
        "model": (
            config.ollama_model if config.ai_provider == "docker" else config.openrouter_model
        ),
        "api_configured": bool(config.openrouter_api_key_value),
        "key_source": config.openrouter_key_source,
        "default_configured": bool(settings.openrouter_default or settings.openrouter_api_key),
        "custom_configured": config.openrouter_custom_configured,
        # Pilihan model lokal: model ai-docker, model di link saat tes terakhir, dan yang aktif.
        "local_model": config.ollama_model,
        "local_models": sorted(
            {*MODEL_LOKAL, *brain_runtime.penulis_npc.model_tautan_tersedia, config.ollama_model}
        ),
        "token_source": (
            "panel"
            if ai_runtime.diatur_panel("ollama_tunnel_token")
            else "env" if settings.ollama_tunnel_token else "none"
        ),
    }


# Terima hanya tunnel HTTPS publik tanpa kredensial atau parameter URL.
def validate_endpoint(endpoint):
    url = urlsplit(endpoint)
    if (
        url.scheme != "https"
        or not url.hostname
        or url.username
        or url.password
        or url.query
        or url.fragment
    ):
        raise AlamatTunnelDitolak("Masukkan URL tunnel HTTPS tanpa password, query, atau fragment.")
    try:
        addresses = socket.getaddrinfo(url.hostname, url.port or 443, type=socket.SOCK_STREAM)
        if not addresses or any(
            not ipaddress.ip_address(item[4][0]).is_global for item in addresses
        ):
            raise ValueError()
    except (OSError, ValueError) as error:
        raise AlamatTunnelDitolak(
            "Tunnel harus memiliki alamat publik yang dapat diakses."
        ) from error
    return endpoint.rstrip("/")


# Validasi endpoint dan sumber kunci sebelum menyimpan konfigurasi AI.
def simpan_konfigurasi(
    provider, endpoint, *, api_key, key_source, tunnel_token, clear_tunnel_token, model
):
    api_key = api_key.strip()
    if api_key and (len(api_key) > 1024 or any(c.isspace() for c in api_key)):
        raise ValueError("Format API key tidak valid.")
    tunnel_token = tunnel_token.strip()
    if tunnel_token and (len(tunnel_token) > 512 or any(c.isspace() for c in tunnel_token)):
        raise ValueError("Format token tunnel tidak valid.")
    model = (model or "").strip()
    if model and not POLA_MODEL_TAUTAN.fullmatch(model):
        raise ValueError("Nama model tidak valid (contoh: qwen3:4b-instruct).")
    endpoint = endpoint.strip()
    if endpoint:
        endpoint = validate_endpoint(endpoint)
    elif provider == "docker":
        raise AlamatTunnelDitolak("URL tunnel Ollama wajib diisi.")
    else:
        endpoint = ai_runtime.current().ollama_base_url
    simpan_konfigurasi_ai(
        provider,
        endpoint,
        api_key=api_key or None,
        key_source=key_source,
        tunnel_token=tunnel_token or None,
        clear_tunnel_token=clear_tunnel_token,
        model=model or None,
    )
    # Key OpenRouter dan link LLM juga dipakai rantai penulis kalimat NPC: bangun ulang dan cek di latar.
    brain_runtime.segarkan_penulis()
    return config_view()


PILIHAN_NPC = {
    "penulis": {
        "otomatis": "Rantai LLM sesuai prioritas; semua gagal → templat",
        "templat": "Templat bervariasi saja (tanpa LLM)",
    },
    # Jalur rantai penulis: nama tampilan dan asal key/link-nya (nilai key tidak pernah dikirim).
    "jalur_penulis": {
        "openrouter": {"label": "OpenRouter", "sumber": "API key di menu Konfigurasi AI"},
        "tautan": {
            "label": "LLM sendiri lewat link",
            "sumber": "URL tunnel (Docker/Ollama) di menu Konfigurasi AI",
        },
    },
}


# Status pemuatan otak, sumber NLU, rantai penulis, dan pilihan konfigurasi.
def status_npc():
    return {"status": brain_runtime.ringkasan(), "pilihan": PILIHAN_NPC}


# Simpan konfigurasi; rantai penulis langsung dipakai.
def simpan_npc(penulis, urutan_penulis, model_openrouter, model_tautan):
    status = save_npc_configuration(penulis, urutan_penulis, model_openrouter, model_tautan)
    return {"status": status, "pilihan": PILIHAN_NPC}


# Hit semua jalur aktif di latar; status per jalur dibaca lewat status_npc agar tidak timeout.
def cek_penulis_npc():
    return {"status": brain_runtime.segarkan_penulis(latar=True), "pilihan": PILIHAN_NPC}


# Daftar room yang pernah tercatat (cursor ID), jumlah pesan, dan tanda room yang masih hidup di memori.
def daftar_room(after_id):
    daftar_baris = transaction(lambda database: panel_queries.archived_rooms(database, after_id))
    with room_service.lock:
        kode_room_hidup = {room.code for room in room_service.rooms.values()}
    for baris in daftar_baris:
        baris["live"] = baris["room_code"] in kode_room_hidup
    isi_halaman = daftar_baris[:200]
    return {
        "rooms": isi_halaman,
        "has_more": len(daftar_baris) > 200,
        "next_after_id": isi_halaman[-1]["id"] if isi_halaman else after_id,
    }


# Gabungkan jejak tersimpan dan jejak aktif; cursor menjaga urutan halaman.
def halaman_checker(code, before):
    daftar_baris = transaction(
        lambda database: panel_queries.checker_trace_page(database, code, before)
    )
    isi_halaman = daftar_baris[:100]
    # Jejak di memori menimpa arsip ber-ID sama; halaman lanjutan hanya berisi arsip.
    jejak_arsip = [_baca_kolom_json(baris["trace"]) for baris in isi_halaman]
    jejak_aktif = checker_service.list(code) if before is None else []
    jejak_per_id = {jejak["id"]: jejak for jejak in jejak_arsip}
    jejak_per_id.update({jejak["id"]: jejak for jejak in jejak_aktif})
    jejak_terbaru_dulu = sorted(
        jejak_per_id.values(), key=lambda jejak: jejak["created_at"], reverse=True
    )
    return {
        "traces": jejak_terbaru_dulu,
        "events": activity.list(code) if before is None else [],
        # Ringkasan room hanya di halaman pertama: status, komposisi role, metode/persona bot.
        "room": (
            checker_service.ringkasan_room(code, jejak_terbaru_dulu) if before is None else None
        ),
        "has_more": len(daftar_baris) > 100,
        "next_before": isi_halaman[-1]["trace_cursor"] if isi_halaman else None,
    }


# Satu jejak lengkap beserta penjelasan keputusan bot (parameter, penalaran metode, NLG); None bila tidak ada.
def jejak_checker(code, trace_id):
    jejak_aktif = checker_service.cari(code, trace_id)
    if jejak_aktif is not None:
        return jejak_aktif
    jejak_arsip = transaction(
        lambda database: panel_queries.checker_trace(database, trace_id, code)
    )
    return None if jejak_arsip is None else _baca_kolom_json(jejak_arsip)


# Periksa rentang tanggal WIB, konversi ke UTC, lalu bangun kondisi SQL berparameter.
def history_filter(room_code, date_from, date_to, sender_kind="all"):
    if date_from == date.min:
        raise FilterRiwayatSalah("Tanggal awal terlalu kecil.")
    if date_from and date_to and date_from > date_to:
        raise FilterRiwayatSalah("Tanggal awal harus sebelum atau sama dengan tanggal akhir.")
    if date_to == date.max:
        raise FilterRiwayatSalah("Tanggal akhir terlalu besar.")
    selisih_wib = timedelta(hours=7)
    awal = datetime.combine(date_from, time()) - selisih_wib if date_from else None
    akhir = datetime.combine(date_to + timedelta(days=1), time()) - selisih_wib if date_to else None
    return panel_queries.history_conditions(room_code, awal, akhir, sender_kind)


# Ambil halaman pesan sesuai filter tanpa memuat seluruh arsip.
def halaman_riwayat(room_code, date_from, date_to, after_id, before_id, urut, sender_kind):
    syarat_sql, parameter_sql = history_filter(room_code, date_from, date_to, sender_kind)
    daftar_baris = transaction(
        lambda database: panel_queries.history_page(
            database,
            syarat_sql,
            parameter_sql,
            terbaru_dulu=urut == "baru",
            after_id=after_id,
            before_id=before_id,
        )
    )
    for baris in daftar_baris:  # bacaan IndoBERT saat game berjalan (JSON; kosong untuk pesan lama)
        baris["nlu"] = _baca_kolom_json(baris["nlu"])
    isi_halaman = daftar_baris[:200]
    return {
        "messages": isi_halaman,
        "has_more": len(daftar_baris) > 200,
        # id pesan terakhir di halaman ini: lanjutkan dengan after_id (urut lama) atau before_id (urut baru).
        "next_after_id": isi_halaman[-1]["id"] if isi_halaman else after_id,
    }


# Kolom CSV riwayat = format dataset NLU (sama dengan dataset latih IndoBERT), lalu info pesan. label_intent dan
# target adalah bacaan IndoBERT saat game berjalan, jadi perlu dicek manusia sebelum dipakai sebagai label.
KOLOM_CSV = ["pengirim", "teks_chat", "label_intent", "chat_sebelumnya", "daftar_pemain", "target",
             "session_id", "chat_id", "room_code", "confidence", "sender_kind", "waktu_utc"]  # fmt: skip


# Target bacaan → [{pemain, relasi}]. Bacaan baru menyimpan dict; konteks lama menyimpan teks "NOX: offend (0.88)".
def target_dataset(daftar_target):
    hasil = []
    for target in daftar_target or []:
        if isinstance(target, dict):
            hasil.append({"pemain": target["pemain"], "relasi": target["relasi"]})
        elif cocok := re.match(r"(.+): (offend|defend|neutral)\b", str(target)):
            hasil.append({"pemain": cocok[1], "relasi": cocok[2]})
    return hasil


# Ekspor snapshot riwayat menjadi CSV dengan pembacaan database per halaman. Hasil: berkas sementara yang
# posisinya di awal; pemanggil wajib menutupnya.
def ekspor_riwayat_csv(room_code, date_from, date_to, sender_kind, urut):
    # INPUT: filter yang sama dengan daftar riwayat
    syarat_sql, parameter_sql = history_filter(room_code, date_from, date_to, sender_kind)

    # PROSES: CSV ditulis ke berkas sementara. Lewat 1 MB berkas pindah ke disk, jadi transkrip besar
    # tidak menumpuk di memori dan transaksi database tidak terbuka lama.
    berkas_csv = SpooledTemporaryFile(max_size=1024 * 1024, mode="w+b")

    # Encode satu baris CSV sebagai UTF-8 ke berkas sementara ekspor.
    def tulis_baris_csv(nilai_kolom):
        penampung = io.StringIO(newline="")
        csv.writer(penampung).writerow(nilai_kolom)
        berkas_csv.write(penampung.getvalue().encode("utf-8"))

    def teks_json(nilai):
        return json.dumps(nilai, ensure_ascii=False)

    try:
        berkas_csv.write(b"\xef\xbb\xbf")
        tulis_baris_csv(KOLOM_CSV)
        id_maksimum = transaction(panel_queries.max_message_id)
        # Snapshot sampai id maksimum saat ekspor dimulai; halaman berjalan naik ("lama") atau turun ("baru").
        urut_baru = urut == "baru"
        batas = id_maksimum + 1 if urut_baru else 0
        while True:
            daftar_baris = transaction(
                lambda database: panel_queries.history_export_page(
                    database,
                    syarat_sql,
                    parameter_sql,
                    terbaru_dulu=urut_baru,
                    batas=batas,
                    maximum=id_maksimum,
                )
            )
            if not daftar_baris:
                break
            for id_chat, pengirim, jenis, teks, nlu, id_match, kode_room, waktu in daftar_baris:
                # Satu pesan → satu baris dataset, urutannya mengikuti KOLOM_CSV.
                # Pesan tanpa bacaan IndoBERT (arsip lama) → kolom bacaan kosong.
                bacaan = _baca_kolom_json(nlu) or {}
                chat_sebelumnya = [
                    {
                        "pengirim": pesan["pengirim"],
                        "teks_chat": pesan["teks"],
                        "label_intent": pesan.get("intent"),
                        "target": target_dataset(pesan.get("target")),
                    }
                    for pesan in bacaan.get("konteks") or []
                ]
                tulis_baris_csv(
                    [
                        pengirim,
                        teks,
                        bacaan.get("intent", ""),
                        teks_json(chat_sebelumnya) if bacaan else "",
                        teks_json(bacaan.get("daftar_pemain") or []) if bacaan else "",
                        teks_json(target_dataset(bacaan.get("target"))) if bacaan else "",
                        id_match or kode_room or "",
                        id_chat,
                        kode_room or "",
                        bacaan.get("confidence", ""),
                        jenis,
                        waktu.isoformat(sep=" ") if hasattr(waktu, "isoformat") else (waktu or ""),
                    ]
                )
            batas = daftar_baris[-1][0]
        berkas_csv.seek(0)
    except BaseException:
        berkas_csv.close()
        raise
    return berkas_csv
