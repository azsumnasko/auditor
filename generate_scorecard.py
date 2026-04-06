#!/usr/bin/env python3
"""
generate_scorecard.py -- Produce a single-page HTML visual scorecard.

Reads ``scorecard.json`` and outputs ``scorecard.html`` with:
  - Five domain cards with colour-coded scores
  - Radar / spider chart (Chart.js)
  - DORA metrics section
  - Data completeness indicator
  - "Needs human review" callouts

Design reference: dark-mode GitHub-style CSS from git_release_audit_report.ps1.
"""

import json
import os
import sys
import logging
from datetime import datetime, timezone

from analytics_utils import load_env, read_json

log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Score -> colour gradient
# ---------------------------------------------------------------------------

SCORE_COLORS = {
    1: "#e74c3c",  # red
    2: "#e67e22",  # orange
    3: "#f1c40f",  # yellow
    4: "#2ecc71",  # lime green
    5: "#27ae60",  # green
}

SCORE_LABELS = {1: "Critical", 2: "Needs Improvement", 3: "Adequate", 4: "Good", 5: "Excellent"}


def _color(score):
    return SCORE_COLORS.get(score, "#6c757d")


def _label(score):
    return SCORE_LABELS.get(score, "N/A")


# ---------------------------------------------------------------------------
# HTML generation
# ---------------------------------------------------------------------------

def generate_html(scorecard, evidence=None):
    domains = scorecard.get("domains", {})
    overall = scorecard.get("overall_score")
    completeness = scorecard.get("data_completeness", {})
    run_ts = scorecard.get("run_iso_ts", "")

    dora = {}
    if evidence:
        dora = evidence.get("dora", {})

    domain_order = ["delivery_flow", "architecture_health", "team_topology", "decision_making", "tech_debt_sustainability"]
    domain_labels = {
        "delivery_flow": "Delivery Flow",
        "architecture_health": "Architecture & Tech Health",
        "team_topology": "Team Topology & Org",
        "decision_making": "Decision-Making & Governance",
        "tech_debt_sustainability": "Tech Debt & Sustainability",
    }

    # Domain cards HTML
    cards_html = ""
    radar_labels = []
    radar_values = []
    for key in domain_order:
        d = domains.get(key, {})
        score = d.get("score")
        if d.get("manual_override"):
            score = d["manual_override"].get("score", score)
        radar_labels.append(domain_labels.get(key, key))
        radar_values.append(score if score is not None else 0)

        signals_html = ""
        for sig in d.get("signals", []):
            s_score = sig.get("score")
            s_color = _color(s_score) if s_score else "#6c757d"
            val = sig.get("value")
            val_str = f"{val}" if val is not None else "N/A"
            signals_html += f"""
            <tr>
                <td>{sig.get('name','')}</td>
                <td>{val_str} {sig.get('unit','')}</td>
                <td style="color:{s_color};font-weight:bold">{s_score if s_score else '?'}/5</td>
                <td style="font-size:0.75em;color:#888">{sig.get('source','')}</td>
            </tr>"""

        review_badge = ""
        if d.get("needs_human_review"):
            reason = d.get("review_reason", "")
            review_badge = f'<span style="background:#e67e22;color:#fff;padding:2px 8px;border-radius:4px;font-size:0.8em;margin-left:8px">Needs Human Review</span>'
            if reason:
                review_badge += f'<p style="color:#e67e22;font-size:0.85em;margin-top:4px">{reason}</p>'

        override_note = ""
        if d.get("manual_override"):
            ov = d["manual_override"]
            override_note = f'<p style="color:#3498db;font-size:0.85em">Manual override: {ov.get("score")}/5 &mdash; {ov.get("reason","")}</p>'

        cards_html += f"""
        <div class="domain-card">
            <div class="domain-header" style="border-left: 4px solid {_color(score)}">
                <span class="domain-score" style="background:{_color(score)}">{score if score else '?'}</span>
                <h3>{domain_labels.get(key, key)}{review_badge}</h3>
            </div>
            {override_note}
            <p class="evidence-summary">{d.get('evidence_summary','')}</p>
            <table class="signals-table">
                <thead><tr><th>Signal</th><th>Value</th><th>Score</th><th>Source</th></tr></thead>
                <tbody>{signals_html}</tbody>
            </table>
        </div>"""

    # DORA section
    dora_html = ""
    if dora:
        dora_rows = ""
        for key_name in ("deployment_frequency", "lead_time_for_changes", "change_failure_rate", "mttr"):
            m = dora.get(key_name, {})
            if not m:
                continue
            val = m.get("value") or m.get("value_days") or m.get("value_pct") or m.get("value_hours") or "N/A"
            cat = m.get("category", "N/A")
            src = m.get("source", "")
            cat_color = {"elite": "#27ae60", "high": "#2ecc71", "medium": "#f1c40f", "low": "#e74c3c"}.get(cat, "#888")
            dora_rows += f"""
            <tr>
                <td>{key_name.replace('_',' ').title()}</td>
                <td>{val}</td>
                <td style="color:{cat_color};font-weight:bold">{cat.title()}</td>
                <td>{src}</td>
            </tr>"""

        overall_dora = dora.get("overall_category", "N/A")
        overall_dora_color = {"elite": "#27ae60", "high": "#2ecc71", "medium": "#f1c40f", "low": "#e74c3c"}.get(overall_dora, "#888")
        dora_html = f"""
        <div class="dora-section">
            <h2>DORA Metrics <span class="dora-overall" style="background:{overall_dora_color}">{overall_dora.title()}</span></h2>
            <table class="signals-table">
                <thead><tr><th>Metric</th><th>Value</th><th>Category</th><th>Source</th></tr></thead>
                <tbody>{dora_rows}</tbody>
            </table>
        </div>"""

    # Data completeness
    comp_items = ""
    for src, available in completeness.items():
        icon = "&#10003;" if available else "&#10007;"
        color = "#27ae60" if available else "#e74c3c"
        comp_items += f'<span style="color:{color};margin-right:12px">{icon} {src}</span>'

    radar_labels_js = json.dumps(radar_labels)
    radar_values_js = json.dumps(radar_values)

    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Engineering Maturity Scorecard</title>
<script src="https://cdn.jsdelivr.net/npm/chart.js@4.4.0/dist/chart.umd.min.js"></script>
<style>
:root {{
    --bg: #0d1117;
    --card-bg: #161b22;
    --border: #30363d;
    --text: #c9d1d9;
    --text-muted: #8b949e;
    --accent: #58a6ff;
}}
* {{ box-sizing: border-box; margin: 0; padding: 0; }}
body {{ background: var(--bg); color: var(--text); font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Helvetica, Arial, sans-serif; padding: 24px; }}
h1 {{ font-size: 1.8em; margin-bottom: 4px; }}
h2 {{ font-size: 1.3em; margin: 24px 0 12px; }}
h3 {{ font-size: 1.05em; display: inline; }}
.header {{ text-align: center; margin-bottom: 32px; }}
.header .overall {{ font-size: 2.5em; font-weight: bold; }}
.header .timestamp {{ color: var(--text-muted); font-size: 0.85em; }}
.completeness {{ text-align: center; margin-bottom: 24px; font-size: 0.9em; }}
.chart-container {{ max-width: 420px; margin: 0 auto 32px; }}
.domain-card {{ background: var(--card-bg); border: 1px solid var(--border); border-radius: 8px; padding: 16px; margin-bottom: 16px; }}
.domain-header {{ display: flex; align-items: center; gap: 12px; padding-left: 12px; margin-bottom: 8px; }}
.domain-score {{ display: inline-flex; align-items: center; justify-content: center; width: 36px; height: 36px; border-radius: 50%; color: #fff; font-weight: bold; font-size: 1.1em; flex-shrink: 0; }}
.evidence-summary {{ color: var(--text-muted); font-size: 0.85em; margin-bottom: 10px; }}
.signals-table {{ width: 100%; border-collapse: collapse; font-size: 0.85em; }}
.signals-table th {{ text-align: left; color: var(--text-muted); border-bottom: 1px solid var(--border); padding: 4px 8px; }}
.signals-table td {{ padding: 4px 8px; border-bottom: 1px solid var(--border); }}
.dora-section {{ background: var(--card-bg); border: 1px solid var(--border); border-radius: 8px; padding: 16px; margin-bottom: 16px; }}
.dora-overall {{ padding: 2px 10px; border-radius: 4px; color: #fff; font-size: 0.8em; margin-left: 8px; }}
</style>
</head>
<body>
<div class="header">
    <h1>Engineering Maturity Scorecard</h1>
    <div class="overall" style="color:{_color(round(overall) if overall else None)}">{overall if overall else '?'}/5</div>
    <div class="timestamp">Generated: {run_ts}</div>
</div>
<div class="completeness">Data Sources: {comp_items}</div>
<div class="chart-container"><canvas id="radar"></canvas></div>
{cards_html}
{dora_html}
<script>
new Chart(document.getElementById('radar'), {{
    type: 'radar',
    data: {{
        labels: {radar_labels_js},
        datasets: [{{
            label: 'Score',
            data: {radar_values_js},
            backgroundColor: 'rgba(88,166,255,0.15)',
            borderColor: '#58a6ff',
            pointBackgroundColor: '#58a6ff',
            pointBorderColor: '#fff',
            pointRadius: 5,
        }}]
    }},
    options: {{
        scales: {{ r: {{ min: 0, max: 5, ticks: {{ stepSize: 1, color: '#8b949e' }}, grid: {{ color: '#30363d' }}, angleLines: {{ color: '#30363d' }}, pointLabels: {{ color: '#c9d1d9', font: {{ size: 11 }} }} }} }},
        plugins: {{ legend: {{ display: false }} }}
    }}
}});
</script>
</body>
</html>"""

    return html


def generate_placeholder_html() -> str:
    """Single-page message when scorecard.json is missing (avoids 404 on static hosts)."""
    ts = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8"/>
  <meta name="viewport" content="width=device-width, initial-scale=1"/>
  <title>Scorecard unavailable</title>
  <style>
    body {{ font-family: ui-sans-serif, system-ui, sans-serif; background: #0d1117; color: #c9d1d9; margin: 0; padding: 2rem; line-height: 1.5; }}
    .box {{ max-width: 40rem; margin: 4rem auto; padding: 1.5rem 1.75rem; background: #161b22; border: 1px solid #30363d; border-radius: 8px; }}
    h1 {{ font-size: 1.25rem; margin: 0 0 0.75rem; color: #f0f6fc; }}
    p {{ margin: 0.65rem 0; color: #8b949e; font-size: 0.9rem; }}
    code {{ background: #21262d; padding: 0.1em 0.35em; border-radius: 4px; font-size: 0.85em; }}
    a {{ color: #58a6ff; }}
    .ts {{ font-size: 0.75rem; color: #6e7681; margin-top: 1rem; }}
  </style>
</head>
<body>
  <div class="box">
    <h1>Engineering Maturity Scorecard</h1>
    <p><strong>scorecard.json</strong> was not found when generating this page. The full scorecard requires merged evidence and a successful scoring run.</p>
    <p>Run <code>merge_evidence</code> (produces <code>unified_evidence.json</code>), then <code>score_engine</code> (writes <code>scorecard.json</code>), then regenerate. Deploy the whole <code>OUTPUT_DIR</code> including <code>scorecard.html</code> alongside the main dashboard.</p>
    <p>Open the main <a href="jira_dashboard.html">Jira analytics dashboard</a> if it is hosted in the same folder.</p>
    <p class="ts">Placeholder generated: {ts}</p>
  </div>
</body>
</html>"""


# ---------------------------------------------------------------------------
# main()
# ---------------------------------------------------------------------------

def main():
    """Write scorecard.html. Returns 'full' if scorecard.json was used, 'placeholder' otherwise."""
    load_env()
    output_dir = os.environ.get("OUTPUT_DIR") or os.path.dirname(__file__) or "."

    path = os.path.join(output_dir, "scorecard.html")
    scorecard = read_json("scorecard", output_dir)
    if not scorecard:
        print("[generate_scorecard] scorecard.json not found; writing placeholder scorecard.html.")
        with open(path, "w", encoding="utf-8") as f:
            f.write(generate_placeholder_html())
        print(f"[generate_scorecard] Wrote {path} (placeholder)")
        return "placeholder"

    evidence = read_json("unified_evidence", output_dir)

    html = generate_html(scorecard, evidence)
    with open(path, "w", encoding="utf-8") as f:
        f.write(html)
    print(f"[generate_scorecard] Wrote {path}")
    return "full"


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    main()
