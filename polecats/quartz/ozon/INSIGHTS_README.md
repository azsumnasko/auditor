# Jira analytics – format and how to get insights

## Where the data is saved

After each run, the script writes:

- **`jira_analytics_latest.json`** – always the last run (overwritten).
- **`jira_analytics_<timestamp>.json`** – one file per run (e.g. `jira_analytics_2026-02-18T14-30-00Z.json`).

Use `jira_analytics_latest.json` when you want “current state”; use timestamped files for history or comparison.

---

## JSON structure (for tools and Cursor)

All values are JSON-serializable (numbers, strings, arrays, objects, `null`). No `NaN`; missing ratios are `null`.

| Key | Description |
|-----|-------------|
| `run_iso_ts` | Run time (UTC), e.g. `"2026-02-18T14:30:00Z"` |
| `projects` | List of project keys |
| `wip_count` | Number of issues not Done |
| `wip_components` | Component name → issue count (WIP) |
| `wip_teams` | Team name → issue count (WIP; only if a custom field with "team" in name exists) |
| `status_category` | `{"new": N, "indeterminate": N}` |
| `status_distribution` | Status name → count for WIP |
| `wip_aging_days` | `{count, avg_days, p50_days, p85_days, p95_days}` |
| `blocked_count` | Number of blocked issues |
| `blocked_oldest` | `[[issueKey, ageDays], ...]` top 10 |
| `throughput_by_week` | `{"2026-W07": 117, ...}` last 12 weeks |
| `lead_time_days` | `{count, avg_days, p50_days, p85_days, p95_days}` |
| `cycle_time_days` | Same shape for cycle time |
| `open_bugs_count` | Open bug count |
| `open_bugs_age_days` | Same summary shape for bug age |
| `oldest_open_bugs` | `[{key, project, age_days, summary}, ...]` top 15 |
| `kanban_boards` | `[{project, board_id, board_name, issue_count, done_count, status_breakdown}, ...]` |
| `sprint_metrics` | `[{..., assignee_count, assignees, component_breakdown, team_breakdown, added_after_sprint_start, added_after_sprint_start_issue_keys, removed_during_sprint}, ...]` (Scrum only). `added_after_sprint_start` = issues added to sprint after start (from changelog); `removed_during_sprint` = from report if available, else `null`. |
| `cfr_failures_count` | Count of issues matching CFR JQL, or `null` if query failed |

---

## How to get “next best actions” in Cursor

1. Run the script:  
   `.\run_jira_analytics.ps1`
2. In Cursor chat, reference the latest file and ask for insights, for example:
   - *“Using @jira_analytics_latest.json, what are the top 3–5 next best actions for the team?”*
   - *“From @jira_analytics_latest.json, where are we at risk (WIP age, blockers, old bugs, velocity)?”*
   - *“Summarize @jira_analytics_latest.json and suggest priorities.”*

The model can read the JSON and turn metrics (WIP age, blocked count, oldest bugs, sprint/kanban outcomes, throughput) into concrete recommendations.

---

## Scrum vs Kanban in the JSON

- **Scrum:** `sprint_metrics` has velocity and commitment vs done per sprint. Kanban boards are skipped for sprints.
- **Kanban:** `kanban_boards` has, per board, current issue count, done count, and `status_breakdown` (status name → count). No sprint data.

So you get both: sprint-based metrics for Scrum boards and board-level WIP/flow for Kanban boards.

---

## Split by project and next best actions

After each analytics run you can generate a **per-project** view and an **insights + next best actions** report:

```powershell
python insights_by_project.py
# Or: python insights_by_project.py jira_analytics_2026-02-18T15-51-39Z.json
```

This writes:

- **`by_project.json`** – metrics split by project key (blocked, oldest bugs, sprint summary, kanban).
- **`INSIGHTS_AND_ACTIONS.md`** – overall snapshot, by-project summary, and prioritized next best actions.

Use `@by_project.json` or `@INSIGHTS_AND_ACTIONS.md` in Cursor for follow-up questions (e.g. "Why is PBI blocked?" or "What should O3 do first?").

## HTML dashboard

Run `python generate_dashboard.py` to create **jira_dashboard.html** (charts, sortable/filterable tables, dark theme). Open in a browser. Use `@by_project.json` or `@INSIGHTS_AND_ACTIONS.md` in Cursor for follow-up questions (e.g. “Why is PBI blocked?” or “What should O3 do first?”).
