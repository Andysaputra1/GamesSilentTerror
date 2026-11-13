"""Isi penulis kalimat bot (NLG), satu file per tahap. Urutan tahapnya dirangkai di app/bot/nlg_controller.py.

    prompt.py      [PROMPT]          rencana chat → perintah untuk LLM
    penulis.py     [PENULIS LLM]     perintah → kalimat dari OpenRouter atau tautan ai-docker
    aturan.py      [PERIKSA ATURAN]  kalimat → lolos, atau ditolak beserta alasannya
    templat.py     [TEMPLAT]         kalimat siap pakai bila LLM gagal atau ditolak
    pengaturan.py  [PANEL]           jalur, urutan, dan model penulis dari panel
"""
