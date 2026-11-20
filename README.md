# Silent Terror

Silent Terror is a web-based social deduction game. Hitmen hide among the townspeople, and players try to identify
them through conversation, alibis, and voting. **Zero economy**: no money, item purchases, or ransom payments. NPC
bots can fill empty seats. Their brains interpret chat with IndoBERT, make decisions with Mamdani fuzzy logic,
and generate dialogue through an LLM or templates.

This README is the repository's starting point: an overview, local setup instructions, and a guide to the other
documentation. Game rules are in [GAME_CONCEPT.md](GAME_CONCEPT.md), and the code structure is explained in
[CODE_GUIDE.md](CODE_GUIDE.md). Linked documentation and application labels may still be in Indonesian; UI labels
below retain their original names so you can find them in the application.

The repository is named `GamesSilentTerror`. The database (`shadow_heist`), containers (`shadow_*`), and parts of
the code still use the project's former name, Shadow Heist.

This game is part of an undergraduate thesis. The manuscript is available here:
[Silent Terror thesis manuscript (BINUS OneDrive)](https://binusianorg-my.sharepoint.com/personal/andy_saputra001_binus_ac_id/_layouts/15/guestaccess.aspx?share=IQDKQcDT5f1NSIhXTwwSsCgVAUckMBzh9nTX9KbN52iZ1sE&e=RmW4Ck).

## Documentation map

| File | Contents | Read when |
| --- | --- | --- |
| `README.md` (this file) | Overview, local setup, admin panel, containers, and data | Opening the repository for the first time |
| [GAME_CONCEPT.md](GAME_CONCEPT.md) | Game rules, bot behavior, and role composition balance | Learning how to play or how bots behave |
| [CODE_GUIDE.md](CODE_GUIDE.md) | Folder structure, layer boundaries, code style, bot and fuzzy logic changes, tests, and simulations | Changing the code |
| [backend/README.md](backend/README.md) | Environment variables, panel settings, running the backend without Docker, and model SQL patterns | Configuring `.env`, keys, or models |
| [backend/migrations/README.md](backend/migrations/README.md) | SQL migration list and how to add migrations | Changing database tables |
| [backend/deployment/README.md](backend/deployment/README.md) | Routine backend updates on an Azure VM: backups, migrations, and builds | Updating production |
| [backend/deployment/AZURE_SETUP.md](backend/deployment/AZURE_SETUP.md) | Initial Azure VM setup, DNS, Google OAuth, and Vercel | Setting up a new server |
| [OLLAMA.md](OLLAMA.md) | Local Ollama and LLM endpoints for bot dialogue generation | Using your own LLM |
| [ai-docker/README.md](ai-docker/README.md) | Exposing a laptop-hosted LLM to the VM through Cloudflare Tunnel | Letting the VM use your laptop's GPU |
| [frontend/STYLING.md](frontend/STYLING.md) | Color tokens, fonts, and per-page CSS files | Changing the appearance |
| [frontend/DEPLOYMENT.md](frontend/DEPLOYMENT.md) | Deploying the frontend to Vercel | Publishing the frontend |
| [frontend/docker/README.md](frontend/docker/README.md) | Running a local frontend against the production backend | Working only on the frontend |

**Web documentation** is available in the administrator panel under **08 Dokumen** (files in
`backend/public/dokumen/`). Start with **Peta Dokumen** (Documentation Map), which explains the contents and
suggested reading order: System Architecture, ERD, AI Process, Backend Flow Walkthrough, NLU Dataset, NLU
Flowchart, NLU Intent Code, NLU Target Code, Fuzzy Logic Flowchart, Fuzzy Brain Walkthrough, How Bots Work,
Fuzzy Logic Code, and NLG Code. Each document card identifies its source: **Training** (built from notebooks and
datasets in the prethesis repository), **Backend** (built from game code), or **Panduan** (a guide summarizing
other documents). The HTML files in this repository are copies of generated documents from
`communicationfolder/<topic>-<date>/`, a local folder excluded from Git. Edit the source, regenerate the
documents, and copy the output to `backend/public/dokumen/`.

**Thesis notebooks** live outside this repository in `../training/prethesis/ai_2_dataset_baru/`
(`npc_fuzzy.ipynb`, `npc_nlg.ipynb`, and the NLU notebooks). The notebooks are for the research report only.
The source of bot logic is `backend/app/bot/`; see [CODE_GUIDE.md](CODE_GUIDE.md#mengubah-logika-bot).

## Implemented features

- Account registration, username/password login, Google login, and avatar selection (6 skins, saved per account).
  Email addresses entered during registration are not stored because they are not verified. Display names that
  confuse bot interpretation (pronouns, game terms, or names without letters or numbers) are rejected.
- A main page, rooms for 4–10 participants, and optional bots to fill empty seats (added individually, up to 5).
  Only the room creator can manage bots and start the game.
- Server-assigned random roles, a preparation screen, day → Tribunal → night rounds (no Tribunal in round 1)
  until a team wins, skills and cooldowns, voting, executions, nighttime team chat, and win conditions.
- A post-match survey with questions managed through the panel. The default set contains ten formal research
  questions from migration V12 ([V12 notes](backend/migrations/README.md#catatan-v12)).
- An administrator panel at `/panel` with eight menus (see [Administrator panel](#administrator-panel)).

Roles: **Hitman** (Hostage, Gag Order), **Spy** (Guard), **Stalker** (Peek), and **Civilian**. Detailed rules,
phase durations, and bot behavior are documented in [GAME_CONCEPT.md](GAME_CONCEPT.md).

## System overview

| Component | Technology | Location |
| --- | --- | --- |
| Frontend | Angular 21 | `frontend/` |
| Backend | Python 3.11, FastAPI for HTTP, Socket.IO for chat | `backend/app/` |
| Database | MySQL 8.4, database `shadow_heist` | `backend/migrations/` (schema) |
| Bot brain | IndoBERT (chat interpretation), Mamdani fuzzy logic (21 systems), NLG (LLM or templates) | `backend/app/bot/` |
| Gateway | Local Nginx (`proxy/nginx.conf`); Caddy on Azure | `proxy/`, `backend/deployment/` |

The backend is the source of truth. The match engine validates every action, vote, and chat message, including
those from bots. If a bot brain fails, engine fallback actions fill in missing actions. Human chat is only
validated, stored, and broadcast; bots interpret it independently through IndoBERT.

The bot brain has three stages. See [GAME_CONCEPT.md](GAME_CONCEPT.md#npc-otak-bot) for details and
[CODE_GUIDE.md](CODE_GUIDE.md#otak-bot-di-kode) for the corresponding code locations.

| Stage | Purpose |
| --- | --- |
| NLU (IndoBERT, two models: intent and target) | Interprets chat as an intent (accuse, defend, or neutral) and identifies the target |
| Reasoning (Mamdani fuzzy logic) | Selects accusations, defenses, votes, and night actions |
| NLG (an LLM writer chain, then templates) | Turns plans into dialogue. Failed LLM routes are skipped; if no route is available, the bot uses templates |

All bots use the fuzzy brain. Previously archived methods are listed in
[GAME_CONCEPT.md](GAME_CONCEPT.md#metode-yang-diarsipkan).

## Running locally

### Prerequisites

- Git and Docker with the `docker compose` command. If using Docker Desktop, start it first and use Linux
  containers.
- Internet access to download images, dependencies, and models.
- Available local ports `4200`, `8000`, and `3307`. Ollama mode also uses `11435`.
- For Ollama mode: sufficient RAM and disk space. The CPU version does not require a GPU; the NVIDIA version
  requires a GPU and drivers accessible to Docker.

You do not need Python, Node.js, or MySQL installed on the host when running everything through Docker.

### Setup

1. **Clone the repository**, then run all Compose commands from this directory (which contains `docker-compose.yml`):

   ```sh
   git clone https://github.com/Andysaputra1/GamesSilentTerror.git
   cd GamesSilentTerror
   ```

2. **Create `.env`** once during initial setup. Do not overwrite an existing configured `.env`; it contains secrets
   and must not be committed.

   ```powershell
   Copy-Item .env.example .env      # Windows PowerShell
   ```

   ```sh
   cp .env.example .env             # Linux/macOS
   ```

   Each variable is explained in [backend/README.md](backend/README.md#variabel-environment).

3. **Copy the two IndoBERT models** (approximately 440 MB each, ignored by Git). Without these models, the bot brain
   cannot load: bots will not chat and will use only engine fallback actions.

   ```text
   backend/artifacts/indobert/intent/  ← models/notebook_standalone/intent_classifier_transformer
   backend/artifacts/indobert/target/  ← models/target_classifier/target_classifier_transformer
   ```

   The source is the `models/` folder in `../training/prethesis/ai_2_dataset_baru/`. The target model folder must
   include `pair_builder.json` and `ambang_target.json` generated by `nlu_target.ipynb`. When the backend runs
   directly on the host (outside Docker), it can also find the models in that neighboring notebook directory.

4. **Choose a Compose file.** Both are standalone files (not a base/override pair), with the same services, ports,
   and volumes. Do not run both at once, and use the same file for every subsequent command.

   | File | Use case |
   | --- | --- |
   | `docker-compose.yml` | CPU, including MacBooks and machines without NVIDIA GPUs. Commands without `-f` use this file |
   | `docker-compose.gpu.yml` | NVIDIA GPU. Add `-f docker-compose.gpu.yml` to every command |

5. **Start the stack** using one of the modes below: [A. Local Ollama](#a-local-llm-through-ollama) or
   [B. OpenRouter](#b-llm-through-openrouter-without-ollama).

6. **Set up the panel login** once from the repository root (requires Python with backend dependencies; you can
   also run it inside the container and copy the results to `.env`):

   ```sh
   python backend/scripts/setup_panel.py .env
   ```

   This script writes `PANEL_USERNAME=administrator` and `PANEL_PASSWORD_HASH`, and creates `PANEL_ENCRYPTION_KEY`
   if it is missing. Keep that key safe: API keys saved through the panel are encrypted with it. Then recreate
   the backend (see [Containers and data](#containers-and-data)).

7. **Open the application** using the [Local addresses](#local-addresses) table, then follow
   [Trying the game](#trying-the-game).

### A. Local LLM through Ollama

Set these values in `.env`:

```dotenv
AI_PROVIDER=docker
OLLAMA_MODEL=14
OLLAMA_MODELS_TO_PULL=qwen3:14b
```

```sh
# CPU or MacBook (Ollama runs in Docker; no macOS installation is needed)
docker compose up -d --build
docker compose logs -f ollama-models

# NVIDIA machine
docker compose -f docker-compose.gpu.yml up -d --build
docker compose -f docker-compose.gpu.yml logs -f ollama-models
```

The first startup downloads images and models, so it may take a while. `Ctrl+C` only exits the log viewer.
It is normal for `ollama-models` to stop with exit code `0`: its only job is to download models. The bot dialogue
writer uses this Ollama instance through the custom LLM endpoint route. Model options (`4`, `8`, `14`), CPU
performance, and model checks are covered in [OLLAMA.md](OLLAMA.md).

### B. LLM through OpenRouter, without Ollama

Set these values in `.env` (you can also enter the key later in the **Konfigurasi AI** panel):

```dotenv
AI_PROVIDER=api
OPENROUTER_API_KEY=your_personal_key_here
```

Start only the application services and their dependencies:

```sh
docker compose up -d --build mysql phpmyadmin ai-engine gateway frontend
```

Running `docker compose up` without a service list also starts Ollama and its model downloader. An existing Ollama
instance does not stop automatically when you switch modes; stop it with `docker compose stop ollama-models ollama`.
Only the backend reads the API key, and usage may incur charges on your OpenRouter account.

Configure the OpenRouter dialogue model in the **Otak NPC** panel (or through `NPC_OPENROUTER_MODEL`); the code
default is `qwen/qwen3-14b`. The production model is documented in
[backend/deployment/README.md](backend/deployment/README.md#panel-dan-secret-di-vm).

### Local addresses

| Destination | Address |
| --- | --- |
| Application | http://localhost:4200 |
| Administrator panel | http://localhost:8000/panel |
| Backend status (database, provider, model) | http://localhost:8000/app-status |
| Database and migration readiness, IndoBERT status | http://localhost:8000/ready |
| API documentation (local only; disabled in production) | http://localhost:8000/docs |
| phpMyAdmin | http://localhost:8000/phpmyadmin/ |
| MySQL from the host or a database client | `localhost:3307`, database `shadow_heist` |
| Ollama from the host (mode A) | http://localhost:11435 |

Log in to phpMyAdmin with `MYSQL_USER` and `MYSQL_PASSWORD` from `.env`, not a game account. The backend and
phpMyAdmin share port `8000` through the Nginx gateway; port `3307` is only for MySQL connections. Both ports are
accessible only from this laptop (bound to `127.0.0.1`) because MySQL root and phpMyAdmin use example passwords.
Port `4200` remains accessible over the network for [LAN testing](#lan-testing).

## Trying the game

A new database has no accounts. Create an account using the registration button on the login page, Google login,
the **Manajemen user** panel, or the CLI below.

1. Log in and select **Enter Tribunal** on the main page.
2. Select **Buat Ruangan** (Create Room) and choose a capacity, or **Gabung** (Join) with a room code.
3. The room owner clicks **+ Tambah bot** (Add Bot) once for each desired bot (up to 5, subject to available seats),
   or **− Kurangi bot** (Remove Bot) to remove them individually. Bots let you try the game alone; without bots,
   prepare at least 4 accounts.
4. The room owner clicks **Mulai Permainan** (Start Game); other members click **Masuk Permainan** (Enter Game).
5. After the match, complete the survey, return to the lobby → leave the room → create a new room. Each room is
   used for only one match.

Use standard phase durations to try AI chat. Bot decisions or dialogue completed after a phase changes are
discarded, so the short phases in fast mode can prevent many bot messages from appearing.

The same account in multiple tabs still represents one player. You can create friends' accounts through the local
CLI, which follows the same rules as the registration page. Password input is hidden, passwords are stored as
hashes, and existing accounts are not overwritten:

```sh
docker compose exec ai-engine python scripts/create_user.py friend1 --name "Friend One"
```

## Administrator panel

The panel is available at http://localhost:8000/panel and uses a separate administrator account (setup step 6
above). Game accounts cannot sign in to the panel. Panel sessions last 8 hours and are invalidated when the
panel password changes.

| Menu | Contents |
| --- | --- |
| 01 Konfigurasi AI (AI Configuration) | Provider (`api` or `docker`), OpenRouter key source, custom LLM endpoint URL and token, local model |
| 02 Checker | Per-room phase, composition, and live bot state; traces for each human message (validate → store → broadcast) and bot step (NLU, reasoning, dialogue writing), with a process flow showing the active stage, stage durations, and explicit errors (type, message, failed stage); an **Antrean** (Queue) box for the brain worker (1 thread) and writer workers (6 threads) shared across all rooms, plus panel simulation workers (1 reasoning thread, 2 writer threads) |
| 03 Riwayat chat (Chat History) | MySQL chat archives with filters and CSV export, including IndoBERT intent, target, and interpretation context |
| 04 Manajemen user (User Management) | Add users, edit display names or usernames, reset local account passwords, and delete accounts without deleting chat history |
| 05 Otak NPC (NPC Brain) | Dialogue writer, writer chain order, OpenRouter model, custom endpoint LLM model, **Tes koneksi semua prioritas** (Test All Priority Connections) button, and IndoBERT NLU status |
| 06 Survei (Survey) | Survey questions and ordering, respondent count, per-question answer charts, respondent list (latest submission per person), CSV exports per person or for all submissions, and response cleanup (details in [GAME_CONCEPT.md](GAME_CONCEPT.md#akhir-pertandingan-dan-survei)) |
| 07 Simulasi (Simulation) | Simulated matches with an administrator and 3–9 bots using the real brain: chat, an AI process flowchart highlighting each active stage, and the actual code for each stage |
| 08 Dokumen (Documents) | System web documentation, starting with Peta Dokumen (see [Documentation map](#documentation-map)) |

**CSV exports.** Both survey and chat exports use UTF-8 with a BOM.

- Survey exports have two buttons with the same columns. **CSV per orang** (`survei_silent_terror.csv`) contains
  one row per account, using its latest submission (matching the panel charts). **CSV semua kiriman**
  (`survei_silent_terror_semua_kiriman.csv`, `GET /api/panel/survey/responses.csv?semua=true`) contains one row per
  submission (one account in one match), including older submissions from repeat respondents. Columns are
  `created_at`, `match_id`, `room_code`, `username`, `display_name`, `role`, `team`, `outcome`, followed by one
  column for each question with answers, titled `code: question text` and ordered by panel position, and finally
  `bots` (bots in that match, formatted as `name:method:persona` and separated by ` | `). Question values are
  numbers for scales or text for choices and free-text answers. Text starting with `=`, `+`, `-`, `@`, a tab, or
  CR is prefixed with `'` so spreadsheet applications do not execute it as a formula. Numbers remain numeric.
- Chat history (`riwayat-chat.csv`) preserves message content exactly because it is used as an NLU dataset.
  Columns are `pengirim`, `teks_chat`, `label_intent`, `chat_sebelumnya`, `daftar_pemain`, `target`, `session_id`,
  `chat_id`, `room_code`, `confidence`, `sender_kind`, and `waktu_utc`. Date filters use Western Indonesian Time
  (WIB), and the sender filter supports `all`/`human`/`bot`/`legacy` (older messages are not guessed to be human
  or bot). When opening this file in a spreadsheet, import `teks_chat` as text.

Panel key, model, and endpoint settings are explained in
[backend/README.md](backend/README.md#pengaturan-dari-panel).

## Google login

1. In Google Cloud Console, create an OAuth client of type **Web application** with
   `http://localhost:4200` as an Authorized JavaScript origin. A redirect URI is not required because the flow
   uses a popup.
2. Set `GOOGLE_CLIENT_ID=...apps.googleusercontent.com` in `.env`, then recreate the backend. A Client Secret is
   not used; do not put credential JSON in `.env`.
3. Deployment domains must use HTTPS and be registered as origins. Google login does not support LAN IP addresses
   over HTTP, but password login remains available over LAN.

Account, session, and token verification rules are in [CODE_GUIDE.md](CODE_GUIDE.md#akun-sesi-dan-login).
Official guides: [Google Identity Services setup](https://developers.google.com/identity/gsi/web/guides/get-google-api-clientid)
and [backend token verification](https://developers.google.com/identity/gsi/web/guides/verify-google-id-token).

## Containers and data

```sh
docker compose ps -a                 # Status, including completed initializers
docker compose logs -f ai-engine     # Backend logs; Ctrl+C to exit
docker compose down                  # Stop without deleting volumes
```

After changing `.env`, recreate the backend (a restart alone does not load the new environment):

```sh
docker compose up -d --force-recreate ai-engine
docker compose restart gateway
```

- To start again, repeat the `up` command for mode A or B. Use `--build` when images or dependencies change.
- Python code is bind-mounted, so code changes only require `docker compose restart ai-engine`. The frontend
  watches its source files automatically.
- To switch Compose files, stop the old stack (`down` without `-v`), then run `up` with the new file from the same
  directory. Existing volumes are reused.
- The database is stored in `shadow_heist_mysql_data`, and Ollama models are stored in `games_ollama_data`.
  **Do not use `docker compose down -v` if you still need the data or models**: it deletes both volumes. Volumes
  are not a substitute for backups.
- Restarting or recreating the backend clears active matches because match state is held only in memory
  ([Implementation limits](CODE_GUIDE.md#batas-implementasi)). Chat archives in MySQL are preserved.
- SQL files in `backend/migrations/` (V01–V12) run automatically only when the database volume is first created.
  Existing databases require new migrations to be applied manually; see
  [backend/migrations/README.md](backend/migrations/README.md).

## LAN testing

The development frontend allows `localhost`, `127.0.0.1`, and the developer's LAN IP `192.168.40.176`. For another IP:

1. Update both `allowedHosts` lists (build and serve) in `frontend/angular.json`.
2. Add the full origin to `CORS_ORIGINS` in `.env`, for example:
   `CORS_ORIGINS=http://localhost:4200,http://127.0.0.1:4200,http://192.168.40.176:4200`. This list applies to both
   the HTTP API and Socket.IO. Do not use a wildcard.
3. Expose port `8000` to the network with `GATEWAY_BIND=0.0.0.0` in `.env`. The default is `127.0.0.1`, which
   prevents other devices from calling the backend. This also exposes phpMyAdmin to the LAN during testing, so
   restore `127.0.0.1` afterward.
4. Apply the changes: `docker compose up -d --force-recreate ai-engine frontend gateway`.
5. Friends on the same network can open `http://<LAN-IP>:4200`. Do not use a WSL adapter IP.

If other devices still time out, check the firewall and Wi-Fi client isolation. Do not expose MySQL or phpMyAdmin
to the internet, and do not disable the entire firewall.

## Frontend development through Docker

The `frontend` service already runs the Angular development server at http://localhost:4200, so you do not need
to run `ng serve` on the host. `frontend/src` and `frontend/public` are mounted into the container, allowing
source changes to be detected automatically.

```sh
# Generate a new component (the container must be running)
docker compose exec frontend npx ng generate component features/component-name

# After changing dependencies in frontend/package.json
docker compose up -d --build frontend
```

Build output is in `/app/dist/frontend` inside the container and is not mounted onto the host. Do not edit `dist`
as source code. There is no `ng e2e` target yet. Test and build commands are in
[CODE_GUIDE.md](CODE_GUIDE.md#tes-dan-simulasi); styling guidance is in [frontend/STYLING.md](frontend/STYLING.md).

## Troubleshooting

| Symptom | What to check |
| --- | --- |
| Cannot connect to Docker | Make sure Docker Engine or Desktop is running; run `docker info` |
| NVIDIA device or driver error | The GPU file is only for NVIDIA machines; on a Mac, use the CPU file or mode B |
| Port already in use | Stop the other service using that port. Changing ports also requires updates to frontend URLs, CORS, and the proxy |
| Login fails or the backend is not ready | Check `docker compose ps -a`, the `ai-engine` and `mysql` logs, and `/ready`. An existing database may be missing the latest migrations |
| Bots are silent or their dialogue sounds rigid | Open **Otak NPC**: NLU must show IndoBERT, and at least one writer route must be available (or use `NPC_WRITER=templat`). Check `database_ready` in `/app-status` |
| Bots respond slowly in large rooms | Open **Checker**: the process flow identifies slow stages, and the Antrean box shows jobs waiting for brain or writer threads. All rooms share these threads (see [Implementation limits](CODE_GUIDE.md#batas-implementasi)) |
| Cannot log in to the panel | Make sure `PANEL_PASSWORD_HASH` was generated with `setup_panel.py` and the backend has been recreated |
| Room not found | The backend may have restarted, the invite code may be incorrect, or the room may have been idle too long (idle lobbies are removed after 1 hour; completed rooms after 30 minutes). Create a new room |
| Chat too fast / too many attempts | Chat is limited to 1 message per 2 seconds and 5 per 20 seconds per player (rejected text returns to the input box); failed room joins are limited to 10 per account per minute; 10 incorrect passwords within 15 minutes temporarily block that account. Wait as instructed by the message |
| Unexpected return to login with "Sesi berakhir" (Session expired) | The server rejected the stored token (account disabled, session revoked, or incorrect device time). Log in again |
| Page reloads with "Akun berganti di tab lain" (Account changed in another tab) | Another tab in the same browser logged in with a different account. One browser uses one account; test two accounts using an incognito window or a separate browser profile |

## Security notes

- Checker traces and prompts are accessible only through `/panel` with an administrator session. They can contain
  roles and private bot information (`penjelasan`: role, suspicion, reasoning), so administrators must be separate
  from experiment participants. Traces show application inputs and outputs, not the model's internal chain of thought.
- This Compose setup is for local development. Before public deployment, replace default credentials, restrict
  access to database and phpMyAdmin ports, and configure HTTPS. Production deployment is documented in
  [backend/deployment/README.md](backend/deployment/README.md).
- Do not commit `.env`, API keys, user uploads, models, or private artifacts. `communicationfolder/` and `plan/`
  are also ignored by Git.
