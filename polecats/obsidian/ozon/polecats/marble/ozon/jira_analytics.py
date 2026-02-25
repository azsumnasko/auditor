import os
import math
import time
import json as _json
from datetime import datetime, timezone, timedelta
from collections import Counter, defaultdict

# Load .env if present (keeps token out of terminal history)
try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

import requests
import pandas as pd
from dateutil import parser as dtparser


# ----------------------------
# Config
# ----------------------------
PROJECT_KEYS = ["OZN", "PMBK", "WMS", "O3", "UP", "RMA", "MA", "LSH", "IN", "HELP", "EBK", "PBI", "BA"]

# JQL reserved words that must be quoted when used as project keys (e.g. "IN")
JQL_RESERVED = frozenset({"in", "and", "or", "not", "null", "empty", "order", "by", "asc", "desc"})

def _jql_project_list(keys):
    """Project list for JQL: quote reserved words so e.g. project key 'IN' works."""
    return ", ".join(f'"{k}"' if k.lower() in JQL_RESERVED else k for k in keys)

# You can tweak these to match your workflow
DONE_CATEGORY = "done"         # Jira statusCategory key: "new", "indeterminate", "done"
INPROGRESS_CATEGORY = "indeterminate"

# "Blocked" varies by Jira setup. Use a label, flag, status, or custom field if you have one.
# We'll default to label=blocked OR status=Blocked OR "Flagged" if present in Sprint field.
BLOCKED_JQL = '(labels = blocked OR status = Blocked OR status = "Blocked")'

# Change Failure Rate depends on how you record incidents/rollbacks.
# Example: Bugs created within N days after a "Deployment" issue is done, or incidents labeled "change-failure".
# We'll provide a framework and you can set the JQL rule.
CFR_FAILURE_JQL = '(project in ({projects}) AND issuetype in (Incident, Bug) AND labels = change-failure)'


# ----------------------------
# Jira client
# ----------------------------
class JiraClient:
    def __init__(self):
        self.base = os.environ.get("JIRA_BASE_URL")
        self.email = os.environ.get("JIRA_EMAIL")
        self.token = os.environ.get("JIRA_TOKEN")
        if not self.base or not self.email or not self.token:
            raise RuntimeError("Missing env vars. Set JIRA_BASE_URL, JIRA_EMAIL, JIRA_TOKEN.")

        self.session = requests.Session()
        self.session.auth = (self.email, self.token)
        self.session.headers.update({"Accept": "application/json"})

    def _get(self, path, params=None, timeout=60):
        url = self.base.rstrip("/") + path
        r = self.session.get(url, params=params or {}, timeout=timeout)
        if r.status_code >= 400:
            raise RuntimeError(f"GET {url} failed {r.status_code}: {r.text[:500]}")
        return r.json()

    def search(self, jql, fields=None, expand=None, max_results=1000):
        """Paginated /rest/api/3/search/jql (new API; old /rest/api/3/search returns 410)."""
        if max_results <= 0:
            return []
        all_issues = []
        page_size = 100
        next_page_token = None

        while True:
            params = {
                "jql": jql,
                "maxResults": min(page_size, max_results - len(all_issues)),
            }
            if next_page_token:
                params["nextPageToken"] = next_page_token
            if fields is not None:
                params["fields"] = ",".join(fields)
            if expand:
                params["expand"] = expand

            data = self._get("/rest/api/3/search/jql", params=params)
            issues = data.get("issues", [])
            all_issues.extend(issues)

            if len(all_issues) >= max_results:
                break
            next_page_token = data.get("nextPageToken")
            if not next_page_token or not issues:
                break

            time.sleep(0.1)

        return all_issues

    def list_fields(self):
        return self._get("/rest/api/3/field")

    def list_boards_for_project(self, project_key, max_results=50):
        # Jira Software Agile API
        return self._get("/rest/agile/1.0/board", params={"projectKeyOrId": project_key, "maxResults": max_results})

    def list_sprints(self, board_id, state="active,future,closed", max_results=50):
        return self._get(f"/rest/agile/1.0/board/{board_id}/sprint", params={"state": state, "maxResults": max_results})

    def sprint_issues(self, sprint_id, fields=None, expand=None, max_results=1000):
        """Paginated: Agile API uses startAt (not nextPageToken)."""
        if max_results <= 0:
            return []
        all_issues = []
        page_size = 100
        start_at = 0
        while True:
            params = {"startAt": start_at, "maxResults": min(page_size, max_results - len(all_issues))}
            if fields is not None:
                params["fields"] = ",".join(fields)
            if expand:
                params["expand"] = expand
            data = self._get(f"/rest/agile/1.0/sprint/{sprint_id}/issue", params=params)
            issues = data.get("issues", [])
            all_issues.extend(issues)
            if len(all_issues) >= max_results or start_at + len(issues) >= data.get("total", 0) or not issues:
                break
            start_at += len(issues)
            time.sleep(0.1)
        return all_issues

    def get_sprint_report(self, board_id, sprint_id):
        """Try to get sprint report (may include added/removed counts). Returns None if not available."""
        try:
            return self._get(f"/rest/agile/1.0/board/{board_id}/sprint/{sprint_id}")
        except Exception:
            return None

    def board_issues(self, board_id, fields=None, max_results=2000):
        """Paginated: issues currently on a board (works for Kanban and Scrum)."""
        if max_results <= 0:
            return []
        all_issues = []
        page_size = 100
        start_at = 0
        while True:
            params = {"startAt": start_at, "maxResults": min(page_size, max_results - len(all_issues))}
            if fields is not None:
                params["fields"] = ",".join(fields)
            data = self._get(f"/rest/agile/1.0/board/{board_id}/issue", params=params)
            issues = data.get("issues", [])
            all_issues.extend(issues)
            if len(all_issues) >= max_results or start_at + len(issues) >= data.get("total", 0) or not issues:
                break
            start_at += len(issues)
            time.sleep(0.1)
        return all_issues

    def list_project_versions(self, project_key):
        return self._get(f"/rest/api/3/project/{project_key}/versions")


# ----------------------------
# Helpers
# ----------------------------
def parse_dt(s):
    if not s:
        return None
    try:
        return dtparser.isoparse(s)
    except (TypeError, ValueError):
        return None

def iso_week(dt: datetime):
    y, w, _ = dt.isocalendar()
    return f"{y}-W{w:02d}"

def percentile(values, p):
    if not values:
        return None
    values = sorted(values)
    k = (len(values) - 1) * (p / 100.0)
    f = math.floor(k)
    c = math.ceil(k)
    if f == c:
        return values[int(k)]
    return values[f] + (values[c] - values[f]) * (k - f)


# ----------------------------
# Metric extraction
# ----------------------------
def get_story_points_field_id(jira: JiraClient):
    # Common names: "Story Points", "Story point estimate"
    fields = jira.list_fields()
    candidates = []
    for f in fields:
        fid, name = f.get("id"), f.get("name")
        if fid is not None and name and "story point" in (name or "").lower():
            candidates.append((fid, name))
    return candidates  # list of (id, name)

def get_team_field_id(jira: JiraClient):
    """Find a custom field that looks like 'team' (e.g. Team, Squad, Development Team)."""
    fields = jira.list_fields()
    for f in fields:
        fid, name = f.get("id"), (f.get("name") or "")
        if fid is None or not name:
            continue
        if fid.startswith("customfield_") and "team" in name.lower():
            return (fid, name)
    return (None, None)

def get_sprint_field_id(jira: JiraClient):
    """Find the Sprint custom field (e.g. customfield_10020) for changelog analysis."""
    fields = jira.list_fields()
    for f in fields:
        fid, name = f.get("id"), (f.get("name") or "")
        if fid is None or not name:
            continue
        if fid.startswith("customfield_") and "sprint" in name.lower():
            return (fid, name)
    return (None, None)

def _added_after_sprint_start(issues, sprint_id, sprint_name, start_dt, sprint_field_id):
    """
    Count issues that were added to this sprint after sprint start (via changelog).
    start_dt: datetime (timezone-aware) of sprint start.
    Returns (count, list of issue keys added late).
    """
    if not sprint_field_id or not start_dt:
        return (0, [])
    added_late_keys = []
    sprint_id_str = str(sprint_id)
    for it in issues:
        histories = (it.get("changelog") or {}).get("histories") or []
        added_at = None  # when this issue was added to this sprint
        for h in sorted(histories, key=lambda x: x.get("created", "")):
            changed_at = parse_dt(h.get("created"))
            if not changed_at:
                continue
            for item in h.get("items") or []:
                if item.get("field") != sprint_field_id and item.get("field") != "Sprint":
                    continue
                to_val = item.get("to")
                to_str = (item.get("toString") or "")
                if not to_str and to_val is not None:
                    to_str = str(to_val) if not isinstance(to_val, list) else " ".join(str(x) for x in to_val)
                if sprint_id_str in to_str or (sprint_name and sprint_name in to_str):
                    added_at = changed_at
                    break
            if added_at is not None:
                break
        if added_at is not None and added_at > start_dt:
            added_late_keys.append(it.get("key") or "?")
    return (len(added_late_keys), added_late_keys)

def _component_breakdown(issues):
    """Return dict: component name -> issue count. Issues can have 0 or more components."""
    c = Counter()
    for it in issues:
        comps = (it.get("fields") or {}).get("components")
        if not isinstance(comps, list):
            c["(no component)"] += 1
            continue
        for comp in comps:
            if isinstance(comp, dict):
                name = comp.get("name") or comp.get("id") or "?"
                c[name] += 1
        if not comps:
            c["(no component)"] += 1
    return dict(c)

def _team_breakdown(issues, team_field_id):
    """Return dict: team value/name -> issue count. team_field_id is custom field id."""
    if not team_field_id:
        return {}
    c = Counter()
    for it in issues:
        raw = (it.get("fields") or {}).get(team_field_id)
        if raw is None:
            c["(no team)"] += 1
            continue
        if isinstance(raw, list):
            for x in raw:
                label = _team_field_value_to_label(x)
                c[label] += 1
            if not raw:
                c["(no team)"] += 1
        else:
            c[_team_field_value_to_label(raw)] += 1
    return dict(c)

def _team_field_value_to_label(x):
    if x is None:
        return "(no team)"
    if not isinstance(x, dict):
        return str(x)
    return x.get("value") or x.get("name") or x.get("displayName") or x.get("id") or "?"

def status_distribution(issues):
    c = Counter()
    for it in issues:
        st = (it.get("fields") or {}).get("status")
        if st and isinstance(st, dict):
            name = st.get("name")
            if name:
                c[name] += 1
    return c

def categorize_status(issues):
    # group by statusCategory (new/indeterminate/done)
    c = Counter()
    for it in issues:
        st = (it.get("fields") or {}).get("status")
        cat = (st.get("statusCategory") or {}).get("key") if isinstance(st, dict) else None
        if cat:
            c[cat] += 1
    return c

def throughput_weekly(issues, done_date_field="resolutiondate"):
    weekly = Counter()
    for it in issues:
        dt = parse_dt((it.get("fields") or {}).get(done_date_field))
        if not dt:
            continue
        weekly[iso_week(dt)] += 1
    return weekly

def lead_time_days(issue):
    fields = issue.get("fields") or {}
    created = parse_dt(fields.get("created"))
    resolved = parse_dt(fields.get("resolutiondate"))
    if created and resolved:
        return (resolved - created).total_seconds() / 86400.0
    return None

def cycle_time_days_from_changelog(issue):
    """
    Cycle time = time between first entering an "in progress" category and reaching "done".
    Requires expand=changelog. Changelog is at issue root in search response.
    """
    fields = issue.get("fields") or {}
    created = parse_dt(fields.get("created"))
    resolved = parse_dt(fields.get("resolutiondate"))
    if not resolved:
        return None

    histories = (issue.get("changelog") or {}).get("histories", [])
    in_progress_start = None

    # Find first time it moved into INPROGRESS_CATEGORY
    for h in sorted(histories, key=lambda x: x.get("created", "")):
        changed_at = parse_dt(h.get("created"))
        for item in h.get("items", []):
            if item.get("field") == "status":
                # We only have status names here, but we can approximate via current statuses mapping if needed.
                # As a practical heuristic: treat any transition to a status containing "In Progress", "Doing", "Dev", "Review" as in progress.
                to_str = (item.get("toString") or "").lower()
                if in_progress_start is None and any(k in to_str for k in ["in progress", "doing", "development", "dev", "review", "testing", "qa"]):
                    in_progress_start = changed_at

    # Fallback: if never found, use created as start (not ideal)
    if in_progress_start is None:
        in_progress_start = created

    if in_progress_start and resolved:
        return (resolved - in_progress_start).total_seconds() / 86400.0
    return None

def summarize_time_metrics(values):
    values = [v for v in values if v is not None and v >= 0]
    if not values:
        return {}
    return {
        "count": len(values),
        "avg_days": sum(values) / len(values),
        "p50_days": percentile(values, 50),
        "p85_days": percentile(values, 85),
        "p95_days": percentile(values, 95),
    }

def bug_age_days(issue, now=None):
    now = now or datetime.now(timezone.utc)
    created = parse_dt((issue.get("fields") or {}).get("created"))
    if not created:
        return None
    return (now - created).total_seconds() / 86400.0

def _is_done(issue):
    """True if issue is in done status category; avoids KeyError on malformed data."""
    try:
        return issue["fields"]["status"]["statusCategory"]["key"] == DONE_CATEGORY
    except (KeyError, TypeError):
        return False


# ----------------------------
# WIP phase classification
# ----------------------------
_PHASE_EXACT = {
    "not_started": {
        "to do", "new", "backlog", "requirements gathering", "open",
        "selected for development", "ready for development",
    },
    "in_progress": {
        "in progress", "in dev", "doing", "development", "in development",
    },
    "review_qa": {
        "for review", "ready for qa", "in testing", "staging", "qa passed",
        "finished", "approved", "code review", "in review", "qa", "testing",
    },
    "blocked": {
        "blocked", "on hold", "impediment",
    },
}

def _classify_phase(status_name):
    lower = (status_name or "").strip().lower()
    for phase, names in _PHASE_EXACT.items():
        if lower in names:
            return phase
    if any(k in lower for k in ("todo", "to do", "new", "backlog", "open", "requirement")):
        return "not_started"
    if any(k in lower for k in ("progress", "dev", "doing")):
        return "in_progress"
    if any(k in lower for k in ("review", "qa", "test", "staging", "approved", "finished")):
        return "review_qa"
    if any(k in lower for k in ("block", "hold", "impediment")):
        return "blocked"
    return "in_progress"

def wip_by_phase(status_dist):
    phases = {"not_started": 0, "in_progress": 0, "review_qa": 0, "blocked": 0}
    for status_name, count in status_dist.items():
        phases[_classify_phase(status_name)] += count
    return phases


# ----------------------------
# Lead time distribution (for retroactive-logging detection)
# ----------------------------
def lead_time_distribution(issues, done_date_field="resolutiondate"):
    buckets = {"under_1h": 0, "1h_to_1d": 0, "1d_to_7d": 0, "7d_to_30d": 0, "over_30d": 0}
    total = 0
    for it in issues:
        lt = lead_time_days(it)
        if lt is None:
            continue
        total += 1
        hours = lt * 24
        if hours < 1:
            buckets["under_1h"] += 1
        elif lt < 1:
            buckets["1h_to_1d"] += 1
        elif lt < 7:
            buckets["1d_to_7d"] += 1
        elif lt < 30:
            buckets["7d_to_30d"] += 1
        else:
            buckets["over_30d"] += 1
    buckets["total"] = total
    return buckets

def _sprint_assignees(issues):
    """
    From a list of issues (with assignee in fields), return unique assignees.
    Returns (count, list of display names sorted).
    Jira assignee can be null or { accountId, displayName, ... }.
    """
    seen = set()
    names = []
    for it in issues:
        assignee = (it.get("fields") or {}).get("assignee")
        if not assignee or not isinstance(assignee, dict):
            continue
        aid = assignee.get("accountId")
        display = assignee.get("displayName") or assignee.get("name") or aid or "?"
        if aid and aid not in seen:
            seen.add(aid)
            names.append(display)
        elif not aid and display not in seen:
            seen.add(display)
            names.append(display)
    return len(seen), sorted(names)


# ----------------------------
# Phase 1 helper functions (use already-fetched data)
# ----------------------------
def _status_by_component(issues):
    """Cross-tabulation: component -> {status_name: count}."""
    result = defaultdict(Counter)
    for it in issues:
        st = (it.get("fields") or {}).get("status")
        status_name = st.get("name") if isinstance(st, dict) else None
        if not status_name:
            continue
        comps = (it.get("fields") or {}).get("components")
        if not isinstance(comps, list) or not comps:
            result["(no component)"][status_name] += 1
        else:
            for comp in comps:
                if isinstance(comp, dict):
                    name = comp.get("name") or comp.get("id") or "?"
                    result[name][status_name] += 1
    return {k: dict(v) for k, v in result.items()}

def _resolution_breakdown(issues):
    """Counter of resolution types for done issues."""
    c = Counter()
    for it in issues:
        res = (it.get("fields") or {}).get("resolution")
        name = res.get("name") if isinstance(res, dict) else None
        c[name or "(unresolved)"] += 1
    return dict(c)

def _issuetype_breakdown(issues):
    c = Counter()
    for it in issues:
        itype = (it.get("fields") or {}).get("issuetype")
        name = itype.get("name") if isinstance(itype, dict) else None
        c[name or "(unknown)"] += 1
    return dict(c)

def _priority_breakdown(issues):
    c = Counter()
    for it in issues:
        pri = (it.get("fields") or {}).get("priority")
        name = pri.get("name") if isinstance(pri, dict) else None
        c[name or "(none)"] += 1
    return dict(c)

def _unassigned_count(issues):
    return sum(1 for it in issues if not (it.get("fields") or {}).get("assignee"))

def _resolution_by_weekday(issues):
    days = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
    c = Counter()
    for it in issues:
        dt = parse_dt((it.get("fields") or {}).get("resolutiondate"))
        if dt:
            c[days[dt.weekday()]] += 1
    return {d: c.get(d, 0) for d in days}

def _velocity_cv(throughputs):
    """Coefficient of variation = std/mean. Returns None if < 2 data points."""
    if len(throughputs) < 2:
        return None
    mean = sum(throughputs) / len(throughputs)
    if mean == 0:
        return None
    variance = sum((x - mean) ** 2 for x in throughputs) / len(throughputs)
    return round((variance ** 0.5) / mean, 3)

def _assignee_breakdown(issues):
    c = Counter()
    for it in issues:
        assignee = (it.get("fields") or {}).get("assignee")
        if assignee and isinstance(assignee, dict):
            name = assignee.get("displayName") or assignee.get("name") or "?"
            c[name] += 1
        else:
            c["(unassigned)"] += 1
    return dict(c)

def _gini_coefficient(counts):
    """Gini coefficient (0 = equal, 1 = one person does everything)."""
    if not counts or len(counts) < 2:
        return 0.0
    counts = sorted(counts)
    n = len(counts)
    total = sum(counts)
    if total == 0:
        return 0.0
    cumulative = 0
    gini_sum = 0
    for i, x in enumerate(counts):
        cumulative += x
        gini_sum += (2 * (i + 1) - n - 1) * x
    return round(gini_sum / (n * total), 3)

def _bulk_closures(issues, threshold=10):
    """Days with > threshold resolutions."""
    daily = Counter()
    for it in issues:
        dt = parse_dt((it.get("fields") or {}).get("resolutiondate"))
        if dt:
            daily[dt.strftime("%Y-%m-%d")] += 1
    return [{"date": d, "count": c} for d, c in sorted(daily.items()) if c > threshold]


# ----------------------------
# Phase 2 helper functions (changelog mining)
# ----------------------------
_ACTIVE_STATUS_KEYWORDS = frozenset({
    "in progress", "in dev", "doing", "development", "review", "testing",
    "qa", "code review", "for review", "staging", "in testing",
})

def _is_active_status(name):
    lower = (name or "").strip().lower()
    return lower in _ACTIVE_STATUS_KEYWORDS or any(
        k in lower for k in ("progress", "dev", "doing", "review", "test"))

def _status_path_analysis(issues):
    """Reconstruct status paths from changelog; detect issues that skip active work."""
    paths = Counter()
    skip_count = 0
    total = 0

    for it in issues:
        if not _is_done(it):
            continue
        total += 1
        histories = (it.get("changelog") or {}).get("histories", [])
        status_changes = []
        for h in sorted(histories, key=lambda x: x.get("created", "")):
            for item in h.get("items", []):
                if item.get("field") == "status":
                    status_changes.append(item.get("toString") or "")

        if not status_changes:
            st = (it.get("fields") or {}).get("status")
            if isinstance(st, dict) and st.get("name"):
                status_changes = [st["name"]]

        if len(status_changes) > 5:
            path_str = " -> ".join(status_changes[:2]) + " -> ... -> " + " -> ".join(status_changes[-2:])
        else:
            path_str = " -> ".join(status_changes) if status_changes else "(no transitions)"
        paths[path_str] += 1

        visited_active = any(_is_active_status(s) for s in status_changes[:-1])
        if not visited_active:
            skip_count += 1

    return {
        "total": total,
        "skip_count": skip_count,
        "skip_pct": round(skip_count / total * 100, 1) if total else 0,
        "top_paths": [{"path": p, "count": c} for p, c in paths.most_common(15)],
    }

def _time_in_status(issues):
    """Compute time in each status from changelog transitions."""
    status_durations = defaultdict(list)

    for it in issues:
        fields = it.get("fields") or {}
        created = parse_dt(fields.get("created"))
        resolved = parse_dt(fields.get("resolutiondate"))
        histories = (it.get("changelog") or {}).get("histories", [])

        transitions = []
        for h in sorted(histories, key=lambda x: x.get("created", "")):
            changed_at = parse_dt(h.get("created"))
            if not changed_at:
                continue
            for item in h.get("items", []):
                if item.get("field") == "status":
                    transitions.append({
                        "at": changed_at,
                        "from": item.get("fromString") or "",
                        "to": item.get("toString") or "",
                    })

        if not transitions:
            continue

        prev_time = created
        prev_status = transitions[0]["from"] if transitions else None
        for t in transitions:
            if prev_time and prev_status:
                hours = (t["at"] - prev_time).total_seconds() / 3600.0
                if hours >= 0:
                    status_durations[prev_status].append(hours)
            prev_status = t["to"]
            prev_time = t["at"]

        if prev_status and prev_time and resolved:
            hours = (resolved - prev_time).total_seconds() / 3600.0
            if hours >= 0:
                status_durations[prev_status].append(hours)

    result = {}
    for status, durations in status_durations.items():
        if not durations:
            continue
        durations_sorted = sorted(durations)
        result[status] = {
            "median_hours": round(percentile(durations_sorted, 50), 2),
            "avg_hours": round(sum(durations_sorted) / len(durations_sorted), 2),
            "count": len(durations_sorted),
        }
    return result

def _closer_analysis(issues):
    """Who makes the final transition to done status vs assignee."""
    closers = Counter()
    closer_not_assignee = 0
    total = 0
    with_closer = 0
    DONE_KW = {"done", "closed", "resolved", "complete", "finished"}

    for it in issues:
        if not _is_done(it):
            continue
        total += 1
        histories = (it.get("changelog") or {}).get("histories", [])
        closer = None
        for h in sorted(histories, key=lambda x: x.get("created", ""), reverse=True):
            for item in h.get("items", []):
                if item.get("field") == "status":
                    to_lower = (item.get("toString") or "").lower()
                    if any(k in to_lower for k in DONE_KW):
                        author = h.get("author") or {}
                        closer = author.get("displayName") or author.get("name") or "?"
                        break
            if closer:
                break

        if closer:
            with_closer += 1
            closers[closer] += 1
            assignee = (it.get("fields") or {}).get("assignee")
            assignee_name = (assignee.get("displayName") or assignee.get("name") or "") if isinstance(assignee, dict) else ""
            if closer != assignee_name:
                closer_not_assignee += 1

    return {
        "total_analyzed": total,
        "with_closer": with_closer,
        "top_closers": [{"name": n, "count": c} for n, c in closers.most_common(10)],
        "closer_not_assignee_count": closer_not_assignee,
        "closer_not_assignee_pct": round(closer_not_assignee / with_closer * 100, 1) if with_closer else 0,
    }

def _reopen_count(issues):
    """Count issues re-opened (done -> non-done transition in changelog)."""
    reopened = 0
    total = 0
    DONE_KW = {"done", "closed", "resolved", "complete", "finished"}

    for it in issues:
        total += 1
        histories = (it.get("changelog") or {}).get("histories", [])
        was_done = False
        for h in sorted(histories, key=lambda x: x.get("created", "")):
            for item in h.get("items", []):
                if item.get("field") == "status":
                    to_lower = (item.get("toString") or "").lower()
                    if any(k in to_lower for k in DONE_KW):
                        was_done = True
                    elif was_done:
                        reopened += 1
                        was_done = False

    return {
        "total": total,
        "reopened_count": reopened,
        "reopened_pct": round(reopened / total * 100, 1) if total else 0,
    }

def _flow_efficiency(time_in_status_data):
    """active time / total time from time-in-status aggregates."""
    active_total = 0
    wait_total = 0
    for status, data in time_in_status_data.items():
        hours = data.get("avg_hours", 0) * data.get("count", 0)
        if _is_active_status(status):
            active_total += hours
        else:
            wait_total += hours
    total = active_total + wait_total
    return {
        "active_hours": round(active_total, 1),
        "wait_hours": round(wait_total, 1),
        "efficiency_pct": round(active_total / total * 100, 1) if total > 0 else 0,
    }

def _sprint_end_closures(sprint_issues, sprint_end_dt):
    """Count issues resolved in the final 24h of a sprint."""
    if not sprint_end_dt:
        return None, None
    cutoff = sprint_end_dt - timedelta(hours=24)
    upper = sprint_end_dt + timedelta(hours=6)
    total_done = 0
    last_24h = 0
    for it in sprint_issues:
        if not _is_done(it):
            continue
        total_done += 1
        resolved = parse_dt((it.get("fields") or {}).get("resolutiondate"))
        if resolved and resolved >= cutoff and resolved <= upper:
            last_24h += 1
    pct = round(last_24h / total_done * 100, 1) if total_done else 0
    return last_24h, pct


# ----------------------------
# Phase 3 helper functions (need additional fields)
# ----------------------------
def _empty_description_pct(issues):
    if not issues:
        return 0
    empty = 0
    for it in issues:
        desc = (it.get("fields") or {}).get("description")
        if desc is None:
            empty += 1
        elif isinstance(desc, str) and len(desc.strip()) < 20:
            empty += 1
        elif isinstance(desc, dict):
            content = desc.get("content") or []
            if not content:
                empty += 1
    return round(empty / len(issues) * 100, 1)

def _zero_comment_pct(issues):
    if not issues:
        return 0
    zero = 0
    for it in issues:
        comment = (it.get("fields") or {}).get("comment")
        if comment is None:
            zero += 1
        elif isinstance(comment, dict) and comment.get("total", 0) == 0:
            zero += 1
        elif isinstance(comment, list) and len(comment) == 0:
            zero += 1
    return round(zero / len(issues) * 100, 1)

def _orphan_pct(issues):
    if not issues:
        return 0
    orphan = 0
    for it in issues:
        links = (it.get("fields") or {}).get("issuelinks")
        if not links or (isinstance(links, list) and len(links) == 0):
            orphan += 1
    return round(orphan / len(issues) * 100, 1)


def _project_key(issue):
    p = (issue.get("fields") or {}).get("project")
    return p.get("key", "?") if isinstance(p, dict) else "?"


# ----------------------------
# Phase 4/5/6: New metric helpers
# ----------------------------

def _assignee_change_near_resolution(issues, hours=24):
    """Detect issues where assignee changed within last N hours before resolution (from changelog)."""
    total = 0
    changed = 0
    offenders = Counter()
    for it in issues:
        if not _is_done(it):
            continue
        total += 1
        resolved = parse_dt((it.get("fields") or {}).get("resolutiondate"))
        if not resolved:
            continue
        cutoff = resolved - timedelta(hours=hours)
        histories = (it.get("changelog") or {}).get("histories", [])
        found = False
        for h in sorted(histories, key=lambda x: x.get("created", ""), reverse=True):
            changed_at = parse_dt(h.get("created"))
            if not changed_at or changed_at < cutoff:
                break
            for item in h.get("items", []):
                if item.get("field") == "assignee":
                    changed += 1
                    author = h.get("author") or {}
                    offenders[author.get("displayName") or "?"] += 1
                    found = True
                    break
            if found:
                break
    return {
        "total": total,
        "changed_count": changed,
        "changed_pct": round(changed / total * 100, 1) if total else 0,
        "top_changers": [{"name": n, "count": c} for n, c in offenders.most_common(10)],
    }


def _comment_timing(issues):
    """Analyze comment timing relative to resolution date."""
    total_issues = 0
    with_post_resolution = 0
    total_comments = 0
    post_res_comments = 0
    for it in issues:
        if not _is_done(it):
            continue
        total_issues += 1
        resolved = parse_dt((it.get("fields") or {}).get("resolutiondate"))
        if not resolved:
            continue
        comment = (it.get("fields") or {}).get("comment")
        comments = []
        if isinstance(comment, dict):
            comments = comment.get("comments", [])
        elif isinstance(comment, list):
            comments = comment
        if not comments:
            continue
        has_post = False
        for c in comments:
            total_comments += 1
            created = parse_dt(c.get("created"))
            if created and created > resolved:
                post_res_comments += 1
                has_post = True
        if has_post:
            with_post_resolution += 1
    return {
        "total_issues": total_issues,
        "with_post_resolution_comments": with_post_resolution,
        "post_resolution_comment_pct": round(with_post_resolution / total_issues * 100, 1) if total_issues else 0,
        "total_comments": total_comments,
        "post_resolution_comment_count": post_res_comments,
    }


def _worklog_analysis(issues, sp_field=None):
    """Analyze worklog patterns from issues fetched with fields=worklog."""
    total_done = 0
    zero_worklog = 0
    post_resolution = 0
    bulk_entries = 0
    total_hours = 0
    by_person = Counter()
    by_dow = Counter()
    sp_hours_pairs = []

    for it in issues:
        if not _is_done(it):
            continue
        total_done += 1
        resolved = parse_dt((it.get("fields") or {}).get("resolutiondate"))
        worklog = (it.get("fields") or {}).get("worklog")
        worklogs = []
        if isinstance(worklog, dict):
            worklogs = worklog.get("worklogs", [])
        elif isinstance(worklog, list):
            worklogs = worklog

        if not worklogs:
            zero_worklog += 1
            continue

        has_post_res = False
        issue_hours = 0
        for wl in worklogs:
            secs = wl.get("timeSpentSeconds", 0)
            hours = secs / 3600.0
            issue_hours += hours
            total_hours += hours
            if hours > 8:
                bulk_entries += 1
            author = wl.get("author") or wl.get("updateAuthor") or {}
            by_person[author.get("displayName") or "?"] += hours
            started = parse_dt(wl.get("started"))
            if started:
                by_dow[["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"][started.weekday()]] += hours
            if resolved and started and started > resolved:
                has_post_res = True
        if has_post_res:
            post_resolution += 1

        if sp_field:
            sp_val = (it.get("fields") or {}).get(sp_field)
            if sp_val is not None and issue_hours > 0:
                try:
                    sp_hours_pairs.append((float(sp_val), issue_hours))
                except (TypeError, ValueError):
                    pass

    sp_correlation = None
    if len(sp_hours_pairs) >= 5:
        xs = [p[0] for p in sp_hours_pairs]
        ys = [p[1] for p in sp_hours_pairs]
        mx, my = sum(xs) / len(xs), sum(ys) / len(ys)
        num = sum((x - mx) * (y - my) for x, y in zip(xs, ys))
        dx = sum((x - mx) ** 2 for x in xs) ** 0.5
        dy = sum((y - my) ** 2 for y in ys) ** 0.5
        if dx > 0 and dy > 0:
            sp_correlation = round(num / (dx * dy), 3)

    weekend_hours = by_dow.get("Sat", 0) + by_dow.get("Sun", 0)
    worklog_gini = _gini_coefficient(list(by_person.values())) if by_person else 0

    return {
        "total_done": total_done,
        "zero_worklog_count": zero_worklog,
        "zero_worklog_pct": round(zero_worklog / total_done * 100, 1) if total_done else 0,
        "post_resolution_worklog_count": post_resolution,
        "post_resolution_worklog_pct": round(post_resolution / total_done * 100, 1) if total_done else 0,
        "bulk_entries_count": bulk_entries,
        "total_hours": round(total_hours, 1),
        "by_person": dict(sorted(((k, round(v, 1)) for k, v in by_person.items()), key=lambda x: -x[1])[:20]),
        "by_dow": {d: round(by_dow.get(d, 0), 1) for d in ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]},
        "weekend_pct": round(weekend_hours / total_hours * 100, 1) if total_hours > 0 else 0,
        "worklog_gini": worklog_gini,
        "sp_worklog_correlation": sp_correlation,
        "sp_worklog_pairs_count": len(sp_hours_pairs),
    }


def _sp_trend(issues, sp_field):
    """Group average story points per issue by month, per project."""
    if not sp_field:
        return {"by_month": {}, "by_project": {}, "inflation_detected": False}
    by_month = defaultdict(list)
    by_proj_month = defaultdict(lambda: defaultdict(list))
    for it in issues:
        resolved = parse_dt((it.get("fields") or {}).get("resolutiondate"))
        sp = (it.get("fields") or {}).get(sp_field)
        if resolved and sp is not None:
            try:
                sp_val = float(sp)
            except (TypeError, ValueError):
                continue
            month_key = resolved.strftime("%Y-%m")
            by_month[month_key].append(sp_val)
            pk = _project_key(it)
            by_proj_month[pk][month_key].append(sp_val)

    result = {}
    for month in sorted(by_month):
        vals = by_month[month]
        result[month] = {"avg_sp": round(sum(vals) / len(vals), 2), "count": len(vals)}

    per_project = {}
    for pk, months in by_proj_month.items():
        per_project[pk] = {}
        for month in sorted(months):
            vals = months[month]
            per_project[pk][month] = {"avg_sp": round(sum(vals) / len(vals), 2), "count": len(vals)}

    months_sorted = sorted(by_month.keys())
    inflation_flag = False
    if len(months_sorted) >= 4:
        mid = len(months_sorted) // 2
        first_half = [sp for m in months_sorted[:mid] for sp in by_month[m]]
        second_half = [sp for m in months_sorted[mid:] for sp in by_month[m]]
        if first_half and second_half:
            avg_first = sum(first_half) / len(first_half)
            avg_second = sum(second_half) / len(second_half)
            if avg_first > 0 and (avg_second - avg_first) / avg_first > 0.3:
                inflation_flag = True

    return {"by_month": result, "by_project": per_project, "inflation_detected": inflation_flag}


def _created_by_week(issues):
    """Group issues by creation week."""
    weekly = Counter()
    for it in issues:
        created = parse_dt((it.get("fields") or {}).get("created"))
        if created:
            weekly[iso_week(created)] += 1
    return dict(weekly)


def _bug_creation_by_week(done_issues, open_bugs):
    """Count bug creation by week from both resolved and open bugs."""
    weekly = Counter()
    for it in done_issues:
        itype = (it.get("fields") or {}).get("issuetype")
        if isinstance(itype, dict) and (itype.get("name") or "").lower() == "bug":
            created = parse_dt((it.get("fields") or {}).get("created"))
            if created:
                weekly[iso_week(created)] += 1
    for it in open_bugs:
        created = parse_dt((it.get("fields") or {}).get("created"))
        if created:
            weekly[iso_week(created)] += 1
    return dict(weekly)


def _issue_components(issue):
    """Extract component names from an issue, defaulting to '(no component)'."""
    comps = (issue.get("fields") or {}).get("components")
    if not isinstance(comps, list) or not comps:
        return ["(no component)"]
    names = []
    for c in comps:
        if isinstance(c, dict):
            names.append(c.get("name") or c.get("id") or "?")
    return names if names else ["(no component)"]


# ----------------------------
# Main
# ----------------------------
def main():
    run_ts = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    results = {"run_iso_ts": run_ts, "projects": PROJECT_KEYS}

    jira = JiraClient()
    projects_csv = ",".join(PROJECT_KEYS)
    projects_jql = _jql_project_list(PROJECT_KEYS)  # quoted reserved words (e.g. "IN")

    print("Finding Story Points fields...")
    sp_candidates = get_story_points_field_id(jira)
    if sp_candidates:
        print("Story points field candidates:")
        for fid, name in sp_candidates[:10]:
            print(f"  {fid}  -> {name}")
        # Pick the first by default; change if needed:
        STORY_POINTS_FIELD = sp_candidates[0][0]
        print(f"Using story points field: {STORY_POINTS_FIELD} ({sp_candidates[0][1]})")
    else:
        STORY_POINTS_FIELD = None
        print("No story points field found by name. Velocity will be issue-count based unless you set it.")

    TEAM_FIELD_ID, TEAM_FIELD_NAME = get_team_field_id(jira)
    if TEAM_FIELD_ID:
        print(f"Using team field: {TEAM_FIELD_ID} ({TEAM_FIELD_NAME})")
    else:
        print("No custom field with 'team' in name found. Team breakdown will be empty.")

    SPRINT_FIELD_ID, _ = get_sprint_field_id(jira)
    if SPRINT_FIELD_ID:
        print(f"Using Sprint field for scope changes: {SPRINT_FIELD_ID}")
    else:
        print("No Sprint custom field found. 'Added after sprint start' will not be computed.")

    # ---------
    # 1) Status distribution + WIP aging + blockers
    # ---------
    base_fields = ["project", "issuetype", "status", "assignee", "priority", "created",
                    "resolutiondate", "resolution", "labels", "summary", "components",
                    "description", "comment", "issuelinks", "worklog"]
    fields_with_team = list(base_fields) + ([TEAM_FIELD_ID] if TEAM_FIELD_ID else [])
    if STORY_POINTS_FIELD:
        fields_with_team.append(STORY_POINTS_FIELD)

    print("\nPulling current (not done) issues for status distribution & WIP aging...")
    jql_wip = f'project in ({projects_jql}) AND statusCategory != {DONE_CATEGORY}'
    wip_issues = jira.search(jql_wip, fields=fields_with_team, max_results=5000)

    print(f"WIP issues pulled: {len(wip_issues)}")
    status_dist = status_distribution(wip_issues)
    status_cat = categorize_status(wip_issues)

    now = datetime.now(timezone.utc)
    wip_ages = []
    for it in wip_issues:
        age = bug_age_days(it, now=now)
        if age is not None:
            wip_ages.append(age)

    print("\nStatus category counts (new / in progress / done):")
    for k, v in status_cat.items():
        print(f"  {k}: {v}")

    print("\nTop statuses (WIP):")
    for st, cnt in status_dist.most_common(15):
        print(f"  {st}: {cnt}")

    wip_aging = summarize_time_metrics(wip_ages)
    results["wip_count"] = len(wip_issues)
    results["status_category"] = dict(status_cat)
    results["status_distribution"] = dict(status_dist)
    results["wip_by_phase"] = wip_by_phase(dict(status_dist))
    results["wip_aging_days"] = wip_aging
    results["wip_components"] = _component_breakdown(wip_issues)
    if TEAM_FIELD_ID:
        results["wip_teams"] = _team_breakdown(wip_issues, TEAM_FIELD_ID)
    else:
        results["wip_teams"] = {}
    print("\nAging WIP summary (days since created):", wip_aging)
    if results["wip_components"]:
        print("WIP by component:", dict(sorted(results["wip_components"].items(), key=lambda x: -x[1])[:10]))
    if results["wip_teams"]:
        print("WIP by team:", dict(sorted(results["wip_teams"].items(), key=lambda x: -x[1])[:10]))

    # Phase 1 WIP metrics
    results["wip_status_by_component"] = _status_by_component(wip_issues)
    results["wip_issuetype"] = _issuetype_breakdown(wip_issues)
    results["wip_priority"] = _priority_breakdown(wip_issues)
    results["unassigned_wip_count"] = _unassigned_count(wip_issues)
    print(f"Unassigned WIP: {results['unassigned_wip_count']} / {len(wip_issues)}")

    # Phase 3 WIP metrics
    results["empty_description_wip_pct"] = _empty_description_pct(wip_issues)

    # Phase 6a: WIP by assignee
    wip_ab = _assignee_breakdown(wip_issues)
    results["wip_assignees"] = dict(sorted(wip_ab.items(), key=lambda x: -x[1])[:30])
    wip_per_person = [v for k, v in wip_ab.items() if k != "(unassigned)"]
    results["avg_wip_per_assignee"] = round(sum(wip_per_person) / len(wip_per_person), 1) if wip_per_person else 0
    print(f"WIP assignees: {len(wip_ab)}, avg WIP/person: {results['avg_wip_per_assignee']}")

    print("\nPulling blockers (heuristic JQL)...")
    blocked_jql = f'project in ({projects_jql}) AND statusCategory != {DONE_CATEGORY} AND {BLOCKED_JQL}'
    blocked_issues = jira.search(blocked_jql, fields=fields_with_team, max_results=2000)
    print(f"Blocked issues: {len(blocked_issues)}")
    blocked_with_age = []
    if blocked_issues:
        # Show top 10 oldest blocked
        for it in blocked_issues:
            age = bug_age_days(it, now=now)
            blocked_with_age.append((age or -1, it["key"], it["fields"].get("summary", "") or ""))

        blocked_with_age.sort(reverse=True)
        print("Oldest blocked issues (top 10):")
        for age, key, _ in blocked_with_age[:10]:
            print(f"  {key} - {age:.1f} days")
    results["blocked_count"] = len(blocked_issues)
    results["blocked_oldest"] = [(key, round(age, 1)) for age, key, _ in sorted(blocked_with_age, reverse=True)[:10]]

    # ---------
    # 2) Throughput per week (done issues)
    # ---------
    print("\nPulling done issues for throughput + lead time...")
    # last 180 days, adjust as needed
    jql_done = f'project in ({projects_jql}) AND statusCategory = {DONE_CATEGORY} AND resolved >= -180d'
    done_issues = jira.search(jql_done, fields=fields_with_team, max_results=10000)

    print(f"Done issues pulled (last 180d): {len(done_issues)}")
    weekly = throughput_weekly(done_issues)
    weekly_sorted = sorted(weekly.keys())[-12:]
    results["throughput_by_week"] = {wk: weekly[wk] for wk in weekly_sorted}
    print("\nThroughput by ISO week (issues resolved):")
    for wk in weekly_sorted:
        print(f"  {wk}: {weekly[wk]}")

    # Lead time
    lead_times = [lead_time_days(it) for it in done_issues]
    lead_summary = summarize_time_metrics(lead_times)
    results["lead_time_days"] = lead_summary
    print("\nLead time summary (created -> resolved):", lead_summary)

    # Lead time distribution (for retroactive-logging detection)
    lt_dist = lead_time_distribution(done_issues)
    results["lead_time_distribution"] = lt_dist
    print("Lead time distribution:", lt_dist)

    # Phase 1 done-issues metrics
    results["resolution_breakdown"] = _resolution_breakdown(done_issues)
    results["done_issuetype"] = _issuetype_breakdown(done_issues)
    results["resolution_by_weekday"] = _resolution_by_weekday(done_issues)
    ab = _assignee_breakdown(done_issues)
    results["done_assignees"] = dict(sorted(ab.items(), key=lambda x: -x[1])[:20])
    assignee_counts = [v for k, v in ab.items() if k != "(unassigned)"]
    results["workload_gini"] = _gini_coefficient(assignee_counts)
    results["bulk_closure_days"] = _bulk_closures(done_issues)
    print(f"Resolution types: {results['resolution_breakdown']}")
    print(f"Workload Gini: {results['workload_gini']}")
    print(f"Bulk closure days (>{10} resolutions): {len(results['bulk_closure_days'])}")

    # Phase 3 done-issues metrics
    results["empty_description_done_pct"] = _empty_description_pct(done_issues)
    results["zero_comment_done_pct"] = _zero_comment_pct(done_issues)
    results["orphan_done_pct"] = _orphan_pct(done_issues)
    print(f"Empty description (done): {results['empty_description_done_pct']}%")
    print(f"Zero comments (done): {results['zero_comment_done_pct']}%")
    print(f"Orphan issues (done): {results['orphan_done_pct']}%")

    # Phase 4a: Story point inflation
    results["sp_trend"] = _sp_trend(done_issues, STORY_POINTS_FIELD)
    if results["sp_trend"]["inflation_detected"]:
        print("  WARNING: Story point inflation detected (avg SP/issue up >30%)")

    # Phase 5a: Created vs Resolved trend
    print("\nPulling created issues (last 180d) for trend analysis...")
    jql_created = f'project in ({projects_jql}) AND created >= -180d'
    try:
        created_issues = jira.search(jql_created, fields=["project", "issuetype", "created", "components"], max_results=10000)
        results["created_by_week"] = _created_by_week(created_issues)
        print(f"  Created issues (last 180d): {len(created_issues)}")
    except Exception as e:
        results["created_by_week"] = {}
        print(f"  Created issues query failed: {e}")

    # ---------
    # 3) Cycle time from changelog (sample or full)
    # ---------
    # Changelog is heavier; start with last 90 days to keep it reasonable.
    print("\nPulling done issues (last 90d) WITH changelog for cycle time...")
    jql_done_90 = f'project in ({projects_jql}) AND statusCategory = {DONE_CATEGORY} AND resolved >= -90d'
    done_issues_90 = jira.search(jql_done_90, fields=fields_with_team, expand="changelog", max_results=3000)
    cycle_times = [cycle_time_days_from_changelog(it) for it in done_issues_90]
    cycle_summary = summarize_time_metrics(cycle_times)
    results["cycle_time_days"] = cycle_summary
    print("Cycle time summary (heuristic first in-progress -> resolved):", cycle_summary)

    # Phase 2 changelog-based metrics
    print("\nMining changelog for status paths, time-in-status, closers, reopens...")
    results["status_path_analysis"] = _status_path_analysis(done_issues_90)
    print(f"  Status skip: {results['status_path_analysis']['skip_count']}/{results['status_path_analysis']['total']} ({results['status_path_analysis']['skip_pct']}%)")
    tis = _time_in_status(done_issues_90)
    results["time_in_status"] = tis
    results["closer_analysis"] = _closer_analysis(done_issues_90)
    print(f"  Closer != assignee: {results['closer_analysis']['closer_not_assignee_pct']}%")
    results["reopen_analysis"] = _reopen_count(done_issues_90)
    print(f"  Reopened: {results['reopen_analysis']['reopened_count']} ({results['reopen_analysis']['reopened_pct']}%)")
    results["flow_efficiency"] = _flow_efficiency(tis)
    print(f"  Flow efficiency: {results['flow_efficiency']['efficiency_pct']}%")

    # Phase 4c: Assignee change near resolution
    results["assignee_change_near_resolution"] = _assignee_change_near_resolution(done_issues_90)
    print(f"  Assignee change near resolution: {results['assignee_change_near_resolution']['changed_pct']}%")

    # Phase 4e: Comment timing
    results["comment_timing"] = _comment_timing(done_issues_90)
    print(f"  Post-resolution comments: {results['comment_timing']['post_resolution_comment_pct']}%")

    # Phase 4d/6b/6e: Worklog analysis
    results["worklog_analysis"] = _worklog_analysis(done_issues_90, sp_field=STORY_POINTS_FIELD)
    print(f"  Zero-worklog done: {results['worklog_analysis']['zero_worklog_pct']}%, Post-res worklogs: {results['worklog_analysis']['post_resolution_worklog_pct']}%")

    # ---------
    # 4) Bugs: open, average age, oldest
    # ---------
    print("\nPulling open bugs...")
    jql_open_bugs = f'project in ({projects_jql}) AND issuetype = Bug AND statusCategory != {DONE_CATEGORY}'
    open_bugs = jira.search(jql_open_bugs, fields=fields_with_team, max_results=5000)
    print(f"Open bugs: {len(open_bugs)}")

    bug_ages = [(bug_age_days(it, now=now) or -1, it.get("key", "?"), (it.get("fields") or {}).get("summary", "") or "", _project_key(it)) for it in open_bugs]
    bug_age_values = [a for a, *_ in bug_ages if a >= 0]
    print("Open bug age summary (days since created):", summarize_time_metrics(bug_age_values))

    bug_ages.sort(reverse=True)
    results["open_bugs_count"] = len(open_bugs)
    results["open_bugs_age_days"] = summarize_time_metrics(bug_age_values)
    results["oldest_open_bugs"] = [{"key": key, "project": proj, "age_days": round(age, 1), "summary": str(summary or "")[:80]} for age, key, summary, proj in bug_ages[:15]]
    print("\nOldest open bugs (top 15):")
    for age, key, summary, proj in bug_ages[:15]:
        try:
            print(f"  {key} [{proj}] - {age:.1f} days - {summary[:80]}")
        except UnicodeEncodeError:
            print(f"  {key} [{proj}] - {age:.1f} days - (summary contains non-printable chars)")

    # Phase 5b: Bug creation rate
    bug_created_weekly = Counter()
    for it in done_issues:
        itype = (it.get("fields") or {}).get("issuetype")
        if isinstance(itype, dict) and (itype.get("name") or "").lower() == "bug":
            created = parse_dt((it.get("fields") or {}).get("created"))
            if created:
                bug_created_weekly[iso_week(created)] += 1
    for it in open_bugs:
        created = parse_dt((it.get("fields") or {}).get("created"))
        if created:
            bug_created_weekly[iso_week(created)] += 1
    results["bug_creation_by_week"] = dict(bug_created_weekly)

    # ---------
    # Per-project metrics (for dashboard project filter)
    # ---------
    by_project = {}
    wip_by_p = defaultdict(list)
    for it in wip_issues:
        wip_by_p[_project_key(it)].append(it)
    blocked_by_p = defaultdict(list)
    for it in blocked_issues:
        blocked_by_p[_project_key(it)].append(it)
    done_by_p = defaultdict(list)
    for it in done_issues:
        done_by_p[_project_key(it)].append(it)
    done_90_by_p = defaultdict(list)
    for it in done_issues_90:
        done_90_by_p[_project_key(it)].append(it)
    open_bugs_by_p = defaultdict(list)
    for it in open_bugs:
        open_bugs_by_p[_project_key(it)].append(it)

    for pk in PROJECT_KEYS:
        wip_list = wip_by_p.get(pk, [])
        ages = [bug_age_days(it, now=now) for it in wip_list]
        ages = [a for a in ages if a is not None]
        proj_status_dist = dict(status_distribution(wip_list))
        done_list = done_by_p.get(pk, [])
        done_90_list = done_90_by_p.get(pk, [])
        ab_p = _assignee_breakdown(done_list)
        ac_p = [v for k, v in ab_p.items() if k != "(unassigned)"]
        tis_p = _time_in_status(done_90_list)

        by_project[pk] = {
            "wip_count": len(wip_list),
            "status_distribution": proj_status_dist,
            "wip_by_phase": wip_by_phase(proj_status_dist),
            "wip_components": _component_breakdown(wip_list),
            "wip_status_by_component": _status_by_component(wip_list),
            "wip_aging_days": summarize_time_metrics(ages) if ages else None,
            "blocked_count": len(blocked_by_p.get(pk, [])),
            "open_bugs_count": len(open_bugs_by_p.get(pk, [])),
            "throughput_by_week": dict(throughput_weekly(done_list)),
            "lead_time_days": None,
            "lead_time_distribution": lead_time_distribution(done_list),
            "cycle_time_days": None,
            # Phase 1
            "wip_issuetype": _issuetype_breakdown(wip_list),
            "done_issuetype": _issuetype_breakdown(done_list),
            "wip_priority": _priority_breakdown(wip_list),
            "unassigned_wip_count": _unassigned_count(wip_list),
            "resolution_breakdown": _resolution_breakdown(done_list),
            "resolution_by_weekday": _resolution_by_weekday(done_list),
            "done_assignees": dict(sorted(ab_p.items(), key=lambda x: -x[1])[:20]),
            "workload_gini": _gini_coefficient(ac_p),
            "bulk_closure_days": _bulk_closures(done_list),
            # Phase 2
            "status_path_analysis": _status_path_analysis(done_90_list),
            "time_in_status": tis_p,
            "closer_analysis": _closer_analysis(done_90_list),
            "reopen_analysis": _reopen_count(done_90_list),
            "flow_efficiency": _flow_efficiency(tis_p),
            # Phase 3
            "empty_description_wip_pct": _empty_description_pct(wip_list),
            "empty_description_done_pct": _empty_description_pct(done_list),
            "zero_comment_done_pct": _zero_comment_pct(done_list),
            "orphan_done_pct": _orphan_pct(done_list),
            # Phase 4+
            "wip_assignees": dict(sorted(_assignee_breakdown(wip_list).items(), key=lambda x: -x[1])[:20]),
            "assignee_change_near_resolution": _assignee_change_near_resolution(done_90_list),
            "comment_timing": _comment_timing(done_90_list),
            "worklog_analysis": _worklog_analysis(done_90_list, sp_field=STORY_POINTS_FIELD),
            "created_by_week": _created_by_week(wip_list + done_list),
            "sp_trend": _sp_trend(done_list, STORY_POINTS_FIELD),
            "bug_creation_by_week": _bug_creation_by_week(done_list, open_bugs_by_p.get(pk, [])),
        }
        lead_times_p = [lead_time_days(it) for it in done_list]
        lead_times_p = [t for t in lead_times_p if t is not None]
        if lead_times_p:
            by_project[pk]["lead_time_days"] = summarize_time_metrics(lead_times_p)
        cycle_times = [cycle_time_days_from_changelog(it) for it in done_90_list]
        cycle_times = [t for t in cycle_times if t is not None]
        if cycle_times:
            by_project[pk]["cycle_time_days"] = summarize_time_metrics(cycle_times)
    results["by_project"] = by_project

    # ---------
    # Per-component metrics (for dashboard component filter)
    # ---------
    wip_by_c = defaultdict(list)
    for it in wip_issues:
        for cn in _issue_components(it):
            wip_by_c[cn].append(it)
    blocked_by_c = defaultdict(list)
    for it in blocked_issues:
        for cn in _issue_components(it):
            blocked_by_c[cn].append(it)
    done_by_c = defaultdict(list)
    for it in done_issues:
        for cn in _issue_components(it):
            done_by_c[cn].append(it)
    done_90_by_c = defaultdict(list)
    for it in done_issues_90:
        for cn in _issue_components(it):
            done_90_by_c[cn].append(it)
    open_bugs_by_c = defaultdict(list)
    for it in open_bugs:
        for cn in _issue_components(it):
            open_bugs_by_c[cn].append(it)

    all_comp_names = sorted(set(
        list(wip_by_c) + list(blocked_by_c) + list(done_by_c)
        + list(done_90_by_c) + list(open_bugs_by_c)
    ))
    by_component = {}
    for cn in all_comp_names:
        c_wip = wip_by_c.get(cn, [])
        c_ages = [bug_age_days(it, now=now) for it in c_wip]
        c_ages = [a for a in c_ages if a is not None]
        c_status_dist = dict(status_distribution(c_wip))
        c_done = done_by_c.get(cn, [])
        c_done_90 = done_90_by_c.get(cn, [])
        c_ab = _assignee_breakdown(c_done)
        c_ac = [v for k, v in c_ab.items() if k != "(unassigned)"]
        c_tis = _time_in_status(c_done_90)

        by_component[cn] = {
            "wip_count": len(c_wip),
            "status_distribution": c_status_dist,
            "wip_by_phase": wip_by_phase(c_status_dist),
            "wip_aging_days": summarize_time_metrics(c_ages) if c_ages else None,
            "blocked_count": len(blocked_by_c.get(cn, [])),
            "open_bugs_count": len(open_bugs_by_c.get(cn, [])),
            "throughput_by_week": dict(throughput_weekly(c_done)),
            "lead_time_days": None,
            "lead_time_distribution": lead_time_distribution(c_done),
            "cycle_time_days": None,
            "wip_issuetype": _issuetype_breakdown(c_wip),
            "done_issuetype": _issuetype_breakdown(c_done),
            "wip_priority": _priority_breakdown(c_wip),
            "unassigned_wip_count": _unassigned_count(c_wip),
            "resolution_breakdown": _resolution_breakdown(c_done),
            "resolution_by_weekday": _resolution_by_weekday(c_done),
            "done_assignees": dict(sorted(c_ab.items(), key=lambda x: -x[1])[:20]),
            "workload_gini": _gini_coefficient(c_ac),
            "bulk_closure_days": _bulk_closures(c_done),
            "status_path_analysis": _status_path_analysis(c_done_90),
            "time_in_status": c_tis,
            "closer_analysis": _closer_analysis(c_done_90),
            "reopen_analysis": _reopen_count(c_done_90),
            "flow_efficiency": _flow_efficiency(c_tis),
            "empty_description_wip_pct": _empty_description_pct(c_wip),
            "empty_description_done_pct": _empty_description_pct(c_done),
            "zero_comment_done_pct": _zero_comment_pct(c_done),
            "orphan_done_pct": _orphan_pct(c_done),
            "wip_assignees": dict(sorted(_assignee_breakdown(c_wip).items(), key=lambda x: -x[1])[:20]),
            "assignee_change_near_resolution": _assignee_change_near_resolution(c_done_90),
            "comment_timing": _comment_timing(c_done_90),
            "worklog_analysis": _worklog_analysis(c_done_90, sp_field=STORY_POINTS_FIELD),
            "created_by_week": _created_by_week(c_wip + c_done),
            "sp_trend": _sp_trend(c_done, STORY_POINTS_FIELD),
            "bug_creation_by_week": _bug_creation_by_week(c_done, open_bugs_by_c.get(cn, [])),
        }
        c_lead = [lead_time_days(it) for it in c_done]
        c_lead = [t for t in c_lead if t is not None]
        if c_lead:
            by_component[cn]["lead_time_days"] = summarize_time_metrics(c_lead)
        c_cycle = [cycle_time_days_from_changelog(it) for it in c_done_90]
        c_cycle = [t for t in c_cycle if t is not None]
        if c_cycle:
            by_component[cn]["cycle_time_days"] = summarize_time_metrics(c_cycle)
    results["by_component"] = by_component
    print(f"\nPer-component metrics computed for {len(by_component)} components.")

    # ---------
    # 5) Boards: Scrum (sprints + velocity) + Kanban (WIP by status)
    # ---------
    print("\nDiscovering boards per project (first board each, you can refine later)...")
    boards = {}
    for pk in PROJECT_KEYS:
        try:
            b = jira.list_boards_for_project(pk)
            vals = b.get("values", [])
            if vals:
                boards[pk] = vals[0]  # pick first
                btype = vals[0].get("type", "unknown")
                print(f"  {pk}: board {vals[0]['id']} - {vals[0]['name']} ({btype})")
            else:
                print(f"  {pk}: no boards found")
        except Exception as e:
            print(f"  {pk}: failed to list boards ({e})")

    # Kanban: for boards that don't support sprints, get current board issues and status breakdown
    results["kanban_boards"] = []
    for pk, b in list(boards.items()):
        board_id = b["id"]
        btype = b.get("type", "").lower()
        if btype == "kanban":
            try:
                issues = jira.board_issues(board_id, fields=fields_with_team, max_results=2000)
                dist = status_distribution(issues)
                done_on_board = sum(1 for it in issues if _is_done(it))
                results["kanban_boards"].append({
                    "project": pk,
                    "board_id": board_id,
                    "board_name": b.get("name", ""),
                    "issue_count": len(issues),
                    "done_count": done_on_board,
                    "status_breakdown": dict(dist),
                })
                print(f"  Kanban {pk}: {len(issues)} issues on board, {done_on_board} done")
            except Exception as e:
                print(f"  Kanban board {board_id} issues failed: {e}")

    # Scrum: recent closed sprints
    sprint_rows = []
    for pk, b in boards.items():
        board_id = b["id"]
        if (b.get("type") or "").lower() == "kanban":
            continue
        try:
            sprints = jira.list_sprints(board_id, state="closed", max_results=50).get("values", [])
            # take last 6 closed sprints
            sprints = sorted(sprints, key=lambda x: (x.get("endDate") or "", x.get("id", 0)))[-6:]
            for sp in sprints:
                sprint_rows.append((pk, board_id, sp["id"], sp["name"], sp.get("startDate"), sp.get("endDate")))
        except Exception as e:
            print(f"Board {board_id} sprints failed: {e}")

    if sprint_rows:
        print(f"\nAnalyzing {len(sprint_rows)} sprints (recent closed)...")
    else:
        print("\nNo sprints found via boards; check board permissions or project-to-board mapping.")
        sprint_rows = []

    def get_sp(issue):
        if not STORY_POINTS_FIELD:
            return 1.0
        v = (issue.get("fields") or {}).get(STORY_POINTS_FIELD)
        try:
            return float(v) if v is not None else 0.0
        except (TypeError, ValueError):
            return 0.0

    sprint_metrics = []
    for pk, board_id, sprint_id, sprint_name, start, end in sprint_rows:
        # Pull sprint issues (include components, team; add changelog for scope metrics)
        fields = list(fields_with_team)
        expand = "changelog" if SPRINT_FIELD_ID and start else None
        issues = jira.sprint_issues(sprint_id, fields=fields, expand=expand, max_results=1000)

        committed = sum(get_sp(it) for it in issues)  # committed = everything in sprint snapshot (approx)
        done = sum(get_sp(it) for it in issues if _is_done(it))
        throughput = sum(1 for it in issues if _is_done(it))
        assignee_count, assignee_names = _sprint_assignees(issues)
        component_breakdown = _component_breakdown(issues)
        team_breakdown = _team_breakdown(issues, TEAM_FIELD_ID) if TEAM_FIELD_ID else {}

        # Scope stability: added after sprint start (from changelog); removed during sprint (from report if available)
        start_dt = parse_dt(start) if start else None
        added_after_sprint_start, added_late_keys = _added_after_sprint_start(issues, sprint_id, sprint_name, start_dt, SPRINT_FIELD_ID) if SPRINT_FIELD_ID and start_dt else (0, [])
        removed_during_sprint = None
        report = None
        try:
            report = jira.get_sprint_report(board_id, sprint_id)
            if isinstance(report, dict):
                contents = report.get("contents") or report.get("completedIssues")
                if isinstance(contents, dict) and "issueKeysRemovedFromSprint" in contents:
                    removed_during_sprint = len(contents.get("issueKeysRemovedFromSprint") or [])
                elif isinstance(report.get("issueKeysRemovedFromSprint"), list):
                    removed_during_sprint = len(report["issueKeysRemovedFromSprint"])
        except Exception:
            pass
        if removed_during_sprint is None and isinstance(report, dict):
            for key in ("puntedIssues", "removedIssues", "issuesNotCompletedInCurrentSprint"):
                if isinstance(report.get(key), list):
                    removed_during_sprint = len(report[key])
                    break

        ratio = (done / committed) if committed else None
        end_dt = parse_dt(end) if end else None
        last_24h, last_24h_pct = _sprint_end_closures(issues, end_dt)

        # Phase 4b: Sprint scope padding — added late AND immediately done
        added_late_set = set(added_late_keys)
        added_and_done = sum(1 for it in issues if it.get("key") in added_late_set and _is_done(it))
        added_and_done_pct = round(added_and_done / len(issues) * 100, 1) if issues else 0

        sprint_metrics.append({
            "project": pk,
            "board_id": board_id,
            "sprint_id": sprint_id,
            "sprint_name": sprint_name,
            "start": start,
            "end": end,
            "committed_points_or_count": committed,
            "done_points_or_count": done,
            "commitment_done_ratio": ratio,
            "throughput_done_issues": throughput,
            "total_issues": len(issues),
            "assignee_count": assignee_count,
            "assignees": assignee_names,
            "component_breakdown": component_breakdown,
            "team_breakdown": team_breakdown,
            "added_after_sprint_start": added_after_sprint_start,
            "added_after_sprint_start_issue_keys": added_late_keys[:50],
            "added_and_done_count": added_and_done,
            "added_and_done_pct": added_and_done_pct,
            "removed_during_sprint": removed_during_sprint,
            "resolved_last_24h": last_24h,
            "resolved_last_24h_pct": last_24h_pct,
        })

    results["sprint_metrics"] = [
        {
            "project": m["project"],
            "sprint_name": m["sprint_name"],
            "committed": m["committed_points_or_count"],
            "done": m["done_points_or_count"],
            "commitment_done_ratio": m["commitment_done_ratio"],
            "throughput_issues": m["throughput_done_issues"],
            "total_issues": m["total_issues"],
            "assignee_count": m["assignee_count"],
            "assignees": m["assignees"],
            "component_breakdown": m["component_breakdown"],
            "team_breakdown": m["team_breakdown"],
            "added_after_sprint_start": m["added_after_sprint_start"],
            "added_after_sprint_start_issue_keys": m["added_after_sprint_start_issue_keys"],
            "added_and_done_count": m["added_and_done_count"],
            "added_and_done_pct": m["added_and_done_pct"],
            "removed_during_sprint": m["removed_during_sprint"],
            "resolved_last_24h": m["resolved_last_24h"],
            "resolved_last_24h_pct": m["resolved_last_24h_pct"],
        }
        for m in sprint_metrics
    ]

    # Phase 1g: velocity CV per project
    velocity_cv_by_project = {}
    sprint_by_proj = defaultdict(list)
    for m in sprint_metrics:
        sprint_by_proj[m["project"]].append(m["throughput_done_issues"])
    for proj, throughputs in sprint_by_proj.items():
        cv = _velocity_cv(throughputs)
        velocity_cv_by_project[proj] = cv
        if proj in by_project:
            by_project[proj]["velocity_cv"] = cv
    results["velocity_cv_by_project"] = velocity_cv_by_project
    if sprint_metrics:
        df = pd.DataFrame(sprint_metrics)
        print("\nSprint velocity & commitment vs done (recent):")
        # Show a compact view including assignee count
        view_cols = ["project", "sprint_name", "committed_points_or_count", "done_points_or_count", "commitment_done_ratio", "throughput_done_issues", "total_issues", "assignee_count", "added_after_sprint_start", "removed_during_sprint"]
        view = df[[c for c in view_cols if c in df.columns]]
        print(view.tail(20).to_string(index=False))
    else:
        print("\nNo sprint metrics computed.")

    # ---------
    # 6d) Epic health dashboard
    # ---------
    print("\nPulling open epics for health analysis...")
    try:
        epic_jql = f'project in ({projects_jql}) AND issuetype = Epic AND statusCategory != {DONE_CATEGORY}'
        epics = jira.search(epic_jql, fields=["project", "status", "summary", "created", "components"], max_results=2000)
        epic_data = []
        for ep in epics:
            ep_key = ep.get("key", "?")
            ep_fields = ep.get("fields") or {}
            ep_age = bug_age_days(ep, now=now)
            child_jql = f'"Epic Link" = {ep_key}'
            try:
                children = jira.search(child_jql, fields=["status"], max_results=500)
                total_children = len(children)
                done_children = sum(1 for c in children if _is_done(c))
                pct = round(done_children / total_children * 100, 1) if total_children else 0
            except Exception:
                total_children, done_children, pct = 0, 0, 0
            stale = (ep_age or 0) > 180 and pct < 20
            epic_data.append({
                "key": ep_key,
                "project": _project_key(ep),
                "summary": (ep_fields.get("summary") or "")[:80],
                "age_days": round(ep_age, 1) if ep_age else 0,
                "total_children": total_children,
                "done_children": done_children,
                "completion_pct": pct,
                "stale": stale,
            })
        results["epic_health"] = epic_data
        results["open_epics_count"] = len(epics)
        results["stale_epics_count"] = sum(1 for e in epic_data if e["stale"])
        avg_pct = round(sum(e["completion_pct"] for e in epic_data) / len(epic_data), 1) if epic_data else 0
        results["avg_epic_completion_pct"] = avg_pct
        print(f"  Open epics: {len(epics)}, stale: {results['stale_epics_count']}, avg completion: {avg_pct}%")
    except Exception as e:
        results["epic_health"] = []
        results["open_epics_count"] = 0
        results["stale_epics_count"] = 0
        results["avg_epic_completion_pct"] = 0
        print(f"  Epic query failed: {e}")

    # ---------
    # 5d) Release / version tracking
    # ---------
    print("\nPulling project versions for release tracking...")
    release_data = []
    for pk in PROJECT_KEYS:
        try:
            versions = jira.list_project_versions(pk)
            if not isinstance(versions, list):
                continue
            for v in versions:
                released = v.get("released", False)
                release_date = v.get("releaseDate")
                release_data.append({
                    "project": pk,
                    "name": v.get("name", "?"),
                    "released": released,
                    "release_date": release_date,
                })
        except Exception as e:
            print(f"  {pk}: version fetch failed ({e})")
    results["releases"] = release_data
    released_versions = [r for r in release_data if r["released"]]
    results["total_released_versions"] = len(released_versions)
    # releases per month
    from collections import Counter as _Counter
    rel_months = _Counter()
    for r in released_versions:
        if r.get("release_date"):
            dt = parse_dt(r["release_date"])
            if dt:
                rel_months[dt.strftime("%Y-%m")] += 1
    results["releases_per_month"] = dict(rel_months)
    print(f"  Total versions: {len(release_data)}, released: {len(released_versions)}")

    # ---------
    # 6) Change Failure Rate (CFR) framework
    # ---------
    print("\nChange Failure Rate (CFR) - framework:")
    print("You need a definition in Jira, e.g.:")
    print("  - Incidents labeled change-failure")
    print("  - Bugs linked to deployments/releases")
    print("  - Rollback issues, etc.")
    print("Currently using this placeholder failure JQL:")
    print(" ", CFR_FAILURE_JQL.format(projects=projects_jql))
    cfr_count = 0
    try:
        failures = jira.search(CFR_FAILURE_JQL.format(projects=projects_jql), fields=fields_with_team, max_results=2000)
        cfr_count = len(failures)
        results["cfr_failures_count"] = cfr_count
        print(f"Failure issues matched by rule: {cfr_count}")
        print("If you also define 'changes' (e.g., Deployment issues done), CFR = failures / changes.")
    except Exception as e:
        results["cfr_failures_count"] = None
        results["cfr_error"] = str(e)[:200]
        print("CFR query failed (likely issuetype/labels don't exist in your instance). Adjust CFR_FAILURE_JQL.")
        print("Error:", e)

    # Save JSON for insights (Cursor, dashboards, etc.)
    def _json_default(obj):
        if isinstance(obj, float) and math.isnan(obj):
            return None
        raise TypeError(f"Object of type {type(obj).__name__} is not JSON serializable")
    out_dir = os.path.dirname(os.path.abspath(__file__))
    latest_path = os.path.join(out_dir, "jira_analytics_latest.json")
    ts_path = os.path.join(out_dir, f"jira_analytics_{run_ts.replace(':', '-')}.json")
    for path in (latest_path, ts_path):
        with open(path, "w", encoding="utf-8") as f:
            _json.dump(results, f, indent=2, ensure_ascii=False, default=_json_default)
    print(f"\nResults saved to: {latest_path}")
    print(f"              and: {ts_path}")
    print("\nDone.")


if __name__ == "__main__":
    main()
