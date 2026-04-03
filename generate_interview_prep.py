#!/usr/bin/env python3
"""
generate_interview_prep.py -- Produce role-specific interview preparation.

Reads ``scorecard.json`` + ``unified_evidence.json``, selects questions from
the interview guide mapped to low-scoring domains, and pre-populates them
with specific data points to probe.

Outputs ``interview_prep.md``.
"""

import os
import logging
from datetime import datetime, timezone

from analytics_utils import load_env, read_json

log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Question bank (from mds/2 INTERVIEW GUIDES, organised by role + domain)
# ---------------------------------------------------------------------------

QUESTIONS = {
    "CTO / VP Engineering": {
        "delivery_flow": [
            'Where do you lose the most time from idea to production?',
            'How do you measure whether engineering is successful?',
        ],
        "architecture_health": [
            'How do you make architectural decisions?',
            'If you doubled the team in 12 months, what would break first?',
        ],
        "decision_making": [
            'Which decisions go through you?',
            'What are the top 3 delivery problems?',
        ],
        "team_topology": [
            'If you doubled the team in 12 months, what would break first?',
        ],
        "tech_debt_sustainability": [
            'What are the top 3 delivery problems?',
        ],
    },
    "Engineering Manager": {
        "delivery_flow": [
            'How often does the plan get executed?',
            'How much time goes to unplanned work?',
        ],
        "architecture_health": [
            'What most often blocks the team?',
        ],
        "decision_making": [
            'Who makes the final decision when there is a dispute?',
        ],
        "team_topology": [
            'What most often blocks the team?',
        ],
        "tech_debt_sustainability": [
            'What happens when something is late?',
        ],
    },
    "Tech Lead / Senior Engineer": {
        "delivery_flow": [
            'What does a typical PR look like?',
        ],
        "architecture_health": [
            'Which parts of the system do you avoid touching?',
            'What breaks the releases?',
        ],
        "decision_making": [
            'How are tech decisions made?',
        ],
        "team_topology": [
            'Is there clear ownership?',
        ],
        "tech_debt_sustainability": [
            'Which parts of the system do you avoid touching?',
        ],
    },
    "Product Manager": {
        "delivery_flow": [
            'How long from idea to customer?',
            'How often is there rework?',
        ],
        "architecture_health": [],
        "decision_making": [
            'How often do you change the roadmap?',
        ],
        "team_topology": [],
        "tech_debt_sustainability": [
            'How do you estimate effort?',
        ],
    },
}


def _safe(data, *keys, default=None):
    for k in keys:
        if not isinstance(data, dict):
            return default
        data = data.get(k)
        if data is None:
            return default
    return data


def _fmt(val, suffix=""):
    if val is None:
        return "N/A"
    if isinstance(val, float):
        return f"{val:.1f}{suffix}"
    return f"{val}{suffix}"


def _data_point_hints(domain_key, evidence, scorecard):
    """Build contextual data points for a domain to use in interview probes."""
    jira = evidence.get("jira") or {}
    git = evidence.get("git") or {}
    octopus = evidence.get("octopus") or {}
    hints = []

    if domain_key == "delivery_flow":
        lt = _safe(jira, "lead_time_days", "p50_days")
        if lt is not None:
            hints.append(f"Lead time p50 is {_fmt(lt, ' days')}")
        prc = _safe(git, "pr_cycle_time", "p50_days")
        if prc is not None:
            hints.append(f"PR cycle time p50 is {_fmt(prc, ' days')}")
        ctp = _safe(octopus, "commit_to_prod_lead_time", "p50_days")
        if ctp is not None:
            hints.append(f"Commit-to-prod lead time is {_fmt(ctp, ' days')}")
        unplanned = _safe(jira, "sprint_aggregate", "avg_added_after_start_pct")
        if unplanned is not None:
            hints.append(f"Unplanned work ratio is {_fmt(unplanned, '%')}")

    elif domain_key == "architecture_health":
        bf = _safe(git, "contributors", "min_bus_factor")
        if bf is not None:
            hints.append(f"Minimum bus factor across repos is {bf}")
        drift = _safe(git, "branch_drift", "total_missing_across_repos")
        if drift:
            hints.append(f"Branch drift total: {drift} missing commits")
        files = _safe(git, "pr_size", "avg_files_changed")
        if files is not None:
            hints.append(f"Average files changed per PR: {_fmt(files)}")

    elif domain_key == "decision_making":
        gini = _safe(jira, "workload_gini")
        if gini is not None:
            hints.append(f"Workload Gini coefficient is {gini}")
        cv = _safe(jira, "velocity_cv")
        if cv is not None:
            hints.append(f"Velocity CV is {cv}")

    elif domain_key == "team_topology":
        orphans = _safe(git, "ownership", "orphan_directories") or []
        if orphans:
            hints.append(f"Orphan directories (no backup contributor): {len(orphans)}")

    elif domain_key == "tech_debt_sustainability":
        weekend = _safe(git, "work_patterns", "weekend_commit_pct")
        if weekend is not None:
            hints.append(f"Weekend commit pct is {_fmt(weekend, '%')}")
        reopen = _safe(jira, "reopen_pct")
        if reopen is not None:
            hints.append(f"Reopen rate is {_fmt(reopen, '%')}")

    return hints


def generate_interview_prep(evidence, scorecard):
    domains = scorecard.get("domains", {})
    domain_labels = {
        "delivery_flow": "Delivery Flow",
        "architecture_health": "Architecture & Tech Health",
        "team_topology": "Team Topology & Org Model",
        "decision_making": "Decision-Making & Governance",
        "tech_debt_sustainability": "Tech Debt & Sustainability",
    }

    low_domains = []
    for key, d in domains.items():
        score = d.get("score")
        if d.get("manual_override"):
            score = d["manual_override"].get("score", score)
        if score is not None and score <= 3:
            low_domains.append((key, score))
    low_domains.sort(key=lambda x: x[1])

    ambiguous = [key for key, d in domains.items() if d.get("needs_human_review")]

    lines = [
        "# Interview Preparation Guide",
        "",
        f"*Generated: {evidence.get('run_iso_ts', '')}*",
        "",
        "## Focus Areas (Low-scoring Domains)",
        "",
    ]

    for key, score in low_domains:
        label = domain_labels.get(key, key)
        lines.append(f"- **{label}**: {score}/5")
    lines.append("")

    if ambiguous:
        lines.append("## Domains Requiring Human Validation")
        lines.append("")
        for key in ambiguous:
            label = domain_labels.get(key, key)
            reason = domains.get(key, {}).get("review_reason", "")
            lines.append(f"- **{label}**: {reason}")
        lines.append("")

    for role, domain_questions in QUESTIONS.items():
        role_questions = []
        for domain_key, score in low_domains:
            qs = domain_questions.get(domain_key, [])
            hints = _data_point_hints(domain_key, evidence, scorecard)
            for q in qs:
                role_questions.append((q, domain_labels.get(domain_key, domain_key), hints))

        if not role_questions:
            continue

        lines.append(f"---")
        lines.append(f"")
        lines.append(f"## {role}")
        lines.append("")

        seen = set()
        for q, domain_label, hints in role_questions:
            if q in seen:
                continue
            seen.add(q)
            lines.append(f"### Q: \"{q}\"")
            lines.append(f"- Domain: {domain_label}")
            if hints:
                lines.append(f"- Data to probe:")
                for h in hints:
                    lines.append(f"  - {h}")
            lines.append("")

    lines.append("---")
    lines.append("")
    lines.append("## Interview Notes Template")
    lines.append("")
    lines.append("| # | Role | Key Quote | Repeating Theme | Domain Mapping |")
    lines.append("|---|------|-----------|-----------------|----------------|")
    for i in range(1, 8):
        lines.append(f"| {i} |  |  |  |  |")
    lines.append("")

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# main()
# ---------------------------------------------------------------------------

def main():
    load_env()
    output_dir = os.environ.get("OUTPUT_DIR") or os.path.dirname(__file__) or "."

    evidence = read_json("unified_evidence", output_dir)
    scorecard = read_json("scorecard", output_dir)

    if not evidence or not scorecard:
        print("[generate_interview_prep] unified_evidence.json or scorecard.json not found, skipping.")
        return

    md = generate_interview_prep(evidence, scorecard)
    path = os.path.join(output_dir, "interview_prep.md")
    with open(path, "w", encoding="utf-8") as f:
        f.write(md)
    print(f"[generate_interview_prep] Wrote {path}")


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    main()
