#!/usr/bin/env python3
"""
Generate a single-file HTML dashboard from jira_analytics_latest.json.
Run: python generate_dashboard.py [path/to/jira_analytics_latest.json]
Output: jira_dashboard.html
"""
import json
import os
import sys
import html
from datetime import datetime

def _output_dir():
    return os.environ.get("OUTPUT_DIR") or os.path.dirname(__file__)


def load_data(path=None):
    if path is None:
        path = os.path.join(_output_dir(), "jira_analytics_latest.json")
    with open(path, encoding="utf-8") as f:
        return json.load(f)

def escape_js(s):
    if s is None:
        return "null"
    return json.dumps(str(s))

def _try_load(basename):
    path = os.path.join(_output_dir(), f"{basename}_latest.json")
    if os.path.isfile(path):
        try:
            with open(path, encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass
    return None

def _safe_js(obj):
    """JSON-encode and escape sequences that would break a <script> block."""
    return json.dumps(obj, ensure_ascii=False).replace("</", "<\\/")


def _load_scan_history(max_scans=10):
    """Return list of {ts, label, wip, done} dicts from timestamped jira_analytics_*.json files."""
    import glob as _glob
    out_dir = _output_dir()
    pattern = os.path.join(out_dir, "jira_analytics_*.json")
    candidates = []
    for p in _glob.glob(pattern):
        basename = os.path.basename(p)
        if basename == "jira_analytics_latest.json":
            continue
        # filename: jira_analytics_2025-01-15T10-30-00.json
        ts_part = basename[len("jira_analytics_"):-len(".json")]
        candidates.append((ts_part, p))
    candidates.sort(key=lambda x: x[0], reverse=True)
    result = []
    for ts_part, path in candidates[:max_scans]:
        try:
            with open(path, encoding="utf-8") as f:
                snap = json.load(f)
            run_ts = snap.get("run_iso_ts") or ts_part
            label = run_ts[:19].replace("T", " ") if len(run_ts) >= 19 else ts_part
            result.append({
                "ts": run_ts,
                "label": label,
                "wip": snap.get("empty_or_bad_list_wip") or [],
                "done": snap.get("empty_or_bad_list_done") or [],
            })
        except Exception:
            continue
    return result

def main():
    data = load_data(sys.argv[1] if len(sys.argv) > 1 else None)
    data_js = _safe_js(data)
    git_data = _try_load("git_analytics")
    git_data_js = _safe_js(git_data or {})
    cicd_data = _try_load("cicd_analytics")
    cicd_data_js = _safe_js(cicd_data or {})
    octopus_data = _try_load("octopus_analytics")
    octopus_data_js = _safe_js(octopus_data or {})
    scorecard_data = _try_load("scorecard")
    scorecard_data_js = _safe_js(scorecard_data or {})
    evidence_data = _try_load("unified_evidence")
    evidence_data_js = _safe_js((evidence_data or {}).get("dora", {}))

    # Load scan history for Empty/Bad comparison (up to 10 most-recent timestamped snapshots)
    scan_history = _load_scan_history()
    scan_history_js = _safe_js(scan_history)
    pipeline_warnings = (evidence_data or {}).get("pipeline_warnings") or []
    if pipeline_warnings:
        pw_items = "".join(f"<li>{html.escape(str(w))}</li>" for w in pipeline_warnings)
        pw_banner_html = (
            '<div class="pipeline-warnings-banner" role="status">'
            "<strong>Partial data</strong>"
            "<p>Some optional sources did not complete:</p>"
            f"<ul>{pw_items}</ul></div>"
        )
    else:
        pw_banner_html = ""
    jira_base_url = (data.get("jira_base_url") or "").rstrip("/")
    run_ts = data.get("run_iso_ts", "") or ""
    # Agile-friendly naming: open_count (all not done), open_by_phase (backlog, in_progress, in_review, blocked), wip_in_flight
    open_count = data.get("open_count", data.get("wip_count", 0))
    blocked = data.get("blocked_count", 0)
    open_bugs = data.get("open_bugs_count", 0)
    throughput = data.get("throughput_by_week", {})
    last_4_weeks = sum(throughput.get(w, 0) for w in sorted(throughput.keys())[-4:]) if throughput else 0
    wip_aging = data.get("wip_aging_days") or {}
    lead = data.get("lead_time_days") or {}
    cycle = data.get("cycle_time_days") or {}
    status_dist = data.get("status_distribution") or {}
    wip_comp = data.get("wip_components") or {}
    blocked_oldest = data.get("blocked_oldest") or []
    blocked_oldest_details = data.get("blocked_oldest_details") or []
    oldest_bugs = data.get("oldest_open_bugs") or []
    sprint_metrics = data.get("sprint_metrics") or []
    kanban = data.get("kanban_boards") or []
    # Prefer open_by_phase (backlog, in_progress, in_review, blocked); fallback to wip_by_phase (not_started, review_qa)
    obp = data.get("open_by_phase") or {}
    wbp = data.get("wip_by_phase") or {}
    open_phase = {
        "backlog": obp.get("backlog", wbp.get("not_started", 0)),
        "in_progress": obp.get("in_progress", wbp.get("in_progress", 0)),
        "in_review": obp.get("in_review", wbp.get("review_qa", 0)),
        "blocked": obp.get("blocked", wbp.get("blocked", 0)),
    }
    wip_in_flight = data.get("wip_in_flight") or (open_phase["in_progress"] + open_phase["in_review"] + open_phase["blocked"])
    unassigned_open = data.get("unassigned_open_count", data.get("unassigned_wip_count", 0))
    lt_dist = data.get("lead_time_distribution") or {}
    flow_eff = data.get("flow_efficiency") or {}

    wip_assignees = data.get("wip_assignees") or {}
    avg_wip_pp = data.get("avg_wip_per_assignee", 0)
    sp_trend = data.get("sp_trend") or {}
    created_by_week = data.get("created_by_week") or {}
    bug_creation_by_week = data.get("bug_creation_by_week") or {}
    bug_resolved_by_week = data.get("bug_resolved_by_week") or {}
    bug_fix_time = data.get("bug_fix_time_days") or {}
    open_bugs_by_priority = data.get("open_bugs_by_priority") or {}
    reopen_analysis = data.get("reopen_analysis") or {}
    reopen_pct = reopen_analysis.get("reopened_pct", 0)
    flow_eff_pct = (data.get("flow_efficiency") or {}).get("efficiency_pct", 0)
    bug_fix_p50 = bug_fix_time.get("p50_days")
    bug_fix_display = f"{round(bug_fix_p50, 1)}d" if bug_fix_p50 is not None else (f"{round(bug_fix_time['avg_days'], 1)}d (avg)" if bug_fix_time.get("avg_days") is not None else "N/A")
    assignee_change = data.get("assignee_change_near_resolution") or {}
    comment_timing = data.get("comment_timing") or {}
    worklog_analysis = data.get("worklog_analysis") or {}
    epic_health = data.get("epic_health") or []
    releases = data.get("releases") or []
    releases_per_month = data.get("releases_per_month") or {}
    total_released_versions = data.get("total_released_versions", 0)

    projects = data.get("projects", [])
    teams = data.get("teams") or sorted(
        k for k in set((data.get("wip_teams") or {}).keys()) | set((data.get("by_team") or {}).keys())
        if k and k != "(no team)"
    )
    wip_teams = data.get("wip_teams") or {}
    all_components = sorted(set(wip_comp.keys()) | set(
        c for p in (data.get("by_project") or {}).values()
        for c in (p.get("wip_components") or {}).keys()
    ))
    def project_from_key(key):
        return key.split("-", 1)[0] if key and "-" in str(key) else ""

    def link_key(key):
        k = html.escape(str(key))
        if jira_base_url and k:
            return f'<a href="{html.escape(jira_base_url)}/browse/{k}" target="_blank" style="color:var(--accent)">{k}</a>'
        return k

    blocked_rows = "".join(
        f'<tr data-project="{html.escape(str(b.get("project", project_from_key(b.get("key", "")) or "")))}" '
        f'data-components="{html.escape("|".join(b.get("components", [])))}" data-team="{html.escape(b.get("team", ""))}">'
        f'<td>{link_key(b.get("key", ""))}</td><td>{round(float(b.get("age_days", 0)), 1)}</td></tr>'
        for b in blocked_oldest_details
    ) if blocked_oldest_details else "".join(
        f'<tr data-project="{html.escape(project_from_key(b[0]))}"><td>{link_key(b[0])}</td><td>{round(float(b[1]), 1)}</td></tr>'
        for b in blocked_oldest
    ) if blocked_oldest else "<tr><td colspan=\"2\">None</td></tr>"

    bugs_rows = "".join(
        f'<tr data-project="{html.escape(b.get("project", ""))}" data-components="{html.escape("|".join(b.get("components", [])))}" data-team="{html.escape(b.get("team", ""))}">'
        f'<td>{link_key(b.get("key", ""))}</td><td>{html.escape(b.get("project", ""))}</td><td>{round(float(b.get("age_days", 0)), 1)}</td><td>{html.escape((b.get("summary") or "")[:60])}</td></tr>'
        for b in oldest_bugs
    ) if oldest_bugs else "<tr><td colspan=\"4\">None</td></tr>"

    sprint_rows = []
    for s in sprint_metrics:
        ratio = s.get("commitment_done_ratio")
        ratio_str = f"{ratio:.2f}" if ratio is not None else "\u2014"
        added = s.get("added_after_sprint_start")
        removed = s.get("removed_during_sprint")
        last24 = s.get("resolved_last_24h_pct")
        last24_str = f"{last24}%" if last24 is not None else "\u2014"
        a_d = s.get("added_and_done_count")
        a_d_str = str(a_d) if a_d is not None else "\u2014"
        sprint_components = sorted((s.get("component_breakdown") or {}).keys())
        sprint_teams = sorted((s.get("team_breakdown") or {}).keys())
        sprint_rows.append(
            f'<tr data-project="{html.escape(s.get("project", ""))}" data-components="{html.escape("|".join(sprint_components))}" data-team="{html.escape("|".join(sprint_teams))}" data-date="{html.escape(str(s.get("end", "") or s.get("start", "") or ""))[:10]}">'
            f'<td>{html.escape(s.get("project", ""))}</td>'
            f'<td>{html.escape(s.get("sprint_name", ""))}</td>'
            f'<td>{s.get("throughput_issues", 0)}</td>'
            f'<td>{s.get("total_issues", 0)}</td>'
            f'<td>{s.get("assignee_count", "")}</td>'
            f'<td>{ratio_str}</td>'
            f'<td>{added if added is not None else "\u2014"}</td>'
            f'<td>{a_d_str}</td>'
            f'<td>{removed if removed is not None else "\u2014"}</td>'
            f'<td>{last24_str}</td>'
            f'</tr>'
        )
    sprint_rows_str = "".join(sprint_rows) if sprint_rows else "<tr><td colspan=\"10\">No sprint data</td></tr>"

    # Empty or bad structure: list (WIP + Done with Scope column) and breakdowns
    empty_bad_list_wip = data.get("empty_or_bad_list_wip") or []
    empty_bad_list_done = data.get("empty_or_bad_list_done") or []
    empty_bad_count_wip = data.get("empty_or_bad_count_wip", 0)
    empty_bad_count_done = data.get("empty_or_bad_count_done", 0)
    empty_bad_pct_wip = data.get("empty_or_bad_pct_wip", 0)
    empty_bad_pct_done = data.get("empty_or_bad_pct_done", 0)
    empty_or_bad_rows = []
    for row in empty_bad_list_wip:
        empty_or_bad_rows.append(
            f'<tr data-scope="WIP" data-project="{html.escape(row.get("project", ""))}" data-team="{html.escape(row.get("team", ""))}" data-date="{html.escape(row.get("created", ""))}" data-type="{html.escape(row.get("type", ""))}" data-status="{html.escape(row.get("status", ""))}">'
            f'<td>{link_key(row.get("key", ""))}</td><td>WIP</td><td>{html.escape(row.get("project", ""))}</td>'
            f'<td>{html.escape(row.get("type", ""))}</td>'
            f'<td>{html.escape((row.get("summary") or "")[:60])}</td><td>{html.escape(row.get("status", ""))}</td>'
            f'<td>{html.escape(row.get("assignee_display_name", ""))}</td>'
            f'<td>{html.escape(row.get("team", ""))}</td>'
            f'<td>{html.escape(row.get("author_display_name", ""))}</td>'
            f'<td>{html.escape(row.get("created", ""))}</td></tr>'
        )
    for row in empty_bad_list_done:
        empty_or_bad_rows.append(
            f'<tr data-scope="Done" data-project="{html.escape(row.get("project", ""))}" data-team="{html.escape(row.get("team", ""))}" data-date="{html.escape(row.get("created", ""))}" data-type="{html.escape(row.get("type", ""))}" data-status="{html.escape(row.get("status", ""))}">'
            f'<td>{link_key(row.get("key", ""))}</td><td>Done</td><td>{html.escape(row.get("project", ""))}</td>'
            f'<td>{html.escape(row.get("type", ""))}</td>'
            f'<td>{html.escape((row.get("summary") or "")[:60])}</td><td>{html.escape(row.get("status", ""))}</td>'
            f'<td>{html.escape(row.get("assignee_display_name", ""))}</td>'
            f'<td>{html.escape(row.get("team", ""))}</td>'
            f'<td>{html.escape(row.get("author_display_name", ""))}</td>'
            f'<td>{html.escape(row.get("created", ""))}</td></tr>'
        )
    empty_or_bad_rows_str = "".join(empty_or_bad_rows) if empty_or_bad_rows else "<tr><td colspan=\"10\">None</td></tr>"
    top_teams_wip = data.get("empty_or_bad_top_teams_wip") or {}
    top_teams_done = data.get("empty_or_bad_top_teams_done") or {}
    top_assignees_wip = data.get("empty_or_bad_top_assignees_wip") or {}
    top_assignees_done = data.get("empty_or_bad_top_assignees_done") or {}
    top_components_wip = data.get("empty_or_bad_top_components_wip") or {}
    top_components_done = data.get("empty_or_bad_top_components_done") or {}
    top_labels_wip = data.get("empty_or_bad_top_labels_wip") or {}
    top_labels_done = data.get("empty_or_bad_top_labels_done") or {}
    def _top5_table(d, empty_msg="None"):
        if not d:
            return f"<p class=\"summary-desc\">{empty_msg}</p>"
        rows = "".join(f"<tr><td>{html.escape(k)}</td><td>{v}</td></tr>" for k, v in sorted(d.items(), key=lambda x: -x[1]))
        return f'<table class="summary-table" style="font-size:0.8rem"><tbody>{rows}</tbody></table>'
    empty_bad_top_teams_wip_html = _top5_table(top_teams_wip)
    empty_bad_top_teams_done_html = _top5_table(top_teams_done)
    empty_bad_top_assignees_wip_html = _top5_table(top_assignees_wip)
    empty_bad_top_assignees_done_html = _top5_table(top_assignees_done)
    empty_bad_top_components_wip_html = _top5_table(top_components_wip)
    empty_bad_top_components_done_html = _top5_table(top_components_done)
    empty_bad_top_labels_wip_html = _top5_table(top_labels_wip)
    empty_bad_top_labels_done_html = _top5_table(top_labels_done)

    kanban_rows = "".join(
        f'<tr data-project="{html.escape(k.get("project", ""))}"><td>{html.escape(k.get("project", ""))}</td><td>{html.escape(k.get("board_name", ""))}</td><td>{k.get("issue_count", 0)}</td><td>{k.get("done_count", 0)}</td><td>{html.escape(json.dumps(k.get("status_breakdown", {})))}</td></tr>'
        for k in kanban
    ) if kanban else "<tr><td colspan=\"5\">No Kanban boards</td></tr>"

    # Releases: sort by released first, then release_date descending (null last)
    def _release_date_key(r):
        rd = r.get("release_date") or ""
        if not rd or len(rd) < 10:
            return (0, 0, 0)
        try:
            return (int(rd[:4]), int(rd[5:7]), int(rd[8:10]))
        except (ValueError, TypeError):
            return (0, 0, 0)
    releases_sorted = sorted(releases, key=lambda r: ((0 if r.get("released") else 1), tuple(-x for x in _release_date_key(r))))
    releases_rows = "".join(
        f'<tr data-project="{html.escape(r.get("project", ""))}" data-date="{html.escape(r.get("release_date") or "")}">'
        f'<td>{html.escape(r.get("project", ""))}</td><td>{html.escape(r.get("name", ""))}</td>'
        f'<td>{"Yes" if r.get("released") else "No"}</td><td>{html.escape(r.get("release_date") or "\u2014")}</td></tr>'
        for r in releases_sorted
    ) if releases else "<tr><td colspan=\"4\">No version data</td></tr>"
    total_versions = len(releases)
    unreleased_count = total_versions - total_released_versions
    # Releases in last 3/6/12 months from releases_per_month (use run_iso_ts or now for "current" month)
    try:
        ref_year = int(run_ts[:4]) if len(run_ts) >= 4 else datetime.now().year
        ref_month = int(run_ts[5:7]) if len(run_ts) >= 7 else datetime.now().month
    except (ValueError, TypeError):
        ref_year, ref_month = datetime.now().year, datetime.now().month

    def _releases_in_months(n):
        total = 0
        for i in range(n):
            m = ref_month - i
            y = ref_year
            while m < 1:
                m += 12
                y -= 1
            key = f"{y}-{m:02d}"
            total += releases_per_month.get(key, 0)
        return total

    releases_last_3 = _releases_in_months(3)
    releases_last_6 = _releases_in_months(6)
    releases_last_12 = _releases_in_months(12)

    status_labels = list(status_dist.keys())
    status_values = list(status_dist.values())
    comp_items = sorted(wip_comp.items(), key=lambda x: -x[1])[:15]
    comp_labels = [c[0] for c in comp_items]
    comp_values = [c[1] for c in comp_items]
    weekly_labels = list(throughput.keys())
    weekly_values = list(throughput.values())

    # Phase 1 chart data
    res_breakdown = data.get("resolution_breakdown") or {}
    res_labels = list(res_breakdown.keys())
    res_values = list(res_breakdown.values())
    wip_itype = data.get("wip_issuetype") or {}
    done_itype = data.get("done_issuetype") or {}
    wip_pri = data.get("wip_priority") or {}
    dow = data.get("resolution_by_weekday") or {}
    done_assignees = data.get("done_assignees") or {}
    assignee_items = sorted(done_assignees.items(), key=lambda x: -x[1])[:15]

    # Status paths table (Phase 2a)
    spa = data.get("status_path_analysis") or {}
    top_paths = spa.get("top_paths") or []
    paths_rows = "".join(
        f'<tr><td>{html.escape(p.get("path",""))}</td><td>{p.get("count",0)}</td></tr>'
        for p in top_paths[:10]
    ) if top_paths else "<tr><td colspan=\"2\">No data</td></tr>"

    # Time in status (Phase 2b)
    tis = data.get("time_in_status") or {}
    tis_sorted = sorted(tis.items(), key=lambda x: -(x[1].get("median_hours") or 0))

    # Closers (Phase 2c)
    ca = data.get("closer_analysis") or {}
    top_closers = ca.get("top_closers") or []

    html_out = f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Clear Horizon Tech \u2014 Jira Analytics Dashboard \u2014 {html.escape(run_ts)}</title>
  <script src="https://cdn.jsdelivr.net/npm/chart.js@4.4.0/dist/chart.umd.min.js"></script>
  <style>
    :root {{ --bg: #0f1419; --card: #1a2332; --text: #e6edf3; --muted: #8b949e; --accent: #58a6ff; --green: #3fb950; --orange: #d29922; --red: #f85149; }}
    * {{ box-sizing: border-box; }}
    body {{ font-family: 'Segoe UI', system-ui, sans-serif; background: var(--bg); color: var(--text); margin: 0; padding: 1rem; line-height: 1.5; }}
    h1 {{ font-size: 1.5rem; margin: 0 0 0.5rem; }}
    .meta {{ color: var(--muted); font-size: 0.875rem; margin-bottom: 1.5rem; }}
    .cards {{ display: grid; grid-template-columns: repeat(auto-fill, minmax(130px, 1fr)); gap: 0.75rem; margin-bottom: 2rem; }}
    .card {{ background: var(--card); border-radius: 8px; padding: 0.75rem; border: 1px solid #30363d; }}
    .card .value {{ font-size: 1.5rem; font-weight: 700; color: var(--accent); }}
    .card .label {{ font-size: 0.7rem; text-transform: uppercase; color: var(--muted); margin-top: 0.15rem; }}
    section {{ margin-bottom: 2rem; }}
    section h2 {{ font-size: 1.125rem; margin-bottom: 1rem; color: var(--muted); border-bottom: 1px solid #30363d; padding-bottom: 0.5rem; }}
    .chart-wrap {{ max-width: 600px; height: 280px; margin-bottom: 1rem; }}
    .grid2 {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(320px, 1fr)); gap: 1.5rem; }}
    .grid3 {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(280px, 1fr)); gap: 1.5rem; }}
    table {{ width: 100%; border-collapse: collapse; font-size: 0.85rem; }}
    th, td {{ padding: 0.4rem 0.6rem; text-align: left; border-bottom: 1px solid #30363d; }}
    th {{ color: var(--muted); font-weight: 600; cursor: pointer; user-select: none; white-space: nowrap; }}
    th:hover {{ color: var(--accent); }}
    .filter {{ margin-bottom: 0.75rem; }}
    .filter input {{ background: var(--card); border: 1px solid #30363d; color: var(--text); padding: 0.4rem 0.6rem; border-radius: 6px; width: 100%; max-width: 240px; }}
    .filter input::placeholder {{ color: var(--muted); }}
    .table-wrap {{ overflow-x: auto; }}
    .summary-stats {{ display: flex; flex-wrap: wrap; gap: 1rem; margin-bottom: 1rem; font-size: 0.875rem; }}
    .summary-stats span {{ color: var(--muted); }}
    .summary-desc {{ color: var(--muted); font-size: 0.8125rem; margin: -0.5rem 0 0.75rem; }}
    .project-filter {{ display: flex; flex-wrap: wrap; align-items: center; gap: 0.5rem 0.75rem; margin-bottom: 1rem; padding: 0.6rem; background: var(--card); border-radius: 8px; border: 1px solid #30363d; }}
    .project-filter label {{ display: inline-flex; align-items: center; gap: 0.3rem; cursor: pointer; font-size: 0.8rem; }}
    .project-filter input[type="checkbox"] {{ accent-color: var(--accent); }}
    .project-filter .pf-label {{ color: var(--muted); margin-right: 0.2rem; }}
    .audit-flags {{ display: flex; flex-direction: column; gap: 0.75rem; }}
    .audit-flag {{ background: var(--card); border-radius: 8px; padding: 0.75rem 1rem; border-left: 4px solid #30363d; font-size: 0.875rem; }}
    .audit-flag.red {{ border-left-color: var(--red); }}
    .audit-flag.orange {{ border-left-color: var(--orange); }}
    .audit-flag.yellow {{ border-left-color: #e3b341; }}
    .audit-flag .flag-title {{ font-weight: 600; margin-bottom: 0.25rem; }}
    .audit-flag .flag-cat {{ font-size: 0.7rem; color: var(--muted); text-transform: uppercase; letter-spacing: 0.04em; margin-bottom: 0.2rem; }}
    .audit-flag .flag-detail {{ color: var(--muted); font-size: 0.8125rem; }}
    .audit-toolbar {{ display: flex; flex-wrap: wrap; align-items: center; gap: 0.5rem 1rem; margin-bottom: 0.75rem; font-size: 0.8rem; }}
    .audit-toolbar label {{ color: var(--muted); }}
    .audit-toolbar select {{ background: var(--card); border: 1px solid #30363d; color: var(--text); padding: 0.25rem 0.5rem; border-radius: 6px; font-size: 0.8rem; }}
    .audit-data-health {{ font-size: 0.8rem; color: var(--muted); margin-bottom: 0.75rem; padding: 0.5rem 0.75rem; background: rgba(110,118,129,0.12); border-radius: 6px; border: 1px solid #30363d; }}
    .audit-gaming-strip {{ font-size: 0.85rem; margin-bottom: 1rem; padding: 0.75rem 1rem; background: var(--card); border-radius: 8px; border: 1px solid #30363d; }}
    .audit-gaming-strip a {{ color: var(--accent); }}
    .audit-help {{ margin-bottom: 1rem; font-size: 0.8125rem; }}
    .audit-help summary {{ cursor: pointer; color: var(--accent); }}
    .epic-table-tools {{ display: flex; flex-wrap: wrap; align-items: center; gap: 0.75rem 1rem; margin-bottom: 0.5rem; font-size: 0.8rem; }}
    .epic-table-tools label {{ color: var(--muted); }}
    .gaming-score {{ display: flex; align-items: center; gap: 1.5rem; padding: 1rem; background: var(--card); border-radius: 8px; border: 1px solid #30363d; margin-bottom: 2rem; }}
    .gaming-gauge {{ font-size: 2.5rem; font-weight: 800; min-width: 80px; text-align: center; }}
    .gaming-label {{ font-size: 0.85rem; color: var(--muted); }}
    .gaming-detail {{ font-size: 0.85rem; }}
    .export-btn {{ background: var(--accent); color: #0f1419; border: none; padding: 0.5rem 1rem; border-radius: 6px; cursor: pointer; font-weight: 600; font-size: 0.85rem; }}
    .export-btn:hover {{ opacity: 0.85; }}
    .empty-bad-toolbar {{ display: flex; flex-wrap: wrap; align-items: center; gap: 0.5rem 0.75rem; margin-bottom: 0.5rem; }}
    .empty-bad-toolbar select {{ background: var(--card); border: 1px solid #30363d; color: var(--text); padding: 0.3rem 0.6rem; border-radius: 6px; font-size: 0.8rem; max-width: 260px; }}
    .eb-compare-summary {{ font-size: 0.82rem; margin-bottom: 0.5rem; padding: 0.45rem 0.75rem; background: rgba(88,166,255,0.08); border: 1px solid rgba(88,166,255,0.25); border-radius: 6px; color: var(--text); display: none; }}
    .eb-compare-summary .eb-new {{ color: #3fb950; font-weight: 600; }}
    .eb-compare-summary .eb-resolved {{ color: #f85149; font-weight: 600; }}
    tr.eb-row-new td {{ background: rgba(63,185,80,0.1); }}
    tr.eb-row-resolved {{ opacity: 0.6; }}
    tr.eb-row-resolved td {{ text-decoration: line-through; color: var(--muted); background: rgba(248,81,73,0.08); }}
    .time-btn {{ background: none; border: 1px solid transparent; color: var(--muted); padding: 0.3rem 0.7rem; border-radius: 6px; font-size: 0.8rem; cursor: pointer; }}
    .time-btn:hover {{ color: var(--text); background: rgba(88,166,255,0.1); }}
    .time-btn.active {{ background: var(--accent); color: #0f1419; border-color: var(--accent); }}
    .time-input {{ background: var(--bg); border: 1px solid #30363d; color: var(--text); padding: 0.3rem 0.5rem; border-radius: 6px; font-size: 0.8rem; width: 130px; }}
    .tab-bar {{ display: flex; flex-wrap: wrap; gap: 0.25rem; margin-bottom: 1.5rem; padding: 0.4rem; background: var(--card); border-radius: 8px; border: 1px solid #30363d; }}
    .tab-btn {{ background: none; border: none; color: var(--muted); padding: 0.5rem 1rem; border-radius: 6px; font-size: 0.85rem; font-weight: 500; cursor: pointer; transition: background 0.15s, color 0.15s; }}
    .tab-btn:hover {{ color: var(--text); background: rgba(88,166,255,0.1); }}
    .tab-btn.active {{ background: var(--accent); color: #0f1419; }}
    .tab-panel {{ display: none; }}
    .tab-panel.active {{ display: block; }}
    .pipeline-warnings-banner {{ background: rgba(227, 179, 65, 0.12); border: 1px solid #e3b341; border-radius: 8px; padding: 0.75rem 1rem; margin-bottom: 1.25rem; font-size: 0.875rem; }}
    .pipeline-warnings-banner p {{ margin: 0.35rem 0 0.25rem; color: var(--muted); }}
    .pipeline-warnings-banner ul {{ margin: 0.25rem 0 0; padding-left: 1.25rem; color: var(--text); }}
  </style>
</head>
<body>
{pw_banner_html}
  <h1>Clear Horizon Tech \u2014 Jira Analytics Dashboard</h1>
  <p class="meta">Author: Clear Horizon Tech &nbsp; Run: {html.escape(run_ts)} \u00b7 Projects: {", ".join(projects)} &nbsp; <button class="export-btn" onclick="exportEvidence()">Export Audit Evidence</button></p>

  <div id="gamingScoreContainer" class="gaming-score"></div>

  <div class="project-filter">
    <span class="pf-label">Project:</span>
    <label><input type="checkbox" id="projectAll" checked /> All</label>
    {''.join(f'<label><input type="checkbox" class="project-cb" value="{html.escape(p)}" /> {html.escape(p)}</label>' for p in projects)}
  </div>
  <div class="project-filter">
    <span class="pf-label">Component:</span>
    <label><input type="checkbox" id="componentAll" checked /> All</label>
    {''.join(f'<label><input type="checkbox" class="component-cb" value="{html.escape(c)}" /> {html.escape(c)}</label>' for c in all_components)}
  </div>
  {''.join([
      '<div class="project-filter" id="teamFilterBar">',
      '<span class="pf-label">Team:</span>',
      '<label><input type="checkbox" id="teamAll" checked /> All</label>',
      ''.join(f'<label><input type="checkbox" class="team-cb" value="{html.escape(t)}" /> {html.escape(t)}</label>' for t in teams),
      '</div>',
  ]) if teams else ''}
  <p class="meta" id="filterScopeSummary">Scope: all projects, all components{', all teams' if teams else ''}. Metrics are exact.</p>

  <div class="project-filter" id="timeFilterBar">
    <span class="pf-label">Time:</span>
    <button class="time-btn active" data-range="all">All time</button>
    <button class="time-btn" data-range="30">Last 30d</button>
    <button class="time-btn" data-range="90">Last 90d</button>
    <button class="time-btn" data-range="180">Last 6mo</button>
    <input type="date" id="timeFrom" class="time-input" title="From" />
    <span class="pf-label">&ndash;</span>
    <input type="date" id="timeTo" class="time-input" title="To" />
  </div>

  <div class="tab-bar" id="tabBar">
    <button class="tab-btn active" data-tab="overview">Overview</button>
    <button class="tab-btn" data-tab="flow">Flow</button>
    <button class="tab-btn" data-tab="sprints">Sprints</button>
    <button class="tab-btn" data-tab="people">People &amp; Teams</button>
    <button class="tab-btn" data-tab="quality">Quality</button>
    <button class="tab-btn" data-tab="releases">Releases</button>
    <button class="tab-btn" data-tab="audit">Audit</button>
    <button class="tab-btn" data-tab="gitmetrics">Git</button>
    <button class="tab-btn" data-tab="cicdmetrics">CI/CD</button>
    <button class="tab-btn" data-tab="dorametrics">DORA</button>
    <button class="tab-btn" data-tab="scorecardtab">Scorecard</button>
  </div>

  <!-- ===== OVERVIEW TAB ===== -->
  <div class="tab-panel active" id="panel-overview">
  <div class="cards">
    <div class="card"><div class="value" id="cardOpen">{open_count}</div><div class="label">Open (not done)</div></div>
    <div class="card"><div class="value" id="cardWipInFlight" style="color: var(--accent)">{wip_in_flight}</div><div class="label">WIP (in flight)</div></div>
    <div class="card"><div class="value" id="cardBacklog" style="color: var(--muted)">{open_phase.get('backlog', 0)}</div><div class="label">Backlog</div></div>
    <div class="card"><div class="value" id="cardInProgress" style="color: var(--accent)">{open_phase.get('in_progress', 0)}</div><div class="label">In progress</div></div>
    <div class="card"><div class="value" id="cardInReview" style="color: var(--orange)">{open_phase.get('in_review', 0)}</div><div class="label">In review</div></div>
    <div class="card"><div class="value" id="cardBlocked" style="color: var(--red)">{blocked}</div><div class="label">Blocked</div></div>
    <div class="card"><div class="value" id="cardUnassigned" style="color: #e3b341">{unassigned_open}</div><div class="label">Unassigned open</div></div>
    <div class="card"><div class="value" id="cardOpenBugs">{open_bugs}</div><div class="label">Open bugs</div></div>
    <div class="card"><div class="value" id="cardDone4Weeks" style="color: var(--green)">{last_4_weeks}</div><div class="label">Done (last 4 wk)</div></div>
    <div class="card"><div class="value" id="cardOpenMedian">{round(wip_aging.get('p50_days', 0))}</div><div class="label">Open median age (d)</div></div>
    <div class="card"><div class="value" id="cardLeadTime">{round(lead.get('avg_days', 0), 1) if lead.get('avg_days') is not None else '\u2014'}</div><div class="label">Lead time avg (d)</div></div>
    <div class="card"><div class="value" id="cardCycleTime">{round(cycle.get('avg_days', 0), 1) if cycle.get('avg_days') is not None else '\u2014'}</div><div class="label">Cycle time avg (d)</div></div>
    <div class="card"><div class="value" id="cardFlowEff" style="color: var(--orange)">{flow_eff.get('efficiency_pct', 0)}%</div><div class="label">Flow efficiency</div></div>
    <div class="card"><div class="value" id="cardEmptyBadWip" style="color: var(--orange)">{empty_bad_count_wip}</div><div class="label">Empty/bad open</div></div>
    <div class="card"><div class="value" id="cardEmptyBadDone" style="color: var(--orange)">{empty_bad_count_done}</div><div class="label">Empty/bad Done</div></div>
    <div class="card"><div class="value" id="cardReleasedTotal" style="color: var(--green)">{total_released_versions}</div><div class="label">Released (total)</div></div>
    <div class="card"><div class="value" id="cardUnreleasedVersions" style="color: #e3b341">{unreleased_count}</div><div class="label">Unreleased versions</div></div>
  </div>
  <div class="grid2">
    <section>
      <h2>Status distribution (Open)</h2>
      <div class="chart-wrap"><canvas id="chartStatus"></canvas></div>
    </section>
    <section>
      <h2>Open by component (top 15)</h2>
      <div class="chart-wrap"><canvas id="chartComponents"></canvas></div>
    </section>
  </div>
  <div class="grid2">
    <section>
      <h2>WIP by phase</h2>
      <div style="display:flex;gap:12px;flex-wrap:wrap;font-size:0.82rem;margin-bottom:6px" id="wipPhaseToggles">
        <label style="display:inline-flex;align-items:center;gap:4px;cursor:pointer"><input type="checkbox" class="wip-phase-cb" data-phase="backlog"> Backlog</label>
        <label style="display:inline-flex;align-items:center;gap:4px;cursor:pointer"><input type="checkbox" class="wip-phase-cb" data-phase="in_progress" checked> In progress</label>
        <label style="display:inline-flex;align-items:center;gap:4px;cursor:pointer"><input type="checkbox" class="wip-phase-cb" data-phase="in_review" checked> In review</label>
        <label style="display:inline-flex;align-items:center;gap:4px;cursor:pointer"><input type="checkbox" class="wip-phase-cb" data-phase="blocked" checked> Blocked</label>
      </div>
      <div class="chart-wrap"><canvas id="chartPhase"></canvas></div>
    </section>
    <section>
      <h2>Lead time distribution (resolved last 180d)</h2>
      <p class="summary-desc">Large &lt; 1 hour bucket signals retroactive ticket logging.</p>
      <div class="chart-wrap"><canvas id="chartLtDist"></canvas></div>
    </section>
  </div>
  </div>

  <!-- ===== FLOW TAB ===== -->
  <div class="tab-panel" id="panel-flow">
  <section>
    <h2>Throughput by week (issues resolved)</h2>
    <div class="chart-wrap" style="max-width: 900px; height: 220px;"><canvas id="chartThroughput"></canvas></div>
  </section>
  <section>
    <h2>Created vs Resolved trend (by week)</h2>
    <p class="summary-desc">Net positive (created > resolved) means backlog is growing.</p>
    <div class="chart-wrap" style="max-width: 900px; height: 260px;"><canvas id="chartCreatedResolved"></canvas></div>
  </section>
  <section>
    <h2>Lead time &amp; cycle time (days)</h2>
    <p class="summary-desc">Lead = created \u2192 resolved. Cycle = first in progress \u2192 resolved (from changelog).</p>
    <div class="summary-stats" id="leadCycleSummary">
      <span>Lead (created\u2192resolved):</span> count {lead.get('count', '\u2014')}, avg {round(lead.get('avg_days', 0), 1) if lead.get('avg_days') is not None else '\u2014'}, p50 {round(lead.get('p50_days', 0), 1) if lead.get('p50_days') is not None else '\u2014'} &nbsp;|&nbsp;
      <span>Cycle (in progress\u2192resolved):</span> count {cycle.get('count', '\u2014')}, avg {round(cycle.get('avg_days', 0), 1) if cycle.get('avg_days') is not None else '\u2014'}, p85 {round(cycle.get('p85_days', 0), 1) if cycle.get('p85_days') is not None else '\u2014'}
    </div>
  </section>
  <div class="grid3">
    <section>
      <h2>Resolution types (last 180d)</h2>
      <div class="chart-wrap"><canvas id="chartResolution"></canvas></div>
    </section>
    <section>
      <h2>Work mix (issue types)</h2>
      <div class="chart-wrap"><canvas id="chartIssueTypes"></canvas></div>
    </section>
    <section>
      <h2>Priority distribution (WIP)</h2>
      <div class="chart-wrap"><canvas id="chartPriority"></canvas></div>
    </section>
  </div>
  <section>
    <h2>Resolutions by day of week</h2>
    <div class="chart-wrap"><canvas id="chartDow"></canvas></div>
  </section>
  </div>

  <!-- ===== SPRINTS TAB ===== -->
  <div class="tab-panel" id="panel-sprints">
  <section>
    <h2>Sprint metrics</h2>
    <div class="filter"><input type="text" id="filterSprints" placeholder="Filter by project\u2026" /></div>
    <div class="table-wrap">
      <table id="tableSprints">
        <thead><tr><th data-sort="project">Project</th><th data-sort="sprint_name">Sprint</th><th data-sort="throughput_issues">Done</th><th data-sort="total_issues">Total</th><th data-sort="assignee_count">People</th><th>Commit ratio</th><th data-sort="added_after_sprint_start">Added late</th><th>Added+Done</th><th>Removed</th><th>Last-day %</th></tr></thead>
        <tbody>{sprint_rows_str}</tbody>
      </table>
    </div>
  </section>
  <section>
    <h2>Sprint scope change (added after sprint start)</h2>
    <div class="chart-wrap" style="max-width: 900px; height: 220px;"><canvas id="chartAddedLate"></canvas></div>
  </section>
  <section>
    <h2>Kanban boards</h2>
    <div class="table-wrap">
      <table id="tableKanban">
        <thead><tr><th>Project</th><th>Board</th><th>Issues</th><th>Done</th><th>Status breakdown</th></tr></thead>
        <tbody>{kanban_rows}</tbody>
      </table>
    </div>
  </section>
  </div>

  <!-- ===== PEOPLE & TEAMS TAB ===== -->
  <div class="tab-panel" id="panel-people">
  <div class="grid2">
    <section>
      <h2>WIP by assignee (top 20)</h2>
      <p class="summary-desc">Avg WIP per person: <strong id="avgWipPP">{avg_wip_pp}</strong></p>
      <div class="chart-wrap"><canvas id="chartWipAssignees"></canvas></div>
    </section>
    <section>
      <h2>Top assignees (resolved last 180d)</h2>
      <p class="summary-desc">Gini coefficient: <strong id="giniValue">{data.get('workload_gini', 0)}</strong> (0 = equal, 1 = one person does all)</p>
      <div class="chart-wrap"><canvas id="chartAssignees"></canvas></div>
    </section>
  </div>
  <div class="grid2">
    <section>
      <h2>WIP by team</h2>
      <div class="chart-wrap"><canvas id="chartWipTeams"></canvas></div>
    </section>
    <section id="sectionTeamThroughput">
      <h2>Sprint throughput by team</h2>
      <div class="chart-wrap"><canvas id="chartTeamThroughput"></canvas></div>
    </section>
  </div>
  <div class="grid2">
    <section>
      <h2>Focus factor (WIP per assignee distribution)</h2>
      <p class="summary-desc">Low focus = person juggling many issues. Avg WIP/person: <strong id="avgWipPP2">{avg_wip_pp}</strong></p>
      <div class="chart-wrap"><canvas id="chartFocusFactor"></canvas></div>
    </section>
    <section>
      <h2>Top issue closers</h2>
      <p class="summary-desc" id="closerDesc">Closer != assignee in <strong>{ca.get('closer_not_assignee_pct', 0)}%</strong> of cases.</p>
      <div class="chart-wrap"><canvas id="chartClosers"></canvas></div>
    </section>
  </div>
  </div>

  <!-- ===== QUALITY TAB ===== -->
  <div class="tab-panel" id="panel-quality">
  <div class="summary-stats" id="qualityKpis">
    <span>Open bugs: <strong id="qKpiOpenBugs">{open_bugs}</strong></span>
    <span>Reopen rate: <strong id="qKpiReopenPct">{reopen_pct}%</strong></span>
    <span>Bug fix time (p50): <strong id="qKpiBugFixTime">{bug_fix_display}</strong></span>
    <span>Flow efficiency: <strong id="qKpiFlowEff">{flow_eff_pct}%</strong></span>
  </div>
  <div class="grid2">
    <section>
      <h2>Logged vs Fixed Bugs (by week)</h2>
      <p class="summary-desc">Red = bugs created, green = bugs resolved. Shows whether the bug backlog is growing or shrinking.</p>
      <div class="chart-wrap"><canvas id="chartBugLoggedVsFixed"></canvas></div>
    </section>
    <section>
      <h2>Bug creation rate (by week)</h2>
      <div class="chart-wrap"><canvas id="chartBugCreation"></canvas></div>
    </section>
  </div>
  <div class="grid2">
    <section>
      <h2>Defect density by component</h2>
      <p class="summary-desc">Open bugs / WIP count per component. Higher = more bugs relative to active work.</p>
      <div class="chart-wrap"><canvas id="chartDefectDensity"></canvas></div>
    </section>
    <section>
      <h2>Open bugs by priority</h2>
      <div class="chart-wrap"><canvas id="chartBugPriority"></canvas></div>
    </section>
  </div>
  <div class="grid2">
    <section>
      <h2>Resolution breakdown</h2>
      <p class="summary-desc">How resolved issues were closed. "Won't Do" / "Duplicate" inflates throughput.</p>
      <div class="chart-wrap"><canvas id="chartResolutionBreakdown"></canvas></div>
    </section>
    <section>
      <h2>Time in status (bottleneck analysis)</h2>
      <p class="summary-desc">Average hours spent in each workflow status. Identifies where issues get stuck.</p>
      <div class="chart-wrap"><canvas id="chartQualityTimeInStatus"></canvas></div>
    </section>
  </div>
  <section>
    <h2>Empty or bad structure</h2>
    <p class="summary-desc">Tickets with no/empty description (or, if configured, bad summary / no labels / no component). Counts and breakdowns by team, assignee, component, and label.</p>
    <div class="summary-stats">
      <span>Open: <strong>{empty_bad_count_wip}</strong> ({empty_bad_pct_wip}%)</span>
      <span>Done: <strong>{empty_bad_count_done}</strong> ({empty_bad_pct_done}%)</span>
    </div>
    <div class="empty-bad-toolbar">
      <input type="text" id="filterEmptyBad" placeholder="Filter by key, project, assignee, type, team, author\u2026" style="flex:1;min-width:180px;max-width:340px;background:var(--bg);border:1px solid #30363d;color:var(--text);padding:0.35rem 0.6rem;border-radius:6px;font-size:0.85rem;" />
      <select id="ebFilterType" style="font-size:0.8rem;background:var(--card);border:1px solid #30363d;color:var(--text);padding:0.3rem 0.6rem;border-radius:6px;max-width:160px;">
        <option value="">All types</option>
      </select>
      <select id="ebFilterStatus" style="font-size:0.8rem;background:var(--card);border:1px solid #30363d;color:var(--text);padding:0.3rem 0.6rem;border-radius:6px;max-width:200px;">
        <option value="">All statuses</option>
      </select>
      <button class="export-btn" onclick="exportEmptyBadCSV()" style="font-size:0.8rem;padding:0.35rem 0.75rem;">Export CSV</button>
      <label style="font-size:0.8rem;color:var(--muted);white-space:nowrap;">Compare vs:</label>
      <select id="emptyBadCompareSelect" onchange="compareEmptyBad(this.value)" style="font-size:0.8rem;background:var(--card);border:1px solid #30363d;color:var(--text);padding:0.3rem 0.6rem;border-radius:6px;max-width:240px;">
        <option value="">-- select a previous scan --</option>
      </select>
      <button id="emptyBadClearBtn" onclick="clearEmptyBadCompare()" style="display:none;background:none;border:1px solid #30363d;color:var(--muted);padding:0.3rem 0.6rem;border-radius:6px;cursor:pointer;font-size:0.8rem;">Clear</button>
    </div>
    <div class="eb-compare-summary" id="ebCompareSummary"></div>
    <div class="table-wrap">
      <table id="tableEmptyBad">
        <thead><tr><th data-sort="key">Key</th><th data-sort="scope">Scope</th><th data-sort="project">Project</th><th data-sort="type">Type</th><th>Summary</th><th data-sort="status">Status</th><th data-sort="assignee">Assignee</th><th data-sort="team">Team</th><th data-sort="author">Author</th><th data-sort="created">Created</th></tr></thead>
        <tbody>{empty_or_bad_rows_str}</tbody>
      </table>
    </div>
    <h3 style="font-size:1rem; margin-top:1.5rem; color: var(--muted);">Top offenders (top 5 by count)</h3>
    <div class="grid3" style="margin-top:0.5rem;">
      <div>
        <h4 style="font-size:0.9rem;">By team (WIP)</h4>
        {empty_bad_top_teams_wip_html}
      </div>
      <div>
        <h4 style="font-size:0.9rem;">By team (Done)</h4>
        {empty_bad_top_teams_done_html}
      </div>
      <div>
        <h4 style="font-size:0.9rem;">By assignee (WIP)</h4>
        {empty_bad_top_assignees_wip_html}
      </div>
      <div>
        <h4 style="font-size:0.9rem;">By assignee (Done)</h4>
        {empty_bad_top_assignees_done_html}
      </div>
      <div>
        <h4 style="font-size:0.9rem;">By component (WIP)</h4>
        {empty_bad_top_components_wip_html}
      </div>
      <div>
        <h4 style="font-size:0.9rem;">By component (Done)</h4>
        {empty_bad_top_components_done_html}
      </div>
      <div>
        <h4 style="font-size:0.9rem;">By label (WIP)</h4>
        {empty_bad_top_labels_wip_html}
      </div>
      <div>
        <h4 style="font-size:0.9rem;">By label (Done)</h4>
        {empty_bad_top_labels_done_html}
      </div>
    </div>
  </section>
  <section>
    <h2>Blocked issues (oldest)</h2>
    <div class="table-wrap">
      <table id="tableBlocked">
        <thead><tr><th>Key</th><th>Age (days)</th></tr></thead>
        <tbody>{blocked_rows}</tbody>
      </table>
    </div>
  </section>
  <section>
    <h2>Oldest open bugs</h2>
    <div class="filter"><input type="text" id="filterBugs" placeholder="Filter by project or key\u2026" /></div>
    <div class="table-wrap">
      <table id="tableBugs">
        <thead><tr><th data-sort="key">Key</th><th data-sort="project">Project</th><th data-sort="age_days">Age (days)</th><th>Summary</th></tr></thead>
        <tbody>{bugs_rows}</tbody>
      </table>
    </div>
  </section>
  </div>

  <!-- ===== RELEASES TAB ===== -->
  <div class="tab-panel" id="panel-releases">
  <section>
    <h2>Releases / versions</h2>
    <p class="summary-desc">Total versions: {total_versions} | Released: {total_released_versions} | Unreleased: {unreleased_count} | Last 3 mo: {releases_last_3} | Last 6 mo: {releases_last_6} | Last 12 mo: {releases_last_12}</p>
    <div class="chart-wrap"><canvas id="chartReleasesPerMonth"></canvas></div>
    <div class="filter"><input type="text" id="filterReleases" placeholder="Filter by project\u2026" /></div>
    <div class="table-wrap">
      <table id="tableReleases">
        <thead><tr><th data-sort="project">Project</th><th data-sort="name">Version name</th><th data-sort="released">Released</th><th data-sort="release_date">Release date</th></tr></thead>
        <tbody>{releases_rows}</tbody>
      </table>
    </div>
  </section>
  </div>

  <!-- ===== AUDIT TAB ===== -->
  <div class="tab-panel" id="panel-audit">
  <section>
    <h2>Potential Issues (Audit Flags)</h2>
    <p class="summary-desc">Automated checks for data quality, process health, and potential gaming. Deploy <code>scorecard.html</code> next to this dashboard for the full-page scorecard.</p>
    <details class="audit-help"><summary>How these flags work</summary>
      <p style="margin:0.5rem 0 0;color:var(--muted);line-height:1.45"><strong>Workflow</strong> &mdash; statuses, flow efficiency, descriptions. <strong>Throughput</strong> &mdash; lead/cycle time, resolutions, bulk closure. <strong>Sprint</strong> &mdash; sprint hygiene and estimates. <strong>People</strong> &mdash; assignment and load. <strong>Release</strong> &mdash; versions and cadence. <strong>Other</strong> &mdash; bugs, traceability, epics. <strong>Git/CI/CD</strong> &mdash; when Git/CI/Octopus data is present. Thresholds are fixed heuristics; tune process, not the dashboard.</p>
    </details>
    <div id="auditGamingStrip" class="audit-gaming-strip" style="display:none"></div>
    <div id="auditDataHealth" class="audit-data-health" style="display:none"></div>
    <div class="audit-toolbar">
      <label>Severity <select id="auditFilterSeverity" aria-label="Filter by severity"><option value="all">All</option><option value="red">Red</option><option value="orange">Orange</option><option value="yellow">Yellow</option></select></label>
      <label>Category <select id="auditFilterCategory" aria-label="Filter by category"><option value="all">All</option></select></label>
    </div>
    <div id="auditFlags" class="audit-flags"></div>
  </section>
  <section>
    <h2>Epic health (open epics)</h2>
    <p class="summary-desc" id="epicHealthSummary">Open: {data.get('open_epics_count', 0)} | Stale (>6mo, <20% done): <strong style="color:var(--red)">{data.get('stale_epics_count', 0)}</strong> | Avg completion: {data.get('avg_epic_completion_pct', 0)}%</p>
    <div class="epic-table-tools">
      <label><input type="checkbox" id="epicStaleOnly" /> Stale only</label>
      <button type="button" class="time-btn" id="epicShowAllBtn" style="display:none">Show all rows</button>
    </div>
    <div class="table-wrap">
      <table id="tableEpics">
        <thead><tr><th data-sort="project">Project</th><th data-sort="key">Key</th><th>Summary</th><th data-sort="age_days">Age (d)</th><th data-sort="total_children">Children</th><th data-sort="done_children">Done</th><th data-sort="completion_pct">%</th><th>Stale</th></tr></thead>
        <tbody>{''.join(
            f'<tr data-project="{html.escape(e.get("project",""))}" data-stale="{"1" if e.get("stale") else "0"}" data-date="{html.escape(str(e.get("created_date") or "")[:10])}" data-components="{html.escape("|".join(e.get("components", [])))}" style="{"color:var(--red)" if e.get("stale") else ""}">'
            f'<td>{html.escape(e.get("project",""))}</td><td>{link_key(e.get("key",""))}</td>'
            f'<td>{html.escape((e.get("summary",""))[:50])}</td><td>{e.get("age_days",0)}</td>'
            f'<td>{e.get("total_children",0)}</td><td>{e.get("done_children",0)}</td>'
            f'<td>{e.get("completion_pct",0)}%</td><td>{"Yes" if e.get("stale") else ""}</td></tr>'
            for e in sorted(epic_health, key=lambda x: (-1 if x.get("stale") else 0, -(x.get("age_days") or 0)))
        ) if epic_health else "<tr><td colspan='8'>No epic data</td></tr>"}</tbody>
      </table>
    </div>
  </section>
  <div class="grid2">
    <section>
      <h2>Median time in status (last 90d, hours)</h2>
      <p class="summary-desc">Near-zero time in active statuses = retroactive status changes.</p>
      <div class="chart-wrap"><canvas id="chartTimeInStatus"></canvas></div>
    </section>
    <section>
      <h2>Story point trend (avg SP/issue by month)</h2>
      <p class="summary-desc">Rising average may signal point inflation for velocity padding.</p>
      <div class="chart-wrap"><canvas id="chartSpTrend"></canvas></div>
    </section>
  </div>
  <section>
    <h2>Most common status paths (last 90d)</h2>
    <p class="summary-desc" id="skipDesc">Status skip rate: <strong>{spa.get('skip_pct', 0)}%</strong> ({spa.get('skip_count', 0)}/{spa.get('total', 0)} issues never entered an active work status).</p>
    <div class="table-wrap">
      <table><thead><tr><th>Status Path</th><th>Count</th></tr></thead>
      <tbody id="pathsTbody">{paths_rows}</tbody></table>
    </div>
  </section>
  <div class="grid2">
    <section>
      <h2>Worklog by day of week</h2>
      <p class="summary-desc">Weekend %: <strong id="weekendPct">{worklog_analysis.get('weekend_pct', 0)}%</strong>, SP-worklog correlation: <strong id="spCorr">{worklog_analysis.get('sp_worklog_correlation', 'N/A')}</strong></p>
      <div class="chart-wrap"><canvas id="chartWorklogDow"></canvas></div>
    </section>
    <section>
      <h2>Resolutions per day (bulk closure detection)</h2>
      <p class="summary-desc">Spikes indicate batch closure. Horizontal line = 10 issues/day threshold.</p>
      <div class="chart-wrap" style="max-width: 900px; height: 220px;"><canvas id="chartBulkClosure"></canvas></div>
    </section>
  </div>
  </div>

  <!-- ===== GIT TAB ===== -->
  <div class="tab-panel" id="panel-gitmetrics">
    <section><h2>Git Analytics</h2>
      <p class="summary-desc">Repository-scoped metrics from Git/GitHub. <strong>Jira</strong> project/component/team filters apply to Jira tabs only. Use the <strong>repository</strong> checkboxes below and the global <strong>time range</strong> (top) to scope PR and merge charts.</p>
    </section>
    <div class="project-filter" id="gitRepoFilterBar"></div>
    <p class="meta" id="gitBreakdownNote" style="display:none"></p>
    <div class="cards" id="gitCards"></div>
    <p class="meta" id="gitContribNote" style="display:none">Contributors and Min Bus Factor reflect the full data lookback period, not the active time filter.</p>
    <section><h2>PR cycle breakdown (median hours)</h2>
      <p class="summary-desc" id="gitBreakdownDesc">Coding &rarr; review/approval &rarr; merge (see <code>pr_cycle_breakdown_meta</code> in JSON when present).</p>
      <div class="cards" id="gitBreakdownCards"></div>
      <div class="chart-wrap" style="max-width:900px;height:280px"><canvas id="chartPrCycleBreakdown"></canvas></div>
    </section>
    <div class="grid2">
      <section><h2>PR Cycle Time by Week</h2><div class="chart-wrap"><canvas id="chartPrCycle"></canvas></div></section>
      <section><h2>Merge Frequency by Week</h2><div class="chart-wrap"><canvas id="chartMergeFreq"></canvas></div></section>
    </div>
    <div class="grid2">
      <section><h2>PR Size Distribution</h2><div class="chart-wrap"><canvas id="chartPrSize"></canvas></div></section>
      <section><h2>Review Turnaround by Week</h2><div class="chart-wrap"><canvas id="chartReviewTurnaround"></canvas></div></section>
    </div>
    <section><h2>Bus Factor by Repo</h2><div class="chart-wrap"><canvas id="chartBusFactor"></canvas></div></section>
    <section><h2>Branch Drift</h2><div id="branchDriftTable"></div></section>
  </div>

  <!-- ===== CI/CD TAB ===== -->
  <div class="tab-panel" id="panel-cicdmetrics">
    <section><h2>CI/CD Analytics</h2><p class="summary-desc">Build success rates, deployment frequency, MTTR, and change failure rate.</p></section>
    <div class="cards" id="cicdCards"></div>
    <div class="grid2">
      <section><h2>Build Time Trend</h2><div class="chart-wrap"><canvas id="chartBuildTime"></canvas></div></section>
      <section><h2>Deploy Frequency</h2><div class="chart-wrap"><canvas id="chartDeployFreq"></canvas></div></section>
    </div>
  </div>

  <!-- ===== DORA TAB ===== -->
  <div class="tab-panel" id="panel-dorametrics">
    <section><h2>DORA Four Key Metrics</h2><p class="summary-desc">Industry-standard delivery performance indicators.</p></section>
    <div class="cards" id="doraCards"></div>
    <section><h2>Benchmark Comparison</h2><div id="doraBenchmark"></div></section>
  </div>

  <!-- ===== SCORECARD TAB ===== -->
  <div class="tab-panel" id="panel-scorecardtab">
    <section><h2>Engineering Maturity Scorecard</h2><p class="summary-desc">5-domain maturity assessment. <a href="scorecard.html" target="_blank" style="color:var(--accent)">Open full scorecard &rarr;</a> (generate_scorecard writes this file next to the dashboard; publish both to the same path.)</p></section>
    <div class="cards" id="scorecardCards"></div>
    <section><h2>Radar</h2><div class="chart-wrap" style="max-width:420px;margin:0 auto"><canvas id="chartScoreRadar"></canvas></div></section>
    <section><h2>Signal Details</h2><div id="scorecardSignals"></div></section>
  </div>

  <script>
    const DATA = {data_js};
    const GIT_DATA = {git_data_js};
    const CICD_DATA = {cicd_data_js};
    const OCTOPUS_DATA = {octopus_data_js};
    const SCORECARD_DATA = {scorecard_data_js};
    const DORA_DATA = {evidence_data_js};
    const SCAN_HISTORY = {scan_history_js};
    const JIRA_BASE = (DATA.jira_base_url || '').replace(/\\/+$/, '');
    function linkKey(key) {{
      if (!key) return '';
      const k = String(key).replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;');
      if (JIRA_BASE) return '<a href="' + JIRA_BASE + '/browse/' + encodeURIComponent(key) + '" target="_blank" style="color:var(--accent)">' + k + '</a>';
      return k;
    }}

    // Tab switching
    (function() {{
      const bar = document.getElementById('tabBar');
      const panels = document.querySelectorAll('.tab-panel');
      const btns = bar.querySelectorAll('.tab-btn');
      function activate(tabId) {{
        btns.forEach(b => b.classList.toggle('active', b.dataset.tab === tabId));
        panels.forEach(p => p.classList.toggle('active', p.id === 'panel-' + tabId));
        history.replaceState(null, '', '#' + tabId);
        window.dispatchEvent(new Event('resize'));
      }}
      bar.addEventListener('click', e => {{
        const btn = e.target.closest('.tab-btn');
        if (btn) activate(btn.dataset.tab);
      }});
      const hash = location.hash.replace('#', '');
      if (hash && document.getElementById('panel-' + hash)) activate(hash);
    }})();

    // Time range filter state
    window._timeRange = {{ from: null, to: null }};
    (function() {{
      const btns = document.querySelectorAll('.time-btn[data-range]');
      const fromEl = document.getElementById('timeFrom');
      const toEl = document.getElementById('timeTo');
      function setRange(fromDate, toDate) {{
        window._timeRange = {{ from: fromDate, to: toDate }};
        if (typeof applyProjectFilter === 'function') applyProjectFilter();
        else if (typeof window.applyTimeFilter === 'function') window.applyTimeFilter();
      }}
      btns.forEach(btn => {{
        btn.addEventListener('click', function() {{
          btns.forEach(b => b.classList.remove('active'));
          this.classList.add('active');
          const r = this.dataset.range;
          if (r === 'all') {{
            fromEl.value = '';
            toEl.value = '';
            setRange(null, null);
          }} else {{
            const d = new Date();
            d.setDate(d.getDate() - parseInt(r));
            const iso = d.toISOString().slice(0, 10);
            fromEl.value = iso;
            toEl.value = '';
            setRange(iso, null);
          }}
        }});
      }});
      function onCustomChange() {{
        btns.forEach(b => b.classList.remove('active'));
        setRange(fromEl.value || null, toEl.value || null);
      }}
      fromEl.addEventListener('change', onCustomChange);
      toEl.addEventListener('change', onCustomChange);
    }})();

    function keyToComparableDate(k) {{
      const wMatch = k.match(/^(\\d{{4}})-W(\\d{{2}})$/);
      if (wMatch) {{
        const year = +wMatch[1], week = +wMatch[2];
        const jan4 = new Date(year, 0, 4);
        const dow = jan4.getDay() || 7;
        const mon = new Date(jan4);
        mon.setDate(jan4.getDate() - dow + 1 + (week - 1) * 7);
        return mon.toISOString().slice(0, 10);
      }}
      if (/^\\d{{4}}-\\d{{2}}$/.test(k)) return k + '-01';
      return k;
    }}

    function filterWeekKeys(keys, values) {{
      const tr = window._timeRange;
      if (!tr.from && !tr.to) return {{ keys, values }};
      const fk = [], fv = [];
      for (let i = 0; i < keys.length; i++) {{
        const d = keyToComparableDate(keys[i]);
        if (tr.from && d < tr.from) continue;
        if (tr.to && d > tr.to) continue;
        fk.push(keys[i]); fv.push(values[i]);
      }}
      return {{ keys: fk, values: fv }};
    }}

    function isDateInRange(dateStr) {{
      const tr = window._timeRange;
      if (!tr.from && !tr.to) return true;
      if (!dateStr) return true;
      const d = keyToComparableDate(dateStr.slice(0, 10));
      if (tr.from && d < tr.from) return false;
      if (tr.to && d > tr.to) return false;
      return true;
    }}

    Chart.defaults.color = '#8b949e';
    Chart.defaults.borderColor = '#30363d';

    const PHASE_EXACT = {{
      not_started: new Set(['to do','new','backlog','requirements gathering','open','selected for development','ready for development']),
      in_progress: new Set(['in progress','in dev','doing','development','in development']),
      review_qa: new Set(['for review','ready for qa','in testing','staging','qa passed','finished','approved','code review','in review','qa','testing']),
      blocked: new Set(['blocked','on hold','impediment']),
    }};
    function classifyPhase(name) {{
      const l = (name || '').trim().toLowerCase();
      for (const [phase, set] of Object.entries(PHASE_EXACT)) if (set.has(l)) return phase;
      if (/todo|to do|new|backlog|open|requirement/i.test(l)) return 'not_started';
      if (/progress|dev|doing/i.test(l)) return 'in_progress';
      if (/review|qa|test|staging|approved|finished/i.test(l)) return 'review_qa';
      if (/block|hold|impediment/i.test(l)) return 'blocked';
      return 'in_progress';
    }}
    function phaseFromStatusDist(sd) {{
      const r = {{not_started:0, in_progress:0, review_qa:0, blocked:0}};
      for (const [s,c] of Object.entries(sd||{{}})) r[classifyPhase(s)] += c;
      return r;
    }}
    function giniCoefficient(vals) {{
      if (!vals || vals.length < 2) return 0;
      const s = [...vals].sort((a,b) => a-b), n = s.length, tot = s.reduce((a,v) => a+v, 0);
      if (tot === 0) return 0;
      let g = 0; for (let i = 0; i < n; i++) g += (2*(i+1) - n - 1) * s[i];
      return Math.round(g / (n * tot) * 1000) / 1000;
    }}
    function isActiveStatusJS(name) {{
      const l = (name||'').trim().toLowerCase();
      return /progress|dev|doing|review|test|qa/.test(l);
    }}
    function computeFlowEff(tisData) {{
      let active = 0, wait = 0;
      for (const [st, d] of Object.entries(tisData||{{}})) {{
        const hrs = (d.avg_hours||0) * (d.count||0);
        if (isActiveStatusJS(st)) active += hrs; else wait += hrs;
      }}
      const total = active + wait;
      return {{ active_hours: Math.round(active*10)/10, wait_hours: Math.round(wait*10)/10, efficiency_pct: total > 0 ? Math.round(active/total*1000)/10 : 0 }};
    }}
    function sumLastWeeks(sourceDict, count=4) {{
      const keys = Object.keys(sourceDict || {{}}).sort().slice(-count);
      return keys.reduce((acc, key) => acc + (sourceDict[key] || 0), 0);
    }}

    function normalizeMetrics(source, scopeMeta) {{
      const s = source || {{}};
      const lead = s.lead_time_days || s.lead || null;
      const cycle = s.cycle_time_days || s.cycle || null;
      const wipAging = s.wip_aging_days || null;
      return Object.assign({{}}, s, {{
        run_iso_ts: s.run_iso_ts || DATA.run_iso_ts,
        lead,
        cycle,
        last_4_weeks: s.last_4_weeks != null ? s.last_4_weeks : sumLastWeeks(s.throughput_by_week || {{}}, 4),
        wip_median: scopeMeta && scopeMeta.nonAdditiveExact && wipAging && wipAging.p50_days != null ? Math.round(wipAging.p50_days) : null,
        open_by_phase: s.open_by_phase || phaseFromStatusDist(s.status_distribution || {{}}),
        wip_by_phase: s.wip_by_phase || s.open_by_phase || phaseFromStatusDist(s.status_distribution || {{}}),
        open_count: s.open_count != null ? s.open_count : s.wip_count,
        wip_in_flight: s.wip_in_flight,
        unassigned_open_count: s.unassigned_open_count != null ? s.unassigned_open_count : s.unassigned_wip_count,
        scope_meta: scopeMeta || {{}},
      }});
    }}

    function filterEpicsForScope(projects, components) {{
      return (DATA.epic_health || []).filter(epic => {{
        const projectOk = !projects || !projects.length || projects.includes(epic.project);
        const epicComponents = epic.components || [];
        const componentOk = !components || !components.length || components.some(c => epicComponents.includes(c));
        return projectOk && componentOk;
      }});
    }}

    function deriveEffectiveProjects(explicitProjects, selectedComponents) {{
      if (explicitProjects && explicitProjects.length) return explicitProjects;
      if (!selectedComponents || !selectedComponents.length) return null;
      const byPc = DATA.by_project_component || {{}};
      const implied = (DATA.projects || []).filter(pk =>
        selectedComponents.some(c => byPc[pk] && byPc[pk][c])
      );
      if (!implied.length || implied.length === (DATA.projects || []).length) return null;
      return implied;
    }}

    function getEffectiveData() {{
      const explicitProjects = getSelectedProjects();
      const selectedComponents = getSelectedComponents();
      const selectedTeams = getSelectedTeams();
      const effectiveProjects = deriveEffectiveProjects(explicitProjects, selectedComponents);
      const byProject = DATA.by_project || {{}};
      const byComponent = DATA.by_component || {{}};
      const byTeam = DATA.by_team || {{}};
      const byProjectComponent = DATA.by_project_component || {{}};

      const hasProjects = effectiveProjects && effectiveProjects.length;
      const hasComponents = selectedComponents && selectedComponents.length;
      const hasTeams = selectedTeams && selectedTeams.length;

      const labelProjects = hasProjects ? effectiveProjects.join(', ') : 'All projects';
      const labelComponents = hasComponents ? selectedComponents.join(', ') : 'All components';
      const labelTeams = hasTeams ? selectedTeams.join(', ') : 'All teams';
      const buildMeta = (exact) => ({{
        exactness: exact ? 'exact' : 'merged-additive',
        nonAdditiveExact: exact,
        effectiveProjects,
        components: selectedComponents,
        teams: selectedTeams,
        label: `Project: ${{labelProjects}} | Component: ${{labelComponents}} | Team: ${{labelTeams}} | Mode: ${{exact ? 'exact' : 'additive-only'}}`,
      }});

      let scoped;
      if (!hasProjects && !hasComponents && !hasTeams) {{
        scoped = normalizeMetrics(DATA, buildMeta(true));
      }} else if (hasTeams && !hasProjects && !hasComponents && selectedTeams.length === 1 && byTeam[selectedTeams[0]]) {{
        scoped = normalizeMetrics(byTeam[selectedTeams[0]], buildMeta(true));
      }} else if (hasProjects && effectiveProjects.length === 1 && !hasComponents && !hasTeams && byProject[effectiveProjects[0]]) {{
        scoped = normalizeMetrics(byProject[effectiveProjects[0]], buildMeta(true));
      }} else if (!hasProjects && hasComponents && selectedComponents.length === 1 && !hasTeams && byComponent[selectedComponents[0]]) {{
        scoped = normalizeMetrics(byComponent[selectedComponents[0]], buildMeta(true));
      }} else if (hasProjects && effectiveProjects.length === 1 && hasComponents && selectedComponents.length === 1 && !hasTeams && byProjectComponent[effectiveProjects[0]] && byProjectComponent[effectiveProjects[0]][selectedComponents[0]]) {{
        scoped = normalizeMetrics(byProjectComponent[effectiveProjects[0]][selectedComponents[0]], buildMeta(true));
      }} else {{
        const metricsList = [];
        if (hasTeams && !hasProjects && !hasComponents) {{
          for (const tn of selectedTeams) if (byTeam[tn]) metricsList.push(byTeam[tn]);
        }} else if (hasComponents && hasProjects) {{
          for (const pk of effectiveProjects) {{
            const compMap = byProjectComponent[pk] || {{}};
            for (const comp of selectedComponents) {{
              if (compMap[comp]) metricsList.push(compMap[comp]);
            }}
          }}
        }} else if (hasComponents) {{
          for (const comp of selectedComponents) if (byComponent[comp]) metricsList.push(byComponent[comp]);
        }} else if (hasProjects) {{
          for (const pk of effectiveProjects) if (byProject[pk]) metricsList.push(byProject[pk]);
        }}
        scoped = _mergeSource(metricsList, buildMeta(false)) || normalizeMetrics({{}}, buildMeta(false));
      }}

      let epicRows = filterEpicsForScope(effectiveProjects, selectedComponents);
      epicRows = epicRows.filter(epic => {{
        const ds = String(epic.created_date || '').slice(0, 10);
        if (!ds) return true;
        return isDateInRange(ds);
      }});
      const sprintRows = (DATA.sprint_metrics || []).filter(s => {{
        const projectOk = !hasProjects || effectiveProjects.includes(s.project);
        const sprintComponents = Object.keys(s.component_breakdown || {{}});
        const componentOk = !hasComponents || !sprintComponents.length || selectedComponents.some(c => sprintComponents.includes(c));
        const sprintTeams = Object.keys(s.team_breakdown || {{}});
        const teamOk = !hasTeams || !sprintTeams.length || selectedTeams.some(t => sprintTeams.includes(t));
        return projectOk && componentOk && teamOk;
      }});
      const bugRows = (DATA.oldest_open_bugs || []).filter(b => {{
        const projectOk = !hasProjects || effectiveProjects.includes(b.project);
        const bugComponents = b.components || [];
        const componentOk = !hasComponents || !bugComponents.length || selectedComponents.some(c => bugComponents.includes(c));
        const teamOk = !hasTeams || (b.team && selectedTeams.includes(b.team));
        return projectOk && componentOk && teamOk;
      }});
      scoped.open_epics_count = epicRows.length;
      scoped.stale_epics_count = epicRows.filter(e => e.stale).length;
      scoped.avg_epic_completion_pct = epicRows.length
        ? Math.round(epicRows.reduce((acc, epic) => acc + (epic.completion_pct || 0), 0) / epicRows.length * 10) / 10
        : 0;
      scoped.by_project = (!hasComponents)
        ? Object.fromEntries((effectiveProjects || []).filter(pk => byProject[pk]).map(pk => [pk, byProject[pk]]))
        : {{}};
      scoped.projects = effectiveProjects || (DATA.projects || []);
      scoped.velocity_cv_by_project = (!hasComponents)
        ? Object.fromEntries((effectiveProjects || []).map(pk => [pk, (DATA.velocity_cv_by_project || {{}})[pk]]).filter(([,v]) => v != null))
        : {{}};
      scoped.sprint_metrics = sprintRows;
      scoped.oldest_open_bugs = bugRows;
      return scoped;
    }}

    const _hbarScales = {{ y: {{ ticks: {{ crossAlign: 'far' }} }} }};
    const chartStatus = new Chart(document.getElementById('chartStatus'), {{
      type: 'bar',
      data: {{ labels: {json.dumps(status_labels)}, datasets: [{{ label: 'Issues', data: {json.dumps(status_values)}, backgroundColor: 'rgba(88,166,255,0.6)' }}] }},
      options: {{ indexAxis: 'y', responsive: true, maintainAspectRatio: false, plugins: {{ legend: {{ display: false }} }}, scales: _hbarScales }}
    }});

    const chartComponents = new Chart(document.getElementById('chartComponents'), {{
      type: 'bar',
      data: {{ labels: {json.dumps(comp_labels)}, datasets: [{{ label: 'Issues', data: {json.dumps(comp_values)}, backgroundColor: 'rgba(63,185,80,0.6)' }}] }},
      options: {{ indexAxis: 'y', responsive: true, maintainAspectRatio: false, plugins: {{ legend: {{ display: false }} }}, scales: _hbarScales }}
    }});

    const chartThroughput = new Chart(document.getElementById('chartThroughput'), {{
      type: 'bar',
      data: {{ labels: {json.dumps(weekly_labels)}, datasets: [{{ label: 'Resolved', data: {json.dumps(weekly_values)}, backgroundColor: 'rgba(210,153,34,0.6)' }}] }},
      options: {{ responsive: true, maintainAspectRatio: false, plugins: {{ legend: {{ display: false }} }} }}
    }});

    const rpm = DATA.releases_per_month || {{}};
    const rpmKeys = Object.keys(rpm).sort().slice(-24);
    const chartReleasesPerMonth = new Chart(document.getElementById('chartReleasesPerMonth'), {{
      type: 'bar',
      data: {{ labels: rpmKeys, datasets: [{{ label: 'Releases', data: rpmKeys.map(k => rpm[k] || 0), backgroundColor: 'rgba(63,185,80,0.6)' }}] }},
      options: {{ responsive: true, maintainAspectRatio: false, plugins: {{ legend: {{ display: false }} }} }}
    }});

    const phaseData = DATA.open_by_phase || DATA.wip_by_phase || {{}};
    const chartPhase = new Chart(document.getElementById('chartPhase'), {{
      type: 'doughnut',
      data: {{
        labels: ['Backlog','In progress','In review','Blocked'],
        datasets: [{{ data: [phaseData.backlog||phaseData.not_started||0, phaseData.in_progress||0, phaseData.in_review||phaseData.review_qa||0, phaseData.blocked||0],
          backgroundColor: ['rgba(139,148,158,0.6)','rgba(88,166,255,0.6)','rgba(210,153,34,0.6)','rgba(248,81,73,0.6)'],
          borderColor: ['#8b949e','#58a6ff','#d29922','#f85149'], borderWidth: 1 }}]
      }},
      options: {{ responsive: true, maintainAspectRatio: false, plugins: {{ legend: {{ position: 'right', labels: {{ padding: 12 }} }} }} }}
    }});

    const ltDist = DATA.lead_time_distribution || {{}};
    const chartLtDist = new Chart(document.getElementById('chartLtDist'), {{
      type: 'bar',
      data: {{
        labels: ['< 1 hour','1h \u2013 1 day','1 \u2013 7 days','7 \u2013 30 days','> 30 days'],
        datasets: [{{ label: 'Issues', data: [ltDist.under_1h||0, ltDist['1h_to_1d']||0, ltDist['1d_to_7d']||0, ltDist['7d_to_30d']||0, ltDist.over_30d||0],
          backgroundColor: ['rgba(248,81,73,0.7)','rgba(210,153,34,0.6)','rgba(63,185,80,0.6)','rgba(88,166,255,0.6)','rgba(139,148,158,0.6)'] }}]
      }},
      options: {{ responsive: true, maintainAspectRatio: false, plugins: {{ legend: {{ display: false }} }} }}
    }});

    // Resolution types (1b)
    const chartResolution = new Chart(document.getElementById('chartResolution'), {{
      type: 'doughnut',
      data: {{
        labels: {json.dumps(res_labels)},
        datasets: [{{ data: {json.dumps(res_values)},
          backgroundColor: ['rgba(63,185,80,0.7)','rgba(248,81,73,0.6)','rgba(210,153,34,0.6)','rgba(88,166,255,0.6)','rgba(139,148,158,0.6)','rgba(227,179,65,0.6)','rgba(163,113,247,0.6)'],
          borderWidth: 1 }}]
      }},
      options: {{ responsive: true, maintainAspectRatio: false, plugins: {{ legend: {{ position: 'right', labels: {{ padding: 8, font: {{ size: 11 }} }} }} }} }}
    }});

    // Issue types (1c)
    const wipIt = DATA.wip_issuetype || {{}};
    const doneIt = DATA.done_issuetype || {{}};
    const allTypes = [...new Set([...Object.keys(wipIt), ...Object.keys(doneIt)])];
    const itColors = ['rgba(88,166,255,0.6)','rgba(63,185,80,0.6)','rgba(248,81,73,0.6)','rgba(210,153,34,0.6)','rgba(139,148,158,0.6)','rgba(163,113,247,0.6)'];
    const chartIssueTypes = new Chart(document.getElementById('chartIssueTypes'), {{
      type: 'bar',
      data: {{
        labels: ['WIP','Done (180d)'],
        datasets: allTypes.map((t,i) => ({{ label: t, data: [wipIt[t]||0, doneIt[t]||0], backgroundColor: itColors[i % itColors.length] }}))
      }},
      options: {{ responsive: true, maintainAspectRatio: false, scales: {{ x: {{ stacked: true }}, y: {{ stacked: true }} }}, plugins: {{ legend: {{ position: 'bottom', labels: {{ font: {{ size: 10 }} }} }} }} }}
    }});

    // Priority distribution (1d)
    const priData = DATA.wip_priority || {{}};
    const priLabels = Object.keys(priData);
    const priColors = {{'Highest':'rgba(248,81,73,0.8)','High':'rgba(248,81,73,0.5)','Medium':'rgba(210,153,34,0.6)','Low':'rgba(88,166,255,0.5)','Lowest':'rgba(139,148,158,0.5)'}};
    const chartPriority = new Chart(document.getElementById('chartPriority'), {{
      type: 'bar',
      data: {{
        labels: priLabels,
        datasets: [{{ label: 'Issues', data: priLabels.map(l => priData[l]||0), backgroundColor: priLabels.map(l => priColors[l] || 'rgba(139,148,158,0.6)') }}]
      }},
      options: {{ responsive: true, maintainAspectRatio: false, plugins: {{ legend: {{ display: false }} }} }}
    }});

    // Day of week (1f)
    const dowData = DATA.resolution_by_weekday || {{}};
    const dowLabels = ['Mon','Tue','Wed','Thu','Fri','Sat','Sun'];
    const chartDow = new Chart(document.getElementById('chartDow'), {{
      type: 'bar',
      data: {{
        labels: dowLabels,
        datasets: [{{ label: 'Resolved', data: dowLabels.map(d => dowData[d]||0), backgroundColor: 'rgba(88,166,255,0.6)' }}]
      }},
      options: {{ responsive: true, maintainAspectRatio: false, plugins: {{ legend: {{ display: false }} }} }}
    }});

    // Top assignees (1h)
    const chartAssignees = new Chart(document.getElementById('chartAssignees'), {{
      type: 'bar',
      data: {{
        labels: {json.dumps([a[0] for a in assignee_items])},
        datasets: [{{ label: 'Resolved', data: {json.dumps([a[1] for a in assignee_items])}, backgroundColor: 'rgba(63,185,80,0.6)' }}]
      }},
      options: {{ indexAxis: 'y', responsive: true, maintainAspectRatio: false, plugins: {{ legend: {{ display: false }} }}, scales: _hbarScales }}
    }});

    // Bulk closure (1i)
    const bulkDays = DATA.bulk_closure_days || [];
    const chartBulkClosure = new Chart(document.getElementById('chartBulkClosure'), {{
      type: 'bar',
      data: {{
        labels: bulkDays.map(d => d.date),
        datasets: [{{ label: 'Resolutions', data: bulkDays.map(d => d.count), backgroundColor: 'rgba(248,81,73,0.6)' }}]
      }},
      options: {{ responsive: true, maintainAspectRatio: false, plugins: {{ legend: {{ display: false }} }} }}
    }});

    // Time in status (2b)
    const tisData = DATA.time_in_status || {{}};
    const tisSorted = Object.entries(tisData).sort((a,b) => (b[1].median_hours||0) - (a[1].median_hours||0)).slice(0, 12);
    const chartTimeInStatus = new Chart(document.getElementById('chartTimeInStatus'), {{
      type: 'bar',
      data: {{
        labels: tisSorted.map(x => x[0]),
        datasets: [{{ label: 'Median hours', data: tisSorted.map(x => x[1].median_hours||0), backgroundColor: tisSorted.map(x => {{
          const l = x[0].toLowerCase();
          if (/progress|dev|doing/.test(l)) return 'rgba(88,166,255,0.6)';
          if (/review|qa|test/.test(l)) return 'rgba(210,153,34,0.6)';
          if (/block|hold/.test(l)) return 'rgba(248,81,73,0.6)';
          return 'rgba(139,148,158,0.5)';
        }}) }}]
      }},
      options: {{ indexAxis: 'y', responsive: true, maintainAspectRatio: false, plugins: {{ legend: {{ display: false }} }}, scales: _hbarScales }}
    }});

    // Top closers (2c)
    const closerData = (DATA.closer_analysis || {{}}).top_closers || [];
    const chartClosers = new Chart(document.getElementById('chartClosers'), {{
      type: 'bar',
      data: {{
        labels: closerData.map(c => c.name),
        datasets: [{{ label: 'Issues closed', data: closerData.map(c => c.count), backgroundColor: 'rgba(163,113,247,0.6)' }}]
      }},
      options: {{ indexAxis: 'y', responsive: true, maintainAspectRatio: false, plugins: {{ legend: {{ display: false }} }}, scales: _hbarScales }}
    }});

    // Sprint added late
    const sprintLabels = DATA.sprint_metrics.map(s => s.project + ' \u2013 ' + (s.sprint_name || ''));
    const addedLateValues = DATA.sprint_metrics.map(s => s.added_after_sprint_start != null ? s.added_after_sprint_start : 0);
    const chartAddedLate = new Chart(document.getElementById('chartAddedLate'), {{
      type: 'bar',
      data: {{ labels: sprintLabels, datasets: [{{ label: 'Added after sprint start', data: addedLateValues, backgroundColor: 'rgba(248,81,73,0.6)' }}] }},
      options: {{ responsive: true, maintainAspectRatio: false, plugins: {{ legend: {{ display: false }} }} }}
    }});

    // Created vs Resolved trend (5a)
    const createdWeek = DATA.created_by_week || {{}};
    const resolvedWeek = DATA.throughput_by_week || {{}};
    const allWeeks = [...new Set([...Object.keys(createdWeek), ...Object.keys(resolvedWeek)])].sort().slice(-16);
    const chartCreatedResolved = new Chart(document.getElementById('chartCreatedResolved'), {{
      type: 'bar',
      data: {{
        labels: allWeeks,
        datasets: [
          {{ label: 'Created', data: allWeeks.map(w => createdWeek[w]||0), backgroundColor: 'rgba(248,81,73,0.5)' }},
          {{ label: 'Resolved', data: allWeeks.map(w => resolvedWeek[w]||0), backgroundColor: 'rgba(63,185,80,0.5)' }}
        ]
      }},
      options: {{ responsive: true, maintainAspectRatio: false, plugins: {{ legend: {{ position: 'top' }} }} }}
    }});

    // WIP by assignee (6a)
    const wipAss = DATA.wip_assignees || {{}};
    const wipAssItems = Object.entries(wipAss).sort((a,b)=>b[1]-a[1]).slice(0,20);
    const chartWipAssignees = new Chart(document.getElementById('chartWipAssignees'), {{
      type: 'bar',
      data: {{
        labels: wipAssItems.map(a => a[0]),
        datasets: [{{ label: 'WIP issues', data: wipAssItems.map(a => a[1]), backgroundColor: wipAssItems.map(([,v]) => v > 20 ? 'rgba(248,81,73,0.7)' : v > 10 ? 'rgba(210,153,34,0.6)' : 'rgba(88,166,255,0.6)') }}]
      }},
      options: {{ indexAxis: 'y', responsive: true, maintainAspectRatio: false, plugins: {{ legend: {{ display: false }} }}, scales: _hbarScales }}
    }});

    // WIP by Team chart
    const wipTeams = DATA.wip_teams || {{}};
    const wipTeamItems = Object.entries(wipTeams).sort((a,b) => b[1] - a[1]).slice(0, 20);
    const chartWipTeamsEl = document.getElementById('chartWipTeams');
    let chartWipTeams = null;
    if (chartWipTeamsEl) {{
      chartWipTeams = new Chart(chartWipTeamsEl, {{
        type: 'bar',
        data: {{
          labels: wipTeamItems.map(t => t[0]),
          datasets: [{{ label: 'WIP issues', data: wipTeamItems.map(t => t[1]), backgroundColor: 'rgba(88,166,255,0.6)' }}]
        }},
        options: {{ indexAxis: 'y', responsive: true, maintainAspectRatio: false, plugins: {{ legend: {{ display: false }} }}, scales: _hbarScales }}
      }});
    }}

    // Sprint throughput by team chart
    const sprintTeamData = {{}};
    (DATA.sprint_metrics || []).forEach(s => {{
      const tb = s.team_breakdown || {{}};
      for (const [team, count] of Object.entries(tb)) {{
        sprintTeamData[team] = (sprintTeamData[team] || 0) + count;
      }}
    }});
    const teamThrItems = Object.entries(sprintTeamData).sort((a,b) => b[1] - a[1]).slice(0, 20);
    const chartTeamThrEl = document.getElementById('chartTeamThroughput');
    let chartTeamThroughput = null;
    if (chartTeamThrEl) {{
      chartTeamThroughput = new Chart(chartTeamThrEl, {{
        type: 'bar',
        data: {{
          labels: teamThrItems.map(t => t[0]),
          datasets: [{{ label: 'Issues in sprints', data: teamThrItems.map(t => t[1]), backgroundColor: 'rgba(63,185,80,0.6)' }}]
        }},
        options: {{ indexAxis: 'y', responsive: true, maintainAspectRatio: false, plugins: {{ legend: {{ display: false }} }}, scales: _hbarScales }}
      }});
    }}

    // Logged vs Fixed Bugs (grouped bar)
    const _initBugCreated = DATA.bug_creation_by_week || {{}};
    const _initBugResolved = DATA.bug_resolved_by_week || {{}};
    const _initLvfWeeks = [...new Set([...Object.keys(_initBugCreated), ...Object.keys(_initBugResolved)])].sort().slice(-16);
    const chartBugLoggedVsFixed = new Chart(document.getElementById('chartBugLoggedVsFixed'), {{
      type: 'bar',
      data: {{
        labels: _initLvfWeeks,
        datasets: [
          {{ label: 'Bugs created', data: _initLvfWeeks.map(w => _initBugCreated[w]||0), backgroundColor: 'rgba(248,81,73,0.6)' }},
          {{ label: 'Bugs fixed', data: _initLvfWeeks.map(w => _initBugResolved[w]||0), backgroundColor: 'rgba(63,185,80,0.6)' }}
        ]
      }},
      options: {{ responsive: true, maintainAspectRatio: false }}
    }});

    // Bug creation rate (5b)
    const bugWeek = DATA.bug_creation_by_week || {{}};
    const bugWeeks = Object.keys(bugWeek).sort().slice(-16);
    const chartBugCreation = new Chart(document.getElementById('chartBugCreation'), {{
      type: 'bar',
      data: {{
        labels: bugWeeks,
        datasets: [{{ label: 'Bugs created', data: bugWeeks.map(w => bugWeek[w]||0), backgroundColor: 'rgba(248,81,73,0.6)' }}]
      }},
      options: {{ responsive: true, maintainAspectRatio: false, plugins: {{ legend: {{ display: false }} }} }}
    }});

    // Defect density by component (5c)
    const bc = DATA.by_component || {{}};
    const ddItems = Object.entries(bc)
      .filter(([,m]) => ((m.open_count != null ? m.open_count : m.wip_count)||0) > 0)
      .map(([name, m]) => [name, Math.round((m.open_bugs_count||0) / ((m.open_count != null ? m.open_count : m.wip_count)||1) * 1000) / 10])
      .sort((a,b) => b[1] - a[1])
      .slice(0, 15);
    const chartDefectDensity = new Chart(document.getElementById('chartDefectDensity'), {{
      type: 'bar',
      data: {{
        labels: ddItems.map(d => d[0]),
        datasets: [{{ label: 'Bugs / WIP %', data: ddItems.map(d => d[1]), backgroundColor: ddItems.map(([,v]) => v > 30 ? 'rgba(248,81,73,0.7)' : v > 10 ? 'rgba(210,153,34,0.6)' : 'rgba(88,166,255,0.6)') }}]
      }},
      options: {{ indexAxis: 'y', responsive: true, maintainAspectRatio: false, plugins: {{ legend: {{ display: false }} }}, scales: _hbarScales }}
    }});

    // Open bugs by priority (doughnut)
    const _initBugPri = DATA.open_bugs_by_priority || {{}};
    const _initBugPriLabels = Object.keys(_initBugPri);
    const _bugPriColors = ['rgba(248,81,73,0.7)', 'rgba(210,153,34,0.7)', 'rgba(88,166,255,0.7)', 'rgba(63,185,80,0.7)', 'rgba(139,148,158,0.6)', 'rgba(188,140,255,0.6)'];
    const chartBugPriority = new Chart(document.getElementById('chartBugPriority'), {{
      type: 'doughnut',
      data: {{
        labels: _initBugPriLabels,
        datasets: [{{ data: _initBugPriLabels.map(l => _initBugPri[l]||0), backgroundColor: _bugPriColors.slice(0, _initBugPriLabels.length) }}]
      }},
      options: {{ responsive: true, maintainAspectRatio: false, plugins: {{ legend: {{ position: 'right' }} }} }}
    }});

    // Resolution breakdown (doughnut)
    const _initRb = DATA.resolution_breakdown || {{}};
    const _initRbLabels = Object.keys(_initRb);
    const _rbColors = ['rgba(63,185,80,0.7)', 'rgba(210,153,34,0.7)', 'rgba(248,81,73,0.7)', 'rgba(88,166,255,0.7)', 'rgba(139,148,158,0.6)', 'rgba(188,140,255,0.6)', 'rgba(255,203,107,0.6)'];
    const chartResBreakdown = new Chart(document.getElementById('chartResolutionBreakdown'), {{
      type: 'doughnut',
      data: {{
        labels: _initRbLabels,
        datasets: [{{ data: _initRbLabels.map(l => _initRb[l]||0), backgroundColor: _rbColors.slice(0, _initRbLabels.length) }}]
      }},
      options: {{ responsive: true, maintainAspectRatio: false, plugins: {{ legend: {{ position: 'right' }} }} }}
    }});

    // Time in status — Quality tab (bottleneck horizontal bar, avg hours)
    const _initQTis = DATA.time_in_status || {{}};
    const _initQTisItems = Object.entries(_initQTis).sort((a,b) => (b[1].avg_hours||0) - (a[1].avg_hours||0)).slice(0, 12);
    const chartQualityTIS = new Chart(document.getElementById('chartQualityTimeInStatus'), {{
      type: 'bar',
      data: {{
        labels: _initQTisItems.map(t => t[0]),
        datasets: [{{ label: 'Avg hours', data: _initQTisItems.map(t => t[1].avg_hours||0), backgroundColor: 'rgba(88,166,255,0.6)' }}]
      }},
      options: {{ indexAxis: 'y', responsive: true, maintainAspectRatio: false, plugins: {{ legend: {{ display: false }} }}, scales: _hbarScales }}
    }});

    // Focus factor — histogram of WIP per assignee (6c)
    const wipAssObj = DATA.wip_assignees || {{}};
    const wipCounts = Object.entries(wipAssObj).filter(([k]) => k !== '(unassigned)').map(([,v]) => v);
    const ffBuckets = {{'1': 0, '2-3': 0, '4-5': 0, '6-10': 0, '11-20': 0, '20+': 0}};
    for (const c of wipCounts) {{
      if (c <= 1) ffBuckets['1']++;
      else if (c <= 3) ffBuckets['2-3']++;
      else if (c <= 5) ffBuckets['4-5']++;
      else if (c <= 10) ffBuckets['6-10']++;
      else if (c <= 20) ffBuckets['11-20']++;
      else ffBuckets['20+']++;
    }}
    const ffLabels = Object.keys(ffBuckets);
    const chartFocusFactor = new Chart(document.getElementById('chartFocusFactor'), {{
      type: 'bar',
      data: {{
        labels: ffLabels,
        datasets: [{{ label: 'People', data: ffLabels.map(l => ffBuckets[l]), backgroundColor: ['rgba(63,185,80,0.7)','rgba(63,185,80,0.6)','rgba(88,166,255,0.6)','rgba(210,153,34,0.6)','rgba(248,81,73,0.6)','rgba(248,81,73,0.8)'] }}]
      }},
      options: {{ responsive: true, maintainAspectRatio: false, plugins: {{ legend: {{ display: false }} }}, scales: {{ x: {{ title: {{ display: true, text: 'WIP issues per person' }} }}, y: {{ title: {{ display: true, text: 'People count' }} }} }} }}
    }});

    // SP trend (4a)
    const spTrend = (DATA.sp_trend || {{}}).by_month || {{}};
    const spMonths = Object.keys(spTrend).sort();
    const chartSpTrend = new Chart(document.getElementById('chartSpTrend'), {{
      type: 'line',
      data: {{
        labels: spMonths,
        datasets: [{{
          label: 'Avg SP/issue',
          data: spMonths.map(m => spTrend[m]?.avg_sp || 0),
          borderColor: '#58a6ff', backgroundColor: 'rgba(88,166,255,0.15)',
          fill: true, tension: 0.3
        }}]
      }},
      options: {{ responsive: true, maintainAspectRatio: false, plugins: {{ legend: {{ display: false }} }} }}
    }});

    // Worklog by day of week (6b)
    const wlDow = (DATA.worklog_analysis || {{}}).by_dow || {{}};
    const wlDowLabels = ['Mon','Tue','Wed','Thu','Fri','Sat','Sun'];
    const chartWorklogDow = new Chart(document.getElementById('chartWorklogDow'), {{
      type: 'bar',
      data: {{
        labels: wlDowLabels,
        datasets: [{{ label: 'Hours', data: wlDowLabels.map(d => wlDow[d]||0), backgroundColor: wlDowLabels.map(d => (d==='Sat'||d==='Sun') ? 'rgba(248,81,73,0.7)' : 'rgba(88,166,255,0.6)') }}]
      }},
      options: {{ responsive: true, maintainAspectRatio: false, plugins: {{ legend: {{ display: false }} }} }}
    }});

    // ---------- Audit Flags (expanded) ----------
    const AUDIT_CAT_LABELS = {{ workflow: 'Workflow', throughput: 'Throughput', sprint: 'Sprint', people: 'People', release: 'Release', other: 'Other', git_cicd: 'Git/CI/CD' }};
    function renderAuditCategoryOptions() {{
      const sel = document.getElementById('auditFilterCategory');
      if (!sel) return;
      const cats = new Set((window._auditFlagsAll || []).map(f => f.category).filter(Boolean));
      const order = ['workflow','throughput','sprint','people','release','other','git_cicd'];
      const cur = sel.value;
      sel.innerHTML = '<option value="all">All</option>' + order.filter(c => cats.has(c)).map(c => `<option value="${{c}}">${{AUDIT_CAT_LABELS[c]||c}}</option>`).join('');
      if ([...sel.options].some(o => o.value === cur)) sel.value = cur;
    }}
    function renderAuditDataHealth() {{
      const el = document.getElementById('auditDataHealth');
      if (!el) return;
      const missing = [];
      if (!GIT_DATA || !Object.keys(GIT_DATA).length) missing.push('Git');
      if (!CICD_DATA || !Object.keys(CICD_DATA).length) missing.push('CI/CD');
      if (!OCTOPUS_DATA || !Object.keys(OCTOPUS_DATA).length) missing.push('Octopus');
      if (!missing.length) {{ el.style.display = 'none'; el.textContent = ''; return; }}
      el.style.display = 'block';
      el.textContent = 'Note: ' + missing.join(', ') + ' data not loaded — audit flags from those sources are skipped.';
    }}
    function renderAuditFlagsDOM() {{
      const container = document.getElementById('auditFlags');
      if (!container) return;
      const sevF = document.getElementById('auditFilterSeverity')?.value || 'all';
      const catF = document.getElementById('auditFilterCategory')?.value || 'all';
      let list = [...(window._auditFlagsAll || [])];
      if (sevF !== 'all') list = list.filter(f => f.severity === sevF);
      if (catF !== 'all') list = list.filter(f => f.category === catF);
      if (list.length === 0) {{
        container.innerHTML = '<div class="audit-flag" style="border-left-color:var(--green)"><div class="flag-title" style="color:var(--green)">No flags match filters</div><div class="flag-detail">Try All severities and All categories.</div></div>';
        window._auditFlags = [];
        return;
      }}
      const order = {{ red: 0, orange: 1, yellow: 2 }};
      list.sort((a, b) => (order[a.severity] ?? 9) - (order[b.severity] ?? 9));
      const L = AUDIT_CAT_LABELS;
      container.innerHTML = list.map(f =>
        `<div class="audit-flag ${{f.severity}}"><div class="flag-cat">${{L[f.category]||f.category||''}}</div><div class="flag-title">${{f.title}}</div><div class="flag-detail">${{f.detail}}</div></div>`
      ).join('');
      window._auditFlags = list;
    }}
    function renderAuditGamingStrip() {{
      const strip = document.getElementById('auditGamingStrip');
      if (!strip) return;
      const gs = window._gamingScore;
      const drivers = window._gamingScoreDrivers || [];
      if (gs == null) {{ strip.style.display = 'none'; return; }}
      strip.style.display = 'block';
      const c = gs >= 60 ? 'var(--red)' : gs >= 40 ? 'var(--orange)' : gs >= 20 ? '#e3b341' : 'var(--green)';
      const ul = drivers.length ? '<ul style="margin:0.35rem 0 0 1.1rem;padding:0;line-height:1.4">' + drivers.slice(0,3).map(d => `<li>${{d}}</li>`).join('') + '</ul>' : '';
      strip.innerHTML = `<strong style="color:${{c}}">Gaming score: ${{gs}}</strong>/100 <span style="color:var(--muted)">(larger = more manipulation signals)</span>. Top drivers: ${{ul}}<div style="margin-top:0.35rem">See the gauge on the <a href="#overview">Overview</a> tab.</div>`;
    }}
    function computeAuditFlags() {{
      const D = getEffectiveData();
      const flags = [];
      const sev = (s, cat, title, detail) => flags.push({{ severity: s, category: cat, title, detail }});
      const bp = D.by_project || {{}};

      const ltd = D.lead_time_distribution || {{}};
      const ltTotal = ltd.total || 0;
      const instantPct = ltTotal ? Math.round((ltd.under_1h || 0) / ltTotal * 100) : 0;
      if (instantPct > 30)
        sev('red', 'throughput', `${{instantPct}}% of resolved issues have lead time < 1 hour (retroactive logging likely)`,
          `${{ltd.under_1h}} of ${{ltTotal}} issues created and resolved within 1 hour.`);
      else if (instantPct > 15)
        sev('orange', 'throughput', `${{instantPct}}% of resolved issues have lead time < 1 hour`,
          `${{ltd.under_1h}} of ${{ltTotal}} issues. Consider whether tickets are being logged after work is done.`);

      const ct = D.cycle_time_days || {{}};
      if (ct.p50_days != null && ct.p50_days < 0.01 && ct.avg_days != null && ct.avg_days > 1)
        sev('red', 'workflow', `Cycle time median is ${{(ct.p50_days * 24 * 60).toFixed(0)}} min vs average ${{ct.avg_days.toFixed(1)}} days`,
          'Near-zero median with high average confirms most issues skip the normal workflow.');

      const sprints = D.sprint_metrics || [];
      const byProj = {{}};
      sprints.forEach(s => {{ if (!byProj[s.project]) byProj[s.project] = []; byProj[s.project].push(s); }});
      for (const [proj, pSprints] of Object.entries(byProj)) {{
        const perfect = pSprints.filter(s => s.total_issues > 0 && s.throughput_issues === s.total_issues);
        if (perfect.length >= 3)
          sev('red', 'sprint', `${{proj}}: ${{perfect.length}}/${{pSprints.length}} sprints with 100% completion`,
            'Every issue marked done. Unfinished work is likely removed before sprint close.');
      }}

      for (const [proj, pSprints] of Object.entries(byProj)) {{
        const highScope = pSprints.filter(s => s.total_issues > 0 && s.added_after_sprint_start != null && s.added_after_sprint_start / s.total_issues > 0.5);
        if (highScope.length > 0)
          sev('orange', 'sprint', `${{proj}}: ${{highScope.length}} sprint(s) with > 50% issues added after start`,
            highScope.map(s => `${{s.sprint_name}}: ${{s.added_after_sprint_start}}/${{s.total_issues}}`).join('; '));
      }}

      const emptySprints = sprints.filter(s => s.total_issues === 0);
      if (emptySprints.length > 0)
        sev('orange', 'sprint', `${{emptySprints.length}} empty sprint(s) (0 issues)`,
          emptySprints.map(s => `${{s.project}} \u2013 ${{s.sprint_name}}`).join(', '));

      for (const [proj, pSprints] of Object.entries(byProj)) {{
        const totalDone = pSprints.reduce((a, s) => a + s.throughput_issues, 0);
        const totalIssues = pSprints.reduce((a, s) => a + s.total_issues, 0);
        if (pSprints.length >= 2 && totalIssues > 5 && totalDone / totalIssues < 0.15)
          sev('orange', 'sprint', `${{proj}}: Only ${{totalDone}}/${{totalIssues}} done across ${{pSprints.length}} sprints (${{Math.round(totalDone/totalIssues*100)}}%)`,
            'Very little is being completed.');
      }}

      const noSp = Object.entries(byProj).filter(([, sp]) => sp.every(s => s.committed === 0 || s.committed === null));
      if (noSp.length > 0)
        sev('yellow', 'sprint', `${{noSp.length}} project(s) do not use story points: ${{noSp.map(x => x[0]).join(', ')}}`,
          'Velocity is issue-count only. Throughput numbers cannot distinguish a 5-min task from a 2-week feature.');

      const graveyards = [];
      for (const [proj, pm] of Object.entries(bp)) {{
        const ph = pm.open_by_phase || pm.wip_by_phase || {{}};
        const backlog = ph.backlog != null ? ph.backlog : (ph.not_started||0);
        const total = backlog + (ph.in_progress||0) + (ph.in_review||ph.review_qa||0) + (ph.blocked||0);
        if (total >= 20 && backlog / total > 0.85)
          graveyards.push(`${{proj}} (${{backlog}}/${{total}})`);
      }}
      if (graveyards.length > 0)
        sev('orange', 'workflow', `${{graveyards.length}} project(s) with > 85% open in Backlog`,
          graveyards.join('; ') + '. These backlogs are graveyards.');

      const blockedCount = D.blocked_count || 0;
      const openCount = D.open_count != null ? D.open_count : (D.wip_count || 1);
      const blockedPct = Math.round(blockedCount / openCount * 1000) / 10;
      if (blockedPct < 1 && openCount > 50)
        sev('yellow', 'workflow', `Only ${{blockedCount}} blocked issues (${{blockedPct}}% of ${{openCount}} open)`,
          'In orgs with cross-team dependencies, 5\\u201315% blocked is normal. Very low rates usually mean blockers are not tracked.');

      const oldBugs = (D.oldest_open_bugs || []).filter(b => b.age_days > 365);
      if (oldBugs.length >= 5)
        sev('red', 'other', `${{oldBugs.length}} open bugs older than 1 year`,
          `Oldest: ${{oldBugs.slice(0,5).map(b => linkKey(b.key)+' ('+Math.round(b.age_days)+'d)').join(', ')}}.`);
      else if (oldBugs.length > 0)
        sev('orange', 'other', `${{oldBugs.length}} open bug(s) older than 1 year`,
          oldBugs.map(b => linkKey(b.key)+' ('+Math.round(b.age_days)+'d)').join(', '));

      const bugAge = D.open_bugs_age_days || {{}};
      if (bugAge.p50_days != null && bugAge.p50_days > 180)
        sev('orange', 'other', `Median open bug age is ${{Math.round(bugAge.p50_days)}} days`,
          'Bugs have a median age over 6 months.');

      for (const [proj, pm] of Object.entries(bp)) {{
        const pLtd = pm.lead_time_distribution || {{}};
        const pTotal = pLtd.total || 0;
        const pInstPct = pTotal >= 10 ? Math.round((pLtd.under_1h||0) / pTotal * 100) : 0;
        if (pInstPct > 50)
          sev('red', 'throughput', `${{proj}}: ${{pInstPct}}% of resolved issues < 1 hour (${{pLtd.under_1h}}/${{pTotal}})`,
            'Majority of work is logged retroactively.');
        else if (pInstPct > 30 && pTotal >= 20)
          sev('orange', 'throughput', `${{proj}}: ${{pInstPct}}% of resolved issues < 1 hour (${{pLtd.under_1h}}/${{pTotal}})`,
            'Significant retroactive ticket logging.');
      }}

      const rb = D.resolution_breakdown || {{}};
      const rbTotal = Object.values(rb).reduce((a,v) => a+v, 0);
      const rbNonDone = (rb["Won't Do"]||0) + (rb["Duplicate"]||0) + (rb["Cannot Reproduce"]||0) + (rb["Incomplete"]||0) + (rb["Won't Fix"]||0);
      const rbPct = rbTotal ? Math.round(rbNonDone / rbTotal * 100) : 0;
      if (rbPct > 40)
        sev('red', 'throughput', `${{rbPct}}% of resolved issues are Won't Do/Duplicate/etc (${{rbNonDone}}/${{rbTotal}})`,
          'Throughput numbers are heavily inflated by administrative closures.');
      else if (rbPct > 25)
        sev('orange', 'throughput', `${{rbPct}}% of resolved issues are Won't Do/Duplicate/etc`,
          'Consider separating real work throughput from administrative closures.');

      const dit = D.done_issuetype || {{}};
      const ditTotal = Object.values(dit).reduce((a,v) => a+v, 0);
      const taskPct = ditTotal ? Math.round((dit['Task']||0) / ditTotal * 100) : 0;
      if (taskPct > 80)
        sev('yellow', 'throughput', `${{taskPct}}% of done issues are Tasks (not Stories/Epics)`,
          'No feature-level planning visible. Throughput is granular task-count only.');

      const pri = D.wip_priority || {{}};
      const priTotal = Object.values(pri).reduce((a,v) => a+v, 0);
      const priMax = Math.max(...Object.values(pri), 0);
      if (priTotal > 20 && priMax / priTotal > 0.9)
        sev('yellow', 'workflow', `${{Math.round(priMax/priTotal*100)}}% of WIP has the same priority`,
          'Priority field is not being used for triage.');

      const unassigned = D.unassigned_open_count != null ? D.unassigned_open_count : (D.unassigned_wip_count || 0);
      const unaPct = openCount ? Math.round(unassigned / openCount * 100) : 0;
      if (unaPct > 50)
        sev('orange', 'people', `${{unaPct}}% of open is unassigned (${{unassigned}}/${{openCount}})`,
          'Majority of open issues have no owner.');
      else if (unaPct > 30 && openCount > 30)
        sev('yellow', 'people', `${{unaPct}}% of open is unassigned (${{unassigned}}/${{openCount}})`,
          'Significant portion of open has no assignee.');

      const dow = D.resolution_by_weekday || {{}};
      const dowTotal = Object.values(dow).reduce((a,v) => a+v, 0);
      for (const [day, count] of Object.entries(dow)) {{
        if (dowTotal > 20 && count / dowTotal > 0.35)
          sev('orange', 'throughput', `${{Math.round(count/dowTotal*100)}}% of resolutions happen on ${{day}} (${{count}}/${{dowTotal}})`,
            'Resolution activity is concentrated on a single day, suggesting batch closure.');
      }}

      const vcv = D.velocity_cv_by_project || {{}};
      for (const [proj, cv] of Object.entries(vcv)) {{
        if (cv !== null && cv < 0.10 && (byProj[proj]||[]).length >= 4)
          sev('orange', 'sprint', `${{proj}}: Velocity CV is ${{(cv*100).toFixed(1)}}% (suspiciously stable)`,
            'Real teams fluctuate 20-40%. Very low variance suggests sprint scope is being managed to hit targets.');
        else if (cv !== null && cv > 0.60)
          sev('yellow', 'sprint', `${{proj}}: Velocity CV is ${{(cv*100).toFixed(1)}}% (highly unstable)`,
            'Suggests poor planning or significant scope churn.');
      }}

      const gini = D.workload_gini;
      if (gini != null && gini > 0.7)
        sev('orange', 'people', `Workload Gini coefficient is ${{gini}} (heavily concentrated)`,
          'Work is disproportionately done by a few people.');

      const bulk = D.bulk_closure_days || [];
      const bigBulk = bulk.filter(d => d.count > 40);
      const medBulk = bulk.filter(d => d.count > 20);
      if (bigBulk.length > 0)
        sev('red', 'throughput', `${{bigBulk.length}} day(s) with > 40 issues resolved`,
          bigBulk.map(d => `${{d.date}}: ${{d.count}}`).join(', '));
      else if (medBulk.length > 0)
        sev('orange', 'throughput', `${{medBulk.length}} day(s) with > 20 issues resolved`,
          medBulk.slice(0,5).map(d => `${{d.date}}: ${{d.count}}`).join(', '));

      const spa = D.status_path_analysis || {{}};
      if (spa.skip_pct > 30 && spa.total >= 20)
        sev('red', 'workflow', `${{spa.skip_pct}}% of resolved issues skip active work statuses (${{spa.skip_count}}/${{spa.total}})`,
          'Issues go directly to Done without ever entering In Progress/Dev/Review.');
      else if (spa.skip_pct > 15 && spa.total >= 20)
        sev('orange', 'workflow', `${{spa.skip_pct}}% of resolved issues skip active work statuses`,
          'Consider whether workflow statuses reflect reality.');

      const tis = D.time_in_status || {{}};
      const ipTime = tis['In Progress'] || tis['In Dev'] || tis['Doing'];
      if (ipTime && ipTime.median_hours != null && ipTime.median_hours < 0.1 && ipTime.count > 10)
        sev('red', 'workflow', `Median time in "${{Object.keys(tis).find(k => /progress|dev|doing/i.test(k)) || 'In Progress'}}" is ${{(ipTime.median_hours * 60).toFixed(0)}} minutes`,
          'Statuses are being set retroactively, not during actual work.');

      const ca = D.closer_analysis || {{}};
      if (ca.closer_not_assignee_pct > 60 && ca.total_analyzed > 20)
        sev('orange', 'workflow', `${{ca.closer_not_assignee_pct}}% of issues are closed by someone other than the assignee`,
          'Issues are predominantly closed by a different person than who worked on them.');
      const topCloser = (ca.top_closers || [])[0];
      if (topCloser && ca.total_analyzed > 20 && topCloser.count / ca.total_analyzed > 0.4)
        sev('orange', 'workflow', `${{topCloser.name}} closes ${{Math.round(topCloser.count/ca.total_analyzed*100)}}% of all issues (${{topCloser.count}}/${{ca.total_analyzed}})`,
          'Single person closing majority of issues suggests centralized batch processing.');

      const ra = D.reopen_analysis || {{}};
      if (ra.reopened_pct > 15 && ra.total > 20)
        sev('orange', 'other', `${{ra.reopened_pct}}% of issues were reopened (${{ra.reopened_count}}/${{ra.total}})`,
          'High reopen rate suggests premature closure or quality issues.');

      const fe = D.flow_efficiency || {{}};
      if (fe.efficiency_pct != null && fe.efficiency_pct < 10 && (fe.active_hours + fe.wait_hours) > 100)
        sev('orange', 'workflow', `Flow efficiency is only ${{fe.efficiency_pct}}%`,
          `Issues spend only ${{fe.efficiency_pct}}% of their time in active work statuses.`);

      for (const [proj, pSprints] of Object.entries(byProj)) {{
        const highEnd = pSprints.filter(s => s.resolved_last_24h_pct != null && s.resolved_last_24h_pct > 60 && s.throughput_issues > 5);
        if (highEnd.length > 0)
          sev('red', 'sprint', `${{proj}}: ${{highEnd.length}} sprint(s) with > 60% issues resolved in final 24h`,
            highEnd.map(s => `${{s.sprint_name}}: ${{s.resolved_last_24h_pct}}%`).join('; '));
      }}

      const edp = D.empty_description_done_pct;
      if (edp != null && edp > 40)
        sev('orange', 'workflow', `${{edp}}% of done issues have no description`,
          'Issues are closed without descriptions, suggesting retroactive logging.');

      const eobDonePct = D.empty_or_bad_pct_done ?? 0;
      const eobDoneCount = D.empty_or_bad_count_done ?? 0;
      if (eobDonePct > 40 && eobDoneCount > 10)
        sev('orange', 'workflow', `${{eobDoneCount}} done issues (${{eobDonePct}}%) have empty or bad structure`,
          'Tickets closed with no/empty description or bad structure. Track improvement over time.');
      const eobWip = D.empty_or_bad_count_wip ?? 0;
      if (eobWip > 100)
        sev('yellow', 'workflow', `${{eobWip}} WIP issues have empty or bad structure`,
          'Many open tickets lack description or have bad structure. Consider cleanup.');

      const zcp = D.zero_comment_done_pct;
      if (zcp != null && zcp > 60)
        sev('yellow', 'workflow', `${{zcp}}% of done issues have zero comments`,
          'Most resolved issues have no discussion or review trail.');

      const orp = D.orphan_done_pct;
      if (orp != null && orp > 70)
        sev('yellow', 'other', `${{orp}}% of done issues have no issue links`,
          'Issues are not linked to other work, making traceability impossible.');

      // Phase 4b: Sprint scope padding (added and immediately done)
      for (const [proj, pSprints] of Object.entries(byProj)) {{
        const paddedSprints = pSprints.filter(s => s.added_and_done_count != null && s.total_issues > 5 && s.added_and_done_count / s.total_issues > 0.2);
        if (paddedSprints.length > 0)
          sev('red', 'sprint', `${{proj}}: ${{paddedSprints.length}} sprint(s) with > 20% issues added AND done (scope padding)`,
            paddedSprints.map(s => `${{s.sprint_name}}: ${{s.added_and_done_count}}/${{s.total_issues}}`).join('; '));
      }}

      // Phase 4c: Assignee change near resolution
      const acnr = D.assignee_change_near_resolution || {{}};
      if (acnr.changed_pct > 15 && acnr.total > 20)
        sev('orange', 'workflow', `${{acnr.changed_pct}}% of issues had assignee changed in last 24h before resolution (${{acnr.changed_count}}/${{acnr.total}})`,
          'Potential credit reassignment or completion sniping.');

      // Phase 4d: Post-resolution worklogs
      const wla = D.worklog_analysis || {{}};
      if (wla.post_resolution_worklog_pct > 20 && wla.total_done > 10)
        sev('orange', 'workflow', `${{wla.post_resolution_worklog_pct}}% of done issues have worklogs after resolution (${{wla.post_resolution_worklog_count}}/${{wla.total_done}})`,
          'Time is being logged retroactively after issue closure.');
      if (wla.zero_worklog_pct > 80 && wla.total_done > 20)
        sev('yellow', 'workflow', `${{wla.zero_worklog_pct}}% of done issues have zero worklogs`,
          'No time tracking for the vast majority of completed work.');

      // Phase 4e: Post-resolution comments
      const ctm = D.comment_timing || {{}};
      if (ctm.post_resolution_comment_pct > 30 && ctm.total_issues > 20)
        sev('orange', 'workflow', `${{ctm.post_resolution_comment_pct}}% of done issues have comments added after resolution`,
          'High rate of post-resolution documentation suggests retroactive activity.');

      // Phase 4a: Story point inflation
      const spt = D.sp_trend || {{}};
      if (spt.inflation_detected)
        sev('orange', 'sprint', 'Story point inflation detected (avg SP/issue rose > 30% over period)',
          'Teams may be inflating estimates to meet velocity targets.');

      // Phase 5a: Backlog growth (created > resolved for 4+ weeks)
      const cbw = D.created_by_week || {{}};
      const tbw = D.throughput_by_week || {{}};
      const trendWeeks = [...new Set([...Object.keys(cbw), ...Object.keys(tbw)])].sort().slice(-8);
      let consGrowth = 0;
      for (const w of trendWeeks) {{ if ((cbw[w]||0) > (tbw[w]||0)) consGrowth++; else consGrowth = 0; }}
      if (consGrowth >= 4)
        sev('orange', 'workflow', `Backlog growing: created > resolved for ${{consGrowth}} consecutive weeks`,
          'The team is not keeping up with incoming work.');

      // Phase 6a: WIP overload per person
      const wipAss = D.wip_assignees || {{}};
      const overloaded = Object.entries(wipAss).filter(([k,v]) => k !== '(unassigned)' && v > 20);
      if (overloaded.length > 0)
        sev('orange', 'people', `${{overloaded.length}} person(s) with > 20 WIP issues`,
          overloaded.slice(0,5).map(([n,c]) => `${{n}}: ${{c}}`).join(', '));

      // Phase 6d: Stale epics
      const staleEpics = D.stale_epics_count || 0;
      if (staleEpics > 3)
        sev('orange', 'other', `${{staleEpics}} stale epics (>6 months old, <20% complete)`,
          'Long-running epics with little progress suggest abandoned or poorly managed initiatives.');

      // Phase 6d2: Release-related flags
      const releasesList = D.releases || [];
      const totalReleasedVersions = D.total_released_versions || 0;
      const totalVersions = releasesList.length;
      const unreleased = totalVersions - totalReleasedVersions;
      const releasedWithDate = releasesList.filter(r => r.released && r.release_date);
      let latestReleaseDate = null;
      if (releasedWithDate.length > 0) {{
        const dates = releasedWithDate.map(r => r.release_date).filter(Boolean);
        if (dates.length) latestReleaseDate = dates.sort().pop();
      }}
      if (latestReleaseDate) {{
        const relDate = new Date(latestReleaseDate);
        const now = new Date();
        const daysSince = Math.floor((now - relDate) / (24 * 60 * 60 * 1000));
        if (daysSince > 90)
          sev('orange', 'release', 'No release in the last 90 days',
            'Consider shipping a version or archiving unreleased versions.');
      }}
      if (unreleased > 10)
        sev('yellow', 'release', `Many unreleased versions (${{unreleased}})`,
          'Review and either release or archive.');
      const rpm = D.releases_per_month || {{}};
      const monthKeys = Object.keys(rpm).sort();
      if (monthKeys.length >= 6) {{
        const last3 = monthKeys.slice(-3).reduce((s, k) => s + (rpm[k] || 0), 0);
        const prev3 = monthKeys.slice(-6, -3).reduce((s, k) => s + (rpm[k] || 0), 0);
        if (prev3 > 0 && last3 < prev3 * 0.5)
          sev('yellow', 'release', 'Release cadence has slowed (last 3 months vs previous 3)',
            'Consider keeping a steady release cadence or communicating a change in strategy.');
      }}

      // Phase 6e: SP vs worklog correlation
      if (wla.sp_worklog_correlation != null && wla.sp_worklog_correlation < 0.3 && wla.sp_worklog_pairs_count >= 10)
        sev('yellow', 'sprint', `Story points vs worklog correlation is only ${{wla.sp_worklog_correlation}} (weak)`,
          'Story point estimates do not correlate with actual effort. Points may be arbitrary.');

      // Git / CI-CD / Octopus audit flags
      if (GIT_DATA && Object.keys(GIT_DATA).length) {{
        const bf = (GIT_DATA.contributors||{{}}).min_bus_factor;
        if (bf != null && bf <= 1)
          sev('red', 'git_cicd', 'Bus factor = 1 in at least one repo',
            'A single contributor covers 80%+ of commits. Key-person risk is high.');
        const drift = (GIT_DATA.branch_drift||{{}}).total_missing_across_repos || 0;
        if (drift > 50)
          sev('red', 'git_cicd', `Branch drift: ${{drift}} commits behind across repos`,
            'Large branch drift indicates significant release lag or incomplete merge processes.');
        else if (drift > 10)
          sev('orange', 'git_cicd', `Branch drift: ${{drift}} commits behind across repos`,
            'Moderate branch drift — consider reconciling branches.');
        const weekend = (GIT_DATA.work_patterns||{{}}).weekend_commit_pct || 0;
        if (weekend > 15)
          sev('orange', 'git_cicd', `Weekend commits: ${{weekend.toFixed(0)}}%`,
            'Potential burnout signal. Review workload distribution.');
        const noReview = (GIT_DATA.review_turnaround||{{}}).pct_no_review || 0;
        if (noReview > 40)
          sev('orange', 'git_cicd', `${{noReview.toFixed(0)}}% of PRs merged without review`,
            'High rate of unreviewed PRs increases quality risk.');
      }}
      if (OCTOPUS_DATA && Object.keys(OCTOPUS_DATA).length) {{
        const pending = OCTOPUS_DATA.pending_changes || {{}};
        const reposBehind = pending.total_pending_repos || 0;
        const commitsBehind = pending.total_pending_commits || 0;
        if (reposBehind > 5)
          sev('red', 'git_cicd', `${{reposBehind}} repos behind on deployment (${{commitsBehind}} pending commits)`,
            'Many repos have unreleased changes. Deployment lag increases risk.');
        else if (reposBehind > 2)
          sev('orange', 'git_cicd', `${{reposBehind}} repos behind on deployment (${{commitsBehind}} pending commits)`,
            'Some repos have pending changes waiting to be deployed.');
      }}
      if (CICD_DATA && Object.keys(CICD_DATA).length) {{
        const cfr = (CICD_DATA.change_failure_rate||{{}}).cfr_pct || 0;
        if (cfr > 15)
          sev('red', 'git_cicd', `Change failure rate: ${{cfr}}%`,
            'More than 15% of deployments fail. Investigate CI pipeline and test coverage.');
        else if (cfr > 10)
          sev('orange', 'git_cicd', `Change failure rate: ${{cfr}}%`,
            'Moderate failure rate. Review test automation and deployment process.');
        const buildRate = (CICD_DATA.builds||{{}}).success_rate;
        if (buildRate != null && buildRate < 80)
          sev('orange', 'git_cicd', `Build success rate: ${{buildRate}}%`,
            'Low build success rate slows delivery. Investigate flaky tests and build issues.');
      }}

      const order = {{ red: 0, orange: 1, yellow: 2 }};
      flags.sort((a, b) => (order[a.severity] ?? 9) - (order[b.severity] ?? 9));
      window._auditFlagsAll = flags;

      const container = document.getElementById('auditFlags');
      if (!container) return;
      if (flags.length === 0) {{
        container.innerHTML = '<div class="audit-flag" style="border-left-color:var(--green)"><div class="flag-title" style="color:var(--green)">No significant issues detected</div></div>';
        window._auditFlags = [];
        renderAuditCategoryOptions();
        renderAuditDataHealth();
        return;
      }}
      renderAuditCategoryOptions();
      renderAuditDataHealth();
      renderAuditFlagsDOM();
    }}

    // ---------- Gaming Score (Phase 4a) ----------
    function computeGamingScore() {{
      const D = getEffectiveData();
      const bp = D.by_project || {{}};
      const projects = D.projects || [];
      const container = document.getElementById('gamingScoreContainer');
      if (!container) return;

      function projectScoreParts(pk) {{
        const pm = bp[pk] || {{}};
        const parts = [];
        const ltd = pm.lead_time_distribution || {{}};
        const ltTotal = ltd.total || 0;
        const instPct = ltTotal >= 5 ? (ltd.under_1h||0) / ltTotal * 100 : 0;
        parts.push({{ key: 'instant', label: 'Instant lead time', pts: Math.min(instPct / 50 * 20, 20) }});
        const spa = pm.status_path_analysis || {{}};
        parts.push({{ key: 'skip', label: 'Status skip', pts: Math.min((spa.skip_pct||0) / 50 * 20, 20) }});
        const sprints = (D.sprint_metrics||[]).filter(s => s.project === pk);
        let sprintPts = 0;
        if (sprints.length > 0) {{
          const perfectPct = sprints.filter(s => s.total_issues > 0 && s.throughput_issues === s.total_issues).length / sprints.length * 100;
          sprintPts = Math.min(perfectPct / 100 * 15, 15);
        }}
        parts.push({{ key: 'sprint', label: 'Perfect sprints', pts: sprintPts }});
        const bulk = pm.bulk_closure_days || [];
        parts.push({{ key: 'bulk', label: 'Bulk closure days', pts: Math.min(bulk.length * 2.5, 10) }});
        const ca = pm.closer_analysis || {{}};
        parts.push({{ key: 'closer', label: 'Closer mismatch', pts: Math.min((ca.closer_not_assignee_pct||0) / 80 * 10, 10) }});
        parts.push({{ key: 'empty', label: 'Empty descriptions', pts: Math.min((pm.empty_description_done_pct||0) / 60 * 10, 10) }});
        parts.push({{ key: 'nocomm', label: 'Zero comments', pts: Math.min((pm.zero_comment_done_pct||0) / 80 * 5, 5) }});
        const openCount = (pm.open_count != null ? pm.open_count : pm.wip_count) || 1;
        const unaPct = ((pm.unassigned_open_count != null ? pm.unassigned_open_count : pm.unassigned_wip_count)||0) / openCount * 100;
        parts.push({{ key: 'unass', label: 'Unassigned WIP', pts: Math.min(unaPct / 60 * 5, 5) }});
        const blkPct = (pm.blocked_count||0) / openCount * 100;
        let blkPts = 0;
        if (openCount > 20 && blkPct < 2) blkPts = 5;
        else if (openCount > 20 && blkPct < 5) blkPts = 2;
        parts.push({{ key: 'blocked', label: 'Low blocked rate', pts: blkPts }});
        const acnr = pm.assignee_change_near_resolution || {{}};
        parts.push({{ key: 'acnr', label: 'Assignee change near done', pts: Math.min((acnr.changed_pct||0) / 30 * 5, 5) }});
        const ctm = pm.comment_timing || {{}};
        parts.push({{ key: 'postc', label: 'Post-resolution comments', pts: Math.min((ctm.post_resolution_comment_pct||0) / 50 * 5, 5) }});
        const wla = pm.worklog_analysis || {{}};
        parts.push({{ key: 'postw', label: 'Post-resolution worklogs', pts: Math.min((wla.post_resolution_worklog_pct||0) / 40 * 5, 5) }});
        const raw = parts.reduce((a, p) => a + p.pts, 0);
        return {{ parts, total: Math.round(Math.min(raw, 100)) }};
      }}
      function projectScore(pk) {{
        return projectScoreParts(pk).total;
      }}

      const globalScore = projects.length
        ? Math.round(projects.reduce((a, pk) => a + projectScore(pk), 0) / projects.length)
        : 0;
      const color = globalScore >= 60 ? 'var(--red)' : globalScore >= 40 ? 'var(--orange)' : globalScore >= 20 ? '#e3b341' : 'var(--green)';
      const label = globalScore >= 60 ? 'Systemic Gaming' : globalScore >= 40 ? 'Significant Manipulation Signals' : globalScore >= 20 ? 'Concerning' : 'Healthy';

      let perProj = projects.map(pk => {{
        const s = projectScore(pk);
        const c = s >= 60 ? 'var(--red)' : s >= 40 ? 'var(--orange)' : s >= 20 ? '#e3b341' : 'var(--green)';
        return `<span style="color:${{c}};font-weight:700">${{pk}}: ${{s}}</span>`;
      }}).join(' &nbsp; ');

      container.innerHTML = `<div><div class="gaming-gauge" style="color:${{color}}">${{globalScore}}</div><div class="gaming-label">Gaming Score (0\u2013100)</div></div><div><div class="gaming-detail" style="color:${{color}};font-weight:700;font-size:1.1rem">${{label}}</div><div class="gaming-detail" style="margin-top:0.5rem">Per project: ${{perProj}}</div></div>`;
      window._gamingScore = globalScore;
      window._projectScores = Object.fromEntries(projects.map(pk => [pk, projectScore(pk)]));
      const agg = {{}};
      projects.forEach(pk => {{
        projectScoreParts(pk).parts.forEach(p => {{
          if (!agg[p.key]) agg[p.key] = {{ label: p.label, pts: 0 }};
          agg[p.key].pts += p.pts;
        }});
      }});
      const nProj = Math.max(projects.length, 1);
      window._gamingScoreDrivers = Object.values(agg)
        .map(x => ({{ label: x.label, avg: x.pts / nProj }}))
        .sort((a, b) => b.avg - a.avg)
        .filter(x => x.avg >= 0.5)
        .slice(0, 3)
        .map(x => `${{x.label}} (~${{x.avg.toFixed(1)}} pts)`);
      renderAuditGamingStrip();
    }}
    computeGamingScore();
    computeAuditFlags();

    // ---------- Filters & Interactivity ----------
    function getSelectedProjects() {{
      const allCb = document.getElementById('projectAll');
      if (allCb && allCb.checked) return null;
      const checked = Array.from(document.querySelectorAll('.project-cb:checked')).map(cb => cb.value);
      return checked.length ? checked : null;
    }}

    function getSelectedComponents() {{
      const allCb = document.getElementById('componentAll');
      if (allCb && allCb.checked) return null;
      const checked = Array.from(document.querySelectorAll('.component-cb:checked')).map(cb => cb.value);
      return checked.length ? checked : null;
    }}
    function getSelectedTeams() {{
      const allCb = document.getElementById('teamAll');
      if (!allCb || allCb.checked) return null;
      const checked = Array.from(document.querySelectorAll('.team-cb:checked')).map(cb => cb.value);
      return checked.length ? checked : null;
    }}

    function _mergeSource(metricsList, scopeMeta) {{
      if (!metricsList || !metricsList.length) return null;
      const statusMerge = {{}}, compMerge = {{}}, statusByCompMerge = {{}};
      let wip = 0, blocked = 0, openBugs = 0, unassigned = 0;
      let openBacklog = 0, openInProgress = 0, openInReview = 0, openBlocked = 0, wipInFlightSum = 0;
      const throughputMerge = {{}};
      let wipAgingWeight = 0, wipAgingSum = 0;
      let leadCount = 0, leadSum = 0, cycleCount = 0, cycleSum = 0;
      const resMerge = {{}}, wipItMerge = {{}}, doneItMerge = {{}}, wipPriMerge = {{}};
      const dowMerge = {{}}, assigneeMerge = {{}}, bulkMap = {{}}, tisMerge = {{}};
      let cnaCount = 0, cnaWithCloser = 0, cnaTotal = 0;
      const closersMerge = {{}};
      let spaSkip = 0, spaTotal = 0;
      const spaPathsMerge = {{}};
      let reopenC = 0, reopenT = 0;
      const ltdMerge = {{ under_1h:0, '1h_to_1d':0, '1d_to_7d':0, '7d_to_30d':0, over_30d:0, total:0 }};
      let edpW = 0, zcpW = 0, orpW = 0, doneTotal = 0, edpWip = 0, wipTotal = 0;
      const wipAssMerge = {{}};
      let acnrChanged = 0, acnrTotal = 0;
      let ctmPost = 0, ctmTotal = 0;
      let wlaZero = 0, wlaPostRes = 0, wlaDone = 0, wlaBulk = 0, wlaHours = 0;
      const wlaByDow = {{}};
      const createdMerge = {{}};
      const bugCreatedMerge = {{}};
      const bugResolvedMerge = {{}};
      let bftCount = 0, bftSum = 0;
      const bugPriMerge = {{}};
      const spTrendMonthMerge = {{}};
      const rpmMerge = {{}};
      const wipTeamsMerge = {{}};
      for (const m of metricsList) {{
        if (!m) continue;
        const mOpen = m.open_count != null ? m.open_count : (m.wip_count || 0);
        wip += mOpen;
        wipTotal += m.wip_count || mOpen || 0;
        blocked += m.blocked_count || 0;
        openBugs += m.open_bugs_count || 0;
        const mUna = m.unassigned_open_count != null ? m.unassigned_open_count : (m.unassigned_wip_count || 0);
        unassigned += mUna;
        const obp = m.open_by_phase || {{}};
        const wbp = m.wip_by_phase || {{}};
        const mBacklog = obp.backlog != null ? obp.backlog : (wbp.not_started || 0);
        const mInProg = (obp.in_progress != null ? obp.in_progress : wbp.in_progress) || 0;
        const mInRev = obp.in_review != null ? obp.in_review : (wbp.review_qa || 0);
        const mBlocked = (obp.blocked != null ? obp.blocked : wbp.blocked) || 0;
        openBacklog += mBacklog;
        openInProgress += mInProg;
        openInReview += mInRev;
        openBlocked += mBlocked;
        wipInFlightSum += m.wip_in_flight != null ? m.wip_in_flight : (mInProg + mInRev + mBlocked);
        for (const [st, cnt] of Object.entries(m.status_distribution || {{}}))
          statusMerge[st] = (statusMerge[st] || 0) + cnt;
        for (const [c, cnt] of Object.entries(m.wip_components || {{}}))
          compMerge[c] = (compMerge[c] || 0) + cnt;
        for (const [comp, statuses] of Object.entries(m.wip_status_by_component || {{}})) {{
          if (!statusByCompMerge[comp]) statusByCompMerge[comp] = {{}};
          for (const [st, cnt] of Object.entries(statuses))
            statusByCompMerge[comp][st] = (statusByCompMerge[comp][st] || 0) + cnt;
        }}
        for (const [wk, cnt] of Object.entries(m.throughput_by_week || {{}}))
          throughputMerge[wk] = (throughputMerge[wk] || 0) + cnt;
        if (m.wip_aging_days && m.wip_aging_days.avg_days != null) {{
          const agingCount = m.wip_aging_days.count || 0;
          wipAgingWeight += agingCount;
          wipAgingSum += (m.wip_aging_days.avg_days || 0) * agingCount;
        }}
        if (m.lead_time_days) {{ leadCount += m.lead_time_days.count||0; leadSum += (m.lead_time_days.avg_days||0) * (m.lead_time_days.count||0); }}
        if (m.cycle_time_days) {{ cycleCount += m.cycle_time_days.count||0; cycleSum += (m.cycle_time_days.avg_days||0) * (m.cycle_time_days.count||0); }}
        for (const [k,v] of Object.entries(m.resolution_breakdown || {{}})) resMerge[k] = (resMerge[k]||0) + v;
        for (const [k,v] of Object.entries(m.wip_issuetype || {{}})) wipItMerge[k] = (wipItMerge[k]||0) + v;
        for (const [k,v] of Object.entries(m.done_issuetype || {{}})) doneItMerge[k] = (doneItMerge[k]||0) + v;
        for (const [k,v] of Object.entries(m.wip_priority || {{}})) wipPriMerge[k] = (wipPriMerge[k]||0) + v;
        for (const [k,v] of Object.entries(m.resolution_by_weekday || {{}})) dowMerge[k] = (dowMerge[k]||0) + v;
        for (const [k,v] of Object.entries(m.done_assignees || {{}})) assigneeMerge[k] = (assigneeMerge[k]||0) + v;
        for (const dd of (m.bulk_closure_days || [])) bulkMap[dd.date] = (bulkMap[dd.date]||0) + dd.count;
        for (const [st, dd] of Object.entries(m.time_in_status || {{}})) {{
          if (!tisMerge[st]) tisMerge[st] = {{totalH:0, cnt:0}};
          tisMerge[st].totalH += (dd.avg_hours||0) * (dd.count||0);
          tisMerge[st].cnt += dd.count||0;
        }}
        const mca = m.closer_analysis || {{}};
        cnaTotal += mca.total_analyzed || 0;
        cnaWithCloser += mca.with_closer || 0;
        cnaCount += mca.closer_not_assignee_count || 0;
        for (const cc of (mca.top_closers || [])) closersMerge[cc.name] = (closersMerge[cc.name]||0) + cc.count;
        const mspa = m.status_path_analysis || {{}};
        spaSkip += mspa.skip_count || 0; spaTotal += mspa.total || 0;
        for (const pp of (mspa.top_paths || [])) spaPathsMerge[pp.path] = (spaPathsMerge[pp.path]||0) + pp.count;
        const mra = m.reopen_analysis || {{}};
        reopenC += mra.reopened_count || 0; reopenT += mra.total || 0;
        const mltd = m.lead_time_distribution || {{}};
        ltdMerge.under_1h += mltd.under_1h||0; ltdMerge['1h_to_1d'] += mltd['1h_to_1d']||0;
        ltdMerge['1d_to_7d'] += mltd['1d_to_7d']||0; ltdMerge['7d_to_30d'] += mltd['7d_to_30d']||0;
        ltdMerge.over_30d += mltd.over_30d||0; ltdMerge.total += mltd.total||0;
        const dc = Object.values(m.resolution_breakdown || {{}}).reduce((a,v)=>a+v, 0);
        doneTotal += dc;
        edpWip += (m.empty_description_wip_pct||0) * (m.wip_count || 0);
        edpW += (m.empty_description_done_pct||0) * dc;
        zcpW += (m.zero_comment_done_pct||0) * dc;
        orpW += (m.orphan_done_pct||0) * dc;
        for (const [k,v] of Object.entries(m.wip_assignees || {{}})) wipAssMerge[k] = (wipAssMerge[k]||0) + v;
        for (const [k,v] of Object.entries(m.wip_teams || {{}})) wipTeamsMerge[k] = (wipTeamsMerge[k]||0) + v;
        const macnr = m.assignee_change_near_resolution || {{}};
        acnrChanged += macnr.changed_count || 0; acnrTotal += macnr.total || 0;
        const mctm = m.comment_timing || {{}};
        ctmPost += mctm.with_post_resolution_comments || 0; ctmTotal += mctm.total_issues || 0;
        const mwla = m.worklog_analysis || {{}};
        wlaZero += mwla.zero_worklog_count || 0; wlaPostRes += mwla.post_resolution_worklog_count || 0;
        wlaDone += mwla.total_done || 0; wlaBulk += mwla.bulk_entries_count || 0; wlaHours += mwla.total_hours || 0;
        for (const [d,h] of Object.entries(mwla.by_dow || {{}})) wlaByDow[d] = (wlaByDow[d]||0) + h;
        for (const [w,c] of Object.entries(m.created_by_week || {{}})) createdMerge[w] = (createdMerge[w]||0) + c;
        for (const [w,c] of Object.entries(m.bug_creation_by_week || {{}})) bugCreatedMerge[w] = (bugCreatedMerge[w]||0) + c;
        for (const [w,c] of Object.entries(m.bug_resolved_by_week || {{}})) bugResolvedMerge[w] = (bugResolvedMerge[w]||0) + c;
        if (m.bug_fix_time_days) {{ bftCount += m.bug_fix_time_days.count||0; bftSum += (m.bug_fix_time_days.avg_days||0) * (m.bug_fix_time_days.count||0); }}
        for (const [k,v] of Object.entries(m.open_bugs_by_priority || {{}})) bugPriMerge[k] = (bugPriMerge[k]||0) + v;
        for (const [mon,c] of Object.entries(m.releases_per_month || {{}})) rpmMerge[mon] = (rpmMerge[mon]||0) + c;
        const mSpt = m.sp_trend || {{}};
        for (const [mon, mData] of Object.entries(mSpt.by_month || {{}})) {{
          if (!spTrendMonthMerge[mon]) spTrendMonthMerge[mon] = {{ total_sp: 0, total_issues: 0 }};
          spTrendMonthMerge[mon].total_sp += (mData.avg_sp||0) * (mData.count||0);
          spTrendMonthMerge[mon].total_issues += mData.count||0;
        }}
      }}
      const weeks = Object.keys(throughputMerge).sort();
      const last4 = weeks.slice(-4).reduce((a, wk) => a + (throughputMerge[wk] || 0), 0);
      const compTop = Object.entries(compMerge).sort((a, b) => b[1] - a[1]).slice(0, 15);
      const assTop = Object.entries(assigneeMerge).sort((a,b) => b[1]-a[1]).slice(0, 20);
      const assCounts = Object.entries(assigneeMerge).filter(([k])=>k!=='(unassigned)').map(([,v])=>v);
      const tisF = {{}};
      for (const [st, dd] of Object.entries(tisMerge)) if (dd.cnt > 0) tisF[st] = {{ median_hours: null, avg_hours: Math.round(dd.totalH/dd.cnt*100)/100, count: dd.cnt }};
      const clsSorted = Object.entries(closersMerge).sort((a,b)=>b[1]-a[1]).slice(0,10);
      const spaPSorted = Object.entries(spaPathsMerge).sort((a,b)=>b[1]-a[1]).slice(0,15);
      const bulkF = Object.entries(bulkMap).filter(([,c])=>c>10).sort(([a],[b])=>a.localeCompare(b)).map(([date,count])=>({{date,count}}));
      return normalizeMetrics({{
        open_count: wip, open_by_phase: {{ backlog: openBacklog, in_progress: openInProgress, in_review: openInReview, blocked: openBlocked }},
        wip_in_flight: wipInFlightSum, unassigned_open_count: unassigned,
        wip_count: wip, blocked_count: blocked, open_bugs_count: openBugs, unassigned_wip_count: unassigned,
        status_distribution: statusMerge, wip_status_by_component: statusByCompMerge,
        wip_components: Object.fromEntries(compTop),
        throughput_by_week: throughputMerge, last_4_weeks: last4,
        wip_aging_days: wipAgingWeight ? {{ count: wipAgingWeight, avg_days: wipAgingSum / wipAgingWeight, p50_days: null, p85_days: null, p95_days: null }} : null,
        lead_time_days: leadCount ? {{ count: leadCount, avg_days: leadSum / leadCount, p50_days: null, p85_days: null, p95_days: null }} : null,
        cycle_time_days: cycleCount ? {{ count: cycleCount, avg_days: cycleSum / cycleCount, p50_days: null, p85_days: null, p95_days: null }} : null,
        lead_time_distribution: ltdMerge,
        resolution_breakdown: resMerge, wip_issuetype: wipItMerge, done_issuetype: doneItMerge,
        wip_priority: wipPriMerge, resolution_by_weekday: dowMerge,
        done_assignees: Object.fromEntries(assTop),
        workload_gini: giniCoefficient(assCounts),
        bulk_closure_days: bulkF, time_in_status: tisF,
        flow_efficiency: computeFlowEff(tisF),
        closer_analysis: {{
          total_analyzed: cnaTotal, with_closer: cnaWithCloser,
          top_closers: clsSorted.map(([name,count])=>({{name,count}})),
          closer_not_assignee_count: cnaCount,
          closer_not_assignee_pct: cnaWithCloser ? Math.round(cnaCount/cnaWithCloser*1000)/10 : 0,
        }},
        status_path_analysis: {{
          total: spaTotal, skip_count: spaSkip,
          skip_pct: spaTotal ? Math.round(spaSkip/spaTotal*1000)/10 : 0,
          top_paths: spaPSorted.map(([path,count])=>({{path,count}})),
        }},
        reopen_analysis: {{ total: reopenT, reopened_count: reopenC, reopened_pct: reopenT ? Math.round(reopenC/reopenT*1000)/10 : 0 }},
        empty_description_wip_pct: wipTotal ? Math.round(edpWip/wipTotal*10)/10 : 0,
        empty_description_done_pct: doneTotal ? Math.round(edpW/doneTotal*10)/10 : 0,
        zero_comment_done_pct: doneTotal ? Math.round(zcpW/doneTotal*10)/10 : 0,
        orphan_done_pct: doneTotal ? Math.round(orpW/doneTotal*10)/10 : 0,
        avg_wip_per_assignee: (() => {{
          const ppl = Object.entries(wipAssMerge).filter(([k]) => k !== '(unassigned)');
          return ppl.length > 0 ? Math.round(ppl.reduce((a,[,v])=>a+v,0)/ppl.length*10)/10 : 0;
        }})(),
        wip_assignees: wipAssMerge,
        wip_teams: wipTeamsMerge,
        assignee_change_near_resolution: {{ total: acnrTotal, changed_count: acnrChanged, changed_pct: acnrTotal ? Math.round(acnrChanged/acnrTotal*1000)/10 : 0 }},
        comment_timing: {{ total_issues: ctmTotal, with_post_resolution_comments: ctmPost, post_resolution_comment_pct: ctmTotal ? Math.round(ctmPost/ctmTotal*1000)/10 : 0 }},
        worklog_analysis: {{
          total_done: wlaDone, zero_worklog_count: wlaZero, zero_worklog_pct: wlaDone ? Math.round(wlaZero/wlaDone*1000)/10 : 0,
          post_resolution_worklog_count: wlaPostRes, post_resolution_worklog_pct: wlaDone ? Math.round(wlaPostRes/wlaDone*1000)/10 : 0,
          bulk_entries_count: wlaBulk, total_hours: Math.round(wlaHours*10)/10,
          by_dow: wlaByDow, weekend_pct: wlaHours > 0 ? Math.round(((wlaByDow.Sat||0)+(wlaByDow.Sun||0))/wlaHours*1000)/10 : 0,
          sp_worklog_correlation: null,
        }},
        created_by_week: createdMerge,
        bug_creation_by_week: bugCreatedMerge,
        bug_resolved_by_week: bugResolvedMerge,
        bug_fix_time_days: bftCount ? {{ count: bftCount, avg_days: bftSum / bftCount, p50_days: null, p85_days: null, p95_days: null }} : null,
        open_bugs_by_priority: bugPriMerge,
        releases_per_month: rpmMerge,
        sp_trend: (() => {{
          const byM = {{}};
          const sorted = Object.keys(spTrendMonthMerge).sort();
          for (const mon of sorted) {{
            const d = spTrendMonthMerge[mon];
            const avg = d.total_issues > 0 ? Math.round(d.total_sp / d.total_issues * 100) / 100 : 0;
            byM[mon] = {{ avg_sp: avg, count: d.total_issues }};
          }}
          let infl = false;
          if (sorted.length >= 4) {{
            const mid = Math.floor(sorted.length / 2);
            const firstMonths = sorted.slice(0, mid);
            const secondMonths = sorted.slice(mid);
            let firstSum = 0, firstCnt = 0, secondSum = 0, secondCnt = 0;
            for (const mon of firstMonths) {{ const d = spTrendMonthMerge[mon]; firstSum += d.total_sp; firstCnt += d.total_issues; }}
            for (const mon of secondMonths) {{ const d = spTrendMonthMerge[mon]; secondSum += d.total_sp; secondCnt += d.total_issues; }}
            const avgFirst = firstCnt > 0 ? firstSum / firstCnt : 0;
            const avgSecond = secondCnt > 0 ? secondSum / secondCnt : 0;
            if (avgFirst > 0 && (avgSecond - avgFirst) / avgFirst > 0.3) infl = true;
          }}
          return {{ by_month: byM, inflation_detected: infl }};
        }})(),
      }}, scopeMeta);
    }}

    // --- Reusable DORA renderer (called on filter change + initial load) ---
    const _doraCatColor = c => ({{ elite:'#27ae60', high:'#2ecc71', medium:'#f1c40f', low:'#e74c3c' }})[c] || '#888';
    function _doraCategorize(metricType, value) {{
      if (value == null) return null;
      const thresholds = {{
        deployment_frequency: [['elite',5],['high',1],['medium',0.25]],
        lead_time: [['elite',1],['high',7],['medium',30]],
        change_failure_rate: [['elite',5],['high',10],['medium',15]],
        mttr: [['elite',1],['high',24],['medium',168]],
      }};
      const t = thresholds[metricType];
      if (!t) return null;
      if (metricType === 'deployment_frequency') {{
        for (const [cat, min] of t) if (value >= min) return cat;
        return 'low';
      }}
      for (const [cat, max] of t) if (value <= max) return cat;
      return 'low';
    }}
    function updateDORA(scopedJiraData) {{
      const dc = document.getElementById('doraCards');
      const bench = document.getElementById('doraBenchmark');
      if (!dc && !bench) return;
      const base = (DORA_DATA && Object.keys(DORA_DATA).length) ? DORA_DATA : {{}};
      const mkCard = (label, value, color) => `<div class="card"><div class="value" style="color:${{color||'var(--accent)'}}">${{value ?? 'N/A'}}</div><div class="label">${{label}}</div></div>`;

      let df = base.deployment_frequency || {{}};
      let cfr = base.change_failure_rate || {{}};
      let mttr = base.mttr || {{}};

      let lt = base.lead_time_for_changes || {{}};
      if (scopedJiraData) {{
        const slt = scopedJiraData.lead_time_days || {{}};
        if (slt.p50_days != null) {{
          const cat = _doraCategorize('lead_time', slt.p50_days);
          lt = {{ value_days: slt.p50_days, category: cat, source: 'jira_scoped' }};
        }}
      }}

      const categories = [df, lt, cfr, mttr].map(m => m.category).filter(Boolean);
      const rankMap = {{ elite:4, high:3, medium:2, low:1 }};
      let overall = 'N/A';
      if (categories.length) {{
        const avg = categories.reduce((s,c) => s + (rankMap[c]||1), 0) / categories.length;
        if (avg >= 3.5) overall = 'elite';
        else if (avg >= 2.5) overall = 'high';
        else if (avg >= 1.5) overall = 'medium';
        else overall = 'low';
      }}

      if (dc) {{
        dc.innerHTML =
          mkCard('Overall', overall !== 'N/A' ? overall.charAt(0).toUpperCase()+overall.slice(1) : 'N/A', _doraCatColor(overall)) +
          mkCard('Deploy Freq', df.value!=null?df.value+'/wk':'N/A', _doraCatColor(df.category)) +
          mkCard('Lead Time', lt.value_days!=null?lt.value_days.toFixed(1)+'d':'N/A', _doraCatColor(lt.category)) +
          mkCard('CFR', cfr.value_pct!=null?cfr.value_pct+'%':'N/A', _doraCatColor(cfr.category)) +
          mkCard('MTTR', mttr.value_hours!=null?mttr.value_hours.toFixed(1)+'h':'N/A', _doraCatColor(mttr.category));
      }}
      if (bench) {{
        let html = '<table><thead><tr><th>Metric</th><th>Elite</th><th>High</th><th>Medium</th><th>Low</th><th>Current</th></tr></thead><tbody>';
        const rows = [
          ['Deploy Freq', 'Multiple/day', 'Daily-Weekly', 'Weekly-Monthly', 'Monthly+', df],
          ['Lead Time', '<1 day', '1d-1wk', '1wk-1mo', '>1 month', lt],
          ['CFR', '<5%', '5-10%', '10-15%', '>15%', cfr],
          ['MTTR', '<1 hour', '<1 day', '<1 week', '>1 week', mttr],
        ];
        for (const [name,e,h,med,l,cur] of rows) {{
          const cat = (cur||{{}}).category || 'N/A';
          html += `<tr><td>${{name}}</td><td>${{e}}</td><td>${{h}}</td><td>${{med}}</td><td>${{l}}</td><td style="color:${{_doraCatColor(cat)}};font-weight:bold">${{cat}}</td></tr>`;
        }}
        html += '</tbody></table>';
        bench.innerHTML = html;
      }}
    }}

    function setCardsAndChartsFromMetrics(m, selectedComponents, projList) {{
      const d = m || normalizeMetrics(DATA, {{
        exactness: 'exact',
        nonAdditiveExact: true,
        effectiveProjects: null,
        components: null,
        label: 'Project: All projects | Component: All components | Mode: exact',
      }});
      const scopeMeta = d.scope_meta || {{}};
      let comp = d.wip_components || {{}};
      if (selectedComponents && selectedComponents.length) {{
        comp = Object.fromEntries(selectedComponents.map(c => [c, comp[c] || 0]).filter(([, v]) => v > 0));
      }}
      const compItems = Object.entries(comp).sort((a, b) => b[1] - a[1]).slice(0, 15);
      const wipFromComp = compItems.reduce((a, [, v]) => a + v, 0);
      const openCount = (selectedComponents && selectedComponents.length) ? wipFromComp : (d.open_count != null ? d.open_count : d.wip_count || 0);
      const blocked = d.blocked_count || 0;
      const openBugs = d.open_bugs_count || 0;
      const unassigned = d.unassigned_open_count != null ? d.unassigned_open_count : (d.unassigned_wip_count || 0);
      const last4 = d.last_4_weeks || 0;
      const wipAging = d.wip_aging_days || {{}};
      const median = d.wip_median != null ? d.wip_median : '\u2014';
      const el = (id, v) => {{ const e = document.getElementById(id); if (e) e.textContent = v; }};
      const scopeSummaryEl = document.getElementById('filterScopeSummary');
      if (scopeSummaryEl) scopeSummaryEl.textContent = scopeMeta.label || 'Project: All projects | Component: All components | Mode: exact';

      // Status distribution: filter by component if selected
      let statusDist;
      if (selectedComponents && selectedComponents.length) {{
        const sbc = d.wip_status_by_component || {{}};
        statusDist = {{}};
        for (const cn of selectedComponents) {{
          for (const [st, cnt] of Object.entries(sbc[cn]||{{}}))
            statusDist[st] = (statusDist[st]||0) + cnt;
        }}
        // Fallback: if cross-tab yielded nothing, use the merged status_distribution
        if (!Object.keys(statusDist).length) {{
          statusDist = d.status_distribution || {{}};
        }}
      }} else {{
        statusDist = d.status_distribution || {{}};
      }}

      // Phase: prefer open_by_phase (backlog, in_review), else from status dist (not_started, review_qa)
      const obp = d.open_by_phase || {{}};
      const phase = d.open_by_phase ? obp : phaseFromStatusDist(statusDist);
      const backlog = phase.backlog != null ? phase.backlog : (phase.not_started || 0);
      const inReview = phase.in_review != null ? phase.in_review : (phase.review_qa || 0);
      const _phaseMap = {{ backlog: backlog, in_progress: phase.in_progress||0, in_review: inReview, blocked: phase.blocked||0 }};
      const _wipPhases = (typeof getWipPhases === 'function') ? getWipPhases() : ['in_progress','in_review','blocked'];
      const wipInFlight = _wipPhases.reduce((s, p) => s + (_phaseMap[p]||0), 0);
      el('cardOpen', openCount);
      el('cardWipInFlight', wipInFlight);
      el('cardBacklog', backlog);
      el('cardInProgress', phase.in_progress || 0);
      el('cardInReview', inReview);
      el('cardBlocked', blocked);
      el('cardUnassigned', unassigned);
      el('cardOpenBugs', openBugs);
      el('cardDone4Weeks', last4);
      el('cardOpenMedian', median);
      const leadAvg = (d.lead||{{}}).avg_days;
      const cycleAvg = (d.cycle||{{}}).avg_days;
      el('cardLeadTime', leadAvg != null ? leadAvg.toFixed(1) : '\u2014');
      el('cardCycleTime', cycleAvg != null ? cycleAvg.toFixed(1) : '\u2014');

      // Quality KPI cards
      el('qKpiOpenBugs', d.open_bugs_count || 0);
      const _qRa = d.reopen_analysis || {{}};
      el('qKpiReopenPct', (_qRa.reopened_pct != null ? _qRa.reopened_pct : 0) + '%');
      const _qBft = d.bug_fix_time_days || {{}};
      el('qKpiBugFixTime', _qBft.p50_days != null ? Math.round(_qBft.p50_days * 10) / 10 + 'd' : (_qBft.avg_days != null ? Math.round(_qBft.avg_days * 10) / 10 + 'd (avg)' : 'N/A'));
      const _qFe = d.flow_efficiency || {{}};
      el('qKpiFlowEff', (_qFe.efficiency_pct != null ? _qFe.efficiency_pct : 0) + '%');

      chartStatus.data.labels = Object.keys(statusDist);
      chartStatus.data.datasets[0].data = Object.values(statusDist);
      chartStatus.update();

      chartComponents.data.labels = compItems.map(x => x[0]);
      chartComponents.data.datasets[0].data = compItems.map(x => x[1]);
      chartComponents.update();

      const thru = d.throughput_by_week || {{}};
      const wkSort = Object.keys(thru).sort();
      const thrF = filterWeekKeys(wkSort, wkSort.map(k => thru[k] || 0));
      chartThroughput.data.labels = thrF.keys;
      chartThroughput.data.datasets[0].data = thrF.values;
      chartThroughput.update();

      const leadD = d.lead || {{}};
      const cycleD = d.cycle || {{}};
      const leadStr = leadD.count != null ? `count ${{leadD.count}}, avg ${{leadD.avg_days != null ? leadD.avg_days.toFixed(1) : '\u2014'}}, p50 ${{leadD.p50_days != null ? leadD.p50_days.toFixed(1) : '\u2014'}}` : '\u2014';
      const cycleStr = cycleD.count != null ? `count ${{cycleD.count}}, avg ${{cycleD.avg_days != null ? cycleD.avg_days.toFixed(1) : '\u2014'}}, p85 ${{cycleD.p85_days != null ? cycleD.p85_days.toFixed(1) : '\u2014'}}` : '\u2014';
      const summaryEl = document.getElementById('leadCycleSummary');
      if (summaryEl) summaryEl.innerHTML = `<span>Lead (created\u2192resolved):</span> ${{leadStr}} &nbsp;|&nbsp; <span>Cycle (in progress\u2192resolved):</span> ${{cycleStr}} &nbsp;|&nbsp; <span>Exactness:</span> ${{scopeMeta.nonAdditiveExact ? 'exact' : 'additive only'}}`;

      // Phase chart — respect WIP phase checkboxes
      const _phaseKeys = ['backlog','in_progress','in_review','blocked'];
      const _phaseLabels = ['Backlog','In progress','In review','Blocked'];
      const _phaseColors = ['rgba(139,148,158,0.6)','rgba(88,166,255,0.6)','rgba(210,153,34,0.6)','rgba(248,81,73,0.6)'];
      const _phaseBorders = ['#8b949e','#58a6ff','#d29922','#f85149'];
      const _activeIdx = _phaseKeys.map((k,i) => _wipPhases.includes(k) ? i : -1).filter(i => i >= 0);
      chartPhase.data.labels = _activeIdx.map(i => _phaseLabels[i]);
      chartPhase.data.datasets[0].data = _activeIdx.map(i => _phaseMap[_phaseKeys[i]]||0);
      chartPhase.data.datasets[0].backgroundColor = _activeIdx.map(i => _phaseColors[i]);
      chartPhase.data.datasets[0].borderColor = _activeIdx.map(i => _phaseBorders[i]);
      chartPhase.update();

      // Lead time distribution chart
      const ltd = d.lead_time_distribution || {{}};
      chartLtDist.data.datasets[0].data = [ltd.under_1h||0, ltd['1h_to_1d']||0, ltd['1d_to_7d']||0, ltd['7d_to_30d']||0, ltd.over_30d||0];
      chartLtDist.update();

      // Resolution types
      const rd = d.resolution_breakdown || {{}};
      chartResolution.data.labels = Object.keys(rd);
      chartResolution.data.datasets[0].data = Object.values(rd);
      chartResolution.update();

      // Issue types (stacked bar)
      const wipItD = d.wip_issuetype || {{}};
      const doneItD = d.done_issuetype || {{}};
      const allTypesD = [...new Set([...Object.keys(wipItD), ...Object.keys(doneItD)])];
      chartIssueTypes.data.labels = ['Open','Done (180d)'];
      chartIssueTypes.data.datasets = allTypesD.map((t,i) => ({{ label: t, data: [wipItD[t]||0, doneItD[t]||0], backgroundColor: itColors[i % itColors.length] }}));
      chartIssueTypes.update();

      // Priority
      const priD = d.wip_priority || {{}};
      const priL = Object.keys(priD);
      chartPriority.data.labels = priL;
      chartPriority.data.datasets[0].data = priL.map(l => priD[l]||0);
      chartPriority.data.datasets[0].backgroundColor = priL.map(l => priColors[l] || 'rgba(139,148,158,0.6)');
      chartPriority.update();

      // Day of week
      const dowD = d.resolution_by_weekday || {{}};
      chartDow.data.datasets[0].data = dowLabels.map(dd => dowD[dd]||0);
      chartDow.update();

      // Assignees + gini
      const assD = d.done_assignees || {{}};
      const assItems = Object.entries(assD).sort((a,b)=>b[1]-a[1]).slice(0,15);
      chartAssignees.data.labels = assItems.map(a => a[0]);
      chartAssignees.data.datasets[0].data = assItems.map(a => a[1]);
      chartAssignees.update();
      el('giniValue', d.workload_gini || 0);

      // Bulk closure
      const bulkD = (d.bulk_closure_days || []).filter(dd => isDateInRange(dd.date || ''));
      chartBulkClosure.data.labels = bulkD.map(dd => dd.date);
      chartBulkClosure.data.datasets[0].data = bulkD.map(dd => dd.count);
      chartBulkClosure.update();

      // Time in status
      const tisD = d.time_in_status || {{}};
      const tisSrt = Object.entries(tisD).sort((a,b) => ((b[1].median_hours ?? b[1].avg_hours ?? 0))-((a[1].median_hours ?? a[1].avg_hours ?? 0))).slice(0,12);
      chartTimeInStatus.data.labels = tisSrt.map(x => x[0]);
      chartTimeInStatus.data.datasets[0].data = tisSrt.map(x => x[1].median_hours != null ? x[1].median_hours : (x[1].avg_hours||0));
      chartTimeInStatus.data.datasets[0].backgroundColor = tisSrt.map(x => {{
        const l = x[0].toLowerCase();
        if (/progress|dev|doing/.test(l)) return 'rgba(88,166,255,0.6)';
        if (/review|qa|test/.test(l)) return 'rgba(210,153,34,0.6)';
        if (/block|hold/.test(l)) return 'rgba(248,81,73,0.6)';
        return 'rgba(139,148,158,0.5)';
      }});
      chartTimeInStatus.update();

      // Closers
      const caD = d.closer_analysis || {{}};
      const clsD = caD.top_closers || [];
      chartClosers.data.labels = clsD.map(c => c.name);
      chartClosers.data.datasets[0].data = clsD.map(c => c.count);
      chartClosers.update();
      const closerDescEl = document.getElementById('closerDesc');
      if (closerDescEl) closerDescEl.innerHTML = `Closer != assignee in <strong>${{caD.closer_not_assignee_pct||0}}%</strong> of cases.`;

      // Flow efficiency card
      const feD = d.flow_efficiency || {{}};
      el('cardFlowEff', (feD.efficiency_pct||0) + '%');
      el('cardEmptyBadWip', d.empty_or_bad_count_wip ?? 0);
      el('cardEmptyBadDone', d.empty_or_bad_count_done ?? 0);

      // Created vs Resolved chart
      const _hasTimeFilter = !!(window._timeRange.from || window._timeRange.to);
      const cbwD = d.created_by_week || {{}};
      const tbwD = d.throughput_by_week || {{}};
      const crWeeksAll = [...new Set([...Object.keys(cbwD), ...Object.keys(tbwD)])].sort();
      const crF = filterWeekKeys(crWeeksAll, crWeeksAll.map(() => 0));
      const crWeeks = _hasTimeFilter ? crF.keys : crF.keys.slice(-16);
      chartCreatedResolved.data.labels = crWeeks;
      chartCreatedResolved.data.datasets[0].data = crWeeks.map(w => cbwD[w]||0);
      chartCreatedResolved.data.datasets[1].data = crWeeks.map(w => tbwD[w]||0);
      chartCreatedResolved.update();

      // WIP assignees chart
      const waD = d.wip_assignees || {{}};
      const waItems = Object.entries(waD).sort((a,b)=>b[1]-a[1]).slice(0,20);
      chartWipAssignees.data.labels = waItems.map(a => a[0]);
      chartWipAssignees.data.datasets[0].data = waItems.map(a => a[1]);
      chartWipAssignees.data.datasets[0].backgroundColor = waItems.map(([,v]) => v > 20 ? 'rgba(248,81,73,0.7)' : v > 10 ? 'rgba(210,153,34,0.6)' : 'rgba(88,166,255,0.6)');
      chartWipAssignees.update();

      // Defect density chart (5c) — recompute from by_component
      const ddSrc = d.wip_components ? (() => {{
        const fake = {{}};
        const ep = (scopeMeta.effectiveProjects && scopeMeta.effectiveProjects.length) ? scopeMeta.effectiveProjects : null;
        const byPc = DATA.by_project_component || {{}};
        const byC = DATA.by_component || {{}};
        for (const [cn, wc] of Object.entries(d.wip_components || {{}})) {{
          let bugCount = 0;
          if (ep) {{
            for (const pk of ep) {{
              const pcData = (byPc[pk] || {{}})[cn];
              if (pcData) bugCount += pcData.open_bugs_count || 0;
            }}
          }} else {{
            const cData = byC[cn];
            bugCount = cData ? cData.open_bugs_count || 0 : 0;
          }}
          fake[cn] = {{ wip_count: wc, open_bugs_count: bugCount }};
        }}
        return fake;
      }})() : (DATA.by_component||{{}});
      const ddI2 = Object.entries(ddSrc)
        .filter(([,mm]) => ((mm.open_count != null ? mm.open_count : mm.wip_count)||0) > 0)
        .map(([n, mm]) => [n, Math.round((mm.open_bugs_count||0) / ((mm.open_count != null ? mm.open_count : mm.wip_count)||1) * 1000) / 10])
        .sort((a,b) => b[1] - a[1]).slice(0, 15);
      chartDefectDensity.data.labels = ddI2.map(d => d[0]);
      chartDefectDensity.data.datasets[0].data = ddI2.map(d => d[1]);
      chartDefectDensity.data.datasets[0].backgroundColor = ddI2.map(([,v]) => v > 30 ? 'rgba(248,81,73,0.7)' : v > 10 ? 'rgba(210,153,34,0.6)' : 'rgba(88,166,255,0.6)');
      chartDefectDensity.update();

      // Focus factor chart (6c) — rebuild histogram from wip_assignees
      const waForFf = d.wip_assignees || {{}};
      const ffWipCounts = Object.entries(waForFf).filter(([k]) => k !== '(unassigned)').map(([,v]) => v);
      const ffB = {{'1': 0, '2-3': 0, '4-5': 0, '6-10': 0, '11-20': 0, '20+': 0}};
      for (const c of ffWipCounts) {{
        if (c <= 1) ffB['1']++;
        else if (c <= 3) ffB['2-3']++;
        else if (c <= 5) ffB['4-5']++;
        else if (c <= 10) ffB['6-10']++;
        else if (c <= 20) ffB['11-20']++;
        else ffB['20+']++;
      }}
      chartFocusFactor.data.datasets[0].data = Object.keys(ffB).map(l => ffB[l]);
      chartFocusFactor.update();

      // Update avg WIP summary text — prefer pre-computed value, fallback to top-20 approx
      const avgWipVal = d.avg_wip_per_assignee != null
        ? d.avg_wip_per_assignee
        : (ffWipCounts.length > 0 ? (ffWipCounts.reduce((a,b)=>a+b,0)/ffWipCounts.length).toFixed(1) : '0');
      const awEl1 = document.getElementById('avgWipPP');
      const awEl2 = document.getElementById('avgWipPP2');
      if (awEl1) awEl1.textContent = avgWipVal;
      if (awEl2) awEl2.textContent = avgWipVal;

      // Worklog dow chart
      const wlAnalysis = d.worklog_analysis || {{}};
      const wlD = wlAnalysis.by_dow || {{}};
      chartWorklogDow.data.datasets[0].data = wlDowLabels.map(dd => wlD[dd]||0);
      chartWorklogDow.update();

      // Update worklog summary text
      const wkPctEl = document.getElementById('weekendPct');
      const spCorrEl = document.getElementById('spCorr');
      if (wkPctEl) wkPctEl.textContent = (wlAnalysis.weekend_pct || 0) + '%';
      if (spCorrEl) spCorrEl.textContent = wlAnalysis.sp_worklog_correlation != null ? wlAnalysis.sp_worklog_correlation : 'N/A';

      // Logged vs Fixed Bugs chart
      const _lvfCreated = d.bug_creation_by_week || {{}};
      const _lvfResolved = d.bug_resolved_by_week || {{}};
      const _lvfAllWeeks = [...new Set([...Object.keys(_lvfCreated), ...Object.keys(_lvfResolved)])].sort();
      const _lvfCVals = _lvfAllWeeks.map(w => _lvfCreated[w]||0);
      const _lvfRVals = _lvfAllWeeks.map(w => _lvfResolved[w]||0);
      const _lvfFC = filterWeekKeys(_lvfAllWeeks, _lvfCVals);
      const _lvfFR = filterWeekKeys(_lvfAllWeeks, _lvfRVals);
      const _lvfFinalC = _hasTimeFilter ? _lvfFC : {{ keys: _lvfFC.keys.slice(-16), values: _lvfFC.values.slice(-16) }};
      const _lvfFinalR = _hasTimeFilter ? _lvfFR : {{ keys: _lvfFR.keys.slice(-16), values: _lvfFR.values.slice(-16) }};
      chartBugLoggedVsFixed.data.labels = _lvfFinalC.keys;
      chartBugLoggedVsFixed.data.datasets[0].data = _lvfFinalC.values;
      chartBugLoggedVsFixed.data.datasets[1].data = _lvfFinalR.values;
      chartBugLoggedVsFixed.update();

      // Bug creation rate chart
      const bugWkD = d.bug_creation_by_week || {{}};
      const bugWkKeysAll = Object.keys(bugWkD).sort();
      const bugF = filterWeekKeys(bugWkKeysAll, bugWkKeysAll.map(k => bugWkD[k]||0));
      const bugWkFinal = _hasTimeFilter ? bugF : {{ keys: bugF.keys.slice(-16), values: bugF.values.slice(-16) }};
      chartBugCreation.data.labels = bugWkFinal.keys;
      chartBugCreation.data.datasets[0].data = bugWkFinal.values;
      chartBugCreation.update();

      // Open bugs by priority chart
      const _updBugPri = d.open_bugs_by_priority || {{}};
      const _updBugPriLabels = Object.keys(_updBugPri);
      chartBugPriority.data.labels = _updBugPriLabels;
      chartBugPriority.data.datasets[0].data = _updBugPriLabels.map(l => _updBugPri[l]||0);
      chartBugPriority.data.datasets[0].backgroundColor = _bugPriColors.slice(0, _updBugPriLabels.length);
      chartBugPriority.update();

      // Resolution breakdown chart
      const _updRb = d.resolution_breakdown || {{}};
      const _updRbLabels = Object.keys(_updRb);
      chartResBreakdown.data.labels = _updRbLabels;
      chartResBreakdown.data.datasets[0].data = _updRbLabels.map(l => _updRb[l]||0);
      chartResBreakdown.data.datasets[0].backgroundColor = _rbColors.slice(0, _updRbLabels.length);
      chartResBreakdown.update();

      // Time in status bottleneck chart (Quality tab)
      const _updQTis = d.time_in_status || {{}};
      const _updQTisItems = Object.entries(_updQTis).sort((a,b) => (b[1].avg_hours||0) - (a[1].avg_hours||0)).slice(0, 12);
      chartQualityTIS.data.labels = _updQTisItems.map(t => t[0]);
      chartQualityTIS.data.datasets[0].data = _updQTisItems.map(t => t[1].avg_hours||0);
      chartQualityTIS.update();

      // SP trend chart (4a)
      const sptD = d.sp_trend || {{}};
      const sptMon = sptD.by_month || {{}};
      const sptKeysAll = Object.keys(sptMon).sort();
      const sptF = filterWeekKeys(sptKeysAll, sptKeysAll.map(mm => sptMon[mm]?.avg_sp || 0));
      chartSpTrend.data.labels = sptF.keys;
      chartSpTrend.data.datasets[0].data = sptF.values;
      chartSpTrend.update();

      // Epic health summary text
      const epicSummEl = document.getElementById('epicHealthSummary');
      if (epicSummEl) {{
        const oe = d.open_epics_count || 0;
        const se = d.stale_epics_count || 0;
        const ae = d.avg_epic_completion_pct || 0;
        epicSummEl.textContent = `Open: ${{oe}} | Stale (>6mo, <20% done): ${{se}} | Avg completion: ${{ae}}%`;
      }}

      // Status paths table + description
      const spaD = d.status_path_analysis || {{}};
      const skipDescEl = document.getElementById('skipDesc');
      if (skipDescEl) skipDescEl.innerHTML = `Status skip rate: <strong>${{spaD.skip_pct||0}}%</strong> (${{spaD.skip_count||0}}/${{spaD.total||0}} issues never entered an active work status).`;
      const pathsTb = document.getElementById('pathsTbody');
      if (pathsTb) {{
        const tp = spaD.top_paths || [];
        pathsTb.innerHTML = tp.length ? tp.slice(0,10).map(p => `<tr><td>${{p.path.replace(/</g,'&lt;')}}</td><td>${{p.count}}</td></tr>`).join('') : '<tr><td colspan="2">No data</td></tr>';
      }}

      // Releases per month chart (uses scoped data with time filter)
      const rpm = d.releases_per_month || {{}};
      const rpmKeysAll = Object.keys(rpm).sort();
      const rpmF = filterWeekKeys(rpmKeysAll, rpmKeysAll.map(k => rpm[k]));
      const rpmFinal = _hasTimeFilter ? rpmF : {{ keys: rpmF.keys.slice(-24), values: rpmF.values.slice(-24) }};
      if (typeof chartReleasesPerMonth !== 'undefined') {{
        chartReleasesPerMonth.data.labels = rpmFinal.keys;
        chartReleasesPerMonth.data.datasets[0].data = rpmFinal.values;
        chartReleasesPerMonth.update();
      }}

      // WIP by team chart
      if (chartWipTeams) {{
        const wt = d.wip_teams || {{}};
        const wtItems = Object.entries(wt).sort((a,b) => b[1] - a[1]).slice(0, 20);
        chartWipTeams.data.labels = wtItems.map(t => t[0]);
        chartWipTeams.data.datasets[0].data = wtItems.map(t => t[1]);
        chartWipTeams.update();
      }}

      // Sprint throughput by team chart
      if (chartTeamThroughput) {{
        const stData = {{}};
        (d.sprint_metrics || []).filter(s => isDateInRange(s.end || s.start || '')).forEach(s => {{
          const tb = s.team_breakdown || {{}};
          for (const [team, count] of Object.entries(tb))
            stData[team] = (stData[team] || 0) + count;
        }});
        const stItems = Object.entries(stData).sort((a,b) => b[1] - a[1]).slice(0, 20);
        chartTeamThroughput.data.labels = stItems.map(t => t[0]);
        chartTeamThroughput.data.datasets[0].data = stItems.map(t => t[1]);
        chartTeamThroughput.update();
      }}

      // Re-render DORA with scoped Jira data (Lead Time updates per scope)
      updateDORA(d);
    }}

    function applyProjectFilter() {{
      const scoped = getEffectiveData();
      const scopeMeta = scoped.scope_meta || {{}};
      const effectiveProj = scopeMeta.effectiveProjects || null;
      const compSel = scopeMeta.components || null;
      const teamSel = getSelectedTeams();
      window._currentScopeData = scoped;
      window._currentScopeMeta = scopeMeta;

      const show = (tr) => {{
        if (!tr.dataset.project) {{ tr.style.display = ''; return; }}
        const projectOk = effectiveProj === null || effectiveProj.includes(tr.dataset.project);
        const rowComponents = (tr.dataset.components || '').split('|').filter(Boolean);
        const componentOk = !compSel || !compSel.length || !rowComponents.length || compSel.some(c => rowComponents.includes(c));
        const rowTeams = (tr.dataset.team || '').split('|').filter(Boolean);
        const teamOk = !teamSel || !teamSel.length || !rowTeams.length || teamSel.some(t => rowTeams.includes(t));
        const dateOk = isDateInRange(tr.dataset.date || '');
        tr.style.display = (projectOk && componentOk && teamOk && dateOk) ? '' : 'none';
      }};
      ['tableBlocked', 'tableBugs', 'tableSprints', 'tableKanban', 'tableEpics', 'tableReleases'].forEach(tableId => {{
        const t = document.getElementById(tableId);
        if (t && t.tBodies[0]) t.tBodies[0].querySelectorAll('tr').forEach(show);
      }});
      if (typeof applyEpicTableFilters === 'function') applyEpicTableFilters();
      const filtered = (DATA.sprint_metrics || []).filter(s => {{
        const projectOk = effectiveProj === null || effectiveProj.includes(s.project);
        const sprintComponents = Object.keys(s.component_breakdown || {{}});
        const componentOk = !compSel || !compSel.length || !sprintComponents.length || compSel.some(c => sprintComponents.includes(c));
        const sprintTeams = Object.keys(s.team_breakdown || {{}});
        const teamOk = !teamSel || !teamSel.length || !sprintTeams.length || teamSel.some(t => sprintTeams.includes(t));
        const dateOk = isDateInRange(s.end || s.start || '');
        return projectOk && componentOk && teamOk && dateOk;
      }});
      chartAddedLate.data.labels = filtered.map(s => s.project + ' \u2013 ' + (s.sprint_name || ''));
      chartAddedLate.data.datasets[0].data = filtered.map(s => s.added_after_sprint_start != null ? s.added_after_sprint_start : 0);
      chartAddedLate.update();

      setCardsAndChartsFromMetrics(scoped, compSel, effectiveProj);
      computeGamingScore();
      computeAuditFlags();
      document.getElementById('filterBugs')?.dispatchEvent(new Event('input'));
      document.getElementById('filterSprints')?.dispatchEvent(new Event('input'));
      if (typeof window._applyEmptyBadFilter === 'function') window._applyEmptyBadFilter();
      if (typeof refreshGitTab === 'function') refreshGitTab();
      if (typeof refreshCicdCharts === 'function') refreshCicdCharts();
    }}

    const projectAll = document.getElementById('projectAll');
    const projectCbs = document.querySelectorAll('.project-cb');
    if (projectAll) {{
      projectAll.addEventListener('change', function() {{
        if (this.checked) projectCbs.forEach(cb => {{ cb.checked = false; }});
        applyProjectFilter();
      }});
    }}
    projectCbs.forEach(cb => {{
      cb.addEventListener('change', function() {{
        if (document.getElementById('projectAll').checked) document.getElementById('projectAll').checked = false;
        applyProjectFilter();
      }});
    }});
    const componentAll = document.getElementById('componentAll');
    const componentCbs = document.querySelectorAll('.component-cb');
    if (componentAll) {{
      componentAll.addEventListener('change', function() {{
        if (this.checked) componentCbs.forEach(cb => {{ cb.checked = false; }});
        applyProjectFilter();
      }});
    }}
    componentCbs.forEach(cb => {{
      cb.addEventListener('change', function() {{
        if (document.getElementById('componentAll').checked) document.getElementById('componentAll').checked = false;
        applyProjectFilter();
      }});
    }});
    const teamAll = document.getElementById('teamAll');
    const teamCbs = document.querySelectorAll('.team-cb');
    if (teamAll) {{
      teamAll.addEventListener('change', function() {{
        if (this.checked) teamCbs.forEach(cb => {{ cb.checked = false; }});
        applyProjectFilter();
      }});
    }}
    teamCbs.forEach(cb => {{
      cb.addEventListener('change', function() {{
        if (document.getElementById('teamAll')?.checked) document.getElementById('teamAll').checked = false;
        applyProjectFilter();
      }});
    }});

    // WIP phase toggles: load from localStorage, wire changes, then refresh
    (function() {{
      const saved = localStorage.getItem('wip_phases');
      if (saved) {{
        try {{
          const arr = JSON.parse(saved);
          if (Array.isArray(arr)) {{
            document.querySelectorAll('.wip-phase-cb').forEach(cb => {{
              cb.checked = arr.includes(cb.dataset.phase);
            }});
          }}
        }} catch(e) {{
          localStorage.removeItem('wip_phases');
        }}
      }}
      document.querySelectorAll('.wip-phase-cb').forEach(cb => {{
        cb.addEventListener('change', function() {{
          const phases = [];
          document.querySelectorAll('.wip-phase-cb').forEach(c => {{ if (c.checked) phases.push(c.dataset.phase); }});
          localStorage.setItem('wip_phases', JSON.stringify(phases));
          applyProjectFilter();
        }});
      }});
      setTimeout(() => applyProjectFilter(), 0);
    }})();

    function getWipPhases() {{
      const cbs = document.querySelectorAll('.wip-phase-cb');
      if (!cbs.length) return ['in_progress','in_review','blocked'];
      const phases = [];
      cbs.forEach(cb => {{ if (cb.checked) phases.push(cb.dataset.phase); }});
      return phases;
    }}

    function setupFilter(inputId, tableId) {{
      const input = document.getElementById(inputId);
      const table = document.getElementById(tableId);
      if (!input || !table) return;
      const tbody = table.querySelector('tbody');
      input.addEventListener('input', function() {{
        const q = this.value.trim().toLowerCase();
        const scopeMeta = window._currentScopeMeta || {{}};
        const proj = scopeMeta.effectiveProjects || null;
        const compSel = scopeMeta.components || null;
        const teamSel = scopeMeta.teams || null;
        tbody.querySelectorAll('tr').forEach(tr => {{
          if (tr.cells.length < 2) {{ tr.style.display = ''; return; }}
          const projectOk = proj === null || !tr.dataset.project || proj.includes(tr.dataset.project);
          const rowComponents = (tr.dataset.components || '').split('|').filter(Boolean);
          const componentOk = !compSel || !compSel.length || !rowComponents.length || compSel.some(c => rowComponents.includes(c));
          const rowTeams = (tr.dataset.team || '').split('|').filter(Boolean);
          const teamOk = !teamSel || !teamSel.length || !rowTeams.length || teamSel.some(t => rowTeams.includes(t));
          const dateOk = isDateInRange(tr.dataset.date || '');
          const text = Array.from(tr.cells).map(c => c.textContent).join(' ').toLowerCase();
          tr.style.display = (projectOk && componentOk && teamOk && dateOk && text.includes(q)) ? '' : 'none';
        }});
      }});
    }}

    function setupSort(tableId) {{
      const table = document.getElementById(tableId);
      if (!table) return;
      table.querySelectorAll('thead th[data-sort]').forEach(th => {{
        th.addEventListener('click', () => {{
          const tbody = table.querySelector('tbody');
          const rows = Array.from(tbody.querySelectorAll('tr')).filter(r => r.style.display !== 'none' && r.cells.length > 1);
          const col = Array.from(table.querySelectorAll('thead th')).indexOf(th);
          const desc = th.getAttribute('aria-sort') === 'ascending';
          th.setAttribute('aria-sort', desc ? 'descending' : 'ascending');
          table.querySelectorAll('thead th').forEach(h => {{ if (h !== th) h.removeAttribute('aria-sort'); }});
          const num = (s) => {{ const n = parseFloat(s); return isNaN(n) ? (s||'').toString().toLowerCase() : n; }};
          rows.sort((a, b) => {{
            const va = num(a.cells[col]?.textContent?.trim());
            const vb = num(b.cells[col]?.textContent?.trim());
            const cmp = (typeof va === 'number' && typeof vb === 'number') ? va - vb : String(va).localeCompare(String(vb));
            return desc ? -cmp : cmp;
          }});
          rows.forEach(r => tbody.appendChild(r));
        }});
      }});
    }}

    setupFilter('filterBugs', 'tableBugs');
    setupFilter('filterSprints', 'tableSprints');
    setupFilter('filterReleases', 'tableReleases');
    setupSort('tableBugs');
    setupSort('tableSprints');
    setupSort('tableEpics');
    setupSort('tableReleases');
    setupSort('tableEmptyBad');

    // ---------- Empty or bad structure: local Type/Status filters + text filter ----------
    (function() {{
      const allRows = [].concat(
        (DATA.empty_or_bad_list_wip || []),
        (DATA.empty_or_bad_list_done || [])
      );
      const typeSel = document.getElementById('ebFilterType');
      const statusSel = document.getElementById('ebFilterStatus');
      if (typeSel) {{
        const types = [...new Set(allRows.map(r => r.type || '').filter(Boolean))].sort();
        types.forEach(t => {{ const o = document.createElement('option'); o.value = t; o.textContent = t; typeSel.appendChild(o); }});
      }}
      if (statusSel) {{
        const statuses = [...new Set(allRows.map(r => r.status || '').filter(Boolean))].sort();
        statuses.forEach(s => {{ const o = document.createElement('option'); o.value = s; o.textContent = s; statusSel.appendChild(o); }});
      }}

      function applyEmptyBadFilter() {{
        const input = document.getElementById('filterEmptyBad');
        const table = document.getElementById('tableEmptyBad');
        if (!table) return;
        const tbody = table.querySelector('tbody');
        const q = input ? input.value.trim().toLowerCase() : '';
        const typeVal = typeSel ? typeSel.value : '';
        const statusVal = statusSel ? statusSel.value : '';
        const scopeMeta = window._currentScopeMeta || {{}};
        const proj = scopeMeta.effectiveProjects || null;
        const compSel = scopeMeta.components || null;
        const teamSel = scopeMeta.teams || null;
        tbody.querySelectorAll('tr').forEach(tr => {{
          if (tr.cells.length < 2) {{ tr.style.display = ''; return; }}
          const projectOk = proj === null || !tr.dataset.project || proj.includes(tr.dataset.project);
          const rowComponents = (tr.dataset.components || '').split('|').filter(Boolean);
          const componentOk = !compSel || !compSel.length || !rowComponents.length || compSel.some(c => rowComponents.includes(c));
          const rowTeams = (tr.dataset.team || '').split('|').filter(Boolean);
          const teamOk = !teamSel || !teamSel.length || !rowTeams.length || teamSel.some(t => rowTeams.includes(t));
          const dateOk = isDateInRange(tr.dataset.date || '');
          const typeOk = !typeVal || (tr.dataset.type || '') === typeVal;
          const statusOk = !statusVal || (tr.dataset.status || '') === statusVal;
          const text = Array.from(tr.cells).map(c => c.textContent).join(' ').toLowerCase();
          tr.style.display = (projectOk && componentOk && teamOk && dateOk && typeOk && statusOk && text.includes(q)) ? '' : 'none';
        }});
      }}

      const ebTextInput = document.getElementById('filterEmptyBad');
      if (ebTextInput) ebTextInput.addEventListener('input', applyEmptyBadFilter);
      if (typeSel) typeSel.addEventListener('change', applyEmptyBadFilter);
      if (statusSel) statusSel.addEventListener('change', applyEmptyBadFilter);
      window._applyEmptyBadFilter = applyEmptyBadFilter;
    }})();

    // ---------- Empty or bad structure: CSV export ----------
    function exportEmptyBadCSV() {{
      const d = window._currentScopeData || getEffectiveData();
      const wip = d.empty_or_bad_list_wip || [];
      const done = d.empty_or_bad_list_done || [];
      const rows = [['Key','Scope','Project','Type','Summary','Status','Assignee','Team','Author','Created']];
      function csvCell(v) {{
        const s = String(v == null ? '' : v).replace(/"/g, '""');
        return /[",\\n\\r]/.test(s) ? '"' + s + '"' : s;
      }}
      wip.forEach(r => rows.push([r.key,  'WIP',  r.project, r.type, r.summary, r.status, r.assignee_display_name, r.team || '', r.author_display_name || '', r.created || ''].map(csvCell)));
      done.forEach(r => rows.push([r.key, 'Done', r.project, r.type, r.summary, r.status, r.assignee_display_name, r.team || '', r.author_display_name || '', r.created || ''].map(csvCell)));
      const csv = rows.map(r => r.join(',')).join('\\r\\n');
      const ts = (d.run_iso_ts || new Date().toISOString()).replace(/:/g, '-').slice(0,19);
      const blob = new Blob([csv], {{ type: 'text/csv' }});
      const url = URL.createObjectURL(blob);
      const a = document.createElement('a');
      a.href = url; a.download = 'empty_or_bad_' + ts + '.csv'; a.click();
      URL.revokeObjectURL(url);
    }}

    // ---------- Empty or bad structure: compare with previous scan ----------
    (function() {{
      const sel = document.getElementById('emptyBadCompareSelect');
      if (!sel) return;
      SCAN_HISTORY.forEach(function(snap, i) {{
        const opt = document.createElement('option');
        opt.value = String(i);
        opt.textContent = snap.label;
        sel.appendChild(opt);
      }});
    }})();

    function compareEmptyBad(idxStr) {{
      const clearBtn = document.getElementById('emptyBadClearBtn');
      const summary = document.getElementById('ebCompareSummary');
      const tbody = document.querySelector('#tableEmptyBad tbody');
      // Remove any previously-appended resolved rows
      tbody.querySelectorAll('tr.eb-row-resolved').forEach(r => r.remove());
      tbody.querySelectorAll('tr').forEach(r => r.classList.remove('eb-row-new'));
      if (summary) {{ summary.style.display = 'none'; summary.innerHTML = ''; }}
      if (!idxStr || idxStr === '') {{
        if (clearBtn) clearBtn.style.display = 'none';
        return;
      }}
      const snap = SCAN_HISTORY[parseInt(idxStr, 10)];
      if (!snap) return;

      const d = window._currentScopeData || getEffectiveData();
      const curAll = (d.empty_or_bad_list_wip || []).concat(d.empty_or_bad_list_done || []);
      const oldAll = (snap.wip || []).concat(snap.done || []);
      const oldKeys = new Set(oldAll.map(r => r.key));
      const curKeys = new Set(curAll.map(r => r.key));

      let addedCount = 0, resolvedCount = 0, unchangedCount = 0;

      // Highlight new rows (in current but not in old)
      tbody.querySelectorAll('tr').forEach(function(tr) {{
        const keyCell = tr.querySelector('td:first-child');
        if (!keyCell) return;
        const key = keyCell.textContent.trim();
        if (!oldKeys.has(key)) {{ tr.classList.add('eb-row-new'); addedCount++; }}
        else {{ unchangedCount++; }}
      }});

      // Append resolved rows (in old but not in current)
      const resolved = oldAll.filter(r => !curKeys.has(r.key));
      resolvedCount = resolved.length;
      resolved.forEach(function(r) {{
        const tr = document.createElement('tr');
        tr.className = 'eb-row-resolved';
        const scope = snap.wip.some(x => x.key === r.key) ? 'WIP' : 'Done';
        const esc = s => String(s||'').replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;');
        tr.innerHTML = '<td>' + esc(r.key) + '</td><td>' + scope + '</td><td>' + esc(r.project) + '</td>' +
          '<td>' + esc(r.type) + '</td><td>' + esc((r.summary||'').slice(0,60)) + '</td>' +
          '<td>' + esc(r.status) + '</td><td>' + esc(r.assignee_display_name) + '</td>' +
          '<td>' + esc(r.team || '') + '</td>' +
          '<td>' + esc(r.author_display_name || '') + '</td>' +
          '<td>' + esc(r.created || '') + '</td>';
        tbody.appendChild(tr);
      }});

      if (summary) {{
        summary.style.display = '';
        summary.innerHTML = 'vs <strong>' + snap.label + '</strong> &nbsp;&mdash;&nbsp; ' +
          '<span class="eb-new">+' + addedCount + ' new</span> &nbsp; ' +
          '<span class="eb-resolved">&minus;' + resolvedCount + ' resolved</span> &nbsp; ' +
          unchangedCount + ' unchanged';
      }}
      if (clearBtn) clearBtn.style.display = '';
    }}

    function clearEmptyBadCompare() {{
      const sel = document.getElementById('emptyBadCompareSelect');
      if (sel) sel.value = '';
      compareEmptyBad('');
    }}

    const EPIC_ROW_CAP = 80;
    window._epicShowAllRows = false;
    function applyEpicTableFilters() {{
      const tbody = document.querySelector('#tableEpics tbody');
      if (!tbody) return;
      const staleOnly = document.getElementById('epicStaleOnly')?.checked;
      const btn = document.getElementById('epicShowAllBtn');
      const all = Array.from(tbody.querySelectorAll('tr')).filter(r => r.cells.length > 1);
      all.forEach(r => {{
        if (r.style.display === 'none') return;
        if (staleOnly && r.dataset.stale !== '1') r.style.display = 'none';
      }});
      const visible = all.filter(r => r.style.display !== 'none');
      const total = visible.length;
      if (!staleOnly && !window._epicShowAllRows && total > EPIC_ROW_CAP) {{
        visible.forEach((r, i) => {{ if (i >= EPIC_ROW_CAP) r.style.display = 'none'; }});
        if (btn) {{ btn.style.display = ''; btn.textContent = `Show all ${{total}} rows`; }}
      }} else if (btn) {{
        btn.style.display = 'none';
      }}
    }}
    document.getElementById('epicStaleOnly')?.addEventListener('change', () => {{ window._epicShowAllRows = false; applyProjectFilter(); }});
    document.getElementById('epicShowAllBtn')?.addEventListener('click', () => {{ window._epicShowAllRows = true; applyProjectFilter(); }});

    document.getElementById('auditFilterSeverity')?.addEventListener('change', renderAuditFlagsDOM);
    document.getElementById('auditFilterCategory')?.addEventListener('change', renderAuditFlagsDOM);

    // ---------- Evidence Export (Phase 4b) ----------
    function exportEvidence() {{
      const flags = window._auditFlagsAll || window._auditFlags || [];
      const gs = window._gamingScore || 0;
      const ps = window._projectScores || {{}};
      const d = window._currentScopeData || getEffectiveData();
      const scopeMeta = d.scope_meta || {{}};
      let md = '# Jira Engineering Audit \u2014 Evidence Report\\n\\n';
      md += `**Generated:** ${{d.run_iso_ts}}\\n`;
      md += `**Scope:** ${{scopeMeta.label || 'Project: All projects | Component: All components | Mode: exact'}}\\n`;
      md += `**Projects:** ${{(d.projects||[]).join(', ')}}\\n\\n`;
      md += '## Gaming Score\\n\\n';
      md += `**Overall: ${{gs}}/100** (${{gs >= 60 ? 'Systemic Gaming' : gs >= 40 ? 'Significant Manipulation' : gs >= 20 ? 'Concerning' : 'Healthy'}})\\n\\n`;
      md += '| Project | Score |\\n|---------|-------|\\n';
      for (const [pk, s] of Object.entries(ps)) md += `| ${{pk}} | ${{s}} |\\n`;
      md += '\\n## Key Metrics\\n\\n';
      md += `| Metric | Value |\\n|--------|-------|\\n`;
      const openCountExport = d.open_count != null ? d.open_count : d.wip_count;
      const unassignedOpenExport = d.unassigned_open_count != null ? d.unassigned_open_count : (d.unassigned_wip_count||0);
      md += `| Open (not done) | ${{openCountExport}} |\\n`;
      const _expPh = d.open_by_phase || d.wip_by_phase || phaseFromStatusDist(d.status_distribution || {{}});
      const _expMap = {{ backlog: _expPh.backlog ?? _expPh.not_started ?? 0, in_progress: _expPh.in_progress ?? 0, in_review: _expPh.in_review ?? _expPh.review_qa ?? 0, blocked: _expPh.blocked ?? 0 }};
      const _expWip = (typeof getWipPhases==='function'?getWipPhases():['in_progress','in_review','blocked']).reduce((s,p)=>s+(_expMap[p]||0),0);
      md += `| WIP (in flight) | ${{_expWip}} |\\n`;
      md += `| Unassigned open | ${{unassignedOpenExport}} (${{openCountExport ? Math.round(unassignedOpenExport/openCountExport*100) : 0}}%) |\\n`;
      md += `| Blocked | ${{d.blocked_count}} |\\n`;
      md += `| Open Bugs | ${{d.open_bugs_count}} |\\n`;
      md += `| Lead Time Avg | ${{d.lead_time_days?.avg_days?.toFixed(1) || '-'}} days |\\n`;
      md += `| Cycle Time Avg | ${{d.cycle_time_days?.avg_days?.toFixed(1) || '-'}} days |\\n`;
      md += `| Flow Efficiency | ${{d.flow_efficiency?.efficiency_pct || 0}}% |\\n`;
      md += `| Status Skip Rate | ${{d.status_path_analysis?.skip_pct || 0}}% |\\n`;
      md += `| Closer != Assignee | ${{d.closer_analysis?.closer_not_assignee_pct || 0}}% |\\n`;
      md += `| Reopen Rate | ${{d.reopen_analysis?.reopened_pct || 0}}% |\\n`;
      md += `| Empty Descriptions (done) | ${{d.empty_description_done_pct || 0}}% |\\n`;
      md += `| Empty or bad structure (open) | ${{d.empty_or_bad_count_wip ?? 0}} (${{d.empty_or_bad_pct_wip ?? 0}}%) |\\n`;
      md += `| Empty or bad structure (Done) | ${{d.empty_or_bad_count_done ?? 0}} (${{d.empty_or_bad_pct_done ?? 0}}%) |\\n`;
      md += `| Zero Comments (done) | ${{d.zero_comment_done_pct || 0}}% |\\n`;
      md += `| Workload Gini | ${{d.workload_gini || 0}} |\\n`;
      md += `| Assignee Change Near Resolution | ${{(d.assignee_change_near_resolution||{{}}).changed_pct || 0}}% |\\n`;
      md += `| Post-Resolution Comments | ${{(d.comment_timing||{{}}).post_resolution_comment_pct || 0}}% |\\n`;
      md += `| Zero-Worklog Done Issues | ${{(d.worklog_analysis||{{}}).zero_worklog_pct || 0}}% |\\n`;
      md += `| Post-Resolution Worklogs | ${{(d.worklog_analysis||{{}}).post_resolution_worklog_pct || 0}}% |\\n`;
      md += `| Open Epics | ${{d.open_epics_count || 0}} |\\n`;
      md += `| Stale Epics | ${{d.stale_epics_count || 0}} |\\n`;
      md += `| SP Inflation Detected | ${{(d.sp_trend||{{}}).inflation_detected ? 'Yes' : 'No'}} |\\n`;
      md += `| Avg open per person | ${{d.avg_wip_per_assignee || 0}} |\\n`;
      md += '\\n## Audit Flags\\n\\n';
      const sevEmoji = {{ red: '[RED]', orange: '[ORANGE]', yellow: '[YELLOW]' }};
      for (const f of flags) {{
        const cat = f.category ? ` [${{f.category}}]` : '';
        md += `### ${{sevEmoji[f.severity] || ''}}${{cat}} ${{f.title}}\\n\\n${{f.detail}}\\n\\n`;
      }}
      md += '\\n## Resolution Breakdown\\n\\n';
      md += '| Type | Count |\\n|------|-------|\\n';
      for (const [k,v] of Object.entries(d.resolution_breakdown||{{}})) md += `| ${{k}} | ${{v}} |\\n`;
      md += '\\n---\\n\\n*Generated by Clear Horizon Tech \u2014 Jira Analytics Dashboard*\\n';

      const blob = new Blob([md], {{ type: 'text/markdown' }});
      const url = URL.createObjectURL(blob);
      const a = document.createElement('a');
      a.href = url;
      a.download = `audit_evidence_${{d.run_iso_ts?.replace(/:/g,'-') || 'report'}}.md`;
      a.click();
      URL.revokeObjectURL(url);
    }}

    window._gitCharts = {{}};
    window._cicdCharts = {{}};

    function _mkExtraCard(label, value, color) {{
      return `<div class="card"><div class="value" style="color:${{color||'var(--accent)'}}">${{value ?? 'N/A'}}</div><div class="label">${{label}}</div></div>`;
    }}

    function mergeWeekAvgMaps(maps) {{
      if (!maps || !maps.length) return {{}};
      const keys = new Set();
      maps.forEach(m => Object.keys(m||{{}}).forEach(k => keys.add(k)));
      const out = {{}};
      for (const k of [...keys].sort()) {{
        const vals = maps.map(m => m[k]).filter(v => v != null && !Number.isNaN(+v));
        if (!vals.length) continue;
        out[k] = Math.round((vals.reduce((a,b) => a + Number(b), 0) / vals.length) * 100) / 100;
      }}
      return out;
    }}

    function mergeWeekSumMaps(maps) {{
      if (!maps || !maps.length) return {{}};
      const keys = new Set();
      maps.forEach(m => Object.keys(m||{{}}).forEach(k => keys.add(k)));
      const out = {{}};
      for (const k of [...keys].sort()) {{
        out[k] = maps.reduce((s, m) => s + (m[k] || 0), 0);
      }}
      return out;
    }}

    function mergeBreakdownByWeekMaps(maps) {{
      if (!maps || !maps.length) return {{}};
      const keys = new Set();
      maps.forEach(m => Object.keys(m||{{}}).forEach(k => keys.add(k)));
      const out = {{}};
      for (const w of [...keys].sort()) {{
        const rows = maps.map(m => m[w]).filter(Boolean);
        if (!rows.length) continue;
        const n = rows.length;
        out[w] = {{
          avg_progress_hours: Math.round((rows.reduce((s, x) => s + (x.avg_progress_hours || 0), 0) / n) * 100) / 100,
          avg_review_hours: Math.round((rows.reduce((s, x) => s + (x.avg_review_hours || 0), 0) / n) * 100) / 100,
          avg_merge_hours: Math.round((rows.reduce((s, x) => s + (x.avg_merge_hours || 0), 0) / n) * 100) / 100,
          pr_count: rows.reduce((s, x) => s + (x.pr_count || 0), 0),
        }};
      }}
      return out;
    }}

    function mergeWeekReviewMaps(maps) {{
      // Each map: {{ week: {{ avg_hours, n }} }}. Merge across repos using weighted average of avg_hours, summing n.
      if (!maps || !maps.length) return {{}};
      const keys = new Set();
      maps.forEach(m => Object.keys(m || {{}}).forEach(k => keys.add(k)));
      const out = {{}};
      for (const k of [...keys].sort()) {{
        let num = 0, den = 0;
        for (const m of maps) {{
          const e = m && m[k];
          if (e && e.n > 0) {{ num += e.avg_hours * e.n; den += e.n; }}
        }}
        if (den > 0) out[k] = {{ avg_hours: Math.round((num / den) * 10) / 10, n: den }};
      }}
      return out;
    }}

    function mergeGitByRepos(gitRoot, selectedRepos) {{
      if (!gitRoot || !selectedRepos || !selectedRepos.length) return gitRoot;
      const analyzed = gitRoot.repos_analyzed || [];
      if (selectedRepos.length >= analyzed.length) return gitRoot;
      const byR = gitRoot.by_repo || {{}};
      const repos = selectedRepos.filter(r => byR[r]);
      if (!repos.length) return gitRoot;
      const out = JSON.parse(JSON.stringify(gitRoot));
      let mc = 0;
      for (const r of repos) {{
        const c = (byR[r].pr_cycle_time || {{}}).count;
        if (c) mc += c;
      }}
      out.pr_merged_count = mc;
      const wavg = (field) => {{
        let num = 0, den = 0;
        for (const r of repos) {{
          const pc = byR[r].pr_cycle_time || {{}};
          const c = pc.count || 0;
          if (c && pc[field] != null) {{ num += pc[field] * c; den += c; }}
        }}
        return den ? Math.round((num / den) * 100) / 100 : 0;
      }};
      out.pr_cycle_time = {{
        count: mc,
        avg_days: wavg('avg_days'),
        p50_days: wavg('p50_days'),
        p85_days: wavg('p85_days'),
        p95_days: wavg('p95_days'),
      }};
      out.pr_cycle_time_by_week = mergeWeekAvgMaps(repos.map(r => byR[r].pr_cycle_time_by_week || {{}}));
      const mergesByWeek = mergeWeekSumMaps(repos.map(r => ((byR[r].merge_frequency || {{}}).merges_by_week || {{}})));
      const wkKeys = Object.keys(mergesByWeek);
      const totalMerges = Object.values(mergesByWeek).reduce((a, b) => a + b, 0);
      out.merge_frequency = Object.assign({{}}, out.merge_frequency || {{}}, {{
        merges_by_week: mergesByWeek,
        avg_merges_per_week: wkKeys.length ? Math.round((totalMerges / wkKeys.length) * 10) / 10 : 0,
      }});
      const rtw = (field) => {{
        let num = 0, den = 0;
        for (const r of repos) {{
          const rv = byR[r].review_turnaround || {{}};
          const c = rv.count || 0;
          if (c && rv[field] != null) {{ num += rv[field] * c; den += c; }}
        }}
        return den ? Math.round((num / den) * 10) / 10 : 0;
      }};
      let rtc = 0;
      for (const r of repos) rtc += (byR[r].review_turnaround || {{}}).count || 0;
      let pnrNum = 0, pnrDen = 0;
      for (const r of repos) {{
        const rv = byR[r].review_turnaround || {{}};
        const t = rv.count || 0;
        if (t && rv.pct_no_review != null) {{ pnrNum += rv.pct_no_review * t; pnrDen += t; }}
      }}
      let psmNum = 0, psmDen = 0;
      for (const r of repos) {{
        const rv = byR[r].review_turnaround || {{}};
        const t = rv.count || 0;
        if (t && rv.pct_self_merged != null) {{ psmNum += rv.pct_self_merged * t; psmDen += t; }}
      }}
      out.review_turnaround = {{
        count: rtc,
        avg_hours: rtw('avg_hours'),
        p50_hours: rtw('p50_hours'),
        p85_hours: rtw('p85_hours'),
        pct_no_review: pnrDen ? Math.round((pnrNum / pnrDen) * 10) / 10 : 0,
        pct_self_merged: psmDen ? Math.round((psmNum / psmDen) * 10) / 10 : 0,
      }};
      out.review_turnaround_by_week = mergeWeekAvgMaps(repos.map(r => byR[r].review_turnaround_by_week || {{}}));
      out.review_turnaround_by_merge_week = mergeWeekReviewMaps(repos.map(r => byR[r].review_turnaround_by_merge_week || {{}}));
      const dist = {{ xs: 0, small: 0, medium: 0, large: 0, xl: 0 }};
      for (const r of repos) {{
        const d = (byR[r].pr_size || {{}}).distribution || {{}};
        for (const k of Object.keys(dist)) dist[k] += d[k] || 0;
      }}
      out.pr_size = Object.assign({{}}, out.pr_size || {{}}, {{ distribution: dist }});
      const wbd = (phase, field) => {{
        let num = 0, den = 0;
        for (const r of repos) {{
          const pb = ((byR[r].pr_cycle_breakdown || {{}})[phase]) || {{}};
          const c = pb.count || 0;
          if (c && pb[field] != null) {{ num += pb[field] * c; den += c; }}
        }}
        return den ? Math.round((num / den) * 100) / 100 : 0;
      }};
      let phaseCount = 0;
      for (const r of repos) {{
        const c = ((byR[r].pr_cycle_breakdown || {{}}).time_in_progress_hours || {{}}).count;
        if (c) {{ phaseCount = c; break; }}
      }}
      out.pr_cycle_breakdown = {{
        time_in_progress_hours: {{
          count: phaseCount,
          avg_hours: wbd('time_in_progress_hours', 'avg_hours'),
          p50_hours: wbd('time_in_progress_hours', 'p50_hours'),
          p85_hours: wbd('time_in_progress_hours', 'p85_hours'),
          p95_hours: wbd('time_in_progress_hours', 'p95_hours'),
        }},
        time_in_review_hours: {{
          count: phaseCount,
          avg_hours: wbd('time_in_review_hours', 'avg_hours'),
          p50_hours: wbd('time_in_review_hours', 'p50_hours'),
          p85_hours: wbd('time_in_review_hours', 'p85_hours'),
          p95_hours: wbd('time_in_review_hours', 'p95_hours'),
        }},
        time_to_merge_hours: {{
          count: phaseCount,
          avg_hours: wbd('time_to_merge_hours', 'avg_hours'),
          p50_hours: wbd('time_to_merge_hours', 'p50_hours'),
          p85_hours: wbd('time_to_merge_hours', 'p85_hours'),
          p95_hours: wbd('time_to_merge_hours', 'p95_hours'),
        }},
        no_approval_count: repos.reduce((s, r) => s + ((byR[r].pr_cycle_breakdown || {{}}).no_approval_count || 0), 0),
        excluded: {{ missing_dates: 0 }},
      }};
      out.pr_cycle_breakdown_by_week = mergeBreakdownByWeekMaps(repos.map(r => byR[r].pr_cycle_breakdown_by_week || {{}}));
      const bfAll = (gitRoot.contributors || {{}}).bus_factor_by_repo || {{}};
      const bfSel = {{}};
      for (const r of repos) if (bfAll[r] != null) bfSel[r] = bfAll[r];
      out.contributors = Object.assign({{}}, out.contributors || {{}}, {{
        bus_factor_by_repo: bfSel,
        min_bus_factor: Object.values(bfSel).length ? Math.min(...Object.values(bfSel)) : (out.contributors || {{}}).min_bus_factor,
      }});
      const driftAll = (gitRoot.branch_drift || {{}}).by_repo || {{}};
      const driftSel = {{}};
      for (const r of repos) if (driftAll[r]) driftSel[r] = driftAll[r];
      out.branch_drift = Object.assign({{}}, out.branch_drift || {{}}, {{ by_repo: driftSel }});
      return out;
    }}

    function getSelectedGitRepos() {{
      const analyzed = (GIT_DATA && GIT_DATA.repos_analyzed) || [];
      if (!analyzed.length) return null;
      const all = document.getElementById('gitRepoAll');
      if (all && all.checked) return null;
      const cbs = document.querySelectorAll('.git-repo-cb:checked');
      const s = Array.from(cbs).map(cb => cb.value);
      return s.length ? s : null;
    }}

    function buildEffectiveGitData() {{
      if (!GIT_DATA || !Object.keys(GIT_DATA).length) return null;
      const sel = getSelectedGitRepos();
      const base = sel === null ? GIT_DATA : mergeGitByRepos(GIT_DATA, sel);
      return applyGitTimeScope(base, window._timeRange);
    }}

    function applyGitTimeScope(gitRoot, tr) {{
      // Recomputes Git KPI cards to align with the active date filter.
      // When no filter is set, returns gitRoot unchanged (preserving p50/p85 from the JSON).
      if (!tr.from && !tr.to) return gitRoot;

      const mergesW = (gitRoot.merge_frequency || {{}}).merges_by_week || {{}};
      const cycleW = gitRoot.pr_cycle_time_by_week || {{}};
      const revMW = gitRoot.review_turnaround_by_merge_week || {{}};
      const bkW = gitRoot.pr_cycle_breakdown_by_week || {{}};
      const allWeeks = new Set([
        ...Object.keys(mergesW), ...Object.keys(cycleW),
        ...Object.keys(revMW), ...Object.keys(bkW),
      ]);

      let totalMerges = 0, wkCount = 0;
      let cycleNum = 0, cycleDen = 0;
      let revNum = 0, revDen = 0;
      let bkProg = 0, bkRev = 0, bkMrg = 0, bkDen = 0;

      for (const w of allWeeks) {{
        const d = keyToComparableDate(w);
        if (tr.from && d < tr.from) continue;
        if (tr.to && d > tr.to) continue;
        const n = mergesW[w] || 0;
        if (n > 0) {{
          totalMerges += n;
          // count weeks with at least one merge (denominator for merges/wk)
          wkCount++;
          if (cycleW[w] != null) {{ cycleNum += cycleW[w] * n; cycleDen += n; }}
        }}
        const rv = revMW[w];
        if (rv && rv.n > 0) {{ revNum += rv.avg_hours * rv.n; revDen += rv.n; }}
        const bk = bkW[w];
        if (bk && bk.pr_count > 0) {{
          const c = bk.pr_count;
          bkProg += (bk.avg_progress_hours || 0) * c;
          bkRev += (bk.avg_review_hours || 0) * c;
          bkMrg += (bk.avg_merge_hours || 0) * c;
          bkDen += c;
        }}
      }}

      const out = JSON.parse(JSON.stringify(gitRoot));
      out.pr_merged_count = totalMerges;
      out.pr_cycle_time = Object.assign({{}}, out.pr_cycle_time || {{}}, {{
        avg_days: cycleDen ? Math.round((cycleNum / cycleDen) * 100) / 100 : 0,
        _filtered_mean: true,
      }});
      out.merge_frequency = Object.assign({{}}, out.merge_frequency || {{}}, {{
        avg_merges_per_week: wkCount ? Math.round((totalMerges / wkCount) * 10) / 10 : 0,
      }});
      const revMean = revDen ? Math.round((revNum / revDen) * 10) / 10 : null;
      out.review_turnaround = Object.assign({{}}, out.review_turnaround || {{}}, {{
        avg_hours: revMean !== null ? revMean : (out.review_turnaround || {{}}).avg_hours,
        _filtered_mean: revMean !== null,
      }});
      if (!out.pr_cycle_breakdown_skip_reason && bkDen > 0) {{
        const pm = (num) => Math.round((num / bkDen) * 100) / 100;
        out.pr_cycle_breakdown = Object.assign({{}}, out.pr_cycle_breakdown || {{}}, {{
          time_in_progress_hours: Object.assign({{}}, (out.pr_cycle_breakdown || {{}}).time_in_progress_hours || {{}}, {{ avg_hours: pm(bkProg), _filtered_mean: true }}),
          time_in_review_hours: Object.assign({{}}, (out.pr_cycle_breakdown || {{}}).time_in_review_hours || {{}}, {{ avg_hours: pm(bkRev), _filtered_mean: true }}),
          time_to_merge_hours: Object.assign({{}}, (out.pr_cycle_breakdown || {{}}).time_to_merge_hours || {{}}, {{ avg_hours: pm(bkMrg), _filtered_mean: true }}),
        }});
      }}
      return out;
    }}

    function renderGitRepoFilterBar() {{
      const bar = document.getElementById('gitRepoFilterBar');
      if (!bar || !GIT_DATA || !GIT_DATA.repos_analyzed || !GIT_DATA.repos_analyzed.length) {{
        if (bar) bar.innerHTML = '';
        return;
      }}
      let saved = [];
      try {{ saved = JSON.parse(localStorage.getItem('git_repo_filter') || '[]'); }} catch (e) {{ saved = []; }}
      const repos = GIT_DATA.repos_analyzed;
      const allOn = !saved.length || saved.length >= repos.length;
      let html = '<span class="pf-label">Git repos:</span><label><input type="checkbox" id="gitRepoAll" ' + (allOn ? 'checked' : '') + ' /> All</label>';
      repos.forEach(r => {{
        const chk = allOn || saved.includes(r) ? ' checked' : '';
        const esc = String(r).replace(/&/g,'&amp;').replace(/"/g,'&quot;');
        html += '<label style="display:inline-flex;align-items:center;gap:4px;cursor:pointer"><input type="checkbox" class="git-repo-cb" value="' + esc + '"' + chk + ' /> ' + esc + '</label>';
      }});
      bar.innerHTML = html;
      const ra = document.getElementById('gitRepoAll');
      if (ra) ra.addEventListener('change', function() {{
        if (this.checked) document.querySelectorAll('.git-repo-cb').forEach(cb => {{ cb.checked = false; }});
        try {{ localStorage.setItem('git_repo_filter', JSON.stringify([])); }} catch (e) {{}}
        refreshGitTab();
      }});
      document.querySelectorAll('.git-repo-cb').forEach(cb => {{
        cb.addEventListener('change', function() {{
          if (document.getElementById('gitRepoAll')?.checked) document.getElementById('gitRepoAll').checked = false;
          const sel = Array.from(document.querySelectorAll('.git-repo-cb:checked')).map(x => x.value);
          try {{ localStorage.setItem('git_repo_filter', JSON.stringify(sel)); }} catch (e) {{}}
          refreshGitTab();
        }});
      }});
    }}

    function initGitCharts() {{
      const y0 = {{ scales: {{ y: {{ beginAtZero: true }} }} }};
      const hbar = {{ indexAxis: 'y', scales: Object.assign({{}}, _hbarScales, {{ x: {{ beginAtZero: true }} }}) }};
      const G = window._gitCharts;
      if (document.getElementById('chartPrCycle')) {{
        G.prCycle = new Chart(document.getElementById('chartPrCycle'), {{
          type: 'line',
          data: {{ labels: [], datasets: [{{ label: 'PR Cycle (days)', data: [], borderColor: '#58a6ff', fill: false }}] }},
          options: y0,
        }});
      }}
      if (document.getElementById('chartMergeFreq')) {{
        G.mergeFreq = new Chart(document.getElementById('chartMergeFreq'), {{
          type: 'bar',
          data: {{ labels: [], datasets: [{{ label: 'Merges', data: [], backgroundColor: '#238636' }}] }},
          options: y0,
        }});
      }}
      if (document.getElementById('chartPrSize')) {{
        G.prSize = new Chart(document.getElementById('chartPrSize'), {{
          type: 'doughnut',
          data: {{ labels: [], datasets: [{{ data: [], backgroundColor: ['#27ae60','#2ecc71','#f1c40f','#e67e22','#e74c3c'] }}] }},
        }});
      }}
      if (document.getElementById('chartReviewTurnaround')) {{
        G.reviewTurn = new Chart(document.getElementById('chartReviewTurnaround'), {{
          type: 'line',
          data: {{ labels: [], datasets: [{{ label: 'Review (hours)', data: [], borderColor: '#e67e22', fill: false }}] }},
          options: y0,
        }});
      }}
      if (document.getElementById('chartBusFactor')) {{
        G.busFactor = new Chart(document.getElementById('chartBusFactor'), {{
          type: 'bar',
          data: {{ labels: [], datasets: [{{ label: 'Bus Factor', data: [], backgroundColor: [] }}] }},
          options: hbar,
        }});
      }}
      if (document.getElementById('chartPrCycleBreakdown')) {{
        G.prBreakdown = new Chart(document.getElementById('chartPrCycleBreakdown'), {{
          type: 'bar',
          data: {{
            labels: [],
            datasets: [
              {{ label: 'Coding (progress)', data: [], backgroundColor: 'rgba(88,166,255,0.75)' }},
              {{ label: 'Review / approval', data: [], backgroundColor: 'rgba(210,153,34,0.75)' }},
              {{ label: 'To merge', data: [], backgroundColor: 'rgba(46,160,67,0.75)' }},
            ],
          }},
          options: {{ scales: {{ x: {{ stacked: true }}, y: {{ stacked: true, beginAtZero: true }} }} }},
        }});
      }}
    }}

    function refreshGitTab() {{
      const g = buildEffectiveGitData();
      const G = window._gitCharts;
      const note = document.getElementById('gitBreakdownNote');
      const bdDesc = document.getElementById('gitBreakdownDesc');
      if (!g || !Object.keys(g).length) return;
      const gc = document.getElementById('gitCards');
      if (gc) {{
        const prc = g.pr_cycle_time || {{}};
        const rev = g.review_turnaround || {{}};
        const mf = g.merge_frequency || {{}};
        const contrib = g.contributors || {{}};
        const filtered = !!(window._timeRange.from || window._timeRange.to);
        const cycleLabel = (filtered && prc._filtered_mean) ? 'PR Cycle mean' : 'PR Cycle p50';
        const cycleVal = (filtered && prc._filtered_mean) ? prc.avg_days : prc.p50_days;
        const revLabel = (filtered && rev._filtered_mean) ? 'Review mean' : 'Review p50';
        const revVal = (filtered && rev._filtered_mean) ? rev.avg_hours : rev.p50_hours;
        gc.innerHTML =
          _mkExtraCard('PRs Merged', g.pr_merged_count) +
          _mkExtraCard(cycleLabel, (cycleVal || 0).toFixed(1) + 'd') +
          _mkExtraCard(revLabel, (revVal || 0).toFixed(1) + 'h') +
          _mkExtraCard('Merges/wk', mf.avg_merges_per_week) +
          _mkExtraCard('Min Bus Factor', contrib.min_bus_factor, contrib.min_bus_factor <= 1 ? '#e74c3c' : '#2ecc71') +
          _mkExtraCard('Contributors', contrib.total_contributors);
        const gcNote = document.getElementById('gitContribNote');
        if (gcNote) gcNote.style.display = filtered ? '' : 'none';
      }}
      const gbc = document.getElementById('gitBreakdownCards');
      const pcb = g.pr_cycle_breakdown;
      const skip = g.pr_cycle_breakdown_skip_reason;
      if (note) {{
        note.style.display = skip ? 'block' : 'none';
        note.textContent = skip === 'gitlab_not_supported' ? 'PR cycle breakdown is not available for GitLab in this version.' : (skip === 'disabled_via_env' ? 'PR cycle breakdown was disabled (GIT_PR_BREAKDOWN_ENABLED).' : '');
      }}
      if (bdDesc) bdDesc.style.display = skip ? 'none' : 'block';
      if (gbc) {{
        if (!pcb || skip) {{
          gbc.innerHTML = skip ? _mkExtraCard('Breakdown', 'N/A') : '';
        }} else {{
          const p = pcb.time_in_progress_hours || {{}};
          const r = pcb.time_in_review_hours || {{}};
          const m = pcb.time_to_merge_hours || {{}};
          const bkFiltered = !!(p._filtered_mean || r._filtered_mean || m._filtered_mean);
          const bkCodingLabel = bkFiltered ? 'Coding mean (h)' : 'Coding p50 (h)';
          const bkRevLabel = bkFiltered ? 'Review mean (h)' : 'Review p50 (h)';
          const bkMrgLabel = bkFiltered ? 'Merge mean (h)' : 'Merge p50 (h)';
          const bkCodingVal = bkFiltered ? p.avg_hours : p.p50_hours;
          const bkRevVal = bkFiltered ? r.avg_hours : r.p50_hours;
          const bkMrgVal = bkFiltered ? m.avg_hours : m.p50_hours;
          gbc.innerHTML =
            _mkExtraCard(bkCodingLabel, (bkCodingVal ?? 0).toFixed(1)) +
            _mkExtraCard(bkRevLabel, (bkRevVal ?? 0).toFixed(1)) +
            _mkExtraCard(bkMrgLabel, (bkMrgVal ?? 0).toFixed(1));
        }}
      }}
      const prcW = g.pr_cycle_time_by_week || {{}};
      const prcKeys = Object.keys(prcW).sort();
      const prcFv = filterWeekKeys(prcKeys, prcKeys.map(k => prcW[k]));
      if (G.prCycle) {{
        G.prCycle.data.labels = prcFv.keys;
        G.prCycle.data.datasets[0].data = prcFv.values;
        G.prCycle.update();
      }}
      const mfW = (g.merge_frequency || {{}}).merges_by_week || {{}};
      const mfKeys = Object.keys(mfW).sort();
      const mfFv = filterWeekKeys(mfKeys, mfKeys.map(k => mfW[k]));
      if (G.mergeFreq) {{
        G.mergeFreq.data.labels = mfFv.keys;
        G.mergeFreq.data.datasets[0].data = mfFv.values;
        G.mergeFreq.update();
      }}
      const prSize = (g.pr_size || {{}}).distribution || {{}};
      if (G.prSize && Object.keys(prSize).length) {{
        G.prSize.data.labels = Object.keys(prSize);
        G.prSize.data.datasets[0].data = Object.values(prSize);
        G.prSize.update();
      }}
      const revW = g.review_turnaround_by_week || {{}};
      const rvKeys = Object.keys(revW).sort();
      const rvFv = filterWeekKeys(rvKeys, rvKeys.map(k => revW[k]));
      if (G.reviewTurn) {{
        G.reviewTurn.data.labels = rvFv.keys;
        G.reviewTurn.data.datasets[0].data = rvFv.values;
        G.reviewTurn.update();
      }}
      const bf = (g.contributors || {{}}).bus_factor_by_repo || {{}};
      if (G.busFactor && Object.keys(bf).length) {{
        const repos = Object.keys(bf);
        const vals = Object.values(bf);
        const colors = vals.map(v => (v <= 1 ? '#e74c3c' : v === 2 ? '#f1c40f' : '#2ecc71'));
        G.busFactor.data.labels = repos;
        G.busFactor.data.datasets[0].data = vals;
        G.busFactor.data.datasets[0].backgroundColor = colors;
        G.busFactor.update();
      }}
      const drift = (g.branch_drift || {{}}).by_repo || {{}};
      const el = document.getElementById('branchDriftTable');
      if (el && Object.keys(drift).length) {{
        let html = '<table class="table-wrap"><thead><tr><th>Repo</th><th>Base</th><th>Target</th><th>Missing</th></tr></thead><tbody>';
        for (const [r, d] of Object.entries(drift)) {{
          html += `<tr><td>${{r}}</td><td>${{d.base || ''}}</td><td>${{d.target || ''}}</td><td style="color:${{d.total_missing > 10 ? 'var(--red)' : 'inherit'}}">${{d.total_missing || 0}}</td></tr>`;
        }}
        html += '</tbody></table>';
        el.innerHTML = html;
      }} else if (el) el.innerHTML = '';
      const bdW = g.pr_cycle_breakdown_by_week || {{}};
      if (G.prBreakdown && !skip && Object.keys(bdW).length) {{
        const wks = Object.keys(bdW).sort();
        const fk = filterWeekKeys(wks, wks.map(() => 0));
        const labels = fk.keys;
        const prog = labels.map(w => bdW[w]?.avg_progress_hours || 0);
        const revB = labels.map(w => bdW[w]?.avg_review_hours || 0);
        const mrg = labels.map(w => bdW[w]?.avg_merge_hours || 0);
        G.prBreakdown.data.labels = labels;
        G.prBreakdown.data.datasets[0].data = prog;
        G.prBreakdown.data.datasets[1].data = revB;
        G.prBreakdown.data.datasets[2].data = mrg;
        G.prBreakdown.update();
      }} else if (G.prBreakdown) {{
        G.prBreakdown.data.labels = [];
        G.prBreakdown.data.datasets.forEach(ds => {{ ds.data = []; }});
        G.prBreakdown.update();
      }}
    }}

    function initCicdCharts() {{
      const y0 = {{ scales: {{ y: {{ beginAtZero: true }} }} }};
      const C = window._cicdCharts;
      if (document.getElementById('chartBuildTime')) {{
        C.buildTime = new Chart(document.getElementById('chartBuildTime'), {{
          type: 'line',
          data: {{ labels: [], datasets: [{{ label: 'Build Time (min)', data: [], borderColor: '#58a6ff', fill: false }}] }},
          options: y0,
        }});
      }}
      if (document.getElementById('chartDeployFreq')) {{
        C.deployFreq = new Chart(document.getElementById('chartDeployFreq'), {{
          type: 'bar',
          data: {{ labels: [], datasets: [{{ label: 'Deploys', data: [], backgroundColor: '#238636' }}] }},
          options: y0,
        }});
      }}
    }}

    function refreshCicdCharts() {{
      if (!CICD_DATA || !Object.keys(CICD_DATA).length) return;
      const C = window._cicdCharts;
      const btW = (CICD_DATA.builds || {{}}).build_time_trend_by_week || {{}};
      const btKeys = Object.keys(btW).sort();
      const btFv = filterWeekKeys(btKeys, btKeys.map(k => btW[k]));
      if (C.buildTime) {{
        C.buildTime.data.labels = btFv.keys;
        C.buildTime.data.datasets[0].data = btFv.values;
        C.buildTime.update();
      }}
      const dfW = (CICD_DATA.deployments || {{}}).deploy_frequency_per_week || {{}};
      const dfKeys = Object.keys(dfW).sort();
      const dfFv = filterWeekKeys(dfKeys, dfKeys.map(k => dfW[k]));
      if (C.deployFreq) {{
        C.deployFreq.data.labels = dfFv.keys;
        C.deployFreq.data.datasets[0].data = dfFv.values;
        C.deployFreq.update();
      }}
    }}

    // ========== NEW TABS: Git / CI-CD / DORA / Scorecard ==========
    (function populateExtraTabs() {{
      const colorMap = {{ 1:'#e74c3c', 2:'#e67e22', 3:'#f1c40f', 4:'#2ecc71', 5:'#27ae60' }};
      function mkCard(label, value, color) {{
        return `<div class="card"><div class="value" style="color:${{color||'var(--accent)'}}">${{value ?? 'N/A'}}</div><div class="label">${{label}}</div></div>`;
      }}

      renderGitRepoFilterBar();
      initGitCharts();
      initCicdCharts();

      // --- Git tab ---
      if (GIT_DATA && Object.keys(GIT_DATA).length) {{
        refreshGitTab();
      }}

      // --- CI/CD tab ---
      if (CICD_DATA && Object.keys(CICD_DATA).length) {{
        const cc = document.getElementById('cicdCards');
        if (cc) {{
          const b = CICD_DATA.builds || {{}};
          const d = CICD_DATA.deployments || {{}};
          const m = CICD_DATA.mttr || {{}};
          const cfr = CICD_DATA.change_failure_rate || {{}};
          cc.innerHTML =
            mkCard('Build Success', (b.success_rate||0)+'%', b.success_rate>=90?'#2ecc71':'#e74c3c') +
            mkCard('Avg Build Time', (b.avg_build_time_minutes||0).toFixed(1)+'m') +
            mkCard('Deploy Freq', d.deploy_frequency_category||'N/A') +
            mkCard('Deploys/wk', d.avg_deploys_per_week) +
            mkCard('MTTR p50', (m.p50_mttr_hours!=null?(m.p50_mttr_hours).toFixed(1)+'h':'N/A')) +
            mkCard('CFR', (cfr.cfr_pct||0)+'%', cfr.cfr_pct>15?'#e74c3c':'#2ecc71');
        }}
        refreshCicdCharts();
      }}

      // --- DORA tab (initial render; re-rendered on filter change via updateDORA) ---
      updateDORA(null);

      // --- Scorecard tab ---
      if (SCORECARD_DATA && Object.keys(SCORECARD_DATA).length) {{
        const sc = document.getElementById('scorecardCards');
        const domains = SCORECARD_DATA.domains || {{}};
        const domainLabels = {{ delivery_flow:'Delivery Flow', architecture_health:'Architecture', team_topology:'Team Topology', decision_making:'Decision-Making', tech_debt_sustainability:'Tech Debt' }};
        if (sc) {{
          let h = '';
          for (const [k,lbl] of Object.entries(domainLabels)) {{
            const d = domains[k] || {{}};
            const s = (d.manual_override||{{}}).score || d.score;
            h += mkCard(lbl, (s||'?')+'/5', colorMap[s]||'#888');
          }}
          h += mkCard('Overall', (SCORECARD_DATA.overall_score||'?')+'/5', colorMap[Math.round(SCORECARD_DATA.overall_score||0)]||'#888');
          sc.innerHTML = h;
        }}
        // Radar chart
        if (document.getElementById('chartScoreRadar')) {{
          const labels = Object.values(domainLabels);
          const vals = Object.keys(domainLabels).map(k => {{ const d = domains[k]||{{}}; return (d.manual_override||{{}}).score || d.score || 0; }});
          new Chart(document.getElementById('chartScoreRadar'), {{
            type: 'radar',
            data: {{ labels, datasets: [{{ label:'Score', data:vals, backgroundColor:'rgba(88,166,255,0.15)', borderColor:'#58a6ff', pointBackgroundColor:'#58a6ff' }}] }},
            options: {{ scales: {{ r: {{ min:0, max:5, ticks:{{ stepSize:1, color:'#8b949e' }}, grid:{{ color:'#30363d' }}, angleLines:{{ color:'#30363d' }}, pointLabels:{{ color:'#c9d1d9', font:{{ size:11 }} }} }} }} }}
          }});
        }}
        // Signal table
        const sigEl = document.getElementById('scorecardSignals');
        if (sigEl) {{
          let html = '';
          for (const [k,lbl] of Object.entries(domainLabels)) {{
            const d = domains[k] || {{}};
            html += `<h3>${{lbl}} — ${{(d.manual_override||{{}}).score||d.score||'?'}}/5</h3>`;
            if (d.needs_human_review) html += `<p style="color:#e67e22">Needs human review: ${{d.review_reason||''}}</p>`;
            html += '<table><thead><tr><th>Signal</th><th>Value</th><th>Score</th><th>Source</th></tr></thead><tbody>';
            for (const s of (d.signals||[])) {{
              const sc = s.score;
              const col = colorMap[sc] || '#888';
              html += `<tr><td>${{s.name}}</td><td>${{s.value!=null?s.value:'-'}} ${{s.unit||''}}</td><td style="color:${{col}};font-weight:bold">${{sc!=null?sc:'-'}}/5</td><td>${{s.source||''}}</td></tr>`;
            }}
            html += '</tbody></table>';
          }}
          sigEl.innerHTML = html;
        }}
      }}
    }})();
  </script>
</body>
</html>"""

    out_path = os.path.join(_output_dir(), "jira_dashboard.html")
    with open(out_path, "w", encoding="utf-8") as f:
        f.write(html_out)
    print(f"Written: {out_path}")
    return 0

if __name__ == "__main__":
    sys.exit(main() or 0)
