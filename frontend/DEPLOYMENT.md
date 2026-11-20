# Deploying the frontend to Vercel from GitHub

This file explains how to deploy the frontend to Vercel. The Angular frontend is built into static files; the
Python backend, Socket.IO, database, and AI run separately (see
[backend/deployment/README.md](../backend/deployment/README.md)). The frontend `/panel` route only redirects the
browser to `BACKEND_URL` + `/panel`.

## One-time Vercel setup

1. Open https://vercel.com/new and import `Andysaputra1/GamesSilentTerror`.
2. Select **Root Directory: frontend** and **Framework Preset: Other**.
3. The Node.js version is pinned through `engines.node` (`24.x`) in `frontend/package.json`, matching the root
   `package.json`. Vercel uses this value and ignores the Node.js selection in project settings. `vercel.json`
   provides:
   - Install Command: `npm ci`
   - Build Command: `npm run build:vercel`
   - Output Directory: `dist/frontend/browser`
   - `X-Content-Type-Options: nosniff` and `Referrer-Policy: strict-origin-when-cross-origin` headers for all pages.
     Vercel sends HSTS itself. Content-Security-Policy is intentionally omitted: an incomplete policy could break
     Google login (`accounts.google.com` scripts and iframes).
4. Deploy, then make sure the project's Production Branch is `main`. Subsequent pushes to `main` automatically
   build and update the production deployment.

Without `BACKEND_URL`, the frontend pages can be published, but login, registration, and online gameplay will not
work. API requests fail because no backend is configured. Vercel does not create a game server or database.

## After the backend is available

- Set the Vercel environment variable `BACKEND_URL`, for example `https://api.example.com` (HTTPS origin only,
  without `/api` or `/socket.io`). Select the Production environment; Preview also needs a value if you want to test it.
- Redeploy: this value is included in the bundle at build time. It is a public address, not a place to store
  passwords, tokens, or API keys.
- The backend must support HTTPS and WebSocket upgrades at `/socket.io/`. If a player's network blocks WebSocket
  (for example, a campus proxy), Socket.IO falls back to HTTP long-polling on the same path.
- Add the production frontend origin to the backend's `CORS_ORIGINS` for HTTP and Socket.IO. Preview deployments
  use different origins, so explicitly allow them if needed.
- For Google login, register the frontend origin in the OAuth client's Authorized JavaScript origins.
  `GOOGLE_CLIENT_ID` remains configured on the backend.
- Run the backend in production mode; do not publish the development panel, phpMyAdmin, or database ports. Avoid
  restarting the backend during a match because match state is currently stored in backend memory.
- Verify login, room creation/joining with two browsers, real-time chat, phase transitions, and reconnection after
  a connection loss. Two tabs in the same browser share one account, so test two accounts using separate browsers,
  profiles, or an incognito window.

## Local development

From the `frontend` folder, `npm start` and `npm run build` retain local/LAN behavior: the API and Socket.IO use the
same hostname on port `8000`. (`npm start` from the repository root behaves differently: it runs
`frontend/docker/start.mjs`, which uses `BACKEND_URL`; see [docker/README.md](docker/README.md).)

`npm run build:vercel` generates `dist/frontend/browser`; the Vercel environment configuration is generated
automatically and ignored by Git.

References: https://vercel.com/docs/git and https://vercel.com/docs/builds/configure-a-build.
