# Initial Azure Setup

This document covers the one-time steps to set up the Silent Terror backend on a new Azure VM: DNS, firewall,
Google OAuth, `.env.azure`, models, and the connection to the Vercel frontend. Subsequent routine updates
(backups, migrations, builds) are covered in [README.md](README.md).

| Component | Address |
| --- | --- |
| Frontend | https://silent-terror.andylabs.site |
| Backend | https://backendthesis.andylabs.site |
| Panel | https://backendthesis.andylabs.site/panel |
| VM public IP | 70.153.8.162 (check Azure if it changes) |

## 1. DNS and networking

1. DNS is managed by Vercel nameservers even though the domain registrar is Hostinger. Create an A record for
   `backendthesis` pointing to the VM's public IP in Vercel DNS.
2. Do not attach the backend subdomain to a Vercel project.
3. In the Azure VM network settings, allow inbound TCP 80 and 443. Keep MySQL port 3306 and backend port 8000
   closed to the public; Docker exposes only Caddy's ports. Preserve existing SSH access.
4. If UFW is enabled, allow OpenSSH before changing firewall rules.

## 2. Google login

1. In Google Cloud > Google Auth Platform > Clients, edit the existing Web application OAuth client.
2. Set Authorized JavaScript origins without a trailing slash or `/login`:
   - `https://silent-terror.andylabs.site`
   - `https://games-silent-terror.vercel.app` (only if the old URL is still used)
   - `http://localhost:4200` (optional, for local development)
3. Authorized redirect URIs can remain empty. Google Identity Services uses a popup with a JavaScript callback,
   and the frontend then sends the ID token to `/api/auth/google`. A Client Secret is not required.
4. Configure application branding, support and developer emails, and the audience in Google Auth Platform. If
   the console requests test users while in Testing mode, add the Google accounts used for testing.

Never commit Google credentials or environment files.

## 3. Repository, `.env.azure`, and models on the VM

1. Clone the repository to `~/GamesSilentTerror` and enter that directory.
2. Create `.env.azure`:

   ```bash
   python3 backend/scripts/setup_azure.py
   nano .env.azure
   ```

   The script generates missing database passwords and `PANEL_ENCRYPTION_KEY`, preserves existing database
   passwords, adds the `BACKEND_DOMAIN`, `FRONTEND_ORIGIN`, `GOOGLE_CLIENT_ID`, `openrouter_default`, and
   `OLLAMA_TUNNEL_TOKEN` keys, then asks for the panel administrator password twice (at least 8 characters).
   The file is created with permissions `600`.
3. In `nano`, set `GOOGLE_CLIENT_ID` to the same Client ID as the local `.env`. Optionally set `openrouter_default`
   to the default OpenRouter key, or configure your own key later through the panel. Keep
   `BACKEND_DOMAIN=backendthesis.andylabs.site` and `FRONTEND_ORIGIN=https://silent-terror.andylabs.site`.
4. Copy the two IndoBERT model directories from the laptop to `backend/artifacts/indobert/intent/` and
   `backend/artifacts/indobert/target/` on the VM (for example, with `scp -r`). Models are included in the image
   during the build; it stops with a message if either directory is missing its model.

Do not share `.env.azure`. Changing a password in this file later does not rotate the password of an already
initialized database.

## 4. Start MySQL

Create the database and Caddy certificate volumes first as external volumes so `down -v` does not delete them:

```bash
sudo docker volume create shadow_heist_mysql_data
sudo docker volume create silent-terror-azure_caddy_data
sudo docker compose --env-file .env.azure -f docker-compose.azure.yml up -d mysql
sudo docker compose --env-file .env.azure -f docker-compose.azure.yml ps
```

- New volume: MySQL runs all files in `backend/migrations/` (V01–V12, excluding V03) in order, with no default
  accounts. The initial result is 15 tables (including `schema_migrations`), ten formal survey questions, and
  zero accounts.
- Existing volume containing data: migrations do not rerun. Stop, inspect its contents, and follow
  [README.md](README.md#applying-migrations-to-an-existing-database). Do not delete the volume to force initialization.

To inspect tables (the root password is requested in the terminal; do not paste it into chat):

```bash
sudo docker compose --env-file .env.azure -f docker-compose.azure.yml exec mysql mysql -uroot -p shadow_heist
```

```sql
SHOW TABLES;
SELECT COUNT(*) FROM user_accounts;
```

## 5. Start all services

```bash
sudo docker compose --env-file .env.azure -f docker-compose.azure.yml up -d --build
sudo docker compose --env-file .env.azure -f docker-compose.azure.yml ps
sudo docker compose --env-file .env.azure -f docker-compose.azure.yml logs --tail=60 backend proxy
curl -fsS https://backendthesis.andylabs.site/ready
curl -fsS https://backendthesis.andylabs.site/api/auth/google/config
```

Caddy obtains and renews HTTPS certificates automatically once DNS and ports 80/443 are working. `/ready` checks
the database and migrations without contacting AI services, and reports IndoBERT status
([README.md](README.md#routine-updates), step 7). A single backend worker is intentional: rooms and Google nonces
live in one process. Restarting the backend interrupts active matches but does not delete chat archives.

## 6. Connect Vercel

1. In the `games-silent-terror` Vercel project's Production environment, set
   `BACKEND_URL=https://backendthesis.andylabs.site`.
2. Redeploy the frontend only after `/ready` succeeds over HTTPS.
3. The frontend reads `GOOGLE_CLIENT_ID` from the backend, so it is not a frontend build secret.
4. Backend CORS is configured through `FRONTEND_ORIGIN` in `.env.azure`. If both frontend domains are used,
   list both full HTTPS origins, separated by commas.
5. Test from the actual frontend domain: Google login, room creation, WebSocket chat, `/panel` login, and chat
   history download. A real Google login requires the account owner in the browser; unit tests cannot verify
   Google Cloud configuration.

Frontend deployment details are in [frontend/DEPLOYMENT.md](../../frontend/DEPLOYMENT.md).
