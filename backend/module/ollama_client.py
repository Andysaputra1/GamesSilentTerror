"""HTTP adapter for the local Ollama server; no cloud fallback."""

import httpx
from config.settings import settings
from services.ai_diagnostics import record_request, record_response


# Siapkan header akses tunnel Ollama sesuai token yang dikonfigurasi.
def tunnel_headers(config):
    token = config.ollama_tunnel_token
    return {"Authorization": "Bearer " + token.get_secret_value()} if token else {}


# ADAPTER ASYNC: kirim prompt ke Ollama, tunggu respons penuh, lalu validasi dan ambil teks jawabannya.
async def generate_reply(prompt: str, *, config=None) -> str:
    selected = settings if config is None else config
    endpoint = selected.ollama_base_url.rstrip("/") + "/api/chat"
    payload = {
        "model": selected.ollama_model,
        "messages": [{"role": "user", "content": prompt}],
        "stream": False,
        "think": False,
        "options": {
            "num_ctx": selected.ollama_context_length,
            "num_predict": selected.ollama_max_output_tokens,
        },
    }
    record_request(endpoint, payload)
    # TAHAP 7 (docker): kirim prompt ke Ollama /api/chat memakai model dari env.
    async with httpx.AsyncClient(timeout=selected.ollama_timeout_seconds) as client:
        response = await client.post(
            endpoint,
            headers=tunnel_headers(selected),
            json=payload,
        )
        record_response(response.status_code)
        response.raise_for_status()
        # Ambil teks jawaban penuh (stream=False), lalu kembalikan ke alur chat.
        data = response.json()
        reply = data.get("message", {}).get("content", "")
        record_response(
            response.status_code,
            {
                "model": data.get("model"),
                "output": reply,
                "done": data.get("done"),
                "total_duration_ns": data.get("total_duration"),
                "prompt_eval_count": data.get("prompt_eval_count"),
                "eval_count": data.get("eval_count"),
            },
        )
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
                headers=tunnel_headers(selected),
                json={"model": selected.ollama_model},
            )
            return response.status_code == 200
    except httpx.HTTPError:
        return False
