# ai-docker: bot dialogue LLM for the VM

This folder runs **Qwen3** in Docker on a laptop and exposes it to the internet through Cloudflare Tunnel. The game
backend on the VM uses it as the **"LLM sendiri lewat link"** (custom LLM endpoint, `tautan`) route in the bot dialogue
writer chain. This setup is separate from the main `docker-compose.yml`; for ordinary local Ollama, see
[OLLAMA.md](../OLLAMA.md).

```text
VM backend ──HTTPS + Bearer token──▶ Cloudflare tunnel ──▶ gateway (nginx, token check) ──▶ ollama
```

## Models

Two models are prepared. Select the model used by bots in the panel → **Otak NPC** (NPC Brain) → **Model LLM link**
(Endpoint LLM Model).

| Model | When to use it |
| --- | --- |
| `qwen3:4b-instruct` | Recommended. Measured at 1–2 seconds per message through the tunnel (RTX 3060 6 GB), without thinking mode. |
| `qwen3:14b` | Measured at 6–9 seconds per message once loaded. This 10 GB model does not fit in 6 GB of VRAM (64% runs on CPU). Initial loading takes about 80 seconds. Qwen3 has no 12B version; this is the closest size. |

## Folder contents

| File | Contents |
| --- | --- |
| `jalankan.bat` | Starts everything, waits for models to be ready, tests the endpoint from the internet, and sends the URL and token to the backend |
| `lihat-link.bat` | Displays the current URL and token (without restarting), then sends them to the backend again |
| `uji-waktu.bat` | Measures NLU → fuzzy logic → NLG/LLM time per bot through the panel simulation; writes CSV output to `communicationfolder/uji-waktu-<date>/` |
| `hentikan.bat` | Stops the LLM and tunnel (models remain stored) |
| `skrip/` | PowerShell scripts called by `jalankan.bat`, `lihat-link.bat`, and `uji-waktu.bat`. `kirim-link.ps1` sends the endpoint to the backend; `bersama.ps1` contains shared functions (`.env`, tunnel URL, panel login) |
| `docker-compose.yml` | Services: `ollama`, `model` (one-time download), `gerbang`, and `tunnel` |
| `docker-compose.gpu.yml` | NVIDIA GPU override, used automatically when `nvidia-smi` is available |
| `gerbang.conf.template` | Forwards only `/api/tags`, `/api/show`, `/api/chat`, and `/api/version`, with a valid token |
| `.env.example` | Example `.env` contents |
| `.env` | Created automatically: random `LLM_TOKEN`, `LLM_MODELS`, and panel login (`PANEL_USERNAME`, DPAPI-encrypted password). Optional `BACKEND_URL` (default: `https://backendthesis.andylabs.site`). Excluded from Git |

Older `uji-waktu.bat` results were measured when bots used mixed methods (Fuzzy, Utility AI, and Behavior Tree), so
they do not apply to the current fuzzy brain.

## Usage

1. Open Docker Desktop, then double-click `jalankan.bat`.
   - Missing models are downloaded to the `silent_terror_ai_model` volume: approximately 2.5 GB for 4B and 9 GB for 14B.
   - On the first run, the script asks for the **admin panel** username and password. Both are stored in `.env`
     (the password is encrypted with DPAPI and can only be decrypted by this Windows account). They are not requested
     again unless login is rejected.
   - Finally, the script sends the URL and token to the backend through the panel API (equivalent to filling in
     **Konfigurasi AI**, or AI Configuration, and saving). It makes "LLM sendiri lewat link" the first priority in
     the **Otak NPC** writer chain (other enabled routes remain fallbacks), then displays the connection test result
     from the VM. The selected provider and model are unchanged.
2. Choose the endpoint model in the panel → **Otak NPC** → **Model LLM link** (`qwen3:4b-instruct` is fast;
   `qwen3:14b` is more capable). "Bawaan" (Default) uses the model from AI Configuration. After switching to
   `qwen3:14b`, wait about 1–2 minutes for the model to load, then click **Tes koneksi semua prioritas** (Test All
   Priority Connections) again.
3. If sending fails (for example, because the backend is down), the URL is already on the clipboard: paste it
   manually into the panel → **Konfigurasi AI**, then save.

## Things to remember

- **The URL changes** whenever the tunnel restarts, such as after restarting the laptop or running `hentikan.bat`.
  Run `jalankan.bat` (or `lihat-link.bat` if the containers are still running) to send the new URL. The token stays
  the same as long as `.env` is not deleted.
- The laptop must stay on and Docker must keep running while the game is being played. If it goes offline, bots
  use the next route in the chain (for example, OpenRouter), then templates.
- Each dialogue request has a 20-second timeout. Large, slow models fall back to the next route or to templates
  more often.
- Without a token, the endpoint returns 401. Endpoints other than the four listed above (pull, delete, and so on)
  return 404.
- This is a Cloudflare *quick tunnel*: free, with no account required and no uptime guarantee. A permanent URL
  requires a Cloudflare account and a named tunnel.
