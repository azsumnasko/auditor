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

def load_data(path=None):
    path = path or os.path.join(os.path.dirname(__file__), "jira_analytics_latest.json")
    with open(path, encoding="utf-8") as f:
        return json.load(f)

def escape_js(s):
    if s is None:
        return "null"
    return json.dumps(str(s))

def main():
    data = load_data(sys.argv[1] if len(sys.argv) > 1 else None)
    data_js = json.dumps(data, ensure_ascii=False)
    run_ts = data.get("run_iso_ts", "")
    wip = data.get("wip_count", 0)
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
    oldest_bugs = data.get("oldest_open_bugs") or []
    sprint_metrics = data.get("sprint_metrics") or []
    kanban = data.get("kanban_boards") or []
    wip_phase = data.get("wip_by_phase") or {}
    lt_dist = data.get("lead_time_distribution") or {}
    unassigned_wip = data.get("unassigned_wip_count", 0)
    flow_eff = data.get("flow_efficiency") or {}

    projects = data.get("projects", [])
    all_components = sorted(set(wip_comp.keys()) | set(
        c for p in (data.get("by_project") or {}).values()
        for c in (p.get("wip_components") or {}).keys()
    ))
    def project_from_key(key):
        return key.split("-", 1)[0] if key and "-" in str(key) else ""

    blocked_rows = "".join(
        f'<tr data-project="{html.escape(project_from_key(b[0]))}"><td>{html.escape(str(b[0]))}</td><td>{round(float(b[1]), 1)}</td></tr>'
        for b in blocked_oldest
    ) if blocked_oldest else "<tr><td colspan=\"2\">None</td></tr>"

    bugs_rows = "".join(
        f'<tr data-project="{html.escape(b.get("project", ""))}"><td>{html.escape(b.get("key", ""))}</td><td>{html.escape(b.get("project", ""))}</td><td>{round(float(b.get("age_days", 0)), 1)}</td><td>{html.escape((b.get("summary") or "")[:60])}</td></tr>'
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
        sprint_rows.append(
            f'<tr data-project="{html.escape(s.get("project", ""))}">'
            f'<td>{html.escape(s.get("project", ""))}</td>'
            f'<td>{html.escape(s.get("sprint_name", ""))}</td>'
            f'<td>{s.get("throughput_issues", 0)}</td>'
            f'<td>{s.get("total_issues", 0)}</td>'
            f'<td>{s.get("assignee_count", "")}</td>'
            f'<td>{ratio_str}</td>'
            f'<td>{added if added is not None else "\u2014"}</td>'
            f'<td>{removed if removed is not None else "\u2014"}</td>'
            f'<td>{last24_str}</td>'
            f'</tr>'
        )
    sprint_rows_str = "".join(sprint_rows) if sprint_rows else "<tr><td colspan=\"9\">No sprint data</td></tr>"

    kanban_rows = "".join(
        f'<tr data-project="{html.escape(k.get("project", ""))}"><td>{html.escape(k.get("project", ""))}</td><td>{html.escape(k.get("board_name", ""))}</td><td>{k.get("issue_count", 0)}</td><td>{k.get("done_count", 0)}</td><td>{html.escape(json.dumps(k.get("status_breakdown", {})))}</td></tr>'
        for k in kanban
    ) if kanban else "<tr><td colspan=\"5\">No Kanban boards</td></tr>"

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
  <title>Jira Analytics Dashboard \u2014 {html.escape(run_ts)}</title>
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
    .audit-flag .flag-detail {{ color: var(--muted); font-size: 0.8125rem; }}
    .gaming-score {{ display: flex; align-items: center; gap: 1.5rem; padding: 1rem; background: var(--card); border-radius: 8px; border: 1px solid #30363d; margin-bottom: 2rem; }}
    .gaming-gauge {{ font-size: 2.5rem; font-weight: 800; min-width: 80px; text-align: center; }}
    .gaming-label {{ font-size: 0.85rem; color: var(--muted); }}
    .gaming-detail {{ font-size: 0.85rem; }}
    .export-btn {{ background: var(--accent); color: #0f1419; border: none; padding: 0.5rem 1rem; border-radius: 6px; cursor: pointer; font-weight: 600; font-size: 0.85rem; }}
    .export-btn:hover {{ opacity: 0.85; }}
  </style>
</head>
<body>
  <h1>Jira Analytics Dashboard</h1>
  <p class="meta">Run: {html.escape(run_ts)} \u00b7 Projects: {", ".join(projects)} &nbsp; <button class="export-btn" onclick="exportEvidence()">Export Audit Evidence</button></p>

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

  <div class="cards">
    <div class="card"><div class="value" id="cardWip">{wip}</div><div class="label">WIP (not done)</div></div>
    <div class="card"><div class="value" id="cardNotStarted" style="color: var(--muted)">{wip_phase.get('not_started', 0)}</div><div class="label">Not Started</div></div>
    <div class="card"><div class="value" id="cardInProgress" style="color: var(--accent)">{wip_phase.get('in_progress', 0)}</div><div class="label">In Progress</div></div>
    <div class="card"><div class="value" id="cardReviewQa" style="color: var(--orange)">{wip_phase.get('review_qa', 0)}</div><div class="label">Review / QA</div></div>
    <div class="card"><div class="value" id="cardBlocked" style="color: var(--red)">{blocked}</div><div class="label">Blocked / On Hold</div></div>
    <div class="card"><div class="value" id="cardUnassigned" style="color: #e3b341">{unassigned_wip}</div><div class="label">Unassigned WIP</div></div>
    <div class="card"><div class="value" id="cardOpenBugs">{open_bugs}</div><div class="label">Open bugs</div></div>
    <div class="card"><div class="value" id="cardDone4Weeks" style="color: var(--green)">{last_4_weeks}</div><div class="label">Done (last 4 wk)</div></div>
    <div class="card"><div class="value" id="cardWipMedian">{round(wip_aging.get('p50_days', 0))}</div><div class="label">WIP median age (d)</div></div>
    <div class="card"><div class="value" id="cardLeadTime">{round(lead.get('avg_days', 0), 1) if lead.get('avg_days') is not None else '\u2014'}</div><div class="label">Lead time avg (d)</div></div>
    <div class="card"><div class="value" id="cardCycleTime">{round(cycle.get('avg_days', 0), 1) if cycle.get('avg_days') is not None else '\u2014'}</div><div class="label">Cycle time avg (d)</div></div>
    <div class="card"><div class="value" id="cardFlowEff" style="color: var(--orange)">{flow_eff.get('efficiency_pct', 0)}%</div><div class="label">Flow efficiency</div></div>
  </div>

  <div class="grid2">
    <section>
      <h2>Status distribution (WIP)</h2>
      <div class="chart-wrap"><canvas id="chartStatus"></canvas></div>
    </section>
    <section>
      <h2>WIP by component (top 15)</h2>
      <div class="chart-wrap"><canvas id="chartComponents"></canvas></div>
    </section>
  </div>

  <div class="grid2">
    <section>
      <h2>WIP by phase</h2>
      <div class="chart-wrap"><canvas id="chartPhase"></canvas></div>
    </section>
    <section>
      <h2>Lead time distribution (resolved last 180d)</h2>
      <p class="summary-desc">Large &lt; 1 hour bucket signals retroactive ticket logging.</p>
      <div class="chart-wrap"><canvas id="chartLtDist"></canvas></div>
    </section>
  </div>

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

  <div class="grid2">
    <section>
      <h2>Resolutions by day of week</h2>
      <div class="chart-wrap"><canvas id="chartDow"></canvas></div>
    </section>
    <section>
      <h2>Top assignees (resolved last 180d)</h2>
      <p class="summary-desc">Gini coefficient: <strong id="giniValue">{data.get('workload_gini', 0)}</strong> (0 = equal, 1 = one person does all)</p>
      <div class="chart-wrap"><canvas id="chartAssignees"></canvas></div>
    </section>
  </div>

  <section>
    <h2>Throughput by week (issues resolved)</h2>
    <div class="chart-wrap" style="max-width: 900px; height: 220px;"><canvas id="chartThroughput"></canvas></div>
  </section>

  <section>
    <h2>Resolutions per day (bulk closure detection)</h2>
    <p class="summary-desc">Spikes indicate batch closure. Horizontal line = 10 issues/day threshold.</p>
    <div class="chart-wrap" style="max-width: 900px; height: 220px;"><canvas id="chartBulkClosure"></canvas></div>
  </section>

  <section>
    <h2>Sprint scope change (added after sprint start)</h2>
    <div class="chart-wrap" style="max-width: 900px; height: 220px;"><canvas id="chartAddedLate"></canvas></div>
  </section>

  <div class="grid2">
    <section>
      <h2>Median time in status (last 90d, hours)</h2>
      <p class="summary-desc">Near-zero time in active statuses = retroactive status changes.</p>
      <div class="chart-wrap"><canvas id="chartTimeInStatus"></canvas></div>
    </section>
    <section>
      <h2>Top issue closers</h2>
      <p class="summary-desc" id="closerDesc">Closer != assignee in <strong>{ca.get('closer_not_assignee_pct', 0)}%</strong> of cases.</p>
      <div class="chart-wrap"><canvas id="chartClosers"></canvas></div>
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

  <section>
    <h2>Lead time &amp; cycle time (days)</h2>
    <p class="summary-desc">Lead = created \u2192 resolved. Cycle = first in progress \u2192 resolved (from changelog).</p>
    <div class="summary-stats" id="leadCycleSummary">
      <span>Lead (created\u2192resolved):</span> count {lead.get('count', '\u2014')}, avg {round(lead.get('avg_days', 0), 1) if lead.get('avg_days') is not None else '\u2014'}, p50 {round(lead.get('p50_days', 0), 1) if lead.get('p50_days') is not None else '\u2014'} &nbsp;|&nbsp;
      <span>Cycle (in progress\u2192resolved):</span> count {cycle.get('count', '\u2014')}, avg {round(cycle.get('avg_days', 0), 1) if cycle.get('avg_days') is not None else '\u2014'}, p85 {round(cycle.get('p85_days', 0), 1) if cycle.get('p85_days') is not None else '\u2014'}
    </div>
  </section>

  <section>
    <h2>Potential Issues (Audit Flags)</h2>
    <p class="summary-desc">Automated checks for data quality, process health, and potential gaming.</p>
    <div id="auditFlags" class="audit-flags"></div>
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

  <section>
    <h2>Sprint metrics</h2>
    <div class="filter"><input type="text" id="filterSprints" placeholder="Filter by project\u2026" /></div>
    <div class="table-wrap">
      <table id="tableSprints">
        <thead><tr><th data-sort="project">Project</th><th data-sort="sprint_name">Sprint</th><th data-sort="throughput_issues">Done</th><th data-sort="total_issues">Total</th><th data-sort="assignee_count">People</th><th>Commit ratio</th><th data-sort="added_after_sprint_start">Added late</th><th>Removed</th><th>Last-day %</th></tr></thead>
        <tbody>{sprint_rows_str}</tbody>
      </table>
    </div>
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

  <script>
    const DATA = {data_js};

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
    function getEffectiveData(selectedProjects) {{
      if (!selectedProjects || !selectedProjects.length) return DATA;
      const m = mergeProjectMetrics(selectedProjects);
      if (!m) return DATA;
      const bp = DATA.by_project || {{}};
      return Object.assign({{}}, DATA, m, {{
        lead_time_days: m.lead || DATA.lead_time_days,
        cycle_time_days: m.cycle || DATA.cycle_time_days,
        wip_by_phase: phaseFromStatusDist(m.status_distribution),
        by_project: Object.fromEntries(selectedProjects.filter(pk => bp[pk]).map(pk => [pk, bp[pk]])),
        projects: selectedProjects,
        sprint_metrics: (DATA.sprint_metrics||[]).filter(s => selectedProjects.includes(s.project)),
        velocity_cv_by_project: Object.fromEntries(selectedProjects.map(pk => [pk, (DATA.velocity_cv_by_project||{{}})[pk]]).filter(([,v]) => v != null)),
        oldest_open_bugs: (DATA.oldest_open_bugs||[]).filter(b => selectedProjects.includes(b.project)),
      }});
    }}

    const chartStatus = new Chart(document.getElementById('chartStatus'), {{
      type: 'bar',
      data: {{ labels: {json.dumps(status_labels)}, datasets: [{{ label: 'Issues', data: {json.dumps(status_values)}, backgroundColor: 'rgba(88,166,255,0.6)' }}] }},
      options: {{ indexAxis: 'y', responsive: true, maintainAspectRatio: false, plugins: {{ legend: {{ display: false }} }} }}
    }});

    const chartComponents = new Chart(document.getElementById('chartComponents'), {{
      type: 'bar',
      data: {{ labels: {json.dumps(comp_labels)}, datasets: [{{ label: 'Issues', data: {json.dumps(comp_values)}, backgroundColor: 'rgba(63,185,80,0.6)' }}] }},
      options: {{ indexAxis: 'y', responsive: true, maintainAspectRatio: false, plugins: {{ legend: {{ display: false }} }} }}
    }});

    const chartThroughput = new Chart(document.getElementById('chartThroughput'), {{
      type: 'bar',
      data: {{ labels: {json.dumps(weekly_labels)}, datasets: [{{ label: 'Resolved', data: {json.dumps(weekly_values)}, backgroundColor: 'rgba(210,153,34,0.6)' }}] }},
      options: {{ responsive: true, maintainAspectRatio: false, plugins: {{ legend: {{ display: false }} }} }}
    }});

    const phaseData = DATA.wip_by_phase || {{}};
    const chartPhase = new Chart(document.getElementById('chartPhase'), {{
      type: 'doughnut',
      data: {{
        labels: ['Not Started','In Progress','Review / QA','Blocked / On Hold'],
        datasets: [{{ data: [phaseData.not_started||0, phaseData.in_progress||0, phaseData.review_qa||0, phaseData.blocked||0],
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
      options: {{ indexAxis: 'y', responsive: true, maintainAspectRatio: false, plugins: {{ legend: {{ display: false }} }} }}
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
      options: {{ indexAxis: 'y', responsive: true, maintainAspectRatio: false, plugins: {{ legend: {{ display: false }} }} }}
    }});

    // Top closers (2c)
    const closerData = (DATA.closer_analysis || {{}}).top_closers || [];
    const chartClosers = new Chart(document.getElementById('chartClosers'), {{
      type: 'bar',
      data: {{
        labels: closerData.map(c => c.name),
        datasets: [{{ label: 'Issues closed', data: closerData.map(c => c.count), backgroundColor: 'rgba(163,113,247,0.6)' }}]
      }},
      options: {{ indexAxis: 'y', responsive: true, maintainAspectRatio: false, plugins: {{ legend: {{ display: false }} }} }}
    }});

    // Sprint added late
    const sprintLabels = DATA.sprint_metrics.map(s => s.project + ' \u2013 ' + (s.sprint_name || ''));
    const addedLateValues = DATA.sprint_metrics.map(s => s.added_after_sprint_start != null ? s.added_after_sprint_start : 0);
    const chartAddedLate = new Chart(document.getElementById('chartAddedLate'), {{
      type: 'bar',
      data: {{ labels: sprintLabels, datasets: [{{ label: 'Added after sprint start', data: addedLateValues, backgroundColor: 'rgba(248,81,73,0.6)' }}] }},
      options: {{ responsive: true, maintainAspectRatio: false, plugins: {{ legend: {{ display: false }} }} }}
    }});

    // ---------- Audit Flags (expanded) ----------
    function computeAuditFlags(selectedProjects) {{
      const D = getEffectiveData(selectedProjects);
      const flags = [];
      const sev = (s, title, detail) => flags.push({{ severity: s, title, detail }});
      const bp = D.by_project || {{}};

      const ltd = D.lead_time_distribution || {{}};
      const ltTotal = ltd.total || 0;
      const instantPct = ltTotal ? Math.round((ltd.under_1h || 0) / ltTotal * 100) : 0;
      if (instantPct > 30)
        sev('red', `${{instantPct}}% of resolved issues have lead time < 1 hour (retroactive logging likely)`,
          `${{ltd.under_1h}} of ${{ltTotal}} issues created and resolved within 1 hour.`);
      else if (instantPct > 15)
        sev('orange', `${{instantPct}}% of resolved issues have lead time < 1 hour`,
          `${{ltd.under_1h}} of ${{ltTotal}} issues. Consider whether tickets are being logged after work is done.`);

      const ct = D.cycle_time_days || {{}};
      if (ct.p50_days != null && ct.p50_days < 0.01 && ct.avg_days != null && ct.avg_days > 1)
        sev('red', `Cycle time median is ${{(ct.p50_days * 24 * 60).toFixed(0)}} min vs average ${{ct.avg_days.toFixed(1)}} days`,
          'Near-zero median with high average confirms most issues skip the normal workflow.');

      const sprints = D.sprint_metrics || [];
      const byProj = {{}};
      sprints.forEach(s => {{ if (!byProj[s.project]) byProj[s.project] = []; byProj[s.project].push(s); }});
      for (const [proj, pSprints] of Object.entries(byProj)) {{
        const perfect = pSprints.filter(s => s.total_issues > 0 && s.throughput_issues === s.total_issues);
        if (perfect.length >= 3)
          sev('red', `${{proj}}: ${{perfect.length}}/${{pSprints.length}} sprints with 100% completion`,
            'Every issue marked done. Unfinished work is likely removed before sprint close.');
      }}

      for (const [proj, pSprints] of Object.entries(byProj)) {{
        const highScope = pSprints.filter(s => s.total_issues > 0 && s.added_after_sprint_start != null && s.added_after_sprint_start / s.total_issues > 0.5);
        if (highScope.length > 0)
          sev('orange', `${{proj}}: ${{highScope.length}} sprint(s) with > 50% issues added after start`,
            highScope.map(s => `${{s.sprint_name}}: ${{s.added_after_sprint_start}}/${{s.total_issues}}`).join('; '));
      }}

      const emptySprints = sprints.filter(s => s.total_issues === 0);
      if (emptySprints.length > 0)
        sev('orange', `${{emptySprints.length}} empty sprint(s) (0 issues)`,
          emptySprints.map(s => `${{s.project}} \u2013 ${{s.sprint_name}}`).join(', '));

      for (const [proj, pSprints] of Object.entries(byProj)) {{
        const totalDone = pSprints.reduce((a, s) => a + s.throughput_issues, 0);
        const totalIssues = pSprints.reduce((a, s) => a + s.total_issues, 0);
        if (pSprints.length >= 2 && totalIssues > 5 && totalDone / totalIssues < 0.15)
          sev('orange', `${{proj}}: Only ${{totalDone}}/${{totalIssues}} done across ${{pSprints.length}} sprints (${{Math.round(totalDone/totalIssues*100)}}%)`,
            'Very little is being completed.');
      }}

      const noSp = Object.entries(byProj).filter(([, sp]) => sp.every(s => s.committed === 0 || s.committed === null));
      if (noSp.length > 0)
        sev('yellow', `${{noSp.length}} project(s) do not use story points: ${{noSp.map(x => x[0]).join(', ')}}`,
          'Velocity is issue-count only. Throughput numbers cannot distinguish a 5-min task from a 2-week feature.');

      const graveyards = [];
      for (const [proj, pm] of Object.entries(bp)) {{
        const ph = pm.wip_by_phase || {{}};
        const total = (ph.not_started||0) + (ph.in_progress||0) + (ph.review_qa||0) + (ph.blocked||0);
        if (total >= 20 && (ph.not_started||0) / total > 0.85)
          graveyards.push(`${{proj}} (${{ph.not_started}}/${{total}})`);
      }}
      if (graveyards.length > 0)
        sev('orange', `${{graveyards.length}} project(s) with > 85% WIP in "Not Started"`,
          graveyards.join('; ') + '. These backlogs are graveyards.');

      const blockedCount = D.blocked_count || 0;
      const wipCount = D.wip_count || 1;
      const blockedPct = Math.round(blockedCount / wipCount * 1000) / 10;
      if (blockedPct < 1 && wipCount > 50)
        sev('yellow', `Only ${{blockedCount}} blocked issues (${{blockedPct}}% of ${{wipCount}} WIP)`,
          'In orgs with cross-team dependencies, 5\\u201315% blocked is normal. Very low rates usually mean blockers are not tracked.');

      const oldBugs = (D.oldest_open_bugs || []).filter(b => b.age_days > 365);
      if (oldBugs.length >= 5)
        sev('red', `${{oldBugs.length}} open bugs older than 1 year`,
          `Oldest: ${{oldBugs.slice(0,5).map(b => b.key+' ('+Math.round(b.age_days)+'d)').join(', ')}}.`);
      else if (oldBugs.length > 0)
        sev('orange', `${{oldBugs.length}} open bug(s) older than 1 year`,
          oldBugs.map(b => b.key+' ('+Math.round(b.age_days)+'d)').join(', '));

      const bugAge = D.open_bugs_age_days || {{}};
      if (bugAge.p50_days != null && bugAge.p50_days > 180)
        sev('orange', `Median open bug age is ${{Math.round(bugAge.p50_days)}} days`,
          'Bugs have a median age over 6 months.');

      for (const [proj, pm] of Object.entries(bp)) {{
        const pLtd = pm.lead_time_distribution || {{}};
        const pTotal = pLtd.total || 0;
        const pInstPct = pTotal >= 10 ? Math.round((pLtd.under_1h||0) / pTotal * 100) : 0;
        if (pInstPct > 50)
          sev('red', `${{proj}}: ${{pInstPct}}% of resolved issues < 1 hour (${{pLtd.under_1h}}/${{pTotal}})`,
            'Majority of work is logged retroactively.');
        else if (pInstPct > 30 && pTotal >= 20)
          sev('orange', `${{proj}}: ${{pInstPct}}% of resolved issues < 1 hour (${{pLtd.under_1h}}/${{pTotal}})`,
            'Significant retroactive ticket logging.');
      }}

      const rb = D.resolution_breakdown || {{}};
      const rbTotal = Object.values(rb).reduce((a,v) => a+v, 0);
      const rbNonDone = (rb["Won't Do"]||0) + (rb["Duplicate"]||0) + (rb["Cannot Reproduce"]||0) + (rb["Incomplete"]||0) + (rb["Won't Fix"]||0);
      const rbPct = rbTotal ? Math.round(rbNonDone / rbTotal * 100) : 0;
      if (rbPct > 40)
        sev('red', `${{rbPct}}% of resolved issues are Won't Do/Duplicate/etc (${{rbNonDone}}/${{rbTotal}})`,
          'Throughput numbers are heavily inflated by administrative closures.');
      else if (rbPct > 25)
        sev('orange', `${{rbPct}}% of resolved issues are Won't Do/Duplicate/etc`,
          'Consider separating real work throughput from administrative closures.');

      const dit = D.done_issuetype || {{}};
      const ditTotal = Object.values(dit).reduce((a,v) => a+v, 0);
      const taskPct = ditTotal ? Math.round((dit['Task']||0) / ditTotal * 100) : 0;
      if (taskPct > 80)
        sev('yellow', `${{taskPct}}% of done issues are Tasks (not Stories/Epics)`,
          'No feature-level planning visible. Throughput is granular task-count only.');

      const pri = D.wip_priority || {{}};
      const priTotal = Object.values(pri).reduce((a,v) => a+v, 0);
      const priMax = Math.max(...Object.values(pri), 0);
      if (priTotal > 20 && priMax / priTotal > 0.9)
        sev('yellow', `${{Math.round(priMax/priTotal*100)}}% of WIP has the same priority`,
          'Priority field is not being used for triage.');

      const unassigned = D.unassigned_wip_count || 0;
      const unaPct = wipCount ? Math.round(unassigned / wipCount * 100) : 0;
      if (unaPct > 50)
        sev('orange', `${{unaPct}}% of WIP is unassigned (${{unassigned}}/${{wipCount}})`,
          'Majority of open issues have no owner.');
      else if (unaPct > 30 && wipCount > 30)
        sev('yellow', `${{unaPct}}% of WIP is unassigned (${{unassigned}}/${{wipCount}})`,
          'Significant portion of WIP has no assignee.');

      const dow = D.resolution_by_weekday || {{}};
      const dowTotal = Object.values(dow).reduce((a,v) => a+v, 0);
      for (const [day, count] of Object.entries(dow)) {{
        if (dowTotal > 20 && count / dowTotal > 0.35)
          sev('orange', `${{Math.round(count/dowTotal*100)}}% of resolutions happen on ${{day}} (${{count}}/${{dowTotal}})`,
            'Resolution activity is concentrated on a single day, suggesting batch closure.');
      }}

      const vcv = D.velocity_cv_by_project || {{}};
      for (const [proj, cv] of Object.entries(vcv)) {{
        if (cv !== null && cv < 0.10 && (byProj[proj]||[]).length >= 4)
          sev('orange', `${{proj}}: Velocity CV is ${{(cv*100).toFixed(1)}}% (suspiciously stable)`,
            'Real teams fluctuate 20-40%. Very low variance suggests sprint scope is being managed to hit targets.');
        else if (cv !== null && cv > 0.60)
          sev('yellow', `${{proj}}: Velocity CV is ${{(cv*100).toFixed(1)}}% (highly unstable)`,
            'Suggests poor planning or significant scope churn.');
      }}

      const gini = D.workload_gini;
      if (gini != null && gini > 0.7)
        sev('orange', `Workload Gini coefficient is ${{gini}} (heavily concentrated)`,
          'Work is disproportionately done by a few people.');

      const bulk = D.bulk_closure_days || [];
      const bigBulk = bulk.filter(d => d.count > 40);
      const medBulk = bulk.filter(d => d.count > 20);
      if (bigBulk.length > 0)
        sev('red', `${{bigBulk.length}} day(s) with > 40 issues resolved`,
          bigBulk.map(d => `${{d.date}}: ${{d.count}}`).join(', '));
      else if (medBulk.length > 0)
        sev('orange', `${{medBulk.length}} day(s) with > 20 issues resolved`,
          medBulk.slice(0,5).map(d => `${{d.date}}: ${{d.count}}`).join(', '));

      const spa = D.status_path_analysis || {{}};
      if (spa.skip_pct > 30 && spa.total >= 20)
        sev('red', `${{spa.skip_pct}}% of resolved issues skip active work statuses (${{spa.skip_count}}/${{spa.total}})`,
          'Issues go directly to Done without ever entering In Progress/Dev/Review.');
      else if (spa.skip_pct > 15 && spa.total >= 20)
        sev('orange', `${{spa.skip_pct}}% of resolved issues skip active work statuses`,
          'Consider whether workflow statuses reflect reality.');

      const tis = D.time_in_status || {{}};
      const ipTime = tis['In Progress'] || tis['In Dev'] || tis['Doing'];
      if (ipTime && ipTime.median_hours != null && ipTime.median_hours < 0.1 && ipTime.count > 10)
        sev('red', `Median time in "${{Object.keys(tis).find(k => /progress|dev|doing/i.test(k)) || 'In Progress'}}" is ${{(ipTime.median_hours * 60).toFixed(0)}} minutes`,
          'Statuses are being set retroactively, not during actual work.');

      const ca = D.closer_analysis || {{}};
      if (ca.closer_not_assignee_pct > 60 && ca.total_analyzed > 20)
        sev('orange', `${{ca.closer_not_assignee_pct}}% of issues are closed by someone other than the assignee`,
          'Issues are predominantly closed by a different person than who worked on them.');
      const topCloser = (ca.top_closers || [])[0];
      if (topCloser && ca.total_analyzed > 20 && topCloser.count / ca.total_analyzed > 0.4)
        sev('orange', `${{topCloser.name}} closes ${{Math.round(topCloser.count/ca.total_analyzed*100)}}% of all issues (${{topCloser.count}}/${{ca.total_analyzed}})`,
          'Single person closing majority of issues suggests centralized batch processing.');

      const ra = D.reopen_analysis || {{}};
      if (ra.reopened_pct > 15 && ra.total > 20)
        sev('orange', `${{ra.reopened_pct}}% of issues were reopened (${{ra.reopened_count}}/${{ra.total}})`,
          'High reopen rate suggests premature closure or quality issues.');

      const fe = D.flow_efficiency || {{}};
      if (fe.efficiency_pct != null && fe.efficiency_pct < 10 && (fe.active_hours + fe.wait_hours) > 100)
        sev('orange', `Flow efficiency is only ${{fe.efficiency_pct}}%`,
          `Issues spend only ${{fe.efficiency_pct}}% of their time in active work statuses.`);

      for (const [proj, pSprints] of Object.entries(byProj)) {{
        const highEnd = pSprints.filter(s => s.resolved_last_24h_pct != null && s.resolved_last_24h_pct > 60 && s.throughput_issues > 5);
        if (highEnd.length > 0)
          sev('red', `${{proj}}: ${{highEnd.length}} sprint(s) with > 60% issues resolved in final 24h`,
            highEnd.map(s => `${{s.sprint_name}}: ${{s.resolved_last_24h_pct}}%`).join('; '));
      }}

      const edp = D.empty_description_done_pct;
      if (edp != null && edp > 40)
        sev('orange', `${{edp}}% of done issues have no description`,
          'Issues are closed without descriptions, suggesting retroactive logging.');

      const zcp = D.zero_comment_done_pct;
      if (zcp != null && zcp > 60)
        sev('yellow', `${{zcp}}% of done issues have zero comments`,
          'Most resolved issues have no discussion or review trail.');

      const orp = D.orphan_done_pct;
      if (orp != null && orp > 70)
        sev('yellow', `${{orp}}% of done issues have no issue links`,
          'Issues are not linked to other work, making traceability impossible.');

      const container = document.getElementById('auditFlags');
      if (!container) return;
      if (flags.length === 0) {{
        container.innerHTML = '<div class="audit-flag" style="border-left-color:var(--green)"><div class="flag-title" style="color:var(--green)">No significant issues detected</div></div>';
        window._auditFlags = [];
        return;
      }}
      const order = {{ red: 0, orange: 1, yellow: 2 }};
      flags.sort((a, b) => (order[a.severity] ?? 9) - (order[b.severity] ?? 9));
      container.innerHTML = flags.map(f =>
        `<div class="audit-flag ${{f.severity}}"><div class="flag-title">${{f.title}}</div><div class="flag-detail">${{f.detail}}</div></div>`
      ).join('');

      window._auditFlags = flags;
    }}
    computeAuditFlags(null);

    // ---------- Gaming Score (Phase 4a) ----------
    function computeGamingScore(selectedProjects) {{
      const D = getEffectiveData(selectedProjects);
      const bp = D.by_project || {{}};
      const projects = D.projects || [];
      const container = document.getElementById('gamingScoreContainer');
      if (!container) return;

      function projectScore(pk) {{
        let score = 0;
        const pm = bp[pk] || {{}};
        const ltd = pm.lead_time_distribution || {{}};
        const ltTotal = ltd.total || 0;
        const instPct = ltTotal >= 5 ? (ltd.under_1h||0) / ltTotal * 100 : 0;
        score += Math.min(instPct / 50 * 20, 20);
        const spa = pm.status_path_analysis || {{}};
        score += Math.min((spa.skip_pct||0) / 50 * 20, 20);
        const sprints = (D.sprint_metrics||[]).filter(s => s.project === pk);
        if (sprints.length > 0) {{
          const perfectPct = sprints.filter(s => s.total_issues > 0 && s.throughput_issues === s.total_issues).length / sprints.length * 100;
          score += Math.min(perfectPct / 100 * 15, 15);
        }}
        const bulk = pm.bulk_closure_days || [];
        score += Math.min(bulk.length * 2.5, 10);
        const ca = pm.closer_analysis || {{}};
        score += Math.min((ca.closer_not_assignee_pct||0) / 80 * 10, 10);
        score += Math.min((pm.empty_description_done_pct||0) / 60 * 10, 10);
        score += Math.min((pm.zero_comment_done_pct||0) / 80 * 5, 5);
        const wipCount = pm.wip_count || 1;
        const unaPct = (pm.unassigned_wip_count||0) / wipCount * 100;
        score += Math.min(unaPct / 60 * 5, 5);
        const blkPct = (pm.blocked_count||0) / wipCount * 100;
        if (wipCount > 20 && blkPct < 2) score += 5;
        else if (wipCount > 20 && blkPct < 5) score += 2;
        return Math.round(Math.min(score, 100));
      }}

      const globalScore = Math.round(projects.reduce((a, pk) => a + projectScore(pk), 0) / Math.max(projects.length, 1));
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
    }}
    computeGamingScore(null);

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

    function _mergeSource(sourceDict, keyList) {{
      if (!sourceDict) return null;
      const statusMerge = {{}}, compMerge = {{}}, statusByCompMerge = {{}};
      let wip = 0, blocked = 0, openBugs = 0, unassigned = 0;
      const throughputMerge = {{}};
      let wipAgingSum = null;
      let leadCount = 0, leadSum = 0, cycleCount = 0, cycleSum = 0;
      const resMerge = {{}}, wipItMerge = {{}}, doneItMerge = {{}}, wipPriMerge = {{}};
      const dowMerge = {{}}, assigneeMerge = {{}}, bulkMap = {{}}, tisMerge = {{}};
      let cnaCount = 0, cnaWithCloser = 0, cnaTotal = 0;
      const closersMerge = {{}};
      let spaSkip = 0, spaTotal = 0;
      const spaPathsMerge = {{}};
      let reopenC = 0, reopenT = 0;
      const ltdMerge = {{ under_1h:0, '1h_to_1d':0, '1d_to_7d':0, '7d_to_30d':0, over_30d:0, total:0 }};
      let edpW = 0, zcpW = 0, orpW = 0, doneTotal = 0;
      let matched = 0;
      for (const key of keyList) {{
        const m = sourceDict[key];
        if (!m) continue;
        matched++;
        wip += m.wip_count || 0;
        blocked += m.blocked_count || 0;
        openBugs += m.open_bugs_count || 0;
        unassigned += m.unassigned_wip_count || 0;
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
          if (!wipAgingSum) wipAgingSum = {{ count: 0, sum: 0, p50Sum: 0, n: 0 }};
          wipAgingSum.count += m.wip_count || 0;
          wipAgingSum.sum += (m.wip_aging_days.avg_days || 0) * (m.wip_count || 0);
          if (m.wip_aging_days.p50_days != null) {{ wipAgingSum.p50Sum += m.wip_aging_days.p50_days; wipAgingSum.n++; }}
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
        edpW += (m.empty_description_done_pct||0) * dc;
        zcpW += (m.zero_comment_done_pct||0) * dc;
        orpW += (m.orphan_done_pct||0) * dc;
      }}
      if (!matched) return null;
      const weeks = Object.keys(throughputMerge).sort();
      const last4 = weeks.slice(-4).reduce((a, wk) => a + (throughputMerge[wk] || 0), 0);
      let wipMedian = null;
      if (wipAgingSum && wipAgingSum.n) wipMedian = Math.round(wipAgingSum.p50Sum / wipAgingSum.n);
      const compTop = Object.entries(compMerge).sort((a, b) => b[1] - a[1]).slice(0, 15);
      const assTop = Object.entries(assigneeMerge).sort((a,b) => b[1]-a[1]).slice(0, 20);
      const assCounts = Object.entries(assigneeMerge).filter(([k])=>k!=='(unassigned)').map(([,v])=>v);
      const tisF = {{}};
      for (const [st, dd] of Object.entries(tisMerge)) if (dd.cnt > 0) tisF[st] = {{ median_hours: Math.round(dd.totalH/dd.cnt*100)/100, avg_hours: Math.round(dd.totalH/dd.cnt*100)/100, count: dd.cnt }};
      const clsSorted = Object.entries(closersMerge).sort((a,b)=>b[1]-a[1]).slice(0,10);
      const spaPSorted = Object.entries(spaPathsMerge).sort((a,b)=>b[1]-a[1]).slice(0,15);
      const bulkF = Object.entries(bulkMap).filter(([,c])=>c>10).sort(([a],[b])=>a.localeCompare(b)).map(([date,count])=>({{date,count}}));
      return {{
        wip_count: wip, blocked_count: blocked, open_bugs_count: openBugs, unassigned_wip_count: unassigned,
        status_distribution: statusMerge, wip_status_by_component: statusByCompMerge,
        wip_components: Object.fromEntries(compTop),
        throughput_by_week: throughputMerge, last_4_weeks: last4, wip_median: wipMedian,
        lead: leadCount ? {{ count: leadCount, avg_days: leadSum / leadCount }} : null,
        cycle: cycleCount ? {{ count: cycleCount, avg_days: cycleSum / cycleCount }} : null,
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
        empty_description_done_pct: doneTotal ? Math.round(edpW/doneTotal*10)/10 : 0,
        zero_comment_done_pct: doneTotal ? Math.round(zcpW/doneTotal*10)/10 : 0,
        orphan_done_pct: doneTotal ? Math.round(orpW/doneTotal*10)/10 : 0,
      }};
    }}
    function mergeProjectMetrics(projList) {{ return _mergeSource(DATA.by_project, projList); }}
    function mergeComponentMetrics(compList) {{ return _mergeSource(DATA.by_component, compList); }}

    function setCardsAndChartsFromMetrics(m, selectedComponents, projList) {{
      const useGlobal = !m;
      const d = useGlobal ? DATA : m;
      let comp = useGlobal ? (DATA.wip_components || {{}}) : (m.wip_components || {{}});
      if (selectedComponents && selectedComponents.length) {{
        comp = Object.fromEntries(selectedComponents.map(c => [c, comp[c] || 0]).filter(([, v]) => v > 0));
      }}
      const compItems = Object.entries(comp).sort((a, b) => b[1] - a[1]).slice(0, 15);
      const wipFromComp = compItems.reduce((a, [, v]) => a + v, 0);
      const wip = (selectedComponents && selectedComponents.length) ? wipFromComp : (useGlobal ? DATA.wip_count : m.wip_count);
      const blocked = useGlobal ? DATA.blocked_count : m.blocked_count;
      const openBugs = useGlobal ? DATA.open_bugs_count : m.open_bugs_count;
      const unassigned = useGlobal ? (DATA.unassigned_wip_count||0) : (m.unassigned_wip_count||0);
      const last4 = useGlobal ? (() => {{ const tw = DATA.throughput_by_week||{{}}; const wk = Object.keys(tw).sort().slice(-4); return wk.reduce((a,k) => a+(tw[k]||0), 0); }})() : m.last_4_weeks;
      const wipAging = useGlobal ? (DATA.wip_aging_days||{{}}) : {{}};
      const median = useGlobal ? (wipAging.p50_days != null ? Math.round(wipAging.p50_days) : 0) : (m.wip_median != null ? m.wip_median : 0);
      const el = (id, v) => {{ const e = document.getElementById(id); if (e) e.textContent = v; }};

      // Status distribution: filter by component if selected
      let statusDist;
      if (selectedComponents && selectedComponents.length) {{
        const sbc = useGlobal ? (DATA.wip_status_by_component||{{}}) : (m.wip_status_by_component||{{}});
        statusDist = {{}};
        for (const cn of selectedComponents) {{
          for (const [st, cnt] of Object.entries(sbc[cn]||{{}}))
            statusDist[st] = (statusDist[st]||0) + cnt;
        }}
        // Fallback: if cross-tab yielded nothing, use the merged status_distribution
        if (!Object.keys(statusDist).length) {{
          statusDist = useGlobal ? (DATA.status_distribution||{{}}) : (m.status_distribution||{{}});
        }}
      }} else {{
        statusDist = useGlobal ? (DATA.status_distribution||{{}}) : (m.status_distribution||{{}});
      }}

      // Phase from filtered status dist
      const phase = phaseFromStatusDist(statusDist);
      el('cardNotStarted', phase.not_started || 0);
      el('cardInProgress', phase.in_progress || 0);
      el('cardReviewQa', phase.review_qa || 0);
      el('cardWip', wip);
      el('cardBlocked', blocked);
      el('cardUnassigned', unassigned);
      el('cardOpenBugs', openBugs);
      el('cardDone4Weeks', last4);
      el('cardWipMedian', median);
      const leadAvg = useGlobal ? (DATA.lead_time_days||{{}}).avg_days : (m.lead||{{}}).avg_days;
      const cycleAvg = useGlobal ? (DATA.cycle_time_days||{{}}).avg_days : (m.cycle||{{}}).avg_days;
      el('cardLeadTime', leadAvg != null ? leadAvg.toFixed(1) : '\u2014');
      el('cardCycleTime', cycleAvg != null ? cycleAvg.toFixed(1) : '\u2014');

      chartStatus.data.labels = Object.keys(statusDist);
      chartStatus.data.datasets[0].data = Object.values(statusDist);
      chartStatus.update();

      chartComponents.data.labels = compItems.map(x => x[0]);
      chartComponents.data.datasets[0].data = compItems.map(x => x[1]);
      chartComponents.update();

      const thru = useGlobal ? (DATA.throughput_by_week||{{}}) : (m.throughput_by_week||{{}});
      const wkSort = Object.keys(thru).sort();
      chartThroughput.data.labels = wkSort;
      chartThroughput.data.datasets[0].data = wkSort.map(k => thru[k] || 0);
      chartThroughput.update();

      const leadD = useGlobal ? (DATA.lead_time_days||{{}}) : (m.lead||{{}});
      const cycleD = useGlobal ? (DATA.cycle_time_days||{{}}) : (m.cycle||{{}});
      const leadStr = leadD.count != null ? `count ${{leadD.count}}, avg ${{leadD.avg_days != null ? leadD.avg_days.toFixed(1) : '\u2014'}}, p50 ${{leadD.p50_days != null ? leadD.p50_days.toFixed(1) : '\u2014'}}` : '\u2014';
      const cycleStr = cycleD.count != null ? `count ${{cycleD.count}}, avg ${{cycleD.avg_days != null ? cycleD.avg_days.toFixed(1) : '\u2014'}}, p85 ${{cycleD.p85_days != null ? cycleD.p85_days.toFixed(1) : '\u2014'}}` : '\u2014';
      const summaryEl = document.getElementById('leadCycleSummary');
      if (summaryEl) summaryEl.innerHTML = `<span>Lead (created\u2192resolved):</span> ${{leadStr}} &nbsp;|&nbsp; <span>Cycle (in progress\u2192resolved):</span> ${{cycleStr}}`;

      // Phase chart
      chartPhase.data.datasets[0].data = [phase.not_started||0, phase.in_progress||0, phase.review_qa||0, phase.blocked||0];
      chartPhase.update();

      // Lead time distribution chart
      const ltd = useGlobal ? (DATA.lead_time_distribution||{{}}) : (m.lead_time_distribution||{{}});
      chartLtDist.data.datasets[0].data = [ltd.under_1h||0, ltd['1h_to_1d']||0, ltd['1d_to_7d']||0, ltd['7d_to_30d']||0, ltd.over_30d||0];
      chartLtDist.update();

      // Resolution types
      const rd = useGlobal ? (DATA.resolution_breakdown||{{}}) : (m.resolution_breakdown||{{}});
      chartResolution.data.labels = Object.keys(rd);
      chartResolution.data.datasets[0].data = Object.values(rd);
      chartResolution.update();

      // Issue types (stacked bar)
      const wipItD = useGlobal ? (DATA.wip_issuetype||{{}}) : (m.wip_issuetype||{{}});
      const doneItD = useGlobal ? (DATA.done_issuetype||{{}}) : (m.done_issuetype||{{}});
      const allTypesD = [...new Set([...Object.keys(wipItD), ...Object.keys(doneItD)])];
      chartIssueTypes.data.labels = ['WIP','Done (180d)'];
      chartIssueTypes.data.datasets = allTypesD.map((t,i) => ({{ label: t, data: [wipItD[t]||0, doneItD[t]||0], backgroundColor: itColors[i % itColors.length] }}));
      chartIssueTypes.update();

      // Priority
      const priD = useGlobal ? (DATA.wip_priority||{{}}) : (m.wip_priority||{{}});
      const priL = Object.keys(priD);
      chartPriority.data.labels = priL;
      chartPriority.data.datasets[0].data = priL.map(l => priD[l]||0);
      chartPriority.data.datasets[0].backgroundColor = priL.map(l => priColors[l] || 'rgba(139,148,158,0.6)');
      chartPriority.update();

      // Day of week
      const dowD = useGlobal ? (DATA.resolution_by_weekday||{{}}) : (m.resolution_by_weekday||{{}});
      chartDow.data.datasets[0].data = dowLabels.map(dd => dowD[dd]||0);
      chartDow.update();

      // Assignees + gini
      const assD = useGlobal ? (DATA.done_assignees||{{}}) : (m.done_assignees||{{}});
      const assItems = Object.entries(assD).sort((a,b)=>b[1]-a[1]).slice(0,15);
      chartAssignees.data.labels = assItems.map(a => a[0]);
      chartAssignees.data.datasets[0].data = assItems.map(a => a[1]);
      chartAssignees.update();
      el('giniValue', useGlobal ? (DATA.workload_gini||0) : (m.workload_gini||0));

      // Bulk closure
      const bulkD = useGlobal ? (DATA.bulk_closure_days||[]) : (m.bulk_closure_days||[]);
      chartBulkClosure.data.labels = bulkD.map(dd => dd.date);
      chartBulkClosure.data.datasets[0].data = bulkD.map(dd => dd.count);
      chartBulkClosure.update();

      // Time in status
      const tisD = useGlobal ? (DATA.time_in_status||{{}}) : (m.time_in_status||{{}});
      const tisSrt = Object.entries(tisD).sort((a,b) => (b[1].median_hours||0)-(a[1].median_hours||0)).slice(0,12);
      chartTimeInStatus.data.labels = tisSrt.map(x => x[0]);
      chartTimeInStatus.data.datasets[0].data = tisSrt.map(x => x[1].median_hours||0);
      chartTimeInStatus.data.datasets[0].backgroundColor = tisSrt.map(x => {{
        const l = x[0].toLowerCase();
        if (/progress|dev|doing/.test(l)) return 'rgba(88,166,255,0.6)';
        if (/review|qa|test/.test(l)) return 'rgba(210,153,34,0.6)';
        if (/block|hold/.test(l)) return 'rgba(248,81,73,0.6)';
        return 'rgba(139,148,158,0.5)';
      }});
      chartTimeInStatus.update();

      // Closers
      const caD = useGlobal ? (DATA.closer_analysis||{{}}) : (m.closer_analysis||{{}});
      const clsD = caD.top_closers || [];
      chartClosers.data.labels = clsD.map(c => c.name);
      chartClosers.data.datasets[0].data = clsD.map(c => c.count);
      chartClosers.update();
      const closerDescEl = document.getElementById('closerDesc');
      if (closerDescEl) closerDescEl.innerHTML = `Closer != assignee in <strong>${{caD.closer_not_assignee_pct||0}}%</strong> of cases.`;

      // Flow efficiency card
      const feD = useGlobal ? (DATA.flow_efficiency||{{}}) : (m.flow_efficiency||{{}});
      el('cardFlowEff', (feD.efficiency_pct||0) + '%');

      // Status paths table + description
      const spaD = useGlobal ? (DATA.status_path_analysis||{{}}) : (m.status_path_analysis||{{}});
      const skipDescEl = document.getElementById('skipDesc');
      if (skipDescEl) skipDescEl.innerHTML = `Status skip rate: <strong>${{spaD.skip_pct||0}}%</strong> (${{spaD.skip_count||0}}/${{spaD.total||0}} issues never entered an active work status).`;
      const pathsTb = document.getElementById('pathsTbody');
      if (pathsTb) {{
        const tp = spaD.top_paths || [];
        pathsTb.innerHTML = tp.length ? tp.slice(0,10).map(p => `<tr><td>${{p.path.replace(/</g,'&lt;')}}</td><td>${{p.count}}</td></tr>`).join('') : '<tr><td colspan="2">No data</td></tr>';
      }}
    }}

    function applyProjectFilter() {{
      const proj = getSelectedProjects();
      const compSel = getSelectedComponents();

      // Derive effective project list for table / sprint filtering.
      // When only a component filter is active, find which projects contain
      // those components so tables and sprint charts narrow accordingly.
      let effectiveProj = proj;
      if (!proj && compSel && compSel.length && DATA.by_project) {{
        const bp = DATA.by_project;
        const implied = [];
        for (const pk of Object.keys(bp)) {{
          const sbc = bp[pk].wip_status_by_component || {{}};
          if (compSel.some(c => sbc[c])) implied.push(pk);
        }}
        if (implied.length > 0 && implied.length < Object.keys(bp).length) {{
          effectiveProj = implied;
        }}
      }}

      const show = (tr) => {{
        if (!tr.dataset.project) {{ tr.style.display = ''; return; }}
        tr.style.display = (effectiveProj === null || effectiveProj.includes(tr.dataset.project)) ? '' : 'none';
      }};
      ['tableBlocked', 'tableBugs', 'tableSprints', 'tableKanban'].forEach(tableId => {{
        const t = document.getElementById(tableId);
        if (t && t.tBodies[0]) t.tBodies[0].querySelectorAll('tr').forEach(show);
      }});
      const filtered = effectiveProj === null ? DATA.sprint_metrics : DATA.sprint_metrics.filter(s => effectiveProj.includes(s.project));
      chartAddedLate.data.labels = filtered.map(s => s.project + ' \u2013 ' + (s.sprint_name || ''));
      chartAddedLate.data.datasets[0].data = filtered.map(s => s.added_after_sprint_start != null ? s.added_after_sprint_start : 0);
      chartAddedLate.update();

      // Cards & charts: prefer component-level data when component filter is
      // active (by_component gives per-component aggregated metrics).
      // When both project + component filters are active, use component-level
      // metrics (lead time, bugs, etc.) but keep the project-level
      // wip_status_by_component / wip_components for accurate WIP counts
      // (those cross-tabs give the true project-component intersection).
      let merged;
      if (compSel && compSel.length && DATA.by_component) {{
        const compM = mergeComponentMetrics(compSel);
        if (effectiveProj && effectiveProj.length && DATA.by_project) {{
          const projM = mergeProjectMetrics(effectiveProj);
          if (compM && projM) {{
            merged = Object.assign({{}}, compM, {{
              wip_status_by_component: projM.wip_status_by_component,
              wip_components: projM.wip_components,
            }});
          }} else {{
            merged = compM || projM;
          }}
        }} else {{
          // Component-only, no effective project filter — use global cross-tabs
          // so the status distribution chart can still look up per-component WIP.
          merged = compM ? Object.assign({{}}, compM, {{
            wip_status_by_component: DATA.wip_status_by_component || {{}},
            wip_components: DATA.wip_components || {{}},
          }}) : null;
        }}
      }} else if (DATA.by_project && effectiveProj && effectiveProj.length) {{
        merged = mergeProjectMetrics(effectiveProj);
      }} else {{
        merged = null;
      }}
      setCardsAndChartsFromMetrics(merged, compSel, effectiveProj);
      computeAuditFlags(effectiveProj);
      computeGamingScore(effectiveProj);
      document.getElementById('filterBugs')?.dispatchEvent(new Event('input'));
      document.getElementById('filterSprints')?.dispatchEvent(new Event('input'));
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

    function setupFilter(inputId, tableId) {{
      const input = document.getElementById(inputId);
      const table = document.getElementById(tableId);
      if (!input || !table) return;
      const tbody = table.querySelector('tbody');
      input.addEventListener('input', function() {{
        const q = this.value.trim().toLowerCase();
        const proj = getSelectedProjects();
        tbody.querySelectorAll('tr').forEach(tr => {{
          if (tr.cells.length < 2) {{ tr.style.display = ''; return; }}
          const projectOk = proj === null || !tr.dataset.project || proj.includes(tr.dataset.project);
          const text = Array.from(tr.cells).map(c => c.textContent).join(' ').toLowerCase();
          tr.style.display = (projectOk && text.includes(q)) ? '' : 'none';
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
    setupSort('tableBugs');
    setupSort('tableSprints');

    // ---------- Evidence Export (Phase 4b) ----------
    function exportEvidence() {{
      const flags = window._auditFlags || [];
      const gs = window._gamingScore || 0;
      const ps = window._projectScores || {{}};
      const d = DATA;
      let md = '# Jira Engineering Audit \u2014 Evidence Report\\n\\n';
      md += `**Generated:** ${{d.run_iso_ts}}\\n`;
      md += `**Projects:** ${{(d.projects||[]).join(', ')}}\\n\\n`;
      md += '## Gaming Score\\n\\n';
      md += `**Overall: ${{gs}}/100** (${{gs >= 60 ? 'Systemic Gaming' : gs >= 40 ? 'Significant Manipulation' : gs >= 20 ? 'Concerning' : 'Healthy'}})\\n\\n`;
      md += '| Project | Score |\\n|---------|-------|\\n';
      for (const [pk, s] of Object.entries(ps)) md += `| ${{pk}} | ${{s}} |\\n`;
      md += '\\n## Key Metrics\\n\\n';
      md += `| Metric | Value |\\n|--------|-------|\\n`;
      md += `| WIP (not done) | ${{d.wip_count}} |\\n`;
      md += `| Unassigned WIP | ${{d.unassigned_wip_count||0}} (${{d.wip_count ? Math.round((d.unassigned_wip_count||0)/d.wip_count*100) : 0}}%) |\\n`;
      md += `| Blocked | ${{d.blocked_count}} |\\n`;
      md += `| Open Bugs | ${{d.open_bugs_count}} |\\n`;
      md += `| Lead Time Avg | ${{d.lead_time_days?.avg_days?.toFixed(1) || '-'}} days |\\n`;
      md += `| Cycle Time Avg | ${{d.cycle_time_days?.avg_days?.toFixed(1) || '-'}} days |\\n`;
      md += `| Flow Efficiency | ${{d.flow_efficiency?.efficiency_pct || 0}}% |\\n`;
      md += `| Status Skip Rate | ${{d.status_path_analysis?.skip_pct || 0}}% |\\n`;
      md += `| Closer != Assignee | ${{d.closer_analysis?.closer_not_assignee_pct || 0}}% |\\n`;
      md += `| Reopen Rate | ${{d.reopen_analysis?.reopened_pct || 0}}% |\\n`;
      md += `| Empty Descriptions (done) | ${{d.empty_description_done_pct || 0}}% |\\n`;
      md += `| Zero Comments (done) | ${{d.zero_comment_done_pct || 0}}% |\\n`;
      md += `| Workload Gini | ${{d.workload_gini || 0}} |\\n`;
      md += '\\n## Audit Flags\\n\\n';
      const sevEmoji = {{ red: '[RED]', orange: '[ORANGE]', yellow: '[YELLOW]' }};
      for (const f of flags) {{
        md += `### ${{sevEmoji[f.severity] || ''}} ${{f.title}}\\n\\n${{f.detail}}\\n\\n`;
      }}
      md += '\\n## Resolution Breakdown\\n\\n';
      md += '| Type | Count |\\n|------|-------|\\n';
      for (const [k,v] of Object.entries(d.resolution_breakdown||{{}})) md += `| ${{k}} | ${{v}} |\\n`;
      md += '\\n---\\n\\n*Generated by Jira Analytics Dashboard*\\n';

      const blob = new Blob([md], {{ type: 'text/markdown' }});
      const url = URL.createObjectURL(blob);
      const a = document.createElement('a');
      a.href = url;
      a.download = `audit_evidence_${{d.run_iso_ts?.replace(/:/g,'-') || 'report'}}.md`;
      a.click();
      URL.revokeObjectURL(url);
    }}
  </script>
</body>
</html>"""

    out_path = os.path.join(os.path.dirname(__file__), "jira_dashboard.html")
    with open(out_path, "w", encoding="utf-8") as f:
        f.write(html_out)
    print(f"Written: {out_path}")
    return 0

if __name__ == "__main__":
    sys.exit(main() or 0)
