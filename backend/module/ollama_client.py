"""HTTP adapter for the local Ollama server; no cloud fallback."""

import httpx
from config.settings import settings


# ADAPTER ASYNC: kirim prompt ke Ollama, tunggu respons penuh, lalu validasi dan ambil teks jawabannya.
async def generate_reply(prompt: str, *, config=None) -> str:
    selected = settings if config is None else config
    # TAHAP 7 (docker): kirim prompt ke Ollama /api/chat memakai model dari env.
    async with httpx.AsyncClient(timeout=selected.ollama_timeout_seconds) as client:
        response = await client.post(
            selected.ollama_base_url.rstrip("/") + "/api/chat",
            json={
                "model": selected.ollama_model,
                "messages": [{"role": "user", "content": prompt}],
                "stream": False,
                "think": False,
                "options": {
                    "num_ctx": selected.ollama_context_length,
                    "num_predict": selected.ollama_max_output_tokens,
                },
            },
        )
        response.raise_for_status()
        # Ambil teks jawaban penuh (stream=False), lalu kembalikan ke alur chat.
        reply = response.json().get("message", {}).get("content", "")
        if not isinstance(reply, str) or not reply.strip():
            raise ValueError("Ollama returned no text.")
        return reply.strip()


# HEALTH CHECK ASYNC: cek ketersediaan model terpilih lewat Ollama /api/show; gagal koneksi menghasilkan False.
async def model_available(*, config=None) -> bool:
    selected = settings if config is None else config
    try:
        async with httpx.AsyncClient(timeout=3.0) as client:
            response = await client.post(
                selected.ollama_base_url.rstrip("/") + "/api/show",
                json={"model": selected.ollama_model},
            )
            return response.status_code == 200
    except httpx.HTTPError:
        return False
