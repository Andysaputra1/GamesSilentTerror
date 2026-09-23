# Azure deployment: Silent Terror

Frontend: https://silent-terror.andylabs.site
Backend: https://backendthesis.andylabs.site
Panel: https://backendthesis.andylabs.site/panel
VM public IP: 70.153.8.162 (check Azure if this changes).

DNS is managed by Vercel nameservers, even though Hostinger is the registrar.
Create A record backendthesis -> 70.153.8.162 in Vercel DNS.
Do not attach this backend subdomain to a Vercel project.
Azure VM networking must allow inbound TCP 80 and 443. Keep MySQL 3306 and backend
8000 closed publicly; Docker publishes only Caddy ports. Preserve existing SSH access.
If UFW is enabled, allow OpenSSH before enabling/changing firewall rules.

## Google login

In Google Cloud > Google Auth Platform > Clients, edit the existing Web application
OAuth client. Set Authorized JavaScript origins to:

- https://silent-terror.andylabs.site
- https://games-silent-terror.vercel.app (only if the old URL remains in use)
- http://localhost:4200 (optional local development)

No trailing slash or /login. Authorized redirect URIs can stay empty for this
application: Google Identity Services uses a JavaScript popup callback, then the
frontend sends the ID token to /api/auth/google. No Client Secret is required.
Configure app branding, support/developer email and audience in Google Auth Platform;
if the console requires test users while in Testing, add the Google accounts used
for testing. Never commit Google credentials or runtime environment files.

## VM preparation

From the repository root on the VM (after fetching the release containing these files):

```bash
python3 backend/scripts/setup_azure.py
nano .env.azure
```

The script generates missing database passwords and the panel encryption key;
existing database passwords are preserved. Enter the administrator password twice.
In nano, fill GOOGLE_CLIENT_ID with the same Client ID as local .env. Optionally
fill openrouter_default with your default OpenRouter key, or configure your own key
later in /panel. Keep BACKEND_DOMAIN=backendthesis.andylabs.site and
FRONTEND_ORIGIN=https://silent-terror.andylabs.site.

The .pkl classifier is intentionally ignored by Git. Upload the trusted existing
artifact from your own PC; the backend will not be ready without it. Example from
Windows CMD, using the actual clone directory on the VM:

```bat
scp backend\artifacts\svm\intent_classifier.pkl azureuser@70.153.8.162:~/GamesSilentTerror/backend/artifacts/svm/intent_classifier.pkl
```

Do not load a pickle file from an unknown source. It is executable Python data.

```bash
sudo docker volume create shadow_heist_mysql_data
sudo docker compose --env-file .env.azure -f docker-compose.azure.yml up -d mysql
sudo docker compose --env-file .env.azure -f docker-compose.azure.yml ps
```

Fresh volume: MySQL applies all three deployment SQL files automatically, with no
seed users. Existing volume: back up first, inspect schema_migrations, and apply only
missing V5/V6 migrations as described in README.md. If this is an older pre-baseline
database also inspect account_identities (V4) before enabling Google login.
Never delete the volume to force migrations.

After database schema and model are ready:

```bash
sudo docker compose --env-file .env.azure -f docker-compose.azure.yml up -d --build
sudo docker compose --env-file .env.azure -f docker-compose.azure.yml ps
sudo docker compose --env-file .env.azure -f docker-compose.azure.yml logs --tail=60 backend proxy
curl -fsS https://backendthesis.andylabs.site/ready
curl -fsS https://backendthesis.andylabs.site/api/auth/google/config
```

Caddy obtains and renews HTTPS certificates after DNS and ports 80/443 work.
/ready checks schema and SVM without contacting an AI service. One backend worker
is intentional: game rooms and Google nonces live in one process. Restarting the
backend interrupts active games but does not delete archived chat.

## Connect Vercel

Set BACKEND_URL=https://backendthesis.andylabs.site on project games-silent-terror,
Production environment, then redeploy only after the backend HTTPS readiness succeeds.
GOOGLE_CLIENT_ID is read by the frontend from the backend; it is not a frontend build secret.
Set CORS_ORIGINS via FRONTEND_ORIGIN on the VPS. If both frontend domains are used,
FRONTEND_ORIGIN may contain both exact HTTPS origins separated by a comma.
Verify Google login from the real frontend domain, room creation, WebSocket chat,
/panel login, and history download. A real Google login requires the account owner
in the browser; unit tests cannot verify the Google Cloud console configuration.
