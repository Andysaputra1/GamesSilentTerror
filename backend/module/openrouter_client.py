"""OpenRouter chat completions; never routes through another API on failure."""

import httpx


# Kirim prompt ke Qwen melalui OpenRouter dan tolak respons tanpa teks.
async def generate_reply(prompt, *, config, max_tokens=None):
    key = config.openrouter_api_key_value
    if not key:
        raise ValueError("API key OpenRouter untuk sumber yang dipilih belum tersedia.")
    async with httpx.AsyncClient(
        timeout=config.openai_timeout_seconds, follow_redirects=False
    ) as client:
        response = await client.post(
            "https://openrouter.ai/api/v1/chat/completions",
            headers={"Authorization": "Bearer " + key},
            json={
                "model": "qwen/qwen3-14b",
                "messages": [{"role": "user", "content": prompt}],
                "max_tokens": max_tokens or config.openai_max_output_tokens,
                "reasoning": {"enabled": False},
                "stream": False,
            },
        )
        response.raise_for_status()
        content = response.json()["choices"][0]["message"]["content"]
        if not isinstance(content, str) or not content.strip():
            raise ValueError("Provider tidak menghasilkan teks.")
        return content.strip()


def failure_message(error):
    """Safe diagnostics: never expose upstream bodies, headers, or credentials."""
    if isinstance(error, httpx.HTTPStatusError):
        code = error.response.status_code
        return {
            401: "API key OpenRouter ditolak.",
            402: "Saldo atau batas kredit OpenRouter tidak mencukupi.",
            429: "Batas permintaan OpenRouter tercapai. Coba lagi nanti.",
            404: "Model OpenRouter tidak tersedia.",
        }.get(code, f"OpenRouter gagal merespons (HTTP {code}).")
    if isinstance(error, (httpx.TimeoutException, TimeoutError)):
        return "Waktu tunggu AI habis. Coba lagi saat awal diskusi."
    if isinstance(error, ValueError):
        return "AI tidak menghasilkan teks atau API key belum tersedia. Periksa konfigurasi dan coba lagi."
    return "AI tidak dapat dihubungi. Periksa koneksi dan konfigurasi provider."
