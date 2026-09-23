"""OpenRouter chat completions; never routes through another API on failure."""
import httpx

async def generate_reply(prompt, *, config, max_tokens=None):
    key = config.openrouter_api_key_value
    if not key:
        raise ValueError("API key OpenRouter untuk sumber yang dipilih belum tersedia.")
    async with httpx.AsyncClient(timeout=config.openai_timeout_seconds, follow_redirects=False) as client:
        response = await client.post("https://openrouter.ai/api/v1/chat/completions",
            headers={"Authorization": "Bearer " + key}, json={
                "model": "qwen/qwen3-14b", "messages": [{"role": "user", "content": prompt}],
                "max_tokens": max_tokens or config.openai_max_output_tokens,
                "reasoning": {"enabled": False}, "stream": False})
        response.raise_for_status()
        content = response.json()["choices"][0]["message"]["content"]
        if not isinstance(content, str) or not content.strip():
            raise ValueError("Provider tidak menghasilkan teks.")
        return content.strip()
