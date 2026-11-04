"""HTTP adapter for the local Ollama server; no cloud fallback."""

import httpx
from app.config.settings import settings


# Siapkan header akses tunnel Ollama sesuai token yang dikonfigurasi.
def tunnel_headers(config):
    token = config.ollama_tunnel_token
    return {"Authorization": "Bearer " + token.get_secret_value()} if token else {}


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
