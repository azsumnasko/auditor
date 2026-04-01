#!/usr/bin/env python3
"""
generate_report.py -- Produce an executive report in Markdown.

Reads ``unified_evidence.json`` + ``scorecard.json`` and generates
``executive_report.md`` following the 11-slide template from
mds/5 EXECUTIVE REPORT TEMPLATE.
"""

import os
import logging
from datetime import datetime, timezone

from analytics_utils import load_env, read_json

log = logging.getLogger(__name__)


def _safe(data, *keys, default="N/A"):
    for k in keys:
        if not isinstance(data, dict):
            return default
        data = data.get(k)
        if data is None:
            return default
    return data


def _fmt(val, suffix=""):
    if val is None or val == "N/A":
        return "N/A"
    if isinstance(val, float):
        return f"{val:.1f}{suffix}"
    return f"{val}{suffix}"


def generate_report(evidence, scorecard):
    domains = scorecard.get("domains", {})
    completeness = scorecard.get("data_completeness", {})
    overall = scorecard.get("overall_score", "N/A")
    jira = evidence.get("jira") or {}
    git = evidence.get("git") or {}
    octopus = evidence.get("octopus") or {}
    dora = evidence.get("dora") or {}
    pending_risk = evidence.get("pending_risk") or {}
    release_health = evidence.get("release_health") or {}
    run_ts = evidence.get("run_iso_ts", "")
    pipeline_warnings = evidence.get("pipeline_warnings") or []

    # Helpers for domain data
    def _domain_score(key):
        d = domains.get(key, {})
        s = d.get("score", "?")
        if d.get("manual_override"):
            s = d["manual_override"].get("score", s)
        return s

    # Build report sections
    sections = []

    # Slide 1: Executive Summary
    lead_time = _safe(jira, "lead_time_days", "p50_days")
    pr_cycle = _safe(git, "pr_cycle_time", "p50_days")
    deploy_freq_cat = _safe(dora, "deployment_frequency", "category")
    repos_behind = _safe(pending_risk, "total_repos_behind", default=0)

    notes_line = ""
    if pipeline_warnings:
        notes_line = "\n- **Note:** Some optional data sources did not complete; see *Data collection notes* in the appendix.\n"

    sections.append(f"""# Engineering Delivery & Organization Audit -- Executive Summary

**Overall Maturity Score: {overall}/5**

- Lead time (Jira) p50: **{_fmt(lead_time, "d")}**, PR cycle time p50: **{_fmt(pr_cycle, "d")}**
- Deployment frequency: **{deploy_freq_cat}** | DORA overall: **{dora.get('overall_category', 'N/A')}**
- Repos with pending unreleased changes: **{repos_behind}**
- Branch drift across repos: **{_safe(release_health, 'branch_drift_total', default=0)}** missing commits
- Data sources: {', '.join(k for k, v in completeness.items() if v)}{notes_line}""")

    # Slide 2: Context & Scope
    repos_analyzed = _safe(git, "repos_analyzed", default=[])
    n_repos = len(repos_analyzed) if isinstance(repos_analyzed, list) else 0
    lookback = _safe(git, "lookback_days", default=180)
    projects = _safe(jira, "projects", default=[])
    n_projects = len(projects) if isinstance(projects, list) else 0

    sections.append(f"""---

# Context & Scope

| Item | Value |
|------|-------|
| Git repos analyzed | {n_repos} |
| Jira projects | {n_projects} |
| Lookback window | {lookback} days |
| Analysis date | {run_ts} |
| Sources | {', '.join(k for k, v in completeness.items() if v)} |
""")

    # Slide 3: Overall Scorecard
    score_rows = ""
    domain_labels = {
        "delivery_flow": "Delivery Flow",
        "architecture_health": "Architecture & Tech Health",
        "team_topology": "Team Topology & Org Model",
        "decision_making": "Decision-Making & Governance",
        "tech_debt_sustainability": "Tech Debt & Sustainability",
    }
    for key, label in domain_labels.items():
        s = _domain_score(key)
        score_rows += f"| {label} | {s}/5 |\n"

    sections.append(f"""---

# Overall Scorecard

| Domain | Score |
|--------|-------|
{score_rows}
Scores are based on automated metrics and quantitative evidence. Domains marked as needing human review require interview validation.
""")

    # Slide 4: Delivery Flow Findings
    unplanned = _safe(jira, "sprint_metrics", "avg_added_after_start_pct")
    commitment = _safe(jira, "sprint_metrics", "avg_commitment_ratio_pct")
    merge_trend = _safe(git, "merge_frequency", "trend")
    commit_to_prod = _safe(octopus, "commit_to_prod_lead_time", "p50_days")

    sections.append(f"""---

# Delivery Flow Findings

**What we see:**
- Lead time (idea to done) p50: {_fmt(lead_time, " days")}
- PR cycle time p50: {_fmt(pr_cycle, " days")}
- Commit-to-production lead time p50: {_fmt(commit_to_prod, " days")}
- Merge frequency trend: {merge_trend}
- Unplanned work ratio: {_fmt(unplanned, "%")}
- Sprint commitment ratio: {_fmt(commitment, "%")}

**Why it matters:**
- Low predictability if lead time is high
- High context switching if unplanned work exceeds 30%

**Evidence:** Jira analytics, Git PR history, Octopus Deploy records
""")

    # Slide 5: Architecture Findings
    min_bus = _safe(git, "contributors", "min_bus_factor")
    avg_files = _safe(git, "pr_size", "avg_files_changed")
    branch_drift_total = _safe(git, "branch_drift", "total_missing_across_repos")
    coverage = _safe(evidence, "code", "test_coverage", "overall_coverage_pct")

    sections.append(f"""---

# Architecture & Technical Health Findings

**What we see:**
- Minimum bus factor: {_fmt(min_bus)} (across repos)
- Average files changed per PR: {_fmt(avg_files)}
- Branch drift: {_fmt(branch_drift_total)} commits behind across repos
- Test coverage: {_fmt(coverage, "%")}

**Risks:**
- Single points of failure (bus factor = 1)
- Scaling pain from high coupling
- Regression risk from branch drift
""")

    # Slide 6: Org & Operating Model
    gini = _safe(jira, "workload_gini")
    closer_ne = _safe(jira, "closer_not_assignee_pct")

    sections.append(f"""---

# Org & Operating Model

**Current state:**
- Workload concentration (Gini): {_fmt(gini)}
- Work finished by someone else: {_fmt(closer_ne, "%")}
- Contributor Gini: {_safe(git, "contributors", "contributor_gini")}

**Impact:**
- Decision bottleneck if Gini is high
- Knowledge silos and bus factor risk
""")

    # Slide 7: Root Causes
    low_domains = [(k, v) for k, v in domains.items() if v.get("score") is not None and v["score"] <= 2]
    symptoms = []
    root_causes = []
    for key, d in low_domains:
        for sig in d.get("signals", []):
            if sig.get("score") is not None and sig["score"] <= 2:
                symptoms.append(f"{sig['name']} = {sig.get('value')} ({sig.get('unit','')})")
    if _safe(pending_risk, "total_repos_behind", default=0) > 2:
        root_causes.append("Repos behind on deployments suggest release coupling or operational lag")
    if _safe(git, "contributors", "min_bus_factor") == 1:
        root_causes.append("Single-person knowledge silos create dependency bottlenecks")
    if _safe(git, "branch_drift", "total_missing_across_repos", default=0) > 10:
        root_causes.append("Branch drift indicates incomplete release processes")

    sections.append(f"""---

# Root Causes

**Symptoms:**
{chr(10).join('- ' + s for s in symptoms[:8]) or '- No critical symptoms detected'}

**Root causes:**
{chr(10).join('- ' + r for r in root_causes[:5]) or '- Further investigation needed'}

**Result:**
- Reduced delivery predictability and increased operational risk
""")

    # Slide 8: Top 5 Recommendations
    recs = []
    for key, d in domains.items():
        for sig in d.get("signals", []):
            if sig.get("score") is not None and sig["score"] <= 2:
                recs.append((sig["name"], sig.get("score", 0), key))
    recs.sort(key=lambda x: x[1])
    rec_table = "| Recommendation | Impact | Domain |\n|---|---|---|\n"
    for name, score, domain in recs[:5]:
        rec_table += f"| Improve {name.replace('_',' ')} | High | {domain_labels.get(domain, domain)} |\n"

    sections.append(f"""---

# Top 5 Recommendations

{rec_table}
""")

    # Slide 9: 30/60/90 Day Plan
    sections.append(f"""---

# 30 / 60 / 90 Day Plan

**0-30 days:**
- Set PR size limits and review SLAs
- Map code ownership across all repos
- Establish release checklist

**31-60 days:**
- Address bus factor risks in critical repos
- Reduce branch drift to < 10 commits
- Deploy pending releases to close version gaps

**61-90 days:**
- Enable independent releases per service
- Implement metrics-driven planning cadence
- Establish governance framework for architectural decisions
""")

    # Slide 10: Success Metrics
    sections.append(f"""---

# What Success Looks Like

| Metric | Current | Target (90d) |
|--------|---------|-------------|
| Lead time p50 | {_fmt(lead_time, "d")} | < 3 days |
| PR cycle time p50 | {_fmt(pr_cycle, "d")} | < 1 day |
| Deployment frequency | {deploy_freq_cat} | Daily |
| Repos behind on deployment | {repos_behind} | 0-1 |
| Branch drift | {_fmt(branch_drift_total)} commits | < 10 |
| Min bus factor | {_fmt(min_bus)} | >= 3 |
""")

    # Slide 11: Next Steps
    sections.append(f"""---

# Next Steps

1. **Self-implementation:** Use this report and the generated scorecard as a roadmap
2. **Guided enablement (8-12 weeks):** Structured coaching with progress tracking against target metrics

The goal is faster and more predictable delivery, not more process.
""")

    warn_block = ""
    if pipeline_warnings:
        bullets = "\n".join(f"  - {w}" for w in pipeline_warnings)
        warn_block = f"""---

# Data collection notes

The following optional integrations were skipped or failed; the report reflects all data that was collected successfully.

{bullets}

"""

    # Appendix
    sections.append(f"""{warn_block}---

# Appendix -- Evidence Summary

- **Jira:** {'Available' if completeness.get('jira') else 'Not available'}
- **Git:** {'Available' if completeness.get('git') else 'Not available'}
- **Octopus Deploy:** {'Available' if completeness.get('octopus') else 'Not available'}
- **CI/CD:** {'Available' if completeness.get('cicd') else 'Not available'}
- **Code Analysis:** {'Available' if completeness.get('code') else 'Not available'}
- **Interviews:** {'Available' if completeness.get('interviews') else 'Not yet collected'}

Full metric dumps available in the respective ``*_latest.json`` files.
""")

    return "\n".join(sections)


# ---------------------------------------------------------------------------
# main()
# ---------------------------------------------------------------------------

def main():
    load_env()
    output_dir = os.environ.get("OUTPUT_DIR") or os.path.dirname(__file__) or "."

    evidence = read_json("unified_evidence", output_dir)
    scorecard = read_json("scorecard", output_dir)

    if not evidence or not scorecard:
        print("[generate_report] unified_evidence.json or scorecard.json not found, skipping.")
        return

    md = generate_report(evidence, scorecard)
    path = os.path.join(output_dir, "executive_report.md")
    with open(path, "w", encoding="utf-8") as f:
        f.write(md)
    print(f"[generate_report] Wrote {path}")


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    main()
