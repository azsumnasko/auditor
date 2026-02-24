setx JIRA_EMAIL "atanas.m.ignatov@mail.bg"
setx JIRA_TOKEN "PASTE_NEW_TOKEN_HERE"
Easiest safe way to proceed
Option A) Run a local script (you keep the token)

You run it on your machine; I’ll give you the script. You’ll set:

JIRA_EMAIL

JIRA_TOKEN
as environment variables, so the token never appears in the code/history.

Mac/Linux:

export JIRA_EMAIL="atanas.m.ignatov@mail.bg"
export JIRA_TOKEN="PASTE_NEW_TOKEN_HERE"


Windows PowerShell:

setx JIRA_EMAIL "atanas.m.ignatov@mail.bg"
setx JIRA_TOKEN "PASTE_NEW_TOKEN_HERE"


Then run a Python script that outputs:

Issues by status / assignee / priority

Throughput over time

Lead time (created → done)

Cycle time (in progress → done, if you want)

Sprint completion & velocity (if Jira Software board access)

Option B) Connect via your MCP server

Yes, that can be easier — but you still should not give me the token.
Instead, your MCP server should hold credentials and expose safe tools like:

jira.search(jql=...)

jira.get_sprints(board=...)

jira.get_changelog(issue=...)

If you tell me what MCP implementation you’re using (or paste the tool names it exposes), I can immediately start forming the right queries.

To get you analytics fast, tell me just these (no secrets)

Project key(s) (example: OZN)

Are you using Scrum sprints or Kanban?

Which metrics you want first:

Status distribution

Throughput per week

Lead time / cycle time

Sprint velocity & commitment vs done

Aging WIP / blockers

If you answer those, I’ll give you either:

a ready-to-run Python script, or

the exact MCP tool calls / JQL to run.

I chnaged the key and the answers are:
1. the keys are: OZN, PMBK, WMS,O3, UP, RMA, MA, LSH,IN, HELP, EBK, PBI,BA
2. scrum
3. Status distribution, Throughput per week and sprint, Lead time, cycle time, Sprint velocity, commitment vs done, Aging WIP, blockers, open bugs, average age of bugs, oldest ones, change failure rate based on Jira

Perfect — with Scrum + those project keys, you can get all of these metrics via Jira Cloud REST APIs (Core + Agile). The main “gotchas” are:

Board IDs (needed for sprints/velocity) are per board, not per project.

Story points is a custom field (you need its field id once).

Cycle time needs changelog (status transition timestamps).

Below is a practical setup that will produce:

Status distribution (per project + overall)

Throughput per week (done issues)

Throughput per sprint (per board)

Lead time + cycle time (p50/p85 averages, etc.)

Velocity + commitment vs done (story points per sprint)

Aging WIP + blockers

Open bugs + average age + oldest bugs list

Change failure rate (based on “failed” deployments/releases — you’ll need to define what counts as a failure in your Jira)

What you run locally (token stays with you)
1) Set env vars (recommended)

Mac/Linux

export JIRA_BASE_URL="https://ozone.atlassian.net"
export JIRA_EMAIL="atanas.m.ignatov@mail.bg"
export JIRA_TOKEN="YOUR_NEW_TOKEN"


Windows PowerShell

setx JIRA_BASE_URL "https://ozone.atlassian.net"
setx JIRA_EMAIL "atanas.m.ignatov@mail.bg"
setx JIRA_TOKEN "YOUR_NEW_TOKEN"

2) Install deps
pip install requests pandas python-dateutil

One script that pulls everything (starter “analytics pack”)

Copy into jira_analytics.py and run: python jira_analytics.py

import os
import math
import time
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from collections import defaultdict, Counter

import requests
import pandas as pd
from dateutil import parser as dtparser


# ----------------------------
# Config
# ----------------------------
PROJECT_KEYS = ["OZN", "PMBK", "WMS", "O3", "UP", "RMA", "MA", "LSH", "IN", "HELP", "EBK", "PBI", "BA"]

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

    def _get(self, path, params=None):
        url = self.base.rstrip("/") + path
        r = self.session.get(url, params=params or {})
        if r.status_code >= 400:
            raise RuntimeError(f"GET {url} failed {r.status_code}: {r.text[:500]}")
        return r.json()

    def search(self, jql, fields=None, expand=None, max_results=1000):
        """Paginated /rest/api/3/search"""
        all_issues = []
        start_at = 0
        page_size = 100

        while True:
            params = {
                "jql": jql,
                "startAt": start_at,
                "maxResults": min(page_size, max_results - len(all_issues)),
            }
            if fields is not None:
                params["fields"] = ",".join(fields)
            if expand:
                params["expand"] = expand

            data = self._get("/rest/api/3/search", params=params)
            issues = data.get("issues", [])
            all_issues.extend(issues)

            if len(all_issues) >= max_results:
                break
            if start_at + len(issues) >= data.get("total", 0) or not issues:
                break

            start_at += len(issues)
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
        # Agile sprint issues endpoint supports pagination too, but we’ll keep simple for typical sprint sizes.
        params = {"maxResults": min(100, max_results)}
        if fields is not None:
            params["fields"] = ",".join(fields)
        if expand:
            params["expand"] = expand
        data = self._get(f"/rest/agile/1.0/sprint/{sprint_id}/issue", params=params)
        return data.get("issues", [])


# ----------------------------
# Helpers
# ----------------------------
def parse_dt(s):
    if not s:
        return None
    return dtparser.isoparse(s)

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
        name = (f.get("name") or "").lower()
        if "story point" in name:
            candidates.append((f["id"], f["name"]))
    return candidates  # list of (id, name)

def status_distribution(issues):
    c = Counter()
    for it in issues:
        st = it["fields"]["status"]["name"]
        c[st] += 1
    return c

def categorize_status(issues):
    # group by statusCategory (new/indeterminate/done)
    c = Counter()
    for it in issues:
        cat = it["fields"]["status"]["statusCategory"]["key"]
        c[cat] += 1
    return c

def throughput_weekly(issues, done_date_field="resolutiondate"):
    # Using resolutiondate as "done"
    weekly = Counter()
    for it in issues:
        dt = parse_dt(it["fields"].get(done_date_field))
        if not dt:
            continue
        weekly[iso_week(dt)] += 1
    return weekly

def lead_time_days(issue):
    created = parse_dt(issue["fields"].get("created"))
    resolved = parse_dt(issue["fields"].get("resolutiondate"))
    if created and resolved:
        return (resolved - created).total_seconds() / 86400.0
    return None

def cycle_time_days_from_changelog(issue):
    """
    Cycle time = time between first entering an "in progress" category and reaching "done".
    Requires expand=changelog.
    """
    created = parse_dt(issue["fields"].get("created"))
    resolved = parse_dt(issue["fields"].get("resolutiondate"))
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
    created = parse_dt(issue["fields"].get("created"))
    if not created:
        return None
    return (now - created).total_seconds() / 86400.0


# ----------------------------
# Main
# ----------------------------
def main():
    jira = JiraClient()
    projects_csv = ",".join(PROJECT_KEYS)

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

    # ---------
    # 1) Status distribution + WIP aging + blockers
    # ---------
    base_fields = ["project", "issuetype", "status", "assignee", "priority", "created", "resolutiondate", "labels"]

    print("\nPulling current (not done) issues for status distribution & WIP aging...")
    jql_wip = f'project in ({projects_csv}) AND statusCategory != {DONE_CATEGORY}'
    wip_issues = jira.search(jql_wip, fields=base_fields, max_results=5000)

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

    print("\nAging WIP summary (days since created):", summarize_time_metrics(wip_ages))

    print("\nPulling blockers (heuristic JQL)...")
    blocked_jql = f'project in ({projects_csv}) AND statusCategory != {DONE_CATEGORY} AND {BLOCKED_JQL}'
    blocked_issues = jira.search(blocked_jql, fields=base_fields, max_results=2000)
    print(f"Blocked issues: {len(blocked_issues)}")
    if blocked_issues:
        # Show top 10 oldest blocked
        blocked_with_age = []
        for it in blocked_issues:
            age = bug_age_days(it, now=now)
            blocked_with_age.append((age or -1, it["key"], it["fields"]["summary"] if "summary" in it["fields"] else ""))

        blocked_with_age.sort(reverse=True)
        print("Oldest blocked issues (top 10):")
        for age, key, _ in blocked_with_age[:10]:
            print(f"  {key} - {age:.1f} days")

    # ---------
    # 2) Throughput per week (done issues)
    # ---------
    print("\nPulling done issues for throughput + lead time...")
    # last 180 days, adjust as needed
    jql_done = f'project in ({projects_csv}) AND statusCategory = {DONE_CATEGORY} AND resolved >= -180d'
    done_issues = jira.search(jql_done, fields=base_fields, max_results=10000)

    print(f"Done issues pulled (last 180d): {len(done_issues)}")
    weekly = throughput_weekly(done_issues)
    print("\nThroughput by ISO week (issues resolved):")
    for wk in sorted(weekly.keys())[-12:]:
        print(f"  {wk}: {weekly[wk]}")

    # Lead time
    lead_times = [lead_time_days(it) for it in done_issues]
    print("\nLead time summary (created -> resolved):", summarize_time_metrics(lead_times))

    # ---------
    # 3) Cycle time from changelog (sample or full)
    # ---------
    # Changelog is heavier; start with last 90 days to keep it reasonable.
    print("\nPulling done issues (last 90d) WITH changelog for cycle time...")
    jql_done_90 = f'project in ({projects_csv}) AND statusCategory = {DONE_CATEGORY} AND resolved >= -90d'
    done_issues_90 = jira.search(jql_done_90, fields=base_fields, expand="changelog", max_results=3000)
    cycle_times = [cycle_time_days_from_changelog(it) for it in done_issues_90]
    print("Cycle time summary (heuristic first in-progress -> resolved):", summarize_time_metrics(cycle_times))

    # ---------
    # 4) Bugs: open, average age, oldest
    # ---------
    print("\nPulling open bugs...")
    jql_open_bugs = f'project in ({projects_csv}) AND issuetype = Bug AND statusCategory != {DONE_CATEGORY}'
    open_bugs = jira.search(jql_open_bugs, fields=base_fields, max_results=5000)
    print(f"Open bugs: {len(open_bugs)}")

    bug_ages = [(bug_age_days(it, now=now) or -1, it["key"], it["fields"].get("summary", ""), it["fields"]["project"]["key"]) for it in open_bugs]
    bug_age_values = [a for a, *_ in bug_ages if a >= 0]
    print("Open bug age summary (days since created):", summarize_time_metrics(bug_age_values))

    bug_ages.sort(reverse=True)
    print("\nOldest open bugs (top 15):")
    for age, key, summary, proj in bug_ages[:15]:
        print(f"  {key} [{proj}] - {age:.1f} days - {summary[:80]}")

    # ---------
    # 5) Boards + Sprints + Velocity + Commitment vs Done + Throughput per Sprint
    # ---------
    print("\nDiscovering boards per project (first board each, you can refine later)...")
    boards = {}
    for pk in PROJECT_KEYS:
        try:
            b = jira.list_boards_for_project(pk)
            vals = b.get("values", [])
            if vals:
                boards[pk] = vals[0]  # pick first
                print(f"  {pk}: board {vals[0]['id']} - {vals[0]['name']}")
            else:
                print(f"  {pk}: no boards found")
        except Exception as e:
            print(f"  {pk}: failed to list boards ({e})")

    # Collect recent closed sprints from each discovered board
    sprint_rows = []
    for pk, b in boards.items():
        board_id = b["id"]
        try:
            sprints = jira.list_sprints(board_id, state="closed", max_results=50).get("values", [])
            # take last 6 closed sprints
            sprints = sorted(sprints, key=lambda x: x.get("endDate", ""))[-6:]
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
        v = issue["fields"].get(STORY_POINTS_FIELD)
        try:
            return float(v) if v is not None else 0.0
        except Exception:
            return 0.0

    sprint_metrics = []
    for pk, board_id, sprint_id, sprint_name, start, end in sprint_rows:
        # Pull sprint issues
        fields = base_fields + (["summary"] if True else [])
        if STORY_POINTS_FIELD:
            fields.append(STORY_POINTS_FIELD)

        issues = jira.sprint_issues(sprint_id, fields=fields, max_results=1000)

        committed = sum(get_sp(it) for it in issues)  # committed = everything in sprint snapshot (approx)
        done = sum(get_sp(it) for it in issues if it["fields"]["status"]["statusCategory"]["key"] == DONE_CATEGORY)
        throughput = sum(1 for it in issues if it["fields"]["status"]["statusCategory"]["key"] == DONE_CATEGORY)

        sprint_metrics.append({
            "project": pk,
            "board_id": board_id,
            "sprint_id": sprint_id,
            "sprint_name": sprint_name,
            "start": start,
            "end": end,
            "committed_points_or_count": committed,
            "done_points_or_count": done,
            "commitment_done_ratio": (done / committed) if committed else None,
            "throughput_done_issues": throughput,
            "total_issues": len(issues),
        })

    if sprint_metrics:
        df = pd.DataFrame(sprint_metrics)
        print("\nSprint velocity & commitment vs done (recent):")
        # Show a compact view
        view = df[["project","sprint_name","committed_points_or_count","done_points_or_count","commitment_done_ratio","throughput_done_issues","total_issues"]]
        # Print last 20 rows
        print(view.tail(20).to_string(index=False))
    else:
        print("\nNo sprint metrics computed.")

    # ---------
    # 6) Change Failure Rate (CFR) framework
    # ---------
    print("\nChange Failure Rate (CFR) - framework:")
    print("You need a definition in Jira, e.g.:")
    print("  - Incidents labeled change-failure")
    print("  - Bugs linked to deployments/releases")
    print("  - Rollback issues, etc.")
    print("Currently using this placeholder failure JQL:")
    print(" ", CFR_FAILURE_JQL.format(projects=projects_csv))
    try:
        failures = jira.search(CFR_FAILURE_JQL.format(projects=projects_csv), fields=base_fields, max_results=2000)
        print(f"Failure issues matched by rule: {len(failures)}")
        print("If you also define 'changes' (e.g., Deployment issues done), CFR = failures / changes.")
    except Exception as e:
        print("CFR query failed (likely issuetype/labels don't exist in your instance). Adjust CFR_FAILURE_JQL.")
        print("Error:", e)

    print("\nDone.")


if __name__ == "__main__":
    main()

What this script gives you immediately

WIP status distribution + status category (new / in progress / done)

Aging WIP (days since created) with avg/p50/p85/p95

Blockers (best-effort JQL heuristic; you can replace with your real rule)

Throughput per week (resolved per ISO week)

Lead time (created → resolved)

Cycle time (heuristic from changelog; you can tighten it to your exact statuses)

Open bugs + average age + oldest bugs list

Sprint velocity + commitment vs done per sprint (points if it finds story points; else counts)

The 3 things you’ll probably want to customize (fast)
1) “Blocked” definition

If your Jira uses Flagged (common in Scrum boards) or a custom field, tell me what you use and I’ll swap the JQL.

2) Cycle time “start”

Right now it uses a heuristic (“first time status contains in progress/doing/dev/review/testing/qa”).
If you tell me your exact “in progress” statuses (names), I’ll make it exact.

3) Change Failure Rate (CFR)

This one must match how your org records failures. Common options:

Incidents labeled change-failure

Bugs created within 1–3 days after a “Deployment” issue completed

Rollback tickets linked to deployments

If you tell me which Jira issue type represents a change (Deploy/Release/Change Request) and which represents a failure (Incident/Bug/Rollback), I’ll compute CFR properly.

Quick checks (so you don’t get stuck)

If sprint metrics show “no boards found” or “no sprints found”, it’s usually:

you don’t have Jira Software access to those boards, or

the project isn’t mapped to a board, or

permissions

In that case, we can compute sprint-based metrics via JQL + Sprint field instead.

If you paste (non-secret) info:

One example sprint board name you care about most (or the board ID if you know it), and

Your exact “in progress” statuses, and

How you mark “blocked” + what counts as a “change failure” in Jira,

…I’ll tighten the script so the metrics match your process perfectly.