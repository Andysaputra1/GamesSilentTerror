"""HTTP adapter for the local Ollama server; no cloud fallback."""

import httpx


# Siapkan header akses tunnel Ollama sesuai token yang dikonfigurasi.
def tunnel_headers(config):
    token = config.ollama_tunnel_token
    return {"Authorization": "Bearer " + token.get_secret_value()} if token else {}


# HEALTH CHECK ASYNC: cek ketersediaan model terpilih lewat Ollama /api/show; gagal koneksi menghasilkan False.
async def model_available(*, config) -> bool:
    try:
        async with httpx.AsyncClient(timeout=3.0) as client:
            response = await client.post(
                config.ollama_base_url.rstrip("/") + "/api/show",
                headers=tunnel_headers(config),
                json={"model": config.ollama_model},
            )
            return response.status_code == 200
    except httpx.HTTPError:
        return False
