# Deploying the Backend to Azure

This document covers updates to the production backend on the Azure VM: server layout, routine updates, backups,
migrations on existing databases, and panel settings on the VM. Initial setup (DNS, firewall, Google OAuth,
Vercel) is covered in [AZURE_SETUP.md](AZURE_SETUP.md). Each migration is described in
[backend/migrations/README.md](../migrations/README.md).

## Production layout

| Component | Details |
| --- | --- |
| Addresses | Backend `https://backendthesis.andylabs.site`, panel `https://backendthesis.andylabs.site/panel`, frontend `https://silent-terror.andylabs.site` (Vercel) |
| VM | Azure, 2 vCPUs without a GPU. IndoBERT and fuzzy logic run on the VM CPU; the dialogue writer uses OpenRouter or a laptop-hosted LLM through `ai-docker/` |
| Frontend | Automatically rebuilt by Vercel on every push to `main`; no frontend steps run on the VM ([frontend/DEPLOYMENT.md](../../frontend/DEPLOYMENT.md)) |
| Repository on VM | `~/GamesSilentTerror`, with secrets in `.env.azure` (ignored by Git; do not share) |
| Compose | `docker-compose.azure.yml`, always used with `--env-file .env.azure` |
| `mysql` | MySQL 8.4.11. External volume `shadow_heist_mysql_data`; `backend/migrations/` mounted at `/docker-entrypoint-initdb.d`. No host port and no phpMyAdmin |
| `backend` | Image built from `deployment/Dockerfile.azure`: Python 3.11.18, CPU PyTorch, uvicorn with **one worker**, and `--proxy-headers` so player IPs come from Caddy. `AI_PROVIDER=api`, `API_DOCS=false` (no `/docs`) |
| `proxy` | Caddy 2.11.4 (`deployment/Caddyfile`), ports 80 and 443, automatic HTTPS certificates for `BACKEND_DOMAIN`, HSTS, `nosniff`, and `Referrer-Policy` headers, and a 1 MB body limit. Certificates are stored in external volume `silent-terror-azure_caddy_data`. Starts only when the backend is healthy |

Base image versions (`python:3.11.18-slim`, `mysql:8.4.11`, `caddy:2.11.4-alpine`) and all direct dependencies in
`backend/requirements.txt` are pinned, so rebuilding installs the same versions. Upgrade them deliberately and
test before deployment.

The backend image copies the entire `backend/` directory except `tests/` (see `backend/.dockerignore`). The
IndoBERT models in `backend/artifacts/indobert/{intent,target}` must already exist on the VM before building; the
build stops with a message if either is missing. Models are copied into a separate layer before the code, so
code-only deployments reuse the model layer (approximately 950 MB) rather than adding that much disk usage.

Run all commands below from `~/GamesSilentTerror` with the same Compose prefix:

```bash
cd ~/GamesSilentTerror
sudo docker compose --env-file .env.azure -f docker-compose.azure.yml ps
```

## Routine updates

1. **Choose a time with no active matches.** Recreating the backend clears ongoing matches; chat archives remain.
2. **Fetch the code:** `git pull --ff-only`.
3. **Check for new migrations.** Compare files in `backend/migrations/` with `schema_migrations`
   (see [Applying migrations](#applying-migrations-to-an-existing-database)). New files **do not** run
   automatically because the production volume already contains data.
4. **If there are new migrations:** [back up](#database-backups) first, then apply unrecorded files before
   starting the new backend version.
5. **Build and start the backend:**

   ```bash
   sudo docker compose --env-file .env.azure -f docker-compose.azure.yml up -d --build backend
   ```

   A build may take around 10 minutes with an empty cache. If SSH disconnects frequently, run it in the background
   and monitor its log; do not start a second build while the first is running. This example omits `sudo`
   (which cannot prompt for a password in the background), so the VM user must belong to the `docker` group.

   ```bash
   nohup docker compose --env-file .env.azure -f docker-compose.azure.yml up -d --build backend \
     > /tmp/deploy.log 2>&1 < /dev/null &
   tail -f /tmp/deploy.log
   ```

6. **If `deployment/Caddyfile` or the `proxy` section in `docker-compose.azure.yml` changes**, recreate the proxy.
   Caddyfile is mounted as a file, and `git pull` replaces it with a new file, so the existing container keeps
   reading the old contents until recreated. The proxy will stop for a few seconds.

   ```bash
   sudo docker compose --env-file .env.azure -f docker-compose.azure.yml up -d --force-recreate proxy
   ```

7. **Check the result:**

   ```bash
   sudo docker compose --env-file .env.azure -f docker-compose.azure.yml ps
   sudo docker compose --env-file .env.azure -f docker-compose.azure.yml logs --tail=60 backend proxy
   curl -fsS https://backendthesis.andylabs.site/ready
   ```

   `/ready` returns 503 if MySQL does not respond or required migrations are missing (listed in `migrasi_kurang`).
   It reports IndoBERT status in `indobert` (`memuat` = loading shortly after startup, then `siap` = ready).
   See [backend/README.md](../README.md#when-mysql-has-problems) for details. Also try logging in, creating a room,
   and sending chat from the frontend.
8. **If VM disk space is low**, remove unused images and build cache. Leave volumes untouched.

   ```bash
   sudo docker image prune -a
   sudo docker builder prune -a
   ```

## Database backups

The root password is read from the container environment, so it does not need to be typed or printed:

```bash
sudo docker compose --env-file .env.azure -f docker-compose.azure.yml exec -T mysql \
  sh -c 'exec mysqldump -uroot -p"$MYSQL_ROOT_PASSWORD" --single-transaction --routines --triggers shadow_heist' \
  > backup_sebelum_VXX_$(date +%Y%m%d_%H%M).sql
```

Keep a copy of the dump outside the VM. External volumes (database and Caddy certificates) are not removed by
`down` or `down -v`, but manually deleting a volume or losing the VM disk still destroys the data. Volumes are
not backups.

## Applying migrations to an existing database

1. Open the MySQL client:

   ```bash
   sudo docker compose --env-file .env.azure -f docker-compose.azure.yml exec mysql \
     sh -c 'exec mysql -uroot -p"$MYSQL_ROOT_PASSWORD" shadow_heist'
   ```

2. List recorded versions: `SELECT version FROM schema_migrations;`
3. Apply files whose versions are missing, in order:

   | Version in `schema_migrations` | Command |
   | --- | --- |
   | `V5__chat_history` | `SOURCE /docker-entrypoint-initdb.d/V05__chat_history.sql;` |
   | `V6__admin_panel` | `SOURCE /docker-entrypoint-initdb.d/V06__admin_panel.sql;` |
   | `V7__add_skin_preference` | `SOURCE /docker-entrypoint-initdb.d/V07__add_skin_preference.sql;` |
   | `V7__survey_and_npc` | `SOURCE /docker-entrypoint-initdb.d/V07__survey_and_npc.sql;` |
   | `V8__fix_role_stalker_enum` | `SOURCE /docker-entrypoint-initdb.d/V08__fix_role_stalker_enum.sql;` (first ensure `SELECT COUNT(*) FROM players WHERE role = 'detective';` returns 0) |
   | `V9__chat_nlu` | `SOURCE /docker-entrypoint-initdb.d/V09__chat_nlu.sql;` |
   | `V10__match_participants` | `SOURCE /docker-entrypoint-initdb.d/V10__match_participants.sql;` |
   | `V11__survey_player_feedback` | `SOURCE /docker-entrypoint-initdb.d/V11__survey_player_feedback.sql;` |
   | `V12__survey_formal` | `SOURCE /docker-entrypoint-initdb.d/V12__survey_formal.sql;` (back up first: V12 deletes unanswered older survey questions and participant archives from before November 13, 2026) |

   Alternatively, send a file through stdin without opening an interactive client:
   `sudo docker compose ... exec -T mysql sh -c 'exec mysql -uroot -p"$MYSQL_ROOT_PASSWORD" shadow_heist' < backend/migrations/V12__survey_formal.sql`.

Azure databases created before October 26, 2026 use an older baseline: `AZURE_BASELINE_1` replaces V1–V4, so
**do not run V01–V04 on those databases**. Do not delete volumes to force migrations. If SQL fails partway
through, inspect the column structure before retrying because `ALTER TABLE` cannot be rolled back together
with the migration-marker `INSERT`.

## Table audit

The complete schema contains 15 tables. `players` differs from `user_accounts`: one account can participate in
many rooms.

| Table | Backend usage |
| --- | --- |
| `user_accounts`, `auth_sessions`, `account_identities` | Accounts, login sessions, and Google identities (`models/auth_queries.py`). Older `account_identities` rows without a Google `sub` (registration form email, `email_verified = 0`) are not used for login and are automatically removed when Google login uses the same email; no migration is needed |
| `game_sessions`, `players` | Room and room participant identities (`models/game_queries.py`) |
| `chat_messages` | Human and bot chat archives with NLU interpretations (`game_queries.py`, `panel_queries.py`) |
| `checker_traces` | Completed Checker traces (`game_queries.py`, `panel_queries.py`) |
| `panel_configuration`, `panel_sessions` | Panel settings (row 1 Konfigurasi AI / AI Configuration, row 2 Otak NPC / NPC Brain) and administrator sessions (`panel_queries.py`) |
| `survey_questions`, `survey_responses`, `match_bots`, `match_participants` | Surveys, bot methods and personas, and completed-match participants (`survey_queries.py`) |
| `schema_migrations` | Migration version records; read by `/ready` |
| `ai_analyses` | Archived SVM/fuzzy analyses and older bot replies. No longer written |

Legacy columns `players.aggressiveness`, `players.suspicion_score`, `chat_messages.intent`, and
`chat_messages.suspicion_score` have not been populated since the old analysis was removed; their data is retained
as an archive.

**Chat history.** Human chat is stored before broadcasting; bot chat is stored in separate rows. Because the
commit precedes the broadcast, an archive entry does not prove that every browser received the message. Nothing
is automatically deleted on logout, leaving a room, or restart. Messages from before V5 are marked `legacy`;
their original bot identities or rounds are not reconstructed. Old rooms never recorded in the database and
traces from before V6 cannot be recovered.

## Panel and secrets on the VM

- `setup_azure.py` (initial setup) or `python3 backend/scripts/setup_panel.py .env.azure` (password change) writes
  `PANEL_PASSWORD_HASH` and creates `PANEL_ENCRYPTION_KEY` once. The key is retained when the password changes.
  Keep a backup separately from the database: keys saved through the panel cannot be decrypted if it is lost.
  `setup_panel.py` requires an environment filename (the script stops without an argument), and both scripts
  write the file with permissions `600`.
- The panel username remains `administrator` (set in Compose). Administrator sessions last 8 hours, can be revoked
  by logging out, and become invalid after the password hash changes. Panel tokens exist only in tab memory, so
  refreshing the page requires logging in again.
- Other variables in `.env.azure`: `GOOGLE_CLIENT_ID`, `FRONTEND_ORIGIN` (mapped to `CORS_ORIGINS`),
  `BACKEND_DOMAIN`, `openrouter_default`, optional `OPENROUTER_API_KEY`, `OLLAMA_TUNNEL_TOKEN`, and `NPC_*`.
  Each variable is explained in [backend/README.md](../README.md#environment-variables).
- After changing `.env.azure`, apply it with
  `sudo docker compose --env-file .env.azure -f docker-compose.azure.yml up -d backend` (the container is recreated).
- The OpenRouter key, custom LLM endpoint, and writer model can be configured directly through the panel without
  restarting (see [backend/README.md](../README.md#panel-settings)). Production uses the OpenRouter model
  `google/gemini-2.5-flash` in Otak NPC. The laptop LLM endpoint is sent automatically by `ai-docker/jalankan.bat`.
- The Vercel frontend redirects `/panel` to `BACKEND_URL` + `/panel`. The panel must be opened over HTTPS.
