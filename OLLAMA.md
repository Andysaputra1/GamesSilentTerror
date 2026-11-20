# Local Ollama

This file explains how to run Ollama locally in Docker and use it to generate bot dialogue. To expose a laptop-hosted
LLM to the VM backend through a tunnel, see [ai-docker/README.md](ai-docker/README.md). General application setup
instructions are in [README.md](README.md).

## Running Ollama

Ollama runs in the `shadow_ollama` container. Choose one standalone Compose file: `docker-compose.yml` for CPU
(including Mac) or `docker-compose.gpu.yml` for NVIDIA GPUs. Do not run both at the same time.

```sh
# CPU
docker compose up -d ollama ollama-models
docker compose logs -f ollama-models
docker compose exec ollama ollama list

# NVIDIA: use the GPU file for every command
docker compose -f docker-compose.gpu.yml up -d ollama ollama-models
docker compose -f docker-compose.gpu.yml logs -f ollama-models
docker compose -f docker-compose.gpu.yml exec ollama ollama list
```

| Address | Accessible from |
| --- | --- |
| `http://localhost:11435` | The host (loopback 127.0.0.1 only, not the public network) |
| `http://ollama:11434` | Other containers on the Compose network, including the backend |

- Both versions run Ollama in Docker, so a Mac does not need a native Ollama installation. The CPU version can be
  much slower. Give Docker enough memory for the selected model; a model that does not fit may fail, not just run slowly.
- The `ollama-models` service waits for a healthy server, downloads any missing models listed in
  `OLLAMA_MODELS_TO_PULL`, then exits with code 0. Existing models are skipped. `.env.example` and Compose download
  only `qwen3:14b`.
- Models are stored in the `games_ollama_data` volume (`/root/.ollama`). `down`, `up`, restarts, and container
  recreation preserve them. **`docker compose down -v` deletes this volume and the database volume.**
- Ollama provides inference only, not training or fine-tuning.

## Settings

| Variable | Read by | Meaning |
| --- | --- | --- |
| `OLLAMA_MODELS_TO_PULL` | The `ollama-models` container | Space-separated list of models to download (default: `qwen3:14b`) |
| `OLLAMA_CONTEXT_LENGTH` | The `ollama` container | Context size (default: 2048) |
| `OLLAMA_KEEP_ALIVE` | The `ollama` container | How long the model stays in memory after a request (default: `10m`) |
| `OLLAMA_MODEL` | Backend | Endpoint route model: `4` = `qwen3:4b-instruct`, `8` = `qwen3:8b`, `14` = `qwen3:14b` (default). Other values are rejected. The model must be included in `OLLAMA_MODELS_TO_PULL` |

NVIDIA GPU reservations are configured only in `docker-compose.gpu.yml`. The developer's RTX 3060 Laptop has
6 GB of VRAM, so the 14B model also uses system RAM and CPU; measure performance on your own machine. If 14B is too
demanding, use 8B or 4B, or use OpenRouter.

## Using Ollama for bot dialogue

The bot dialogue writer uses a **priority chain** (the **Otak NPC**, or NPC Brain, panel menu): OpenRouter and
"LLM sendiri lewat link" (custom LLM endpoint, `tautan`), followed by templates. The endpoint route uses the URL
saved in **Konfigurasi AI** (AI Configuration), or `OLLAMA_BASE_URL` if no URL has been saved in the panel.

**Local setup.** Compose already sets `OLLAMA_BASE_URL=http://ollama:11434` for the backend, so local Ollama becomes
the endpoint route automatically. Open **Otak NPC**, then click **Tes koneksi semua prioritas** (Test All Priority
Connections). Reorder the routes (▲▼) if the endpoint route should be tried first. Choose its model under
**Model LLM link** (Endpoint LLM Model); "Bawaan" (Default) uses the model from AI Configuration or `OLLAMA_MODEL`.

**Through a tunnel** (for example, with the backend on a VM). The quickest option is `ai-docker/jalankan.bat`
(Qwen3 + token gateway + Cloudflare tunnel). To use Ollama from the main Compose stack manually:

1. Start Ollama (see above) and make sure the model has been downloaded.
2. Open an HTTPS tunnel to the host port, for example:
   `cloudflared tunnel --url http://localhost:11435 --http-host-header localhost:11434`. If the endpoint returns 403,
   this host header is usually missing (Ollama rejects unfamiliar hosts).
3. Enter the tunnel URL in **Konfigurasi AI** and save it. The URL must use HTTPS and a public address. Enter the
   tunnel bearer token in the same panel (stored encrypted), or use `OLLAMA_TUNNEL_TOKEN` as a fallback.
4. Click **Tes koneksi semua prioritas** in the Otak NPC menu.

The backend recognizes both Ollama (`/api/tags`, `/api/chat`) and OpenAI-compatible servers (`/v1/models`,
`/v1/chat/completions`). If the selected model is unavailable at the endpoint, it uses a model from the same family
(for example, `qwen3:8b` instead of `qwen3:14b`) or the first available model. The panel shows the model actually used.

Each dialogue request has a 20-second timeout. Models that run slowly on CPU fall back to the next route or to
templates more often. If the endpoint route fails and OpenRouter is enabled with a key, dialogue is generated
through OpenRouter (which incurs charges); disable that route in the panel if you do not want this behavior.

## `AI_PROVIDER` and status checks

`AI_PROVIDER` does not select the dialogue writer route; the chain in the Otak NPC panel determines that.

- `AI_PROVIDER=docker`: AI Configuration opens with the Ollama or tunnel option selected, and `/app-status` checks
  whether the `OLLAMA_MODEL` model is available (`ollama_ready`).
- `AI_PROVIDER=api`: AI Configuration opens with OpenRouter selected, and `/app-status` reports the OpenRouter model.

After changing environment variables, recreate the backend (a restart alone does not load the new Compose environment):

```sh
docker compose up -d ollama ollama-models
docker compose up -d --force-recreate ai-engine
docker compose restart gateway
```

On NVIDIA machines, use the `docker compose -f docker-compose.gpu.yml` prefix so Ollama retains GPU access; do not
accidentally update NVIDIA Ollama using the CPU file. Restarting the gateway refreshes the backend container address
if it has changed. Check http://localhost:8000/app-status for `ai_provider`, `ai_model`, and `ollama_ready`.

Reference: [Ollama Docker](https://docs.ollama.com/docker).
