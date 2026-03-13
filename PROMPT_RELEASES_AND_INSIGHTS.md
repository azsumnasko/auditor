# Prompt: Expose release/version metrics and add insights/suggestions

Use this prompt with an AI (e.g. Cursor) to implement release metrics in the dashboard and add release-related insights and suggestions in the right places.

---

## Copy-paste prompt

**Goal:** Expose Jira release (version) metrics in the dashboard and add release-related insights and suggestions in the proper sections.

**Context:** The analytics pipeline already computes and stores release data in the results JSON:
- `releases`: list of `{ "project", "name", "released", "release_date" }` for all project versions.
- `total_released_versions`: count of versions with `released === true`.
- `releases_per_month`: `{ "YYYY-MM": count }` for released versions with a date.

This data is currently not shown in the HTML dashboard and is not used in insights or audit flags.

**Requirements:**

1. **Dashboard (generate_dashboard.py and output HTML)**

   - **Releases section:** Add a dedicated section “Releases / versions” that:
     - Shows summary stats: total versions, released count, unreleased count, and (optional) releases in the last 3/6/12 months.
     - Renders a **table** of versions with columns: Project, Version name, Released (Yes/No), Release date. Sort by release_date descending (released first, then by date). Support the existing project/component filter and table filter so the list can be filtered by project.
     - Optionally add a **releases-per-month** chart (bar or line) for the last 12–24 months so release cadence is visible.
   - **Cards (optional):** Add one or two summary cards in the top cards row, e.g. “Released (total)” and “Released (last 6 mo)” or “Unreleased versions”, so release health is visible at a glance.

2. **Audit flags (Potential Issues section in generate_dashboard.py)**

   Add release-related audit flags in the same `computeAuditFlags` (or equivalent) logic that already produces severity-based flags. Examples (tune thresholds to your preference):
   - **No release in 90 days:** If the most recent `release_date` in `releases` (for released versions) is older than 90 days, add an orange or yellow flag: “No release in the last 90 days” with a short suggestion (e.g. “Consider shipping a version or archiving unreleased versions.”).
   - **Many unreleased versions:** If `(total versions - total_released_versions) > N` (e.g. N = 10 or 20), add a yellow flag: “Many unreleased versions (X)” with a suggestion to review or release.
   - **Release cadence drop (optional):** If you have `releases_per_month`, compare last 3 months to previous 3 months; if count dropped sharply (e.g. by more than 50%), add a yellow flag about release cadence slowing.

   Use the same severity and styling as existing flags (e.g. `sev('orange', title, detail)`).

3. **Insights and next best actions (insights_by_project.py → INSIGHTS_AND_ACTIONS.md)**

   - **Overall snapshot:** In the “Overall snapshot” section, add a bullet that summarizes releases, e.g. “**Released versions:** N total; M released in the last 12 months” (derive M from `releases` + `release_date` or from `releases_per_month`).
   - **Next best actions:** Add a subsection (e.g. “### 4. Releases and versions”) that:
     - If no release in 90 days: suggest scheduling a release or cleaning up versions.
     - If many unreleased versions: suggest reviewing and either releasing or archiving.
     - Optionally: one line on release cadence (e.g. “Releases per month: consider keeping a steady cadence.”).
   - **By project (optional):** If useful, in the “By project” section per project, add a short line like “Versions: X total, Y released” using `releases` filtered by `project`.

**Technical notes:**

- In `generate_dashboard.py`, read `data.get("releases")`, `data.get("total_released_versions")`, and `data.get("releases_per_month")`; build `releases_rows` (or similar) for the table and pass them into the HTML template. Add the new section after an existing section (e.g. after “Kanban boards” or “Epic health”). Include the new table in the project/component filter and filter list so `tableReleases` (or your id) is shown/hidden and filterable like `tableBlocked` / `tableBugs`.
- In `insights_by_project.py`, `load_data()` already gets the full analytics JSON; use `data.get("releases")` and `data.get("releases_per_month")` to compute the snapshot line and the release-related next best actions. Keep the same markdown structure and tone as the rest of INSIGHTS_AND_ACTIONS.md.
- Prefer reusing existing patterns: table markup, `setupFilter`/`setupSort`, and `sev()` for audit flags.

**Out of scope for this prompt:** Changing how `releases` / `releases_per_month` are computed in `jira_analytics.py` (that already exists). Focus on exposing and interpreting that data in the dashboard and in the insights document.

---

## Short version (if you need a compact prompt)

**Expose release metrics and add insights:**  
(1) In the Jira dashboard HTML (generate_dashboard.py), add a “Releases / versions” section with a table of all versions (project, name, released, release_date) and optional releases-per-month chart and summary cards.  
(2) In the Audit Flags logic, add flags for “no release in 90 days” and “many unreleased versions” (and optionally release cadence drop).  
(3) In insights_by_project.py and INSIGHTS_AND_ACTIONS.md, add a release line to the overall snapshot and a “Releases and versions” subsection under next best actions with suggestions when there has been no release in 90 days or there are many unreleased versions. Use existing JSON: `releases`, `total_released_versions`, `releases_per_month`.
