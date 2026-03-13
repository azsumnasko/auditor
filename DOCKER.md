# Jira Analytics – Docker and Coolify (multi-tenant, on-demand)

## Env vars

| Where | Variable | Purpose |
|-------|----------|---------|
| **Coolify / env** | `SESSION_SECRET` | Required. Secret for signing JWT session cookies. Set a long random string in production. |
| **Coolify** (optional) | `DATA_DIR` | Override data directory; default `/data` (must match volume mount). |

Per-user Jira config is stored in the SQLite DB (`/data/app.db`); users set it via the Config page after signup/login. Reports are generated on demand (Generate report on the Dashboard); the worker polls for pending jobs and runs analytics per user.

## Local run (Docker Compose)

1. From repo root: `docker compose up --build`
2. Set `SESSION_SECRET` (e.g. `export SESSION_SECRET=your-secret`) or use the default for dev.
3. Open http://localhost:3001 → Sign up, then log in.
4. On Config page, fill and save your Jira settings.
5. On Dashboard, click **Generate report**; wait for the worker to pick up the job (polls every 60s). View the report in the same page or open `/dashboard/report`.

## Deploy with Coolify

1. In Coolify: **New Application** → **Docker Compose** (or Compose source).
2. Connect repo (this repo), branch (e.g. `main`), set compose path to `docker-compose.yml` (repo root).
3. Set env vars for **config-ui**: `SESSION_SECRET` (required). Optionally `DATA_DIR`.
4. Set env for **worker**: optionally `DATA_DIR` (default `/data`).
5. Deploy; Coolify will build both `config-ui` and `worker` and create the shared volume.
6. Point your domain or port to the **config-ui** service (port 3001). Do not expose the worker.
7. Users sign up, configure Jira, and generate reports on demand from the Dashboard.

---

## Deploy at clear-horizon.tech/report (subpath)

To serve the app at **https://clear-horizon.tech/report** (repo can be on GitHub or any Git host Coolify supports):

1. **New Application** in Coolify → **Docker Compose**.
2. **Source**: Connect your Git source (e.g. **GitHub** — connect account or paste repo URL), select branch (e.g. `main`), set compose file path to `docker-compose.yml`.
3. The **config-ui** image is built with base path: for subpath (e.g. clear-horizon.tech/report) set build arg `NEXT_PUBLIC_BASE_PATH`=/report; for subdomain (e.g. report.clean-horzon.tech) leave it empty (default). To serve at domain root instead, you’d need to pass build arg `NEXT_PUBLIC_BASE_PATH` = empty (if your UI supports it).
4. **Environment** for **config-ui**:  
   - `SESSION_SECRET` = (generate a long random string)  
   - Optional: `DATA_DIR` = `/data`
5. **Environment** for **worker**: optional `DATA_DIR` = `/data`.
6. **Domain / URL**:
   - Domain: `clear-horizon.tech`
   - Path (if your Coolify version supports it): `/report`  
   So traffic to `https://clear-horizon.tech/report` is sent to the config-ui container (port 3001).  
   If Coolify only has “Domain”, set the domain to `clear-horizon.tech` and in the **Application URL** or **Path** field set `/report`. Exact labels depend on your Coolify UI.
7. **Persistent volume**: Ensure the Compose volume `jira_data` is persisted (Coolify usually keeps named volumes).
8. **Deploy**. After deploy, open **https://clear-horizon.tech/report** → sign up / log in, configure Jira, then use the Dashboard to generate reports.

### Nothing shows at /report – troubleshooting

- **Path must be preserved**  
  Coolify’s proxy must send requests to your app **with the path kept**. So `https://clean-horzon.tech/report` should hit the container as path `/report`, not as `/`. If the proxy strips the path, the app (built with basePath `/report`) will get `/` and can return 404 or a blank page. In Coolify, check that the route for this app is for **path `/report`** and that the proxy forwards the full path (no “strip path” or “rewrite path”).

- **Port**  
  The **config-ui** service listens on **3001**. In Coolify, the destination port for this application must be **3001** (not 3000).

- **Quick check**  
  Open `https://clean-horzon.tech/report` and in the browser open DevTools → Network. Reload. Check whether the first request (document) returns 200 or 404/502, and whether requests to `/_next/...` or `/report/_next/...` fail (wrong path = blank page).

### Option: use a subdomain instead of a path

If path-based routing is hard to get right, use a **subdomain** so the app is at the root:

1. **DNS**: Add an **A** record for **report.clean-horzon.tech** (or **report.clear-horizon.tech**) pointing to your Coolify server IP.
2. **Coolify**: Set the application **domain** to **report.clean-horzon.tech** (no path).
3. **Build at root**: Build the app with **no** base path so it’s served at `/`.  
   In the **config-ui** build arguments in Coolify, set **`NEXT_PUBLIC_BASE_PATH`** = **(empty)**.  
   If your Coolify doesn’t support build args, we need to change the default in the Dockerfile to empty (see below).
4. Open **https://report.clean-horzon.tech** (no `/report`) to use the app.

The Dockerfile now defaults to **no** base path, so a normal deploy (no build arg) serves the app at the **root** of the domain. Use **report.clean-horzon.tech** (or report.clear-horizon.tech) as the domain in Coolify and open **https://report.clean-horzon.tech** with no path.

## Security

- Passwords are hashed (bcrypt); Jira token is stored in SQLite and only used by the worker; never logged or returned in API responses.
- Session is a signed JWT in an httpOnly cookie; set `SESSION_SECRET` to a strong secret in production.
