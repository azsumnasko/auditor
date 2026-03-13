# Code Review: Multi-tenant Jira Analytics SaaS

Senior dev and product-manager review with applied fixes.

---

## Security

### 1. SESSION_SECRET in production (fixed)
- **Finding**: Default `dev-secret-change-in-production` was used when unset, allowing predictable sessions in production.
- **Fix**: In `lib/auth.ts`, `getSecret()` throws at runtime in production if `SESSION_SECRET` is unset or equals the default. First login/signup or any session read will fail until a proper secret is set.
- **Recommendation**: Set `SESSION_SECRET` in Coolify (and in `.env` locally for production builds).

### 2. Worker job claim race (fixed)
- **Finding**: Two worker instances could SELECT the same pending job before either committed UPDATE, leading to duplicate runs or inconsistent state.
- **Fix**: In `worker/run_next_job.py`, job claim runs inside `BEGIN IMMEDIATE` so the row is locked until commit. Only one worker can claim a given job.

### 3. Dashboard report path (fixed)
- **Finding**: Report path was built from `userId` without ensuring the resolved path stays under `DATA_DIR/users`.
- **Fix**: In `app/dashboard/report/route.ts`, `userId` is validated as a positive integer and the resolved path is checked to be under `USERS_DIR` before reading the file.

### 4. Jira token storage
- **Recommendation**: Consider encrypting `jira_token` in the `config` table with a key from env (e.g. `ENCRYPTION_KEY`) for defense in depth. Not applied; optional follow-up.

---

## API consistency

### 5. JSON error shape (fixed)
- **Finding**: Some routes returned plain text (e.g. `"Unauthorized"`) or inconsistent bodies, making client handling harder.
- **Fix**: All API error responses now use a JSON body `{ error: "<message>" }` with appropriate status codes. Client code (login, signup, config, dashboard) updated to use `data.error` where applicable.

### 6. One pending/running job per user (fixed)
- **Finding**: Users could spam “Generate report” and create many pending jobs, overloading the worker and confusing the UI.
- **Fix**: `POST /api/reports/generate` checks for an existing job in `pending` or `running` for the current user; if found, returns `409` with message “A report is already generating. Wait for it to finish.”

---

## Product and UX

### 7. Config page 401 redirect (fixed)
- **Finding**: If the session expired while on the config page, the config fetch returned 401 but the user stayed on the page with no feedback.
- **Fix**: On `401` from `GET /api/config`, the client redirects to `/login?from=/` so the user can sign in again.

### 8. Login/signup navigation (fixed)
- **Finding**: Auth pages had no link back to the app root, so the product felt disconnected.
- **Fix**: Added “Jira Analytics” link to `/` on both login and signup pages.

### 9. Email validation (fixed)
- **Finding**: Only presence and length were checked; invalid formats were accepted.
- **Fix**: Signup and login now validate email with a simple regex `^[^\s@]+@[^\s@]+\.[^\s@]+$`. Signup already stored email lowercased via `getUserByEmail`; login now lowercases before lookup.

---

## Data and reliability

### 10. SQLite WAL mode (fixed)
- **Finding**: Default delete mode can block readers during writes; with both Next.js and the worker using the same DB, concurrency is important.
- **Fix**: In `lib/db.ts`, `initSchema` runs `PRAGMA journal_mode = WAL` so reads are not blocked by a single writer.

---

## Optional items implemented (after review)

### Rate limiting (report generation)
- **Per-user limit**: Max **10 report generations per hour** (jobs created in the last 60 minutes).
- **Implementation**: `lib/db.ts` adds `countJobsCreatedInLastHour(userId)`; `POST /api/reports/generate` returns **429** with message `Rate limit: max 10 reports per hour. Try again later.` when the count is at or above the limit.
- **UI**: Dashboard shows the rate-limit (and other generate) errors inline below the button instead of only in an alert.

### Stale job cleanup
- **Behaviour**: Jobs stuck in `running` for more than **1 hour** are marked `failed` with message *"Stale (run exceeded 1 hour(s)); you can generate again."*
- **Implementation**: In `worker/run_next_job.py`, `cleanup_stale_running_jobs(conn)` runs at the start of each poll cycle (before claiming a job). Uses `updated_at < datetime('now', '-1 hours')` so users can generate again.

---

## Recommendations not implemented

- **Token encryption**: Encrypt `jira_token` at rest in the config table using an env-based key.
- **Audit log**: Log config changes and report generation (user id, timestamp) for support and compliance.
- **E2E tests**: Add a minimal Playwright (or similar) flow: signup → login → config → generate report → view dashboard.

---

## Additional fixes (second pass)

- **Open redirect**: Login page now validates `from` query param — only allows relative paths (starts with `/`, not `//`) before redirecting after login.
- **Session payload validation**: `getSessionUserId()` now validates `sub` is a string and that the parsed id is a positive integer; otherwise returns `null`.
- **Config API**: Server-side validation for JIRA Base URL (valid URL); max lengths enforced (JIRA_BASE_URL 2048, JIRA_EMAIL 256, JIRA_TOKEN 2048, JIRA_PROJECT_KEYS 500).
- **Login API**: Email format validation added (same regex as signup) for consistency.
- **Signup API**: Unique constraint on email is caught (better-sqlite3 `SQLITE_CONSTRAINT_UNIQUE` or message contains `UNIQUE`); returns 409 "Email already registered" instead of 500.
- **Dashboard report 404**: Explicit `Content-Type: text/plain; charset=utf-8` on 404 response.

---

## Files changed (summary)

| Area        | Files |
|------------|--------|
| Auth        | `config-ui/lib/auth.ts` (getSecret, production check) |
| Middleware  | `config-ui/middleware.ts` (JSON 401 body) |
| DB          | `config-ui/lib/db.ts` (WAL, `countJobsCreatedInLastHour`) |
| API routes  | `config-ui/app/api/config/route.ts`, `auth/login`, `auth/signup`, `reports/generate`, `reports/status` (JSON errors, rate limit 10/hr, email validation) |
| Dashboard   | `config-ui/app/dashboard/report/route.ts` (path validation, JSON errors) |
| Worker      | `worker/run_next_job.py` (atomic job claim, `cleanup_stale_running_jobs` before claim) |
| UI          | `config-ui/app/page.tsx` (401 redirect, error from JSON), `login/page.tsx`, `signup/page.tsx` (nav, error message), `dashboard/page.tsx` (error message, inline generate error) |
