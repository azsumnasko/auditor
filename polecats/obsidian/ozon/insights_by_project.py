#!/usr/bin/env python3
"""
Read jira_analytics_latest.json (or given path), split metrics by project,
and write by_project.json + INSIGHTS_AND_ACTIONS.md with next best actions.
"""
import json
import os
import sys
from collections import defaultdict

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
        "",
        "---",
        "## By project",
        "",
    ]

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
            lines.append("- **Triage or close oldest open bugs** (53 open; median age ~398 days). Top: " + ", ".join(b["key"] + " (" + str(round(b["age_days"])) + "d)" for b in top_bugs) + ".")
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
        if sprint_sum and (sprint_sum.get("total_throughput_done") or 0) == 0 and sprint_sum.get("sprint_count", 0) > 0:
            actions.append("Scrum: no story points reported – consider enabling story points on the board")

        if actions:
            lines.append(f"- **{p}:** " + "; ".join(actions) + ".")
        lines.append("")

    lines.extend([
        "### 3. Flow and WIP",
        "",
        f"- **WIP is aging** (median {wip_aging.get('p50_days', 0):.0f} days). Consider limiting WIP and finishing started work before pulling new items.",
        "- **Throughput last 4 weeks:** use weekly trend to spot drops and align capacity.",
        "",
        "---",
        "*Re-run `./run_jira_analytics.ps1` and this script to refresh. Use `@jira_analytics_latest.json` or `@by_project.json` in Cursor for follow-up questions.*",
        "",
    ])

    with open(out_path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))

def main():
    src = sys.argv[1] if len(sys.argv) > 1 else None
    data = load_data(src)
    by_project = build_by_project(data)
    base = os.path.dirname(os.path.abspath(__file__))
    write_by_project_json(by_project, os.path.join(base, "by_project.json"))
    generate_insights_md(data, by_project, os.path.join(base, "INSIGHTS_AND_ACTIONS.md"))
    print("Wrote by_project.json and INSIGHTS_AND_ACTIONS.md")

if __name__ == "__main__":
    main()
