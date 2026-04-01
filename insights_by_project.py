#!/usr/bin/env python3
"""
Read jira_analytics_latest.json (or given path), split metrics by project,
and write by_project.json + INSIGHTS_AND_ACTIONS.md with next best actions.
"""
import json
import os
import sys
from collections import defaultdict
from datetime import datetime

def project_from_key(key):
    if not key or "-" not in key:
        return None
    return key.split("-", 1)[0]

def load_data(path=None):
    path = path or os.path.join(os.path.dirname(__file__), "jira_analytics_latest.json")
    with open(path, encoding="utf-8") as f:
        return json.load(f)

def build_by_project(data):
    projects = set(data.get("projects", []))
    by_project = {p: {"blocked": [], "oldest_bugs": [], "sprint_metrics": [], "kanban": None} for p in projects}

    # Blocked issues (key, age_days)
    for key, age in data.get("blocked_oldest", []):
        p = project_from_key(key)
        if p and p in by_project:
            by_project[p]["blocked"].append({"key": key, "age_days": age})

    # Oldest open bugs (already have project)
    for b in data.get("oldest_open_bugs", []):
        p = b.get("project")
        if p and p in by_project:
            by_project[p]["oldest_bugs"].append(b)

    # Sprint metrics
    for s in data.get("sprint_metrics", []):
        p = s.get("project")
        if p and p in by_project:
            by_project[p]["sprint_metrics"].append(s)

    # Kanban (one per project)
    for k in data.get("kanban_boards", []):
        p = k.get("project")
        if p and p in by_project:
            by_project[p]["kanban"] = k

    return by_project

def sprint_summary(metrics):
    if not metrics:
        return None
    total_done = sum(m.get("throughput_issues") or 0 for m in metrics)
    total_issues = sum(m.get("total_issues") or 0 for m in metrics)
    with_points = [m for m in metrics if (m.get("committed") or 0) > 0]
    avg_ratio = (sum(m.get("commitment_done_ratio") or 0 for m in with_points) / len(with_points)) if with_points else None
    assignee_counts = [m.get("assignee_count") for m in metrics if m.get("assignee_count") is not None]
    avg_assignees = round(sum(assignee_counts) / len(assignee_counts), 1) if assignee_counts else None
    added_late = [m.get("added_after_sprint_start") or 0 for m in metrics]
    total_added_after_start = sum(added_late)
    avg_added_after_start = round(sum(added_late) / len(added_late), 1) if added_late else None
    removed = [m.get("removed_during_sprint") for m in metrics if m.get("removed_during_sprint") is not None]
    total_removed_during_sprint = sum(removed) if removed else None
    return {
        "sprint_count": len(metrics),
        "total_throughput_done": total_done,
        "total_issues_in_sprints": total_issues,
        "avg_commitment_done_ratio": round(avg_ratio, 2) if avg_ratio is not None else None,
        "avg_assignee_count": avg_assignees,
        "total_added_after_sprint_start": total_added_after_start,
        "avg_added_after_sprint_start": avg_added_after_start,
        "total_removed_during_sprint": total_removed_during_sprint,
        "recent_sprints": metrics[-3:] if len(metrics) >= 3 else metrics,
    }

def write_by_project_json(by_project, out_path):
    out = {}
    for p, d in by_project.items():
        out[p] = {
            "blocked_count": len(d["blocked"]),
            "blocked_issues": d["blocked"],
            "oldest_bugs_count": len(d["oldest_bugs"]),
            "oldest_bugs": d["oldest_bugs"][:10],
            "sprint_summary": sprint_summary(d["sprint_metrics"]),
            "kanban": d["kanban"],
        }
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(out, f, indent=2, ensure_ascii=False)
    return out

def _load_extra_data(base_dir):
    """Try to load git/octopus/cicd/scorecard data alongside Jira."""
    extras = {}
    for name in ("git_analytics", "octopus_analytics", "cicd_analytics", "scorecard", "unified_evidence"):
        path = os.path.join(base_dir, f"{name}_latest.json")
        if os.path.isfile(path):
            try:
                with open(path, encoding="utf-8") as f:
                    extras[name] = json.load(f)
            except Exception:
                pass
    return extras

def generate_insights_md(data, by_project, out_path):
    run_ts = data.get("run_iso_ts", "")
    wip = data.get("wip_count", 0)
    wip_aging = data.get("wip_aging_days") or {}
    blocked_count = data.get("blocked_count", 0)
    open_bugs = data.get("open_bugs_count", 0)
    open_bugs_age = data.get("open_bugs_age_days") or {}
    throughput = data.get("throughput_by_week", {})
    last_weeks = sorted(throughput.keys())[-4:] if throughput else []
    recent_throughput = sum(throughput.get(w, 0) for w in last_weeks)

    releases = data.get("releases") or []
    releases_per_month = data.get("releases_per_month") or {}
    total_released_versions = data.get("total_released_versions", 0)
    try:
        ref_year = int(run_ts[:4]) if len(run_ts) >= 4 else datetime.now().year
        ref_month = int(run_ts[5:7]) if len(run_ts) >= 7 else datetime.now().month
    except (ValueError, TypeError):
        ref_year, ref_month = datetime.now().year, datetime.now().month
    releases_last_12 = 0
    for i in range(12):
        m, y = ref_month - i, ref_year
        while m < 1:
            m += 12
            y -= 1
        key = f"{y}-{m:02d}"
        releases_last_12 += releases_per_month.get(key, 0)

    base_dir = os.path.dirname(out_path) or os.path.dirname(__file__)
    extras = _load_extra_data(base_dir)
    git_data = extras.get("git_analytics", {})
    octopus_data = extras.get("octopus_analytics", {})
    cicd_data = extras.get("cicd_analytics", {})
    scorecard = extras.get("scorecard", {})
    evidence = extras.get("unified_evidence", {})
    dora = evidence.get("dora", {}) if evidence else {}

    lines = [
        "# Jira insights and next best actions",
        f"*Generated from run: {run_ts}*",
        "",
        "---",
        "## Overall snapshot",
        "",
        f"- **WIP (not done):** {wip} issues · median age **{wip_aging.get('p50_days', 0):.0f}** days",
        f"- **Blocked:** {blocked_count} issues",
        f"- **Open bugs:** {open_bugs} · median age **{open_bugs_age.get('p50_days', 0):.0f}** days",
        f"- **Throughput (last 4 weeks):** {recent_throughput} issues done",
        f"- **Released versions:** {total_released_versions} total; {releases_last_12} released in the last 12 months",
    ]

    # Git metrics in snapshot
    if git_data:
        prc = (git_data.get("pr_cycle_time") or {}).get("p50_days")
        review = (git_data.get("review_turnaround") or {}).get("p50_hours")
        merge_freq = (git_data.get("merge_frequency") or {}).get("avg_merges_per_week")
        min_bus = (git_data.get("contributors") or {}).get("min_bus_factor")
        if prc is not None:
            lines.append(f"- **PR cycle time (p50):** {prc:.1f} days")
        if review is not None:
            lines.append(f"- **Review turnaround (p50):** {review:.1f} hours")
        if merge_freq is not None:
            lines.append(f"- **Merge frequency:** {merge_freq:.1f}/week")
        if min_bus is not None:
            lines.append(f"- **Min bus factor:** {min_bus}")

    # DORA summary
    if dora:
        dora_cat = dora.get("overall_category", "N/A")
        df = dora.get("deployment_frequency", {})
        lt = dora.get("lead_time_for_changes", {})
        lines.append(f"- **DORA overall:** {dora_cat} | Deploy freq: {df.get('category', 'N/A')} | Lead time: {lt.get('category', 'N/A')}")

    # Octopus summary
    if octopus_data:
        pending = octopus_data.get("pending_changes", {})
        repos_behind = pending.get("total_pending_repos", 0)
        commits_behind = pending.get("total_pending_commits", 0)
        lines.append(f"- **Repos behind on deployment:** {repos_behind} ({commits_behind} pending commits)")

    lines.extend(["", "---", "## By project", ""])

    # Sort projects: those with blockers or oldest bugs first, then by sprint/kanban activity
    def sort_key(p):
        d = by_project.get(p, {})
        blocked = len(d.get("blocked", []))
        bugs = len(d.get("oldest_bugs", []))
        return (-blocked, -bugs, p)

    for p in sorted(by_project.keys(), key=sort_key):
        d = by_project[p]
        blocked = d.get("blocked", [])
        bugs = d.get("oldest_bugs", [])
        sprint_sum = sprint_summary(d.get("sprint_metrics", []))
        kanban = d.get("kanban")

        lines.append(f"### {p}")
        lines.append("")
        proj_lines = []

        if blocked:
            proj_lines.append(f"- **Blocked:** {len(blocked)} — " + ", ".join(f"{x['key']} ({x['age_days']:.0f}d)" for x in blocked[:5]))
        if bugs:
            proj_lines.append(f"- **Oldest open bugs (in top 15):** {len(bugs)} — e.g. {bugs[0]['key']} ({bugs[0]['age_days']:.0f} days)")
        if sprint_sum:
            s = sprint_sum
            proj_lines.append(f"- **Scrum (last {s['sprint_count']} sprints):** {s['total_throughput_done']} done; commitment ratio {s.get('avg_commitment_done_ratio') or 'N/A'}")
        if kanban:
            k = kanban
            proj_lines.append(f"- **Kanban:** {k.get('issue_count', 0)} on board, {k.get('done_count', 0)} done — {json.dumps(k.get('status_breakdown', {}))}")
        proj_releases = [r for r in releases if r.get("project") == p]
        if proj_releases:
            proj_released = sum(1 for r in proj_releases if r.get("released"))
            proj_lines.append(f"- **Versions:** {len(proj_releases)} total, {proj_released} released")

        if proj_lines:
            lines.extend(proj_lines)
        else:
            lines.append("- No board/sprint or bug data in this export.")
        lines.append("")

    lines.extend([
        "---",
        "## Next best actions",
        "",
        "### 1. Unblock and age (highest impact)",
        "",
    ])

    # Actions from blocked + oldest bugs
    if blocked_count or open_bugs:
        if blocked_count:
            lines.append(f"- **Unblock the {blocked_count} blocked issues.** Oldest: " + ", ".join(f"{k} ({a:.0f}d)" for k, a in data.get("blocked_oldest", [])[:3]) + ".")
        if open_bugs:
            top_bugs = data.get("oldest_open_bugs", [])[:5]
            median_bug_age = open_bugs_age.get("p50_days")
            age_text = f"; median age ~{median_bug_age:.0f} days" if median_bug_age is not None else ""
            lines.append(f"- **Triage or close oldest open bugs** ({open_bugs} open{age_text}). Top: " + ", ".join(b["key"] + " (" + str(round(b["age_days"])) + "d)" for b in top_bugs) + ".")
        lines.append("")
    else:
        lines.append("- No blocked issues or open bugs in scope.")
        lines.append("")

    lines.extend([
        "### 2. By project (priority order)",
        "",
    ])

    # Per-project actions
    for p in sorted(by_project.keys(), key=sort_key):
        d = by_project[p]
        blocked = d.get("blocked", [])
        bugs = d.get("oldest_bugs", [])
        kanban = d.get("kanban")
        sprint_sum = sprint_summary(d.get("sprint_metrics", []))

        actions = []
        if blocked:
            n = len(blocked)
            actions.append(f"Unblock {n} issue{'s' if n != 1 else ''} (e.g. {blocked[0]['key']})")
        if bugs:
            actions.append(f"Address oldest bugs ({bugs[0]['key']} – {bugs[0]['age_days']:.0f} days)")
        if kanban and (kanban.get("issue_count") or 0) > 0 and (kanban.get("done_count") or 0) < 10:
            actions.append(f"Kanban: only {kanban.get('done_count')} done on board – review flow and WIP limits")
        proj_metrics = (data.get("by_project") or {}).get(p, {})
        sp_history = (((proj_metrics.get("sp_trend") or {}).get("by_month")) or {})
        if sprint_sum and sprint_sum.get("sprint_count", 0) > 0 and not sp_history:
            actions.append("Scrum: no story point trend data in done work – consider enabling or standardizing story points on the board")

        if actions:
            lines.append(f"- **{p}:** " + "; ".join(actions) + ".")
        lines.append("")

    lines.extend([
        "### 3. Flow and WIP",
        "",
        f"- **WIP is aging** (median {wip_aging.get('p50_days', 0):.0f} days). Consider limiting WIP and finishing started work before pulling new items.",
        "- **Throughput last 4 weeks:** use weekly trend to spot drops and align capacity.",
        "",
        "### 4. Releases and versions",
        "",
    ])

    # Release-related next best actions
    released_with_date = [r for r in releases if r.get("released") and r.get("release_date")]
    latest_release_date = None
    if released_with_date:
        dates = sorted(r.get("release_date") for r in released_with_date if r.get("release_date"))
        if dates:
            latest_release_date = dates[-1]
    no_release_90_days = False
    if latest_release_date:
        try:
            latest = datetime.strptime(latest_release_date[:10], "%Y-%m-%d")
            now = datetime.now()
            no_release_90_days = (now - latest).days > 90
        except (ValueError, TypeError):
            pass
    unreleased_count = len(releases) - total_released_versions

    if no_release_90_days:
        lines.append("- **No release in the last 90 days.** Consider scheduling a release or cleaning up unreleased versions.")
    if unreleased_count > 10:
        lines.append(f"- **Many unreleased versions ({unreleased_count}).** Review and either release or archive.")
    lines.append("- **Releases per month:** consider keeping a steady cadence where possible.")
    lines.append("")

    # Git / DORA / Octopus next best actions
    if git_data or dora or octopus_data:
        lines.extend(["### 5. Git, CI/CD, and Deployment", ""])

    if git_data:
        min_bus = (git_data.get("contributors") or {}).get("min_bus_factor")
        if min_bus is not None and min_bus <= 1:
            bus_repos = {r: v for r, v in (git_data.get("contributors") or {}).get("bus_factor_by_repo", {}).items() if v <= 1}
            lines.append(f"- **Bus factor = 1** in {len(bus_repos)} repo(s): {', '.join(list(bus_repos.keys())[:5])}. Cross-train and pair to reduce key-person risk.")

        drift = git_data.get("branch_drift", {})
        if drift.get("total_missing_across_repos", 0) > 10:
            lines.append(f"- **Branch drift:** {drift['total_missing_across_repos']} commits missing across repos. Reconcile branches to reduce release risk.")

        weekend = (git_data.get("work_patterns") or {}).get("weekend_commit_pct")
        if weekend and weekend > 15:
            lines.append(f"- **Weekend commits at {weekend:.0f}%** — potential burnout signal. Review workload distribution.")

    if octopus_data:
        pending = octopus_data.get("pending_changes", {}).get("by_repo", {})
        behind = [(r, d) for r, d in pending.items() if d.get("status") == "pending"]
        if behind:
            top = sorted(behind, key=lambda x: -x[1].get("pending_count", 0))[:3]
            lines.append("- **Pending releases:** " + "; ".join(f"{r} ({d['pending_count']} commits)" for r, d in top) + ". Deploy or schedule these releases.")

    if dora:
        if dora.get("overall_category") in ("low", "medium"):
            lines.append(f"- **DORA category is {dora['overall_category']}.** Focus on reducing lead time and increasing deployment frequency for higher delivery maturity.")

    if git_data or dora or octopus_data:
        lines.append("")

    lines.extend([
        "---",
        "*Re-run `./run_jira_analytics.ps1` and this script to refresh. Use `@jira_analytics_latest.json` or `@by_project.json` in Cursor for follow-up questions.*",
        "",
    ])

    with open(out_path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))

def main():
    src = sys.argv[1] if len(sys.argv) > 1 else None
    output_dir = os.environ.get("OUTPUT_DIR") or os.path.dirname(os.path.abspath(__file__))
    if src is None:
        candidate = os.path.join(output_dir, "jira_analytics_latest.json")
        if os.path.isfile(candidate):
            src = candidate
    data = load_data(src)
    by_project = build_by_project(data)
    write_by_project_json(by_project, os.path.join(output_dir, "by_project.json"))
    generate_insights_md(data, by_project, os.path.join(output_dir, "INSIGHTS_AND_ACTIONS.md"))
    print("Wrote by_project.json and INSIGHTS_AND_ACTIONS.md")

if __name__ == "__main__":
    main()
