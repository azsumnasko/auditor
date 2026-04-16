import os
import math
import time
import json as _json
from datetime import datetime, timezone, timedelta
from collections import Counter, defaultdict

# Load .env if present (keeps token out of terminal history)
# Set DOTENV_PATH (e.g. /data/.env) in Docker to load from shared volume.
try:
    from dotenv import load_dotenv
    load_dotenv(os.environ.get("DOTENV_PATH", ".env"))
except ImportError:
    pass

import requests
import pandas as pd
from dateutil import parser as dtparser


# ----------------------------
# Config
# ----------------------------
def _load_project_keys():
    """
    Project keys to analyze. Set JIRA_PROJECT_KEYS to a comma-separated list, e.g.:
      JIRA_PROJECT_KEYS=BETTY,OZN,WMS
    Defaults to BETTY if unset.
    """
    raw = os.environ.get("JIRA_PROJECT_KEYS", "BETTY").strip()
    if not raw:
        return ["BETTY"]
    return [k.strip() for k in raw.split(",") if k.strip()]


PROJECT_KEYS = _load_project_keys()

# JQL reserved words that must be quoted when used as project keys (e.g. "IN")
JQL_RESERVED = frozenset({"in", "and", "or", "not", "null", "empty", "order", "by", "asc", "desc"})

def _jql_project_list(keys):
    """Project list for JQL: quote reserved words so e.g. project key 'IN' works."""
    return ", ".join(f'"{k}"' if k.lower() in JQL_RESERVED else k for k in keys)


def _load_board_id_overrides():
    """
    Optional explicit project -> board id mapping.

    Set JIRA_BOARD_ID_OVERRIDES to a JSON object like:
      {"OZN": 12, "WMS": 34}
    """
    raw = os.environ.get("JIRA_BOARD_ID_OVERRIDES", "").strip()
    if not raw:
        return {}
    try:
        parsed = _json.loads(raw)
    except Exception:
        return {}
    overrides = {}
    if not isinstance(parsed, dict):
        return overrides
    for key, value in parsed.items():
        try:
            overrides[str(key).upper()] = int(value)
        except (TypeError, ValueError):
            continue
    return overrides


BOARD_ID_OVERRIDES = _load_board_id_overrides()

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

# Empty or bad structure report: description is "empty" if null, len(strip) < this, or ADF content empty.
EMPTY_OR_BAD_DESCRIPTION_MIN_LEN = 20
# Optional bad structure: treat as bad if summary missing or length (after strip) below this (0 = disabled).
EMPTY_OR_BAD_SUMMARY_MIN_LENGTH = int(os.environ.get("JIRA_EMPTY_BAD_SUMMARY_MIN_LEN", "0"))
# Optional: treat no labels / no component as bad structure (for separate tracking).
EMPTY_OR_BAD_IF_NO_LABELS = os.environ.get("JIRA_EMPTY_BAD_IF_NO_LABELS", "").strip().lower() in ("1", "true", "yes")
EMPTY_OR_BAD_IF_NO_COMPONENT = os.environ.get("JIRA_EMPTY_BAD_IF_NO_COMPONENT", "").strip().lower() in ("1", "true", "yes")


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
            total = data.get("total")
            if len(all_issues) >= max_results or not issues or (total is not None and start_at + len(issues) >= total):
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

    def get_sprint_scope_report(self, board_id, sprint_id):
        """
        Try the older sprint report endpoint that exposes punted/removed issues.
        Returns None if not available in this Jira instance.
        """
        try:
            return self._get(
                "/rest/greenhopper/1.0/rapid/charts/sprintreport",
                params={"rapidViewId": board_id, "sprintId": sprint_id},
            )
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
            total = data.get("total")
            if len(all_issues) >= max_results or not issues or (total is not None and start_at + len(issues) >= total):
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
        if str(fid).startswith("customfield_") and "team" in name.lower():
            return (fid, name)
    return (None, None)

def get_sprint_field_id(jira: JiraClient):
    """Find the Sprint custom field (e.g. customfield_10020) for changelog analysis."""
    fields = jira.list_fields()
    for f in fields:
        fid, name = f.get("id"), (f.get("name") or "")
        if fid is None or not name:
            continue
        if str(fid).startswith("customfield_") and "sprint" in name.lower():
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


def open_by_phase_from_status_dist(status_dist):
    """Return (open_by_phase, wip_in_flight). Agile-friendly keys: backlog, in_progress, in_review, blocked."""
    wp = wip_by_phase(status_dist)
    open_by_phase = {
        "backlog": wp.get("not_started", 0),
        "in_progress": wp.get("in_progress", 0),
        "in_review": wp.get("review_qa", 0),
        "blocked": wp.get("blocked", 0),
    }
    wip_in_flight = open_by_phase["in_progress"] + open_by_phase["in_review"] + open_by_phase["blocked"]
    return open_by_phase, wip_in_flight


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
        # Keys may exist with null (e.g. merged JSON); .get("avg_hours", 0) would still return None.
        hours = (data.get("avg_hours") or 0) * (data.get("count") or 0)
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
def _empty_description_pct(issues, min_len=None):
    if not issues:
        return 0
    if min_len is None:
        min_len = EMPTY_OR_BAD_DESCRIPTION_MIN_LEN
    empty = 0
    for it in issues:
        if _is_empty_description(it, min_len=min_len):
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


def _is_empty_description(issue, min_len=20):
    """True if issue has no or effectively empty description (reuse _empty_description_pct logic)."""
    desc = (issue.get("fields") or {}).get("description")
    if desc is None:
        return True
    if isinstance(desc, str) and len(desc.strip()) < min_len:
        return True
    if isinstance(desc, dict):
        content = desc.get("content") or []
        if not content:
            return True
    return False


def _is_empty_or_bad_structure(
    issue,
    summary_min_length=0,
    bad_if_no_labels=False,
    bad_if_no_component=False,
    description_min_len=None,
):
    """True if issue is in scope: empty description or (when enabled) bad summary/labels/component."""
    if description_min_len is None:
        description_min_len = EMPTY_OR_BAD_DESCRIPTION_MIN_LEN
    if _is_empty_description(issue, min_len=description_min_len):
        return True
    if summary_min_length > 0:
        summary = (issue.get("fields") or {}).get("summary")
        if summary is None or (isinstance(summary, str) and len(summary.strip()) < summary_min_length):
            return True
    if bad_if_no_labels:
        labels = (issue.get("fields") or {}).get("labels")
        if not labels or (isinstance(labels, list) and len(labels) == 0):
            return True
    if bad_if_no_component:
        comps = (issue.get("fields") or {}).get("components")
        if not comps or (isinstance(comps, list) and len(comps) == 0):
            return True
    return False


def _filter_empty_or_bad(
    issues,
    summary_min_length=None,
    bad_if_no_labels=None,
    bad_if_no_component=None,
):
    """Return (list of issues that are empty or bad, list of their keys)."""
    if summary_min_length is None:
        summary_min_length = EMPTY_OR_BAD_SUMMARY_MIN_LENGTH
    if bad_if_no_labels is None:
        bad_if_no_labels = EMPTY_OR_BAD_IF_NO_LABELS
    if bad_if_no_component is None:
        bad_if_no_component = EMPTY_OR_BAD_IF_NO_COMPONENT
    out = []
    keys = []
    for it in issues:
        if _is_empty_or_bad_structure(
            it,
            summary_min_length=summary_min_length,
            bad_if_no_labels=bad_if_no_labels,
            bad_if_no_component=bad_if_no_component,
        ):
            out.append(it)
            keys.append(it.get("key") or "?")
    return out, keys


def _get_issue_team(issue, team_field_id):
    if not team_field_id:
        return ""
    raw = (issue.get("fields") or {}).get(team_field_id)
    if raw is None:
        return ""
    if isinstance(raw, list):
        labels = [_team_field_value_to_label(x) for x in raw if x is not None]
        return labels[0] if labels else ""
    return _team_field_value_to_label(raw)


def _empty_or_bad_list_details(issues, summary_max_len=60, team_field_id=None):
    """Return list of dicts: key, project, type (issuetype), summary (truncated), status, assignee_display_name, team, author_display_name, created."""
    rows = []
    for it in issues:
        fields = it.get("fields") or {}
        key = it.get("key") or "?"
        proj = _project_key(it)
        type_name = (fields.get("issuetype") or {}).get("name") or ""
        summary = (fields.get("summary") or "").strip()
        if len(summary) > summary_max_len:
            summary = summary[: summary_max_len - 1] + "\u2026"
        st = fields.get("status")
        status_name = st.get("name") if isinstance(st, dict) else ""
        assignee = fields.get("assignee")
        assignee_name = (assignee.get("displayName") or assignee.get("name") or "(unassigned)") if isinstance(assignee, dict) else "(unassigned)"
        reporter = fields.get("reporter")
        author_name = (reporter.get("displayName") or reporter.get("name") or "") if isinstance(reporter, dict) else ""
        created_raw = fields.get("created") or ""
        created_date = created_raw[:10] if created_raw else ""
        rows.append({
            "key": key,
            "project": proj,
            "type": type_name,
            "summary": summary,
            "status": status_name,
            "assignee_display_name": assignee_name,
            "team": _get_issue_team(it, team_field_id),
            "author_display_name": author_name,
            "created": created_date,
        })
    return rows


def _label_breakdown(issues):
    """Return dict: label name -> issue count. An issue can appear under multiple labels. '(no label)' for none."""
    c = Counter()
    for it in issues:
        labels = (it.get("fields") or {}).get("labels")
        if not labels or (isinstance(labels, list) and len(labels) == 0):
            c["(no label)"] += 1
            continue
        for lab in labels:
            if isinstance(lab, str):
                c[lab] += 1
            elif isinstance(lab, dict):
                c[lab.get("name") or lab.get("value") or "?"] += 1
        # If it has labels, we don't add to (no label); we've already counted each label.
    return dict(c)


def _project_key(issue):
    p = (issue.get("fields") or {}).get("project")
    return p.get("key", "?") if isinstance(p, dict) else "?"


def _select_project_board(project_key, boards):
    """
    Choose a board for a project using explicit overrides first, then a stable fallback.
    """
    if not boards:
        return None

    override_id = BOARD_ID_OVERRIDES.get(project_key)
    if override_id is not None:
        for board in boards:
            if board.get("id") == override_id:
                return board

    def score(board):
        name = (board.get("name") or "").lower()
        btype = (board.get("type") or "").lower()
        location = board.get("location") or {}
        location_key = (location.get("projectKey") or "").upper()
        location_name = (location.get("projectName") or "").lower()

        points = 0
        if location_key == project_key:
            points += 100
        if project_key.lower() in name:
            points += 20
        if project_key.lower() in location_name:
            points += 10
        if btype == "scrum":
            points += 3
        elif btype == "kanban":
            points += 2
        return (points, -(board.get("id") or 0))

    return sorted(boards, key=score, reverse=True)[0]


def _scope_metrics(
    *,
    wip_list,
    blocked_list,
    done_list,
    done_90_list,
    open_bug_list,
    created_list,
    story_points_field,
    now,
    team_field_id=None,
):
    ages = [bug_age_days(it, now=now) for it in wip_list]
    ages = [a for a in ages if a is not None]
    status_dist = dict(status_distribution(wip_list))
    ab_done = _assignee_breakdown(done_list)
    ac_done = [v for k, v in ab_done.items() if k != "(unassigned)"]
    tis = _time_in_status(done_90_list)

    lead_vals = [lead_time_days(it) for it in done_list]
    lead_vals = [v for v in lead_vals if v is not None]
    cycle_vals = [cycle_time_days_from_changelog(it) for it in done_90_list]
    cycle_vals = [v for v in cycle_vals if v is not None]

    wp = wip_by_phase(status_dist)
    open_by_phase, wip_in_flight = open_by_phase_from_status_dist(status_dist)
    unassigned_open = _unassigned_count(wip_list)
    metrics = {
        "open_count": len(wip_list),
        "open_by_phase": open_by_phase,
        "wip_in_flight": wip_in_flight,
        "wip_count": len(wip_list),  # backward compatibility
        "status_distribution": status_dist,
        "wip_by_phase": wp,  # backward compatibility
        "wip_components": _component_breakdown(wip_list),
        "wip_status_by_component": _status_by_component(wip_list),
        "wip_aging_days": summarize_time_metrics(ages) if ages else None,
        "blocked_count": len(blocked_list),
        "open_bugs_count": len(open_bug_list),
        "throughput_by_week": dict(throughput_weekly(done_list)),
        "lead_time_days": summarize_time_metrics(lead_vals) if lead_vals else None,
        "lead_time_distribution": lead_time_distribution(done_list),
        "cycle_time_days": summarize_time_metrics(cycle_vals) if cycle_vals else None,
        "wip_issuetype": _issuetype_breakdown(wip_list),
        "done_issuetype": _issuetype_breakdown(done_list),
        "wip_priority": _priority_breakdown(wip_list),
        "unassigned_open_count": unassigned_open,
        "unassigned_wip_count": unassigned_open,  # backward compatibility
        "resolution_breakdown": _resolution_breakdown(done_list),
        "resolution_by_weekday": _resolution_by_weekday(done_list),
        "done_assignees": dict(sorted(ab_done.items(), key=lambda x: -x[1])[:20]),
        "workload_gini": _gini_coefficient(ac_done),
        "bulk_closure_days": _bulk_closures(done_list),
        "status_path_analysis": _status_path_analysis(done_90_list),
        "time_in_status": tis,
        "closer_analysis": _closer_analysis(done_90_list),
        "reopen_analysis": _reopen_count(done_90_list),
        "flow_efficiency": _flow_efficiency(tis),
        "empty_description_wip_pct": _empty_description_pct(wip_list),
        "empty_description_done_pct": _empty_description_pct(done_list),
        "zero_comment_done_pct": _zero_comment_pct(done_list),
        "orphan_done_pct": _orphan_pct(done_list),
        "wip_assignees": dict(sorted(_assignee_breakdown(wip_list).items(), key=lambda x: -x[1])[:20]),
        "assignee_change_near_resolution": _assignee_change_near_resolution(done_90_list),
        "comment_timing": _comment_timing(done_90_list),
        "worklog_analysis": _worklog_analysis(done_90_list, sp_field=story_points_field),
        "created_by_week": _created_by_week(created_list),
        "sp_trend": _sp_trend(done_list, story_points_field),
        "bug_creation_by_week": _bug_creation_by_week(done_list, open_bug_list),
        "bug_resolved_by_week": _bug_resolved_by_week(done_list),
        "bug_fix_time_days": _bug_fix_time(done_list),
        "open_bugs_by_priority": _priority_breakdown(open_bug_list),
        "wip_teams": _team_breakdown(wip_list, team_field_id) if team_field_id else {},
    }
    return metrics


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


def _bug_resolved_by_week(done_issues):
    """Count bug resolutions by week (resolved date)."""
    weekly = Counter()
    for it in done_issues:
        itype = (it.get("fields") or {}).get("issuetype")
        if isinstance(itype, dict) and (itype.get("name") or "").lower() == "bug":
            dt = parse_dt((it.get("fields") or {}).get("resolutiondate"))
            if dt:
                weekly[iso_week(dt)] += 1
    return dict(weekly)


def _bug_fix_time(done_issues):
    """Lead time stats for bugs only (created -> resolved)."""
    vals = []
    for it in done_issues:
        itype = (it.get("fields") or {}).get("issuetype")
        if isinstance(itype, dict) and (itype.get("name") or "").lower() == "bug":
            lt = lead_time_days(it)
            if lt is not None:
                vals.append(lt)
    return summarize_time_metrics(vals)


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


def _jira_created_to_date_str(fields):
    """Parse Jira ``fields['created']`` to YYYY-MM-DD for dashboard time filtering."""
    raw = (fields or {}).get("created")
    if not raw:
        return None
    try:
        dt = dtparser.parse(str(raw))
        if dt.tzinfo:
            dt = dt.astimezone(timezone.utc)
        return dt.date().isoformat()
    except Exception:
        return None


# ----------------------------
# Main
# ----------------------------
def main():
    run_ts = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    results = {"run_iso_ts": run_ts, "projects": PROJECT_KEYS, "jira_base_url": os.environ.get("JIRA_BASE_URL", "")}

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
                    "description", "comment", "issuelinks", "worklog", "reporter"]
    fields_with_team = list(base_fields) + ([TEAM_FIELD_ID] if TEAM_FIELD_ID else [])
    if STORY_POINTS_FIELD:
        fields_with_team.append(STORY_POINTS_FIELD)

    print("\nPulling current (not done) issues for status distribution & Open aging...")
    jql_wip = f'project in ({projects_jql}) AND statusCategory != {DONE_CATEGORY}'
    wip_issues = jira.search(jql_wip, fields=fields_with_team, max_results=5000)

    print(f"Open issues pulled: {len(wip_issues)}")
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

    print("\nTop statuses (Open):")
    for st, cnt in status_dist.most_common(15):
        print(f"  {st}: {cnt}")

    wip_aging = summarize_time_metrics(wip_ages)
    status_dist_dict = dict(status_dist)
    wp = wip_by_phase(status_dist_dict)
    open_by_phase, wip_in_flight = open_by_phase_from_status_dist(status_dist_dict)
    results["open_count"] = len(wip_issues)
    results["open_by_phase"] = open_by_phase
    results["wip_in_flight"] = wip_in_flight
    results["wip_count"] = len(wip_issues)  # backward compatibility
    results["status_category"] = dict(status_cat)
    results["status_distribution"] = dict(status_dist)
    results["wip_by_phase"] = wp  # backward compatibility
    results["wip_aging_days"] = wip_aging
    results["wip_components"] = _component_breakdown(wip_issues)
    if TEAM_FIELD_ID:
        results["wip_teams"] = _team_breakdown(wip_issues, TEAM_FIELD_ID)
    else:
        results["wip_teams"] = {}
    print("\nAging Open summary (days since created):", wip_aging)
    print(f"WIP (in flight): {wip_in_flight}")
    if results["wip_components"]:
        print("Open by component:", dict(sorted(results["wip_components"].items(), key=lambda x: -x[1])[:10]))
    results["teams"] = sorted(results["wip_teams"].keys()) if results["wip_teams"] else []
    if results["wip_teams"]:
        print("Open by team:", dict(sorted(results["wip_teams"].items(), key=lambda x: -x[1])[:10]))

    # Phase 1 Open/WIP metrics
    results["wip_status_by_component"] = _status_by_component(wip_issues)
    results["wip_issuetype"] = _issuetype_breakdown(wip_issues)
    results["wip_priority"] = _priority_breakdown(wip_issues)
    unassigned_open = _unassigned_count(wip_issues)
    results["unassigned_open_count"] = unassigned_open
    results["unassigned_wip_count"] = unassigned_open  # backward compatibility
    print(f"Unassigned open: {results['unassigned_open_count']} / {len(wip_issues)}")

    # Phase 3 WIP metrics
    results["empty_description_wip_pct"] = _empty_description_pct(wip_issues)

    # Empty or bad structure (WIP): count, list, breakdowns
    empty_bad_wip_list, empty_bad_wip_keys = _filter_empty_or_bad(wip_issues)
    results["empty_or_bad_count_wip"] = len(empty_bad_wip_keys)
    results["empty_or_bad_pct_wip"] = round(len(empty_bad_wip_keys) / len(wip_issues) * 100, 1) if wip_issues else 0
    results["empty_or_bad_ticket_keys_wip"] = empty_bad_wip_keys
    results["empty_or_bad_list_wip"] = _empty_or_bad_list_details(empty_bad_wip_list, team_field_id=TEAM_FIELD_ID)
    results["empty_or_bad_by_team_wip"] = _team_breakdown(empty_bad_wip_list, TEAM_FIELD_ID) if TEAM_FIELD_ID else {}
    results["empty_or_bad_by_assignee_wip"] = _assignee_breakdown(empty_bad_wip_list)
    results["empty_or_bad_by_component_wip"] = _component_breakdown(empty_bad_wip_list)
    results["empty_or_bad_by_label_wip"] = _label_breakdown(empty_bad_wip_list)
    _top5 = lambda d: dict(sorted((d or {}).items(), key=lambda x: -x[1])[:5])
    results["empty_or_bad_top_teams_wip"] = _top5(results["empty_or_bad_by_team_wip"])
    results["empty_or_bad_top_assignees_wip"] = _top5(results["empty_or_bad_by_assignee_wip"])
    results["empty_or_bad_top_components_wip"] = _top5(results["empty_or_bad_by_component_wip"])
    results["empty_or_bad_top_labels_wip"] = _top5(results["empty_or_bad_by_label_wip"])
    print(f"Empty or bad structure (WIP): {results['empty_or_bad_count_wip']} / {len(wip_issues)} ({results['empty_or_bad_pct_wip']}%)")

    # Phase 6a: Open by assignee
    wip_ab = _assignee_breakdown(wip_issues)
    results["wip_assignees"] = dict(sorted(wip_ab.items(), key=lambda x: -x[1])[:30])
    wip_per_person = [v for k, v in wip_ab.items() if k != "(unassigned)"]
    results["avg_wip_per_assignee"] = round(sum(wip_per_person) / len(wip_per_person), 1) if wip_per_person else 0
    print(f"Open assignees: {len(wip_ab)}, avg open/person: {results['avg_wip_per_assignee']}")

    print("\nPulling blockers (heuristic JQL)...")
    blocked_jql = f'project in ({projects_jql}) AND statusCategory != {DONE_CATEGORY} AND {BLOCKED_JQL}'
    blocked_issues = jira.search(blocked_jql, fields=fields_with_team, max_results=2000)
    print(f"Blocked issues: {len(blocked_issues)}")
    blocked_with_age = []
    if blocked_issues:
        # Show top 10 oldest blocked
        for it in blocked_issues:
            age = bug_age_days(it, now=now)
            blocked_with_age.append((age or -1, it.get("key", "?"), (it.get("fields") or {}).get("summary", "") or ""))

        blocked_with_age.sort(reverse=True)
        print("Oldest blocked issues (top 10):")
        for age, key, _ in blocked_with_age[:10]:
            print(f"  {key} - {age:.1f} days")
    results["blocked_count"] = len(blocked_issues)
    results["blocked_oldest"] = [(key, round(age, 1)) for age, key, _ in sorted(blocked_with_age, reverse=True)[:10]]
    blocked_issue_lookup = {it.get("key", "?"): it for it in blocked_issues}
    results["blocked_oldest_details"] = [
        {
            "key": key,
            "project": _project_key(blocked_issue_lookup.get(key, {})),
            "age_days": round(age, 1),
            "summary": str((blocked_issue_lookup.get(key, {}).get("fields") or {}).get("summary") or "")[:80],
            "components": _issue_components(blocked_issue_lookup.get(key, {})),
            "team": _get_issue_team(blocked_issue_lookup.get(key, {}), TEAM_FIELD_ID),
        }
        for age, key, _ in sorted(blocked_with_age, reverse=True)[:10]
    ]

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
    results["throughput_total"] = len(done_issues)
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

    # Empty or bad structure (Done): count, list, breakdowns
    empty_bad_done_list, empty_bad_done_keys = _filter_empty_or_bad(done_issues)
    results["empty_or_bad_count_done"] = len(empty_bad_done_keys)
    results["empty_or_bad_pct_done"] = round(len(empty_bad_done_keys) / len(done_issues) * 100, 1) if done_issues else 0
    results["empty_or_bad_ticket_keys_done"] = empty_bad_done_keys
    results["empty_or_bad_list_done"] = _empty_or_bad_list_details(empty_bad_done_list, team_field_id=TEAM_FIELD_ID)
    results["empty_or_bad_by_team_done"] = _team_breakdown(empty_bad_done_list, TEAM_FIELD_ID) if TEAM_FIELD_ID else {}
    results["empty_or_bad_by_assignee_done"] = _assignee_breakdown(empty_bad_done_list)
    results["empty_or_bad_by_component_done"] = _component_breakdown(empty_bad_done_list)
    results["empty_or_bad_by_label_done"] = _label_breakdown(empty_bad_done_list)
    results["empty_or_bad_top_teams_done"] = _top5(results["empty_or_bad_by_team_done"])
    results["empty_or_bad_top_assignees_done"] = _top5(results["empty_or_bad_by_assignee_done"])
    results["empty_or_bad_top_components_done"] = _top5(results["empty_or_bad_by_component_done"])
    results["empty_or_bad_top_labels_done"] = _top5(results["empty_or_bad_by_label_done"])
    print(f"Empty or bad structure (done): {results['empty_or_bad_count_done']} / {len(done_issues)} ({results['empty_or_bad_pct_done']}%)")

    # Phase 4a: Story point inflation
    results["sp_trend"] = _sp_trend(done_issues, STORY_POINTS_FIELD)
    if results["sp_trend"]["inflation_detected"]:
        print("  WARNING: Story point inflation detected (avg SP/issue up >30%)")

    # Phase 5a: Created vs Resolved trend
    print("\nPulling created issues (last 180d) for trend analysis...")
    jql_created = f'project in ({projects_jql}) AND created >= -180d'
    created_issues = []
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
    open_bug_lookup = {it.get("key", "?"): it for it in open_bugs}
    results["oldest_open_bugs"] = [
        {
            "key": key,
            "project": proj,
            "age_days": round(age, 1),
            "summary": str(summary or "")[:80],
            "components": _issue_components(open_bug_lookup.get(key, {})),
            "team": _get_issue_team(open_bug_lookup.get(key, {}), TEAM_FIELD_ID),
        }
        for age, key, summary, proj in bug_ages[:15]
    ]
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
    results["bug_resolved_by_week"] = _bug_resolved_by_week(done_issues)
    results["bug_fix_time_days"] = _bug_fix_time(done_issues)
    results["open_bugs_by_priority"] = _priority_breakdown(open_bugs)

    # ---------
    # Scoped metrics for dashboard filters
    # ---------
    by_project = {}
    by_component = {}
    by_project_component = defaultdict(dict)

    wip_by_p = defaultdict(list)
    blocked_by_p = defaultdict(list)
    done_by_p = defaultdict(list)
    done_90_by_p = defaultdict(list)
    open_bugs_by_p = defaultdict(list)
    created_by_p = defaultdict(list)

    wip_by_c = defaultdict(list)
    blocked_by_c = defaultdict(list)
    done_by_c = defaultdict(list)
    done_90_by_c = defaultdict(list)
    open_bugs_by_c = defaultdict(list)
    created_by_c = defaultdict(list)

    wip_by_pc = defaultdict(lambda: defaultdict(list))
    blocked_by_pc = defaultdict(lambda: defaultdict(list))
    done_by_pc = defaultdict(lambda: defaultdict(list))
    done_90_by_pc = defaultdict(lambda: defaultdict(list))
    open_bugs_by_pc = defaultdict(lambda: defaultdict(list))
    created_by_pc = defaultdict(lambda: defaultdict(list))

    def _group_project_scope(target, issues):
        for issue in issues:
            target[_project_key(issue)].append(issue)

    def _group_component_scope(target, issues):
        for issue in issues:
            for comp_name in _issue_components(issue):
                target[comp_name].append(issue)

    def _group_project_component_scope(target, issues):
        for issue in issues:
            project_key = _project_key(issue)
            for comp_name in _issue_components(issue):
                target[project_key][comp_name].append(issue)

    _group_project_scope(wip_by_p, wip_issues)
    _group_project_scope(blocked_by_p, blocked_issues)
    _group_project_scope(done_by_p, done_issues)
    _group_project_scope(done_90_by_p, done_issues_90)
    _group_project_scope(open_bugs_by_p, open_bugs)
    _group_project_scope(created_by_p, created_issues)

    _group_component_scope(wip_by_c, wip_issues)
    _group_component_scope(blocked_by_c, blocked_issues)
    _group_component_scope(done_by_c, done_issues)
    _group_component_scope(done_90_by_c, done_issues_90)
    _group_component_scope(open_bugs_by_c, open_bugs)
    _group_component_scope(created_by_c, created_issues)

    _group_project_component_scope(wip_by_pc, wip_issues)
    _group_project_component_scope(blocked_by_pc, blocked_issues)
    _group_project_component_scope(done_by_pc, done_issues)
    _group_project_component_scope(done_90_by_pc, done_issues_90)
    _group_project_component_scope(open_bugs_by_pc, open_bugs)
    _group_project_component_scope(created_by_pc, created_issues)

    for pk in PROJECT_KEYS:
        by_project[pk] = _scope_metrics(
            wip_list=wip_by_p.get(pk, []),
            blocked_list=blocked_by_p.get(pk, []),
            done_list=done_by_p.get(pk, []),
            done_90_list=done_90_by_p.get(pk, []),
            open_bug_list=open_bugs_by_p.get(pk, []),
            created_list=created_by_p.get(pk, []),
            story_points_field=STORY_POINTS_FIELD,
            now=now,
            team_field_id=TEAM_FIELD_ID,
        )

    all_comp_names = sorted(set(
        list(wip_by_c) + list(blocked_by_c) + list(done_by_c) +
        list(done_90_by_c) + list(open_bugs_by_c) + list(created_by_c)
    ))
    for cn in all_comp_names:
        by_component[cn] = _scope_metrics(
            wip_list=wip_by_c.get(cn, []),
            blocked_list=blocked_by_c.get(cn, []),
            done_list=done_by_c.get(cn, []),
            done_90_list=done_90_by_c.get(cn, []),
            open_bug_list=open_bugs_by_c.get(cn, []),
            created_list=created_by_c.get(cn, []),
            story_points_field=STORY_POINTS_FIELD,
            now=now,
            team_field_id=TEAM_FIELD_ID,
        )

    for pk in PROJECT_KEYS:
        component_names = sorted(set(
            list(wip_by_pc.get(pk, {})) + list(blocked_by_pc.get(pk, {})) +
            list(done_by_pc.get(pk, {})) + list(done_90_by_pc.get(pk, {})) +
            list(open_bugs_by_pc.get(pk, {})) + list(created_by_pc.get(pk, {}))
        ))
        if not component_names:
            continue
        for cn in component_names:
            by_project_component[pk][cn] = _scope_metrics(
                wip_list=wip_by_pc.get(pk, {}).get(cn, []),
                blocked_list=blocked_by_pc.get(pk, {}).get(cn, []),
                done_list=done_by_pc.get(pk, {}).get(cn, []),
                done_90_list=done_90_by_pc.get(pk, {}).get(cn, []),
                open_bug_list=open_bugs_by_pc.get(pk, {}).get(cn, []),
                created_list=created_by_pc.get(pk, {}).get(cn, []),
                story_points_field=STORY_POINTS_FIELD,
                now=now,
                team_field_id=TEAM_FIELD_ID,
            )

    # Per-team metrics (flat breakdown, like by_component)
    by_team = {}
    if TEAM_FIELD_ID:
        wip_by_t = defaultdict(list)
        blocked_by_t = defaultdict(list)
        done_by_t = defaultdict(list)
        done_90_by_t = defaultdict(list)
        open_bugs_by_t = defaultdict(list)
        created_by_t = defaultdict(list)

        def _group_team_scope(target, issues):
            for issue in issues:
                team = _get_issue_team(issue, TEAM_FIELD_ID)
                target[team or "(no team)"].append(issue)

        _group_team_scope(wip_by_t, wip_issues)
        _group_team_scope(blocked_by_t, blocked_issues)
        _group_team_scope(done_by_t, done_issues)
        _group_team_scope(done_90_by_t, done_issues_90)
        _group_team_scope(open_bugs_by_t, open_bugs)
        _group_team_scope(created_by_t, created_issues)

        all_team_names = sorted(set(
            list(wip_by_t) + list(blocked_by_t) + list(done_by_t) +
            list(done_90_by_t) + list(open_bugs_by_t) + list(created_by_t)
        ))
        for tn in all_team_names:
            by_team[tn] = _scope_metrics(
                wip_list=wip_by_t.get(tn, []),
                blocked_list=blocked_by_t.get(tn, []),
                done_list=done_by_t.get(tn, []),
                done_90_list=done_90_by_t.get(tn, []),
                open_bug_list=open_bugs_by_t.get(tn, []),
                created_list=created_by_t.get(tn, []),
                story_points_field=STORY_POINTS_FIELD,
                now=now,
                team_field_id=TEAM_FIELD_ID,
            )
        print(f"Per-team metrics computed for {len(by_team)} teams.")

    results["by_project"] = by_project
    results["by_component"] = by_component
    results["by_team"] = by_team
    results["by_project_component"] = {pk: dict(comp_map) for pk, comp_map in by_project_component.items()}
    results["metric_metadata"] = {
        "blocked_count": {"kind": "heuristic", "notes": "Derived from BLOCKED_JQL heuristic."},
        "cycle_time_days": {"kind": "heuristic", "notes": "Computed from changelog and status-name heuristics."},
        "created_by_week": {"kind": "exact", "window": "last_180d"},
        "lead_time_days": {"kind": "exact", "window": "last_180d_done"},
        "time_in_status": {"kind": "exact", "window": "last_90d_done_with_changelog"},
    }
    print(f"\nPer-component metrics computed for {len(by_component)} components.")
    print(f"Per project+component metrics computed for {sum(len(v) for v in by_project_component.values())} scopes.")

    # ---------
    # 5) Boards: Scrum (sprints + velocity) + Kanban (WIP by status)
    # ---------
    print("\nDiscovering boards per project (explicit override first, then scored fallback)...")
    boards = {}
    for pk in PROJECT_KEYS:
        try:
            b = jira.list_boards_for_project(pk)
            vals = b.get("values", [])
            if vals:
                selected_board = _select_project_board(pk, vals)
                boards[pk] = selected_board
                btype = selected_board.get("type", "unknown")
                print(f"  {pk}: board {selected_board['id']} - {selected_board['name']} ({btype})")
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
            report = jira.get_sprint_scope_report(board_id, sprint_id)
            if isinstance(report, dict):
                contents = report.get("contents") or report.get("completedIssues")
                if isinstance(contents, dict) and "issueKeysRemovedFromSprint" in contents:
                    removed_during_sprint = len(contents.get("issueKeysRemovedFromSprint") or [])
                elif isinstance(report.get("issueKeysRemovedFromSprint"), list):
                    removed_during_sprint = len(report["issueKeysRemovedFromSprint"])
        except Exception:
            pass
        if removed_during_sprint is None:
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

    sprint_metrics_list = [
        {
            "project": m["project"],
            "sprint_name": m["sprint_name"],
            "start": m.get("start", ""),
            "end": m.get("end", ""),
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

    results["sprint_metrics"] = sprint_metrics_list

    if sprint_metrics:
        _added_pcts = [
            round((m["added_after_sprint_start"] or 0) / m["total_issues"] * 100, 1)
            if m["total_issues"]
            else 0.0
            for m in sprint_metrics
        ]
        results["sprint_aggregate"] = {
            "avg_added_after_start_pct": round(sum(_added_pcts) / len(_added_pcts), 1),
            "avg_commitment_ratio_pct": round(
                sum(round((m["commitment_done_ratio"] or 0) * 100, 1) for m in sprint_metrics)
                / len(sprint_metrics),
                1,
            ),
        }
    else:
        results["sprint_aggregate"] = {
            "avg_added_after_start_pct": None,
            "avg_commitment_ratio_pct": None,
        }

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
            epic_row = {
                "key": ep_key,
                "project": _project_key(ep),
                "summary": (ep_fields.get("summary") or "")[:80],
                "age_days": round(ep_age, 1) if ep_age else 0,
                "components": _issue_components(ep),
                "total_children": total_children,
                "done_children": done_children,
                "completion_pct": pct,
                "stale": stale,
            }
            created_date = _jira_created_to_date_str(ep_fields)
            if created_date:
                epic_row["created_date"] = created_date
            epic_data.append(epic_row)
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
    rel_months = Counter()
    for r in released_versions:
        if r.get("release_date"):
            dt = parse_dt(r["release_date"])
            if dt:
                rel_months[dt.strftime("%Y-%m")] += 1
    results["releases_per_month"] = dict(rel_months)
    print(f"  Total versions: {len(release_data)}, released: {len(released_versions)}")

    # Inject releases_per_month into per-project scopes
    _rpm_by_project = defaultdict(lambda: Counter())
    for r in released_versions:
        if r.get("release_date"):
            dt = parse_dt(r["release_date"])
            if dt:
                _rpm_by_project[r["project"]][dt.strftime("%Y-%m")] += 1
    for pk in PROJECT_KEYS:
        if pk in by_project:
            by_project[pk]["releases_per_month"] = dict(_rpm_by_project.get(pk, {}))

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
    out_dir = os.environ.get("OUTPUT_DIR", os.path.dirname(os.path.abspath(__file__)))
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
