"""Ekspor otak NPC dari notebook skripsi ke modul backend.

Kode bot di game harus SAMA dengan kode yang diuji di notebook. Skrip ini membaca
notebook `npc_fuzzy`, `npc_utility_ai`, `npc_behavior_tree`, dan `npc_nlg`, lalu
menyalin hanya definisi (import, konstanta, fungsi, kelas) ke
`services/npc_brain/generated/`. Demo, print, grafik, skenario, pengujian, dan
pemuatan model di tingkat modul dibuang.

Pemakaian (dari folder backend):
    python scripts/ekspor_otak_npc.py --notebook-dir ../../training/prethesis/ai_2_dataset_baru
"""

from __future__ import annotations

import argparse
import ast
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parents[1]
TUJUAN = BACKEND_DIR / "services" / "npc_brain" / "generated"
DEFAULT_NOTEBOOK_DIR = BACKEND_DIR.parents[1] / "training" / "prethesis" / "ai_2_dataset_baru"

# Notebook NPC: semua sel kode sebelum bagian skenario adalah persepsi, NLG payload, penalaran, dan inti.
NOTEBOOK_NPC = {
    "otak_fuzzy": "npc_fuzzy.ipynb",
    "otak_utility": "npc_utility_ai.ipynb",
    "otak_bt": "npc_behavior_tree.ipynb",
}
BATAS_NPC = "## Skenario Permainan"

# Notebook NLG: hanya bagian yang dipakai saat bermain.
NOTEBOOK_NLG = "npc_nlg.ipynb"
BAGIAN_NLG = {
    "## Library yang Digunakan",
    "## Konfigurasi",
    "## Persona Bot",
    "## Templat Bervariasi",
    "## Pengaman 1: Pemeriksa Aturan",
    "## Pengaman 2: Validasi Ulang dengan IndoBERT",
    "## Penulis Kalimat: Claude",
    "## Pipeline `tulis_pesan`",
}

# Import khusus notebook (tampilan/grafik) diganti stub; sisanya dipertahankan apa adanya.
IMPORT_DIBUANG = {"matplotlib.pyplot", "IPython.display"}
# Variabel tingkat modul yang memuat model, memanggil API, atau berisi data demo.
VARIABEL_DIBUANG = {
    "nlu", "penulis", "RENCANA", "ringkas", "contoh", "tampilkan_contoh", "engine",
}  # fmt: skip
# Nama fungsi tampilan notebook: penugasan yang memakai nama ini adalah demo.
NAMA_TAMPILAN = {"plt", "display", "tampilkan"}

KEPALA = '''"""FILE INI DIHASILKAN OTOMATIS oleh scripts/ekspor_otak_npc.py. JANGAN DIEDIT MANUAL.

Sumber : {sumber}
Sidik  : {sidik}
Dibuat : {waktu}

Perubahan logika bot dilakukan di notebook skripsi, dijalankan ulang sampai semua
skenario/pengujian lulus, lalu diekspor ulang dengan skrip ini.
"""
# ruff: noqa
# fmt: off


# Pengganti fungsi tampilan notebook; backend tidak menampilkan tabel.
def display(*args, **kwargs):
    return None

'''


# Import yang aman untuk backend; modul tampilan notebook dibuang.
def _import_dipakai(node) -> bool:
    if isinstance(node, ast.Import):
        return not any(alias.name in IMPORT_DIBUANG for alias in node.names)
    return node.module not in IMPORT_DIBUANG


# Pertahankan definisi; buang ekspresi, loop demo, assert, dan variabel yang memicu efek samping.
def _definisi(sumber: str) -> list[str]:
    hasil = []
    for node in ast.parse(sumber).body:
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            if _import_dipakai(node):
                hasil.append(ast.get_source_segment(sumber, node))
        elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            awal = min([node.lineno] + [d.lineno for d in node.decorator_list])
            baris = sumber.splitlines()[awal - 1 : node.end_lineno]
            # Sertakan komentar tepat di atas definisi (gaya notebook: komentar penjelas fungsi).
            komentar = []
            semua = sumber.splitlines()
            i = awal - 2
            while i >= 0 and semua[i].lstrip().startswith("#"):
                komentar.insert(0, semua[i])
                i -= 1
            hasil.append("\n".join(komentar + baris))
        elif isinstance(node, (ast.Assign, ast.AnnAssign)):
            targets = node.targets if isinstance(node, ast.Assign) else [node.target]
            nama = {n.id for t in targets for n in ast.walk(t) if isinstance(n, ast.Name)}
            dipakai = (
                {n.id for n in ast.walk(node.value) if isinstance(n, ast.Name)}
                if node.value
                else set()
            )
            # Variabel demo/efek samping dan hasil fungsi tampilan (grafik/tabel) tidak ikut.
            if not nama & VARIABEL_DIBUANG and not dipakai & NAMA_TAMPILAN:
                hasil.append(ast.get_source_segment(sumber, node))
    return hasil


# Sel yang hanya membuat grafik tidak berisi logika bot.
def _sel_logika(teks: str) -> bool:
    return "plt." not in teks


# Sel kode notebook NPC sebelum bagian skenario.
def _sel_npc(nb: dict) -> list[str]:
    sel = []
    for cell in nb["cells"]:
        teks = "".join(cell["source"]) if isinstance(cell["source"], list) else cell["source"]
        if cell["cell_type"] == "markdown" and teks.startswith(BATAS_NPC):
            break
        if cell["cell_type"] == "code" and _sel_logika(teks):
            sel.append(teks)
    return sel


# Sel kode notebook NLG yang berada di bagian runtime.
def _sel_nlg(nb: dict) -> list[str]:
    sel, aktif = [], False
    for cell in nb["cells"]:
        teks = "".join(cell["source"]) if isinstance(cell["source"], list) else cell["source"]
        if cell["cell_type"] == "markdown" and teks.startswith("## "):
            aktif = teks.splitlines()[0].strip() in BAGIAN_NLG
        elif cell["cell_type"] == "code" and aktif and _sel_logika(teks):
            sel.append(teks)
    return sel


# Sidik isi sel yang diekspor; berubah hanya jika logika notebook berubah (bukan output/waktu run).
def sidik_sel(sel: list[str]) -> str:
    return hashlib.sha256("\n".join(sel).encode("utf-8")).hexdigest()[:16]


# Sidik semua notebook sumber, untuk memeriksa apakah modul hasil ekspor masih mutakhir.
def sidik_notebook(folder: Path) -> dict[str, str]:
    sumber = {
        **{m: (f, _sel_npc) for m, f in NOTEBOOK_NPC.items()},
        "nlg": (NOTEBOOK_NLG, _sel_nlg),
    }
    hasil = {}
    for modul, (nama, pilih) in sumber.items():
        nb = json.loads((folder / nama).read_text(encoding="utf-8"))
        hasil[modul] = sidik_sel(pilih(nb))
    return hasil


# Tulis satu modul hasil ekspor dan kembalikan ringkasannya.
def ekspor(nama_modul: str, path_notebook: Path, pilih_sel) -> dict:
    nb = json.loads(path_notebook.read_text(encoding="utf-8"))
    sel = pilih_sel(nb)
    bagian = [blok for s in sel for blok in _definisi(s)]
    sidik = sidik_sel(sel)
    isi = (
        KEPALA.format(
            sumber=path_notebook.name,
            sidik=sidik,
            waktu=datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC"),
        )
        + "\n\n".join(bagian)
        + "\n"
    )
    compile(isi, nama_modul, "exec")  # gagal cepat jika hasil ekspor tidak valid
    TUJUAN.mkdir(parents=True, exist_ok=True)
    # newline="\n": Windows tidak mengubah akhir baris jadi CRLF (Prettier/Black memakai LF).
    (TUJUAN / f"{nama_modul}.py").write_text(isi, encoding="utf-8", newline="\n")
    return {"modul": nama_modul, "notebook": path_notebook.name, "sel": len(sel), "blok": len(bagian),
            "sidik": sidik}  # fmt: skip


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--notebook-dir", type=Path, default=DEFAULT_NOTEBOOK_DIR)
    args = parser.parse_args()
    folder = args.notebook_dir.resolve()
    ringkasan = [ekspor(m, folder / f, _sel_npc) for m, f in NOTEBOOK_NPC.items()]
    ringkasan.append(ekspor("nlg", folder / NOTEBOOK_NLG, _sel_nlg))
    (TUJUAN / "__init__.py").write_text(
        '"""Modul otak NPC hasil ekspor notebook; lihat scripts/ekspor_otak_npc.py."""\n',
        encoding="utf-8",
        newline="\n",
    )
    (TUJUAN / "SUMBER.json").write_text(
        json.dumps(ringkasan, indent=2) + "\n", encoding="utf-8", newline="\n"
    )
    for baris in ringkasan:
        print(f"{baris['modul']:14s} <- {baris['notebook']:26s} {baris['sel']:3d} sel, "
              f"{baris['blok']:4d} blok, sidik {baris['sidik']}")  # fmt: skip


if __name__ == "__main__":
    main()
