# Best beads to improve the Jira analysis

Use these as task prompts for the dispatcher (Path B) or for Gas Town sling (Path A). Run `bd create "..."` for each (if you have [Beads installed](INSTALL.md)), then start the dispatcher or sling them. **No Beads?** Run `py dispatch_workers.py` once; it creates `task_queue.json` and seeds it with the tasks below, so you can use the same workflow without installing `bd`.

---

## High impact (metrics and data)

- **Add cycle time distribution chart to dashboard** – Histogram or percentiles (p50/p85/p95) of cycle time by project so teams see where flow is slow.
- **Add throughput trend chart (last 12 weeks)** – Line chart of issues done per week with optional project filter; highlight drops.
- **Compute and show flow efficiency** – % of lead time spent in active (in progress) vs waiting; add to analytics JSON and dashboard.
- **Add scope creep metric per sprint** – Issues added after sprint start vs removed; show in sprint_metrics and dashboard.
- **Compute change failure rate by project** – Use CFR_FAILURE_JQL (or deployment-linked incidents); add to by_project and dashboard.
- **Add WIP by age bands** – Group WIP into 0–7d, 7–30d, 30–90d, 90d+; show count and list per band in dashboard.
- **Add rework / reopen rate** – Issues moved back from Done to In Progress (from changelog); per project and overall.

---

## Dashboard UX and drill-down

- **Add tooltips to all dashboard metric cards** – Short definition (e.g. lead time vs cycle time) and formula where relevant.
- **Add project filter dropdown to dashboard** – Single-page filter so all sections (throughput, WIP, bugs, sprints) scope to selected project(s).
- **Add drill-down: click project or metric to open Jira filter** – e.g. “Open bugs” opens Jira search for open bugs in that project.
- **Add CSV export for WIP and throughput** – Buttons to download tables (e.g. WIP list, throughput by week) as CSV.
- **Show “Next best action” per project on dashboard** – Pull from INSIGHTS_AND_ACTIONS or compute (unblock, triage oldest bugs, review WIP).

---

## Data quality and robustness

- **Handle missing story points in velocity** – Treat null/blank as 0 and document in dashboard; avoid NaN in commitment ratio.
- **Normalize status names in status_distribution** – Map Jira statuses to simple phases (e.g. Not started / In progress / Review / Done) for consistent labels.
- **Add retry and backoff for Jira API 429/5xx** – In jira_analytics.py so long runs don’t fail on rate limits.
- **Cache Jira responses for 5 minutes** – Optional disk or in-memory cache to speed re-runs and reduce API load.

---

## Sprints and predictability

- **Add sprint predictability chart** – Commitment vs done (story points or count) for last N sprints per board; show trend.
- **Show velocity trend (last 6 sprints)** – Bar or line chart of completed story points per sprint per board.
- **Add “added after sprint start” list per sprint** – In sprint_metrics; link to Jira for each issue.

---

## Bugs and blockers

- **Add average age of open bugs by project** – In by_project and dashboard; highlight projects with oldest bugs.
- **Add blocked-issue table with one-click Jira link** – Dashboard section listing blocked issues with key, age, project; each row links to Jira.
- **Add “oldest WIP” table (top 20)** – Key, project, age in days, summary; link to Jira.

---

## Quick copy-paste (Path B)

**If you have Beads:** from repo root after `bd init`:

```powershell
bd create "Add cycle time distribution chart to dashboard"
bd create "Add throughput trend chart (last 12 weeks)"
bd create "Compute and show flow efficiency in analytics and dashboard"
bd create "Add scope creep metric per sprint (added/removed after start)"
bd create "Compute change failure rate by project and add to dashboard"
bd create "Add WIP by age bands (0-7d, 7-30d, 30-90d, 90d+) to dashboard"
bd create "Add tooltips to all dashboard metric cards"
bd create "Add project filter dropdown to dashboard"
bd create "Add drill-down: Jira filter links for bugs and WIP"
bd create "Add CSV export for WIP and throughput tables"
bd create "Handle missing story points in velocity and commitment ratio"
bd create "Add retry and backoff for Jira API 429/5xx in jira_analytics.py"
bd create "Add sprint predictability chart (commitment vs done last N sprints)"
bd create "Add blocked-issue table with one-click Jira link on dashboard"
bd create "Add oldest WIP table (top 20) with Jira links on dashboard"
```

Then run `py dispatch_workers.py` (or `python dispatch_workers.py`). Use `OLLAMA_NUM_PARALLEL=14` if you run 14 agents. Start with fewer tasks if you want to test with 1–2 workers first.

**If you don't have Beads:** run `py dispatch_workers.py` once from the repo root; it creates `task_queue.json` and seeds it with the 15 tasks above, so you get the same list without installing `bd`.
