"""
merge_evidence.py -- Cross-reference and enrich all collector outputs.

Reads all ``*_latest.json`` files, cross-references Jira issues to PRs,
links PRs to Octopus deployments, computes true end-to-end lead time,
DORA four keys, version-based lead time, pending release risk, and
team health composite.

Outputs ``unified_evidence.json``.
"""

import os
import re
import logging
from datetime import datetime, timezone
from collections import defaultdict

from analytics_utils import (
    load_env,
    parse_dt,
    iso_week,
    percentile,
    summarize_time_metrics,
    extract_jira_keys,
    write_json,
    read_json,
)

log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Cross-reference: Jira issue -> PR mapping
# ---------------------------------------------------------------------------

def _build_issue_to_prs(git_data):
    """
    Parse PR titles and commit messages for Jira issue keys.
    Port of regex pattern from compare_latest_vs_prod.ps1.
    """
    issue_to_prs = defaultdict(list)
    if not git_data:
        return dict(issue_to_prs)

    by_repo = git_data.get("by_repo", {})
    org = git_data.get("org", "")

    for repo_name, repo_data in by_repo.items():
        for pr in repo_data.get("pr_cycle_time", {}).get("details", []):
            title = pr.get("title") or pr.get("subject") or ""
            keys = extract_jira_keys(title)
            for k in keys:
                issue_to_prs[k].append({"repo": repo_name, "pr": pr.get("number"), "source": "pr_title"})

    return dict(issue_to_prs)


def _build_issue_to_prs_from_commits(git_data):
    """Scan commit counts/branch_drift data for Jira keys."""
    issue_to_prs = defaultdict(list)
    if not git_data:
        return dict(issue_to_prs)

    drift = git_data.get("branch_drift", {}).get("by_repo", {})
    for repo_name, drift_data in drift.items():
        for c in drift_data.get("missing_commits", []):
            keys = extract_jira_keys(c.get("subject", ""))
            for k in keys:
                issue_to_prs[k].append({"repo": repo_name, "sha": c.get("sha"), "source": "branch_drift"})

    return dict(issue_to_prs)


# ---------------------------------------------------------------------------
# Version-based lead time (port from jira_release_leadtime_report.ps1)
# ---------------------------------------------------------------------------

def _version_lead_times(jira_data):
    """
    Compute days from issue creation to version release date.
    Uses Jira 'releases' data if available.
    """
    releases = jira_data.get("releases", []) if jira_data else []
    results = []

    for rel in releases:
        if not rel.get("released") or not rel.get("release_date"):
            continue
        release_dt = parse_dt(rel["release_date"])
        if not release_dt:
            continue
        results.append({
            "project": rel.get("project", ""),
            "version": rel.get("name", ""),
            "release_date": rel["release_date"],
        })

    return results


# ---------------------------------------------------------------------------
# DORA four keys
# ---------------------------------------------------------------------------

DORA_BENCHMARKS = {
    "deployment_frequency": {
        "elite": {"label": "Multiple/day", "min_per_week": 5},
        "high": {"label": "Daily-Weekly", "min_per_week": 1},
        "medium": {"label": "Weekly-Monthly", "min_per_week": 0.25},
        "low": {"label": "Monthly+", "min_per_week": 0},
    },
    "lead_time": {
        "elite": {"label": "<1 day", "max_days": 1},
        "high": {"label": "1d-1wk", "max_days": 7},
        "medium": {"label": "1wk-1mo", "max_days": 30},
        "low": {"label": ">1 month", "max_days": 999},
    },
    "change_failure_rate": {
        "elite": {"label": "<5%", "max_pct": 5},
        "high": {"label": "5-10%", "max_pct": 10},
        "medium": {"label": "10-15%", "max_pct": 15},
        "low": {"label": ">15%", "max_pct": 100},
    },
    "mttr": {
        "elite": {"label": "<1 hour", "max_hours": 1},
        "high": {"label": "<1 day", "max_hours": 24},
        "medium": {"label": "<1 week", "max_hours": 168},
        "low": {"label": ">1 week", "max_hours": 9999},
    },
}


def _categorize_dora_metric(metric_type, value):
    benchmarks = DORA_BENCHMARKS.get(metric_type, {})
    if metric_type == "deployment_frequency":
        for cat in ("elite", "high", "medium"):
            if value >= benchmarks[cat]["min_per_week"]:
                return cat
        return "low"
    elif metric_type in ("lead_time", "change_failure_rate", "mttr"):
        key = "max_days" if metric_type == "lead_time" else ("max_pct" if metric_type == "change_failure_rate" else "max_hours")
        for cat in ("elite", "high", "medium"):
            if value <= benchmarks[cat][key]:
                return cat
        return "low"
    return "unknown"


def compute_dora(octopus_data, cicd_data, jira_data, git_data):
    """
    Compute DORA four keys with Octopus as primary source, CI/CD as fallback.
    """
    dora = {}

    # Deployment Frequency
    df_value = None
    df_source = None
    if octopus_data:
        freq = octopus_data.get("deployment_frequency", {})
        df_value = freq.get("overall_avg_per_week")
        df_source = "octopus"
    if df_value is None and cicd_data:
        deploys = cicd_data.get("deployments", {})
        df_value = deploys.get("avg_deploys_per_week")
        df_source = "cicd"

    if df_value is not None:
        dora["deployment_frequency"] = {
            "value": df_value,
            "category": _categorize_dora_metric("deployment_frequency", df_value),
            "source": df_source,
        }

    # Lead Time for Changes
    lt_value = None
    lt_source = None
    if octopus_data:
        lt = octopus_data.get("commit_to_prod_lead_time", {})
        lt_value = lt.get("p50_days")
        lt_source = "octopus_commit_to_prod"
    if lt_value is None and jira_data:
        lt_value = jira_data.get("lead_time_days", {}).get("p50_days")
        lt_source = "jira_to_resolved"

    if lt_value is not None:
        dora["lead_time_for_changes"] = {
            "value_days": lt_value,
            "category": _categorize_dora_metric("lead_time", lt_value),
            "source": lt_source,
        }

    # Change Failure Rate
    cfr_value = None
    cfr_source = None
    if cicd_data:
        cfr = cicd_data.get("change_failure_rate", {})
        cfr_value = cfr.get("cfr_pct")
        cfr_source = "cicd"
    if cfr_value is None and jira_data:
        total = jira_data.get("throughput_total", 0)
        cfr_count = jira_data.get("cfr_failures_count", 0)
        if total:
            cfr_value = round(cfr_count / total * 100, 1)
            cfr_source = "jira_proxy"

    if cfr_value is not None:
        dora["change_failure_rate"] = {
            "value_pct": cfr_value,
            "category": _categorize_dora_metric("change_failure_rate", cfr_value),
            "source": cfr_source,
        }

    # MTTR
    mttr_value = None
    mttr_source = None
    if cicd_data:
        mttr = cicd_data.get("mttr", {})
        mttr_value = mttr.get("p50_mttr_hours")
        mttr_source = "cicd"

    if mttr_value is not None:
        dora["mttr"] = {
            "value_hours": mttr_value,
            "category": _categorize_dora_metric("mttr", mttr_value),
            "source": mttr_source,
        }

    categories = [v.get("category") for v in dora.values() if v.get("category")]
    rank_map = {"elite": 4, "high": 3, "medium": 2, "low": 1}
    if categories:
        avg_rank = sum(rank_map.get(c, 1) for c in categories) / len(categories)
        overall = "low"
        if avg_rank >= 3.5:
            overall = "elite"
        elif avg_rank >= 2.5:
            overall = "high"
        elif avg_rank >= 1.5:
            overall = "medium"
        dora["overall_category"] = overall

    dora["benchmark_comparison"] = DORA_BENCHMARKS
    return dora


# ---------------------------------------------------------------------------
# Pending release risk
# ---------------------------------------------------------------------------

def _pending_risk(octopus_data, jira_data):
    if not octopus_data:
        return {}

    pending = octopus_data.get("pending_changes", {})
    by_repo = pending.get("by_repo", {})
    repos_behind = [(r, d) for r, d in by_repo.items() if d.get("status") == "pending"]

    all_jira_keys = set()
    for _, d in repos_behind:
        all_jira_keys.update(d.get("jira_keys", []))

    return {
        "total_repos_behind": len(repos_behind),
        "critical_jira_keys_pending": sorted(all_jira_keys)[:30],
        "repos_with_most_pending": sorted(
            [{"repo": r, "pending_count": d.get("pending_count", 0)} for r, d in repos_behind],
            key=lambda x: -x["pending_count"],
        )[:10],
    }


# ---------------------------------------------------------------------------
# Release health
# ---------------------------------------------------------------------------

def _release_health(octopus_data, git_data):
    result = {"repos_up_to_date": 0, "repos_behind": 0, "branch_drift_total": 0, "avg_pending_days": 0}

    if octopus_data:
        pending = octopus_data.get("pending_changes", {}).get("by_repo", {})
        result["repos_up_to_date"] = sum(1 for d in pending.values() if d.get("status") == "ok")
        result["repos_behind"] = sum(1 for d in pending.values() if d.get("status") == "pending")

    if git_data:
        drift = git_data.get("branch_drift", {})
        result["branch_drift_total"] = drift.get("total_missing_across_repos", 0)

    return result


# ---------------------------------------------------------------------------
# main()
# ---------------------------------------------------------------------------

def main():
    load_env()
    output_dir = os.environ.get("OUTPUT_DIR")

    jira_data = read_json("jira_analytics", output_dir)
    git_data = read_json("git_analytics", output_dir)
    octopus_data = read_json("octopus_analytics", output_dir)
    cicd_data = read_json("cicd_analytics", output_dir)
    code_data = read_json("code_analytics", output_dir)

    pipeline_warnings: list = []
    pw_raw = read_json("pipeline_warnings", output_dir)
    if isinstance(pw_raw, dict):
        pipeline_warnings = pw_raw.get("warnings") or []
    elif isinstance(pw_raw, list):
        pipeline_warnings = pw_raw

    sources = {
        "jira": jira_data is not None,
        "git": git_data is not None,
        "octopus": octopus_data is not None,
        "cicd": cicd_data is not None,
        "code": code_data is not None,
    }

    print(f"[merge_evidence] Sources available: {', '.join(k for k, v in sources.items() if v)}")

    # Cross-references
    issue_to_prs = _build_issue_to_prs(git_data)
    issue_to_prs_commits = _build_issue_to_prs_from_commits(git_data)
    for k, v in issue_to_prs_commits.items():
        issue_to_prs.setdefault(k, []).extend(v)

    # DORA
    dora = compute_dora(octopus_data, cicd_data, jira_data, git_data)

    # Version lead times
    version_lts = _version_lead_times(jira_data)

    # Pending risk
    pending_risk = _pending_risk(octopus_data, jira_data)

    # Release health
    release_health = _release_health(octopus_data, git_data)

    # True lead time from Octopus (already computed in octopus_analytics)
    true_lead_time = {}
    if octopus_data:
        true_lead_time = octopus_data.get("commit_to_prod_lead_time", {})

    results = {
        "run_iso_ts": datetime.now(timezone.utc).isoformat(),
        "sources": sources,
        "pipeline_warnings": pipeline_warnings,
        "jira": jira_data,
        "git": git_data,
        "octopus": octopus_data,
        "cicd": cicd_data,
        "code": code_data,
        "cross_reference": {
            "issue_to_prs": dict(list(issue_to_prs.items())[:200]),
            "true_lead_time": true_lead_time,
            "version_lead_times": version_lts,
        },
        "pending_risk": pending_risk,
        "dora": dora,
        "release_health": release_health,
        "team_health": {},
    }

    path = write_json(results, "unified_evidence", output_dir)
    print(f"[merge_evidence] Wrote {path}")
    print(f"  DORA overall: {dora.get('overall_category', 'N/A')}")
    print(f"  Repos behind: {pending_risk.get('total_repos_behind', 0)}")

    return results


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    main()
