"""
score_engine.py -- Automated maturity scorecard engine.

Implements the 5-domain scoring model from mds/3 SCORECARD.md with exact
thresholds from mds/4 METRICS.md.  Each domain scores 1-5 with signal-level
evidence.  Levels 2 and 4 are interpolated.

Reads ``unified_evidence.json``, writes ``scorecard.json``.
"""

import math
import os
import logging
from datetime import datetime, timezone

from analytics_utils import load_env, read_json, write_json

log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Generic signal scoring
# ---------------------------------------------------------------------------

def _score_lower_is_better(value, s1_above, s3_above, _unused=None, s5_at_or_below=None):
    """Score where lower values are better.

    Defines three primary bands (1, 3, 5) with 2 and 4 auto-interpolated.
    - value > s1_above            -> 1
    - midpoint(s3, s1) < value    -> 2  (interpolated)
    - s3_above < value            -> 3
    - s5_at_or_below < value      -> 4  (interpolated)
    - value <= s5_at_or_below     -> 5

    For backward compat, the 3rd arg (_unused / old s3_max) is ignored;
    the 4th arg is s5_at_or_below (old s5_max).
    """
    if s5_at_or_below is None:
        s5_at_or_below = _unused if _unused is not None else s3_above
    if value is None:
        return None
    if value > s1_above:
        return 1
    mid_high = (s1_above + s3_above) / 2
    if value > mid_high:
        return 2
    if value > s3_above:
        return 3
    if value > s5_at_or_below:
        return 4
    return 5


def _score_higher_is_better(value, s1_below, s3_min, s3_max, s5_above):
    """Score where higher values are better.

    - value < s1_below                 -> 1
    - value < mid(s1_below, s3_max)    -> 2  (interpolated)
    - value <= s3_max                  -> 3
    - value < mid(s3_max, s5_above)    -> 4  (interpolated)
    - value >= s5_above                -> 5
    """
    if value is None:
        return None
    if value < s1_below:
        return 1
    mid_low = (s1_below + s3_max) / 2
    if value < mid_low:
        return 2
    if value <= s3_max:
        return 3
    mid_high = (s3_max + s5_above) / 2
    if value < mid_high:
        return 4
    return 5


def _score_categorical(value, mapping):
    """Score from a categorical mapping {value: score}."""
    if value is None:
        return None
    return mapping.get(value, mapping.get("default"))


def _safe_get(data, *keys, default=None):
    """Safely traverse nested dicts."""
    for k in keys:
        if not isinstance(data, dict):
            return default
        data = data.get(k, default)
    return data


# ---------------------------------------------------------------------------
# Domain 1: Delivery Flow
# ---------------------------------------------------------------------------

def _score_delivery_flow(evidence):
    jira = evidence.get("jira") or {}
    git = evidence.get("git") or {}
    octopus = evidence.get("octopus") or {}
    dora = evidence.get("dora") or {}

    signals = []

    # Lead time (p50 days) - Jira
    val = _safe_get(jira, "lead_time_days", "p50_days")
    s = _score_lower_is_better(val, 14, 7, 14, 3)
    signals.append({"name": "lead_time_p50", "value": val, "unit": "days", "score": s,
                     "threshold_ref": ">14=1, 7-14=3, <3=5", "source": "jira"})

    # PR cycle time (p50 days)
    val = _safe_get(git, "pr_cycle_time", "p50_days")
    s = _score_lower_is_better(val, 3, 1, 3, 1)
    signals.append({"name": "pr_cycle_time_p50", "value": val, "unit": "days", "score": s,
                     "threshold_ref": ">3=1, 1-3=3, <1=5", "source": "git"})

    # Deployment frequency
    val = _safe_get(dora, "deployment_frequency", "value")
    freq_cat = _safe_get(dora, "deployment_frequency", "category")
    s = _score_categorical(freq_cat, {"on_demand": 5, "daily": 5, "weekly": 3, "monthly": 1, "low": 1, "default": 2})
    signals.append({"name": "deployment_frequency", "value": val, "unit": "per_week", "score": s,
                     "threshold_ref": "monthly=1, weekly=3, daily/on-demand=5",
                     "source": _safe_get(dora, "deployment_frequency", "source") or "unknown"})

    # Commit-to-prod lead time (Octopus)
    val = _safe_get(octopus, "commit_to_prod_lead_time", "p50_days")
    s = _score_lower_is_better(val, 14, 3, 14, 3)
    signals.append({"name": "commit_to_prod_lead_time", "value": val, "unit": "days", "score": s,
                     "threshold_ref": ">14=1, 3-14=3, <3=5", "source": "octopus"})

    # Unplanned work ratio
    val = _safe_get(jira, "sprint_aggregate", "avg_added_after_start_pct")
    s = _score_lower_is_better(val, 30, 15, 30, 15)
    signals.append({"name": "unplanned_work_ratio", "value": val, "unit": "pct", "score": s,
                     "threshold_ref": ">30%=1, 15-30%=3, <15%=5", "source": "jira"})

    # Sprint commitment ratio
    val = _safe_get(jira, "sprint_aggregate", "avg_commitment_ratio_pct")
    s = _score_higher_is_better(val, 60, 60, 85, 85)
    signals.append({"name": "sprint_commitment_ratio", "value": val, "unit": "pct", "score": s,
                     "threshold_ref": "<60%=1, 60-85%=3, >85%=5", "source": "jira"})

    # Throughput trend
    val = _safe_get(git, "merge_frequency", "trend")
    s = _score_categorical(val, {"decreasing": 1, "declining": 1, "stable": 3, "increasing": 5, "default": 3})
    signals.append({"name": "throughput_trend", "value": val, "unit": "trend", "score": s,
                     "threshold_ref": "declining=1, flat=3, stable/growing=5", "source": "git"})

    # Pending release risk (Octopus)
    val = _safe_get(evidence, "pending_risk", "total_repos_behind")
    s = _score_lower_is_better(val, 5, 2, 5, 1)
    signals.append({"name": "pending_release_risk", "value": val, "unit": "repos", "score": s,
                     "threshold_ref": ">5=1, 2-5=3, 0-1=5", "source": "octopus"})

    return _build_domain("delivery_flow", signals)


# ---------------------------------------------------------------------------
# Domain 2: Architecture and Technical Health
# ---------------------------------------------------------------------------

def _score_architecture(evidence):
    git = evidence.get("git") or {}
    code = evidence.get("code") or {}
    octopus = evidence.get("octopus") or {}

    signals = []

    # Bus factor (min)
    val = _safe_get(git, "contributors", "min_bus_factor")
    s = None
    if val is not None:
        s = 1 if val <= 1 else (3 if val == 2 else 5)
    signals.append({"name": "bus_factor_min", "value": val, "unit": "people", "score": s,
                     "threshold_ref": "1=1, 2=3, >=3=5", "source": "git"})

    # Change blast radius (avg files per PR)
    val = _safe_get(git, "pr_size", "avg_files_changed")
    s = _score_lower_is_better(val, 20, 5, 20, 5)
    signals.append({"name": "change_blast_radius", "value": val, "unit": "files/PR", "score": s,
                     "threshold_ref": ">20=1, 5-20=3, <5=5", "source": "git"})

    # Test coverage
    val = _safe_get(code, "test_coverage", "overall_coverage_pct")
    s = _score_higher_is_better(val, 30, 50, 70, 80)
    signals.append({"name": "test_coverage", "value": val, "unit": "pct", "score": s,
                     "threshold_ref": "<30%=1, 50-70%=3, >80%=5", "source": "code"})

    # Complexity (avg CCN)
    val = _safe_get(code, "complexity", "avg_complexity")
    s = _score_lower_is_better(val, 20, 10, 20, 10)
    signals.append({"name": "avg_complexity", "value": val, "unit": "CCN", "score": s,
                     "threshold_ref": ">20=1, 10-20=3, <10=5", "source": "code"})

    # Dependency freshness
    val = _safe_get(code, "dependency_freshness", "outdated_pct")
    s = _score_lower_is_better(val, 30, 10, 30, 10)
    signals.append({"name": "dependency_freshness", "value": val, "unit": "pct outdated", "score": s,
                     "threshold_ref": ">30%=1, 10-30%=3, <10%=5", "source": "code"})

    # Branch drift
    val = _safe_get(git, "branch_drift", "total_missing_across_repos")
    s = _score_lower_is_better(val, 50, 10, 50, 10)
    signals.append({"name": "branch_drift", "value": val, "unit": "commits", "score": s,
                     "threshold_ref": ">50=1, 10-50=3, <10=5", "source": "git"})

    # Prod-latest version gap
    val = _safe_get(evidence, "pending_risk", "total_repos_behind")
    s = _score_lower_is_better(val, 5, 2, 5, 1)
    signals.append({"name": "prod_latest_gap", "value": val, "unit": "repos", "score": s,
                     "threshold_ref": ">5=1, 2-5=3, 0-1=5", "source": "octopus"})

    return _build_domain("architecture_health", signals)


# ---------------------------------------------------------------------------
# Domain 3: Team Topology and Org Model
# ---------------------------------------------------------------------------

def _score_team_topology(evidence):
    jira = evidence.get("jira") or {}
    git = evidence.get("git") or {}

    signals = []

    # Unassigned WIP pct (derived from count / open)
    unassigned = _safe_get(jira, "unassigned_open_count")
    open_count = _safe_get(jira, "open_count") or _safe_get(jira, "wip_count") or 0
    val = round(unassigned / max(open_count, 1) * 100, 1) if unassigned is not None else None
    s = _score_lower_is_better(val, 30, 10, 30, 5)
    signals.append({"name": "unassigned_wip_pct", "value": val, "unit": "pct", "score": s,
                     "threshold_ref": ">30%=1, 10-30%=3, <5%=5", "source": "jira"})

    # Ownership clarity
    ownership = _safe_get(git, "ownership", "ownership_by_directory") or {}
    total_dirs = len(ownership) if ownership else 0
    clear_dirs = sum(1 for d in ownership.values() if d.get("contributors_count", 0) >= 2) if ownership else 0
    val = round(clear_dirs / max(total_dirs, 1) * 100, 1) if total_dirs else None
    s = _score_higher_is_better(val, 50, 50, 80, 90)
    signals.append({"name": "ownership_clarity", "value": val, "unit": "pct dirs with clear owner", "score": s,
                     "threshold_ref": "<50%=1, 50-80%=3, >90%=5", "source": "git"})

    # WIP per assignee
    val = _safe_get(jira, "avg_wip_per_assignee")
    s = _score_lower_is_better(val, 15, 5, 15, 5)
    signals.append({"name": "wip_per_assignee", "value": val, "unit": "issues", "score": s,
                     "threshold_ref": ">15=1, 5-15=3, <5=5", "source": "jira"})

    return _build_domain("team_topology", signals)


# ---------------------------------------------------------------------------
# Domain 4: Decision-Making and Governance
# ---------------------------------------------------------------------------

def _score_decision_making(evidence):
    jira = evidence.get("jira") or {}

    signals = []

    # Workload Gini
    val = _safe_get(jira, "workload_gini")
    s = _score_lower_is_better(val, 0.6, 0.3, 0.6, 0.3)
    signals.append({"name": "workload_gini", "value": val, "unit": "coefficient", "score": s,
                     "threshold_ref": ">0.6=1, 0.3-0.6=3, <0.3=5", "source": "jira"})

    # Closer != assignee pct
    val = _safe_get(jira, "closer_analysis", "closer_not_assignee_pct")
    s = _score_lower_is_better(val, 50, 20, 50, 20)
    signals.append({"name": "closer_not_assignee_pct", "value": val, "unit": "pct", "score": s,
                     "threshold_ref": ">50%=1, 20-50%=3, <20%=5", "source": "jira"})

    # Velocity CV (mean across projects)
    cv_by_proj = _safe_get(jira, "velocity_cv_by_project") or {}
    cv_values = [v for v in cv_by_proj.values() if v is not None]
    val = round(sum(cv_values) / len(cv_values), 2) if cv_values else None
    s = _score_lower_is_better(val, 0.5, 0.2, 0.5, 0.2)
    signals.append({"name": "velocity_cv", "value": val, "unit": "CV", "score": s,
                     "threshold_ref": ">0.5=1, 0.2-0.5=3, <0.2=5", "source": "jira"})

    domain = _build_domain("decision_making", signals)
    domain["needs_human_review"] = True
    domain["review_reason"] = "Decision-making is primarily qualitative; interview data needed"
    return domain


# ---------------------------------------------------------------------------
# Domain 5: Tech Debt and Sustainability
# ---------------------------------------------------------------------------

def _score_tech_debt(evidence):
    jira = evidence.get("jira") or {}
    code = evidence.get("code") or {}
    git = evidence.get("git") or {}

    signals = []

    # Empty/bad description pct
    val = _safe_get(jira, "empty_description_done_pct")
    s = _score_lower_is_better(val, 25, 10, 25, 5)
    signals.append({"name": "empty_description_pct", "value": val, "unit": "pct", "score": s,
                     "threshold_ref": ">25%=1, 10-25%=3, <5%=5", "source": "jira"})

    # Reopen pct
    val = _safe_get(jira, "reopen_analysis", "reopened_pct")
    s = _score_lower_is_better(val, 20, 5, 20, 5)
    signals.append({"name": "reopen_pct", "value": val, "unit": "pct", "score": s,
                     "threshold_ref": ">20%=1, 5-20%=3, <5%=5", "source": "jira"})

    # Open bug median age
    val = _safe_get(jira, "open_bugs_age_days", "p50_days")
    s = _score_lower_is_better(val, 180, 60, 180, 30)
    signals.append({"name": "open_bug_age_p50", "value": val, "unit": "days", "score": s,
                     "threshold_ref": ">180=1, 60-180=3, <30=5", "source": "jira"})

    # Flow efficiency
    val = _safe_get(jira, "flow_efficiency", "efficiency_pct")
    s = _score_higher_is_better(val, 20, 20, 50, 60)
    signals.append({"name": "flow_efficiency", "value": val, "unit": "pct", "score": s,
                     "threshold_ref": "<20%=1, 20-50%=3, >60%=5", "source": "jira"})

    # Vulnerability count
    val = _safe_get(code, "vulnerabilities", "total_vulns")
    s = _score_lower_is_better(val, 20, 5, 20, 5)
    signals.append({"name": "vulnerability_count", "value": val, "unit": "critical+high", "score": s,
                     "threshold_ref": ">20=1, 5-20=3, <5=5", "source": "code"})

    # Weekend commit pct (burnout signal)
    val = _safe_get(git, "work_patterns", "weekend_commit_pct")
    s = _score_lower_is_better(val, 15, 5, 15, 5)
    signals.append({"name": "weekend_commit_pct", "value": val, "unit": "pct", "score": s,
                     "threshold_ref": ">15%=1, 5-15%=3, <5%=5", "source": "git"})

    # Churn instability (files re-touched within 14 days)
    val = _safe_get(git, "churn_instability", "instability_pct")
    s = _score_lower_is_better(val, 50, 25, 50, 10)
    signals.append({"name": "churn_instability_pct", "value": val, "unit": "pct", "score": s,
                     "threshold_ref": ">50%=1, 25-50%=3, <10%=5", "source": "git"})

    return _build_domain("tech_debt_sustainability", signals)


# ---------------------------------------------------------------------------
# Domain builder helper
# ---------------------------------------------------------------------------

def _build_domain(name, signals):
    scored = [s for s in signals if s.get("score") is not None]
    if scored:
        avg = sum(s["score"] for s in scored) / len(scored)
        score = round(avg)
    else:
        score = None

    evidence_parts = []
    for s in signals:
        if s.get("value") is not None:
            evidence_parts.append(f"{s['name']}={s['value']}{s.get('unit', '')}")
    evidence_summary = ", ".join(evidence_parts[:6]) or "Insufficient data"

    return {
        "name": name,
        "score": score,
        "signals": signals,
        "evidence_summary": evidence_summary,
        "needs_human_review": False,
    }


# ---------------------------------------------------------------------------
# main()
# ---------------------------------------------------------------------------

def main():
    load_env()
    output_dir = os.environ.get("OUTPUT_DIR")

    evidence = read_json("unified_evidence", output_dir)
    if not evidence:
        print("[score_engine] unified_evidence.json not found. Run merge_evidence.py first.")
        return None

    print("[score_engine] Scoring 5 domains...")

    delivery = _score_delivery_flow(evidence)
    architecture = _score_architecture(evidence)
    team = _score_team_topology(evidence)
    decisions = _score_decision_making(evidence)
    tech_debt = _score_tech_debt(evidence)

    domains = {
        "delivery_flow": delivery,
        "architecture_health": architecture,
        "team_topology": team,
        "decision_making": decisions,
        "tech_debt_sustainability": tech_debt,
    }

    scored_domains = [d for d in domains.values() if d.get("score") is not None]
    overall = round(sum(d["score"] for d in scored_domains) / max(len(scored_domains), 1), 1) if scored_domains else None

    # Human override support
    overrides = {}
    existing = read_json("scorecard", output_dir)
    if existing and "manual_overrides" in existing:
        overrides = existing["manual_overrides"]
        for domain_name, override in overrides.items():
            if domain_name in domains:
                domains[domain_name]["manual_override"] = override
                print(f"  Manual override for {domain_name}: score={override.get('score')}")

    data_completeness = evidence.get("sources", {})
    data_completeness["interviews"] = False

    result = {
        "run_iso_ts": datetime.now(timezone.utc).isoformat(),
        "domains": domains,
        "overall_score": overall,
        "interview_signals": None,
        "data_completeness": data_completeness,
    }

    if overrides:
        result["manual_overrides"] = overrides

    path = write_json(result, "scorecard", output_dir)
    print(f"[score_engine] Wrote {path}")
    print(f"  Overall score: {overall}")
    for name, d in domains.items():
        s = d.get("score", "?")
        n_signals = len([x for x in d.get("signals", []) if x.get("score") is not None])
        total = len(d.get("signals", []))
        print(f"  {name}: {s}/5 ({n_signals}/{total} signals scored)")

    return result


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    main()
