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
3. Open http://localhost:3000 → Sign up, then log in.
4. On Config page, fill and save your Jira settings.
5. On Dashboard, click **Generate report**; wait for the worker to pick up the job (polls every 60s). View the report in the same page or open `/dashboard/report`.

## Deploy with Coolify

1. In Coolify: **New Application** → **Docker Compose** (or Compose source).
2. Connect repo (this repo), branch (e.g. `main`), set compose path to `docker-compose.yml` (repo root).
3. Set env vars for **config-ui**: `SESSION_SECRET` (required). Optionally `DATA_DIR`.
4. Set env for **worker**: optionally `DATA_DIR` (default `/data`).
5. Deploy; Coolify will build both `config-ui` and `worker` and create the shared volume.
6. Point your domain or port to the **config-ui** service (port 3000). Do not expose the worker.
7. Users sign up, configure Jira, and generate reports on demand from the Dashboard.

---

## Deploy at clean-horzon.tech/report (subpath)

To serve the app at **https://clean-horzon.tech/report** (repo can be on GitHub or any Git host Coolify supports):

1. **New Application** in Coolify → **Docker Compose**.
2. **Source**: Connect your Git source (e.g. **GitHub** — connect account or paste repo URL), select branch (e.g. `main`), set compose file path to `docker-compose.yml`.
3. The **config-ui** image is built with base path `/report` by default (no build arg needed in Coolify). To serve at domain root instead, you’d need to pass build arg `NEXT_PUBLIC_BASE_PATH` = empty (if your UI supports it).
4. **Environment** for **config-ui**:  
   - `SESSION_SECRET` = (generate a long random string)  
   - Optional: `DATA_DIR` = `/data`
5. **Environment** for **worker**: optional `DATA_DIR` = `/data`.
6. **Domain / URL**:
   - Domain: `clean-horzon.tech`
   - Path (if your Coolify version supports it): `/report`  
   So traffic to `https://clean-horzon.tech/report` is sent to the config-ui container (port 3000).  
   If Coolify only has “Domain”, set the domain to `clean-horzon.tech` and in the **Application URL** or **Path** field set `/report`. Exact labels depend on your Coolify UI.
7. **Persistent volume**: Ensure the Compose volume `jira_data` is persisted (Coolify usually keeps named volumes).
8. **Deploy**. After deploy, open **https://clean-horzon.tech/report** → sign up / log in, configure Jira, then use the Dashboard to generate reports.

## Security

- Passwords are hashed (bcrypt); Jira token is stored in SQLite and only used by the worker; never logged or returned in API responses.
- Session is a signed JWT in an httpOnly cookie; set `SESSION_SECRET` to a strong secret in production.
