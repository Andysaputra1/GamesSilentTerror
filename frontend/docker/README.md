# Frontend Docker setup for collaborators

This file is for frontend developers who do not need to run their own backend. The Angular frontend runs on a
collaborator's laptop; the API, WebSocket, AI, and database continue using the VPS backend at
`https://backendthesis.andylabs.site`. CSS/HTML/TypeScript changes in `frontend/src` and assets in `frontend/public`
reload automatically. The laptop does not need Node.js, MySQL, or AI models installed.

## 1. Prepare the laptop

Install Git and Docker Desktop, then start Docker Desktop (Linux containers). Clone the repository after being
granted access:

```bash
git clone https://github.com/Andysaputra1/GamesSilentTerror.git
cd GamesSilentTerror/frontend/docker
```

Copy the example environment file. In Windows PowerShell:

```powershell
Copy-Item .env.example .env
```

Windows CMD: `copy .env.example .env`. macOS/Linux: `cp .env.example .env`.

It already points to the VPS:

```dotenv
BACKEND_URL=https://backendthesis.andylabs.site
FRONTEND_PORT=4200
```

This frontend environment file contains only public addresses. The OpenRouter API key, database password, and Azure
environment configuration stay on the backend and do not need to be shared with frontend developers. All accounts,
rooms, and chat messages created from the local frontend use the same server data as the main website.

## 2. Allow the local frontend on the VPS backend (Andy, once)

Browser connections require CORS permission on the backend. In `~/GamesSilentTerror/.env.azure`, update or add the
following line. Keep the production frontend domain:

```dotenv
FRONTEND_ORIGIN=https://silent-terror.andylabs.site,http://localhost:4200,http://127.0.0.1:4200
```

Keep any other required origins too, separated by commas. Do not add trailing slashes. In the VPS terminal:

```bash
cd ~/GamesSilentTerror
nano .env.azure
```

Save with Ctrl+O, Enter, then exit with Ctrl+X. Apply the change:

```bash
sudo docker compose --env-file .env.azure -f docker-compose.azure.yml up -d backend
```

Compose loads the environment changes by recreating the backend. Active matches in memory are reset, while
database history is preserved; do this when no matches are running. Do not expose the MySQL port for the frontend.

For the Google Login button, add `http://localhost:4200` and `http://127.0.0.1:4200` to the backend OAuth Web Client's
**Authorized JavaScript origins**. Keep the production origin. The frontend fetches the client ID from the backend,
so the frontend Docker environment does not need Google variables. The current popup flow does not require a new
redirect URI. Regular account login can be used for testing without Google.

## 3. Start the frontend

From `frontend/docker`:

```bash
docker compose --env-file .env -f docker-compose.yml up -d --build
docker compose --env-file .env -f docker-compose.yml logs -f frontend
```

Wait for Angular compilation to finish, then open **http://localhost:4200**. Ctrl+C in the log viewer only stops
viewing logs; the container keeps running. The first Docker run takes longer because it downloads images and dependencies.

Edit files in `frontend/src` or `frontend/public` with your laptop's editor. Docker reads changes through bind mounts,
and Angular updates the page. Dependencies are installed in the image, separately from the laptop's `node_modules`.
This configuration is for local development, not a public server.

After changing package.json/package-lock.json, angular.json, scripts, or the Dockerfile, run `up -d --build` again.
After changing `.env`, run `up -d` again to recreate the container. `src/environments/environment.vercel.ts` is
generated automatically when the container starts and is ignored by Git; do not edit it manually. Avoid running a
Vercel build in the same checkout while this container is active, because both write the same `environment.vercel.ts` file.

## 4. Everyday commands

Run these from `frontend/docker` to avoid starting the backend stack in the repository root:

```bash
# Status
docker compose --env-file .env -f docker-compose.yml ps
# Stop and remove the local frontend container
docker compose --env-file .env -f docker-compose.yml down
# After pulling repository updates
git pull
docker compose --env-file .env -f docker-compose.yml up -d --build
```

Work on your own branch so a collaborator's push does not deploy directly to production: from the repository
directory, run `git switch -c frontend/feature-name`, then open a pull request to main.

## 5. Troubleshooting connections

- The UI opens but API/CORS requests fail: make sure the VPS CORS step has been applied, then open exactly
  `http://localhost:4200`.
- WebSocket fails: Socket.IO uses the backend origin permissions too. Make sure the HTTPS backend is reachable
  and VPS port 443 is open.
- Google reports an origin mismatch: check that Authorized JavaScript origins match the browser address, including
  its port.
- Port 4200 is in use: change FRONTEND_PORT (for example, to 4201), then add `http://localhost:4201` to CORS and
  Google origins before restarting.
- Source changes do not appear: check compilation logs; file polling runs every second. Make sure Docker Desktop
  is allowed to access the repository folder.
- The backend is unreachable: open `https://backendthesis.andylabs.site/ready`. The VM must be running.

References: [Docker Compose](https://docs.docker.com/reference/cli/docker/compose/) and
[Angular environment configuration](https://angular.dev/tools/cli/environments).

## Alternative without Docker: run every command from the repository root

Install Git and Node.js 24, then:

```bash
git clone https://github.com/Andysaputra1/GamesSilentTerror.git
cd GamesSilentTerror
npm install
```

Create `.env` in the outermost directory, alongside `package.json` and the `frontend` folder:

```dotenv
BACKEND_URL=https://backendthesis.andylabs.site
FRONTEND_PORT=4200
```

Run `npm start`, then open http://localhost:4200. Running npm install at the root automatically installs frontend
dependencies according to the lockfile. The root environment file is read at startup, so restart npm start after
changing it. You do not need to switch to the frontend folder or run Docker. The CORS and Google localhost origin
instructions above still apply. If the root already has a backend environment file, add these two public variables
without deleting anything else.
