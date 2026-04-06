"""
git_analytics.py -- Git/GitHub/GitLab analytics collector.

Collects PR cycle time, optional PR cycle breakdown (coding / review / merge phases;
GitHub only), size, review turnaround, merge frequency, contributor analysis
(bus factor, Gini), work-pattern analysis, coupling, hotspots, reverts, ownership,
branch drift, pending changes, commit counting, and tag mapping.

Env: GIT_PR_BREAKDOWN_ENABLED (default 1), GIT_PR_DETAIL_MAX (0 = all merged PRs),
GIT_FETCH_WORKERS (default 6).

Outputs ``git_analytics_latest.json`` (+ timestamped copy).
"""

import os
import re
import json
import time
import math
import logging
from datetime import datetime, timezone, timedelta
from collections import Counter, defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed

import requests

from analytics_utils import (
    load_env,
    parse_dt,
    iso_week,
    percentile,
    summarize_time_metrics,
    summarize_hours_metrics,
    gini_coefficient,
    velocity_cv,
    extract_jira_keys,
    extract_pr_number,
    write_json,
    read_json,
)

log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Repo configuration (loaded from REPO_CONFIG env var -- JSON array)
# ---------------------------------------------------------------------------

def _load_repo_config() -> list[dict]:
    """Load repo configuration from REPO_CONFIG env var (JSON array).

    Each entry: {"repo": "Name", "branch": "stable", "octopus": "OctopusName", "exclude_regex": "..."}
    Returns empty list if not configured.
    """
    raw = os.environ.get("REPO_CONFIG", "")
    if not raw:
        return []
    try:
        parsed = json.loads(raw)
        if isinstance(parsed, list):
            return [r for r in parsed if isinstance(r, dict) and r.get("repo")]
    except (json.JSONDecodeError, TypeError):
        log.warning("REPO_CONFIG is not valid JSON, ignoring")
    return []

# ---------------------------------------------------------------------------
# GitHub client
# ---------------------------------------------------------------------------

class GitHubClient:
    """Thin wrapper around the GitHub REST API (mirrors JiraClient patterns)."""

    def __init__(self, token: str, base_url: str = "https://api.github.com"):
        self.base = base_url.rstrip("/")
        self.session = requests.Session()
        self.session.headers.update({
            "Authorization": f"Bearer {token}",
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
        })

    def _get(self, url, params=None, timeout=60):
        if not url.startswith("http"):
            url = f"{self.base}{url}"
        resp = self.session.get(url, params=params, timeout=timeout)
        if resp.status_code == 202:
            return None  # stats endpoints return 202 while computing
        if resp.status_code >= 400:
            log.warning("GitHub %s -> %s %s", url, resp.status_code, resp.text[:200])
            resp.raise_for_status()
        return resp

    def _paginate(self, url, params=None, per_page=100):
        params = dict(params or {})
        params["per_page"] = per_page
        next_url = url if url.startswith("http") else f"{self.base}{url}"
        while next_url:
            resp = self._get(next_url, params=params)
            if resp is None:
                break
            data = resp.json()
            if isinstance(data, list):
                yield from data
                if len(data) < per_page:
                    break
            else:
                break
            link = resp.headers.get("Link", "")
            m = re.search(r'<([^>]+)>;\s*rel="next"', link)
            next_url = m.group(1) if m else None
            params = {}  # params already encoded in next_url
            time.sleep(0.1)

    # ---- Repos ----
    def list_repos(self, org):
        return [r["name"] for r in self._paginate(f"/orgs/{org}/repos")]

    def get_repo(self, owner, repo):
        resp = self._get(f"/repos/{owner}/{repo}")
        return resp.json() if resp else None

    # ---- Pull Requests ----
    def list_pulls(self, owner, repo, state="all", since=None):
        params = {"state": state, "sort": "updated", "direction": "desc"}
        pulls = []
        for pr in self._paginate(f"/repos/{owner}/{repo}/pulls", params):
            if since and parse_dt(pr.get("updated_at")) and parse_dt(pr["updated_at"]) < since:
                break
            pulls.append(pr)
        return pulls

    def get_pull(self, owner, repo, number):
        resp = self._get(f"/repos/{owner}/{repo}/pulls/{number}")
        return resp.json() if resp else None

    def get_pull_reviews(self, owner, repo, number):
        return list(self._paginate(f"/repos/{owner}/{repo}/pulls/{number}/reviews"))

    def get_pull_files(self, owner, repo, number):
        return list(self._paginate(f"/repos/{owner}/{repo}/pulls/{number}/files"))

    def list_pull_commits(self, owner, repo, number):
        """Commits on the PR branch (for earliest-commit / cycle breakdown)."""
        return list(self._paginate(f"/repos/{owner}/{repo}/pulls/{number}/commits"))

    def list_issue_timeline(self, owner, repo, issue_number):
        """Issue/PR timeline events (review_requested, ready_for_review, etc.)."""
        return list(self._paginate(f"/repos/{owner}/{repo}/issues/{issue_number}/timeline"))

    # ---- Commits ----
    def get_commits(self, owner, repo, since=None, until=None, sha=None, per_page=100):
        params = {}
        if since:
            params["since"] = since.isoformat() if isinstance(since, datetime) else since
        if until:
            params["until"] = until.isoformat() if isinstance(until, datetime) else until
        if sha:
            params["sha"] = sha
        return list(self._paginate(f"/repos/{owner}/{repo}/commits", params, per_page))

    def get_commit_pulls(self, owner, repo, sha):
        """Get PRs associated with a commit."""
        try:
            return list(self._paginate(f"/repos/{owner}/{repo}/commits/{sha}/pulls"))
        except Exception:
            return []

    # ---- Contributors / Stats ----
    def get_contributors(self, owner, repo):
        return list(self._paginate(f"/repos/{owner}/{repo}/contributors"))

    def _get_stats(self, owner, repo, stat_type, retries=3):
        for attempt in range(retries):
            resp = self._get(f"/repos/{owner}/{repo}/stats/{stat_type}")
            if resp is not None:
                return resp.json()
            time.sleep(2 ** attempt)
        return None

    def get_stats_punch_card(self, owner, repo):
        return self._get_stats(owner, repo, "punch_card")

    def get_stats_contributors(self, owner, repo):
        return self._get_stats(owner, repo, "contributors")

    # ---- Compare / Tags ----
    def compare(self, owner, repo, base, head):
        resp = self._get(f"/repos/{owner}/{repo}/compare/{base}...{head}")
        return resp.json() if resp else None

    def list_tags(self, owner, repo):
        return list(self._paginate(f"/repos/{owner}/{repo}/tags"))

    def list_releases(self, owner, repo):
        return list(self._paginate(f"/repos/{owner}/{repo}/releases"))


# ---------------------------------------------------------------------------
# GitLab client (minimal, same interface contract)
# ---------------------------------------------------------------------------

class GitLabClient:
    """Minimal GitLab v4 API client."""

    def __init__(self, token: str, base_url: str = "https://gitlab.com/api/v4"):
        self.base = base_url.rstrip("/")
        self.session = requests.Session()
        self.session.headers["PRIVATE-TOKEN"] = token

    def _get(self, url, params=None, timeout=60):
        if not url.startswith("http"):
            url = f"{self.base}{url}"
        resp = self.session.get(url, params=params, timeout=timeout)
        if resp.status_code >= 400:
            log.warning("GitLab %s -> %s", url, resp.status_code)
            resp.raise_for_status()
        return resp

    def _paginate(self, url, params=None, per_page=100):
        params = dict(params or {})
        params["per_page"] = per_page
        page = 1
        while True:
            params["page"] = page
            resp = self._get(url, params=params)
            data = resp.json()
            if not data:
                break
            yield from data
            if len(data) < per_page:
                break
            page += 1
            time.sleep(0.1)

    def list_projects(self, group):
        return [p["path"] for p in self._paginate(f"/groups/{group}/projects")]

    def list_merge_requests(self, project_id, state="merged", since=None):
        params = {"state": state, "order_by": "updated_at", "sort": "desc"}
        if since:
            params["updated_after"] = since.isoformat() if isinstance(since, datetime) else since
        return list(self._paginate(f"/projects/{project_id}/merge_requests", params))

    def get_mr_commits(self, project_id, mr_iid):
        return list(self._paginate(f"/projects/{project_id}/merge_requests/{mr_iid}/commits"))

    def get_mr_changes(self, project_id, mr_iid):
        resp = self._get(f"/projects/{project_id}/merge_requests/{mr_iid}/changes")
        return resp.json() if resp else None

    def get_repository_contributors(self, project_id):
        return list(self._paginate(f"/projects/{project_id}/repository/contributors"))


# ---------------------------------------------------------------------------
# Metric functions
# ---------------------------------------------------------------------------

def pr_cycle_time_metrics(pulls):
    """PR open-to-merge cycle time statistics."""
    values = []
    by_week = defaultdict(list)
    by_repo = defaultdict(list)
    for pr in pulls:
        if not pr.get("merged_at"):
            continue
        created = parse_dt(pr["created_at"])
        merged = parse_dt(pr["merged_at"])
        if not created or not merged:
            continue
        days = (merged - created).total_seconds() / 86400
        values.append(days)
        by_week[iso_week(merged)].append(days)
        repo_name = pr.get("_repo", "unknown")
        by_repo[repo_name].append(days)

    return {
        "pr_cycle_time": summarize_time_metrics(values),
        "pr_cycle_time_by_week": {w: round(sum(v) / len(v), 2) for w, v in sorted(by_week.items())},
        "pr_cycle_time_by_repo": {r: summarize_time_metrics(v) for r, v in by_repo.items()},
    }


def pr_size_metrics(pulls):
    """PR size distribution and averages."""
    buckets = Counter()
    additions_all, deletions_all, files_all = [], [], []
    for pr in pulls:
        if not pr.get("merged_at"):
            continue
        adds = pr.get("additions", 0) or 0
        dels = pr.get("deletions", 0) or 0
        files = pr.get("changed_files", 0) or 0
        total = adds + dels
        if total < 10:
            buckets["xs"] += 1
        elif total < 100:
            buckets["small"] += 1
        elif total < 500:
            buckets["medium"] += 1
        elif total < 1000:
            buckets["large"] += 1
        else:
            buckets["xl"] += 1
        additions_all.append(adds)
        deletions_all.append(dels)
        files_all.append(files)

    return {
        "pr_size": {
            "distribution": dict(buckets),
            "avg_additions": round(sum(additions_all) / max(len(additions_all), 1), 1),
            "avg_deletions": round(sum(deletions_all) / max(len(deletions_all), 1), 1),
            "avg_files_changed": round(sum(files_all) / max(len(files_all), 1), 1),
            "p50_lines": percentile([a + d for a, d in zip(additions_all, deletions_all)], 50),
            "p95_lines": percentile([a + d for a, d in zip(additions_all, deletions_all)], 95),
        }
    }


def _pr_detail_key(pr) -> str:
    repo = pr.get("_repo") or ""
    return f"{repo}:{pr.get('number')}"


def review_turnaround_metrics(pulls, reviews_map):
    """Time-to-first-review and self-merge statistics."""
    values = []
    by_week = defaultdict(list)
    by_merge_week = defaultdict(list)  # keyed by iso_week(merged_at) for time-filter alignment
    no_review = 0
    self_merged = 0
    total = 0

    for pr in pulls:
        if not pr.get("merged_at"):
            continue
        total += 1
        reviews = reviews_map.get(_pr_detail_key(pr), [])
        created = parse_dt(pr["created_at"])
        pr_author = (pr.get("user") or {}).get("login", "")

        if not reviews:
            no_review += 1
            continue

        reviewer_reviews = [r for r in reviews if r.get("user", {}).get("login") != pr_author]
        if not reviewer_reviews:
            self_merged += 1
            no_review += 1
            continue

        first_review_dt = min(
            (parse_dt(r["submitted_at"]) for r in reviewer_reviews if parse_dt(r.get("submitted_at"))),
            default=None,
        )
        if not first_review_dt or not created:
            continue

        hours = (first_review_dt - created).total_seconds() / 3600
        values.append(hours)
        by_week[iso_week(first_review_dt)].append(hours)
        merged_dt = parse_dt(pr["merged_at"])
        if merged_dt:
            by_merge_week[iso_week(merged_dt)].append(hours)

    return {
        "review_turnaround": {
            "count": len(values),
            "avg_hours": round(sum(values) / max(len(values), 1), 1),
            "p50_hours": round(percentile(values, 50) or 0, 1),
            "p85_hours": round(percentile(values, 85) or 0, 1),
            "pct_no_review": round(no_review / max(total, 1) * 100, 1),
            "pct_self_merged": round(self_merged / max(total, 1) * 100, 1),
        },
        "review_turnaround_by_week": {w: round(sum(v) / len(v), 1) for w, v in sorted(by_week.items())},
        # Keyed by merge week so the dashboard can align review stats to a date-range filter.
        # Each entry: { avg_hours: float, n: int }
        "review_turnaround_by_merge_week": {
            w: {"avg_hours": round(sum(v) / len(v), 1), "n": len(v)}
            for w, v in sorted(by_merge_week.items())
        },
    }


def merge_frequency_metrics(pulls):
    """PRs merged per ISO week, with trend detection."""
    by_week = Counter()
    for pr in pulls:
        merged_at = parse_dt(pr.get("merged_at"))
        if merged_at:
            by_week[iso_week(merged_at)] += 1

    weeks_sorted = sorted(by_week.items())
    counts = [c for _, c in weeks_sorted]
    avg = round(sum(counts) / max(len(counts), 1), 1)

    trend = "stable"
    if len(counts) >= 4:
        first_half = sum(counts[: len(counts) // 2])
        second_half = sum(counts[len(counts) // 2 :])
        if second_half > first_half * 1.2:
            trend = "increasing"
        elif second_half < first_half * 0.8:
            trend = "decreasing"

    return {
        "merge_frequency": {
            "merges_by_week": dict(weeks_sorted),
            "avg_merges_per_week": avg,
            "trend": trend,
        }
    }


PR_CYCLE_BREAKDOWN_META = {
    "time_in_progress_hours": (
        "From min(PR opened, earliest commit on the PR) to the first review_requested timeline event "
        "or first non-author submitted review (whichever is earlier). If neither exists, coding spans until merge."
    ),
    "time_in_review_hours": (
        "From end of progress phase to the latest APPROVED review before merge. If no approval, end is merge (phase may equal wait until merge)."
    ),
    "time_to_merge_hours": "From final approval (or merge if none) to merged_at.",
}


def compute_phase_hours_for_pr(pr, commits, timeline, reviews):
    """
    Sequential phases: coding -> review/approval -> merge.
    Returns dict with hours and flags, or None if merged_at/created_at missing.
    """
    merged = parse_dt(pr.get("merged_at"))
    created = parse_dt(pr.get("created_at"))
    if not merged or not created:
        return None

    earliest = None
    for c in commits or []:
        cobj = c.get("commit") or {}
        for key in ("author", "committer"):
            part = cobj.get(key) or {}
            d = parse_dt(part.get("date"))
            if d and (earliest is None or d < earliest):
                earliest = d
    work_start = min(created, earliest) if earliest else created

    req_ts = None
    for ev in timeline or []:
        evname = ev.get("event") or ""
        if evname in ("review_requested", "ready_for_review"):
            t = parse_dt(ev.get("created_at"))
            if t and (req_ts is None or t < req_ts):
                req_ts = t

    pr_author = (pr.get("user") or {}).get("login", "")
    first_submit = None
    for r in reviews or []:
        if r.get("user", {}).get("login") == pr_author:
            continue
        t = parse_dt(r.get("submitted_at"))
        if t and (first_submit is None or t < first_submit):
            first_submit = t

    candidates = [x for x in (req_ts, first_submit) if x is not None]
    if candidates:
        phase_end_coding = min(candidates)
    else:
        phase_end_coding = merged

    approval_ts = None
    for r in reviews or []:
        if r.get("state") != "APPROVED":
            continue
        t = parse_dt(r.get("submitted_at"))
        if not t or t > merged:
            continue
        if approval_ts is None or t > approval_ts:
            approval_ts = t
    no_approval = approval_ts is None
    approval_or_merge = approval_ts if approval_ts is not None else merged

    tip = max(0.0, (phase_end_coding - work_start).total_seconds() / 3600.0)
    tir = max(0.0, (approval_or_merge - phase_end_coding).total_seconds() / 3600.0)
    ttm = max(0.0, (merged - approval_or_merge).total_seconds() / 3600.0)

    return {
        "time_in_progress_hours": tip,
        "time_in_review_hours": tir,
        "time_to_merge_hours": ttm,
        "no_approval": no_approval,
    }


def pr_cycle_breakdown_metrics(merged_pulls, commits_map, timeline_map, reviews_map):
    """
    commits_map / timeline_map keyed by _pr_detail_key(pr).
    """
    prog, rev, mrg = [], [], []
    by_week = defaultdict(lambda: {"prog": [], "rev": [], "mrg": []})
    by_repo = defaultdict(lambda: {"prog": [], "rev": [], "mrg": []})
    excluded = {"missing_dates": 0}
    no_approval_count = 0

    for pr in merged_pulls:
        key = _pr_detail_key(pr)
        cm = commits_map.get(key)
        tm = timeline_map.get(key)
        rv = reviews_map.get(key, [])
        row = compute_phase_hours_for_pr(pr, cm or [], tm or [], rv)
        if row is None:
            excluded["missing_dates"] += 1
            continue
        if row.get("no_approval"):
            no_approval_count += 1
        p, r_, m_ = row["time_in_progress_hours"], row["time_in_review_hours"], row["time_to_merge_hours"]
        prog.append(p)
        rev.append(r_)
        mrg.append(m_)
        merged = parse_dt(pr.get("merged_at"))
        if merged:
            wk = iso_week(merged)
            by_week[wk]["prog"].append(p)
            by_week[wk]["rev"].append(r_)
            by_week[wk]["mrg"].append(m_)
        repo = pr.get("_repo") or "unknown"
        by_repo[repo]["prog"].append(p)
        by_repo[repo]["rev"].append(r_)
        by_repo[repo]["mrg"].append(m_)

    def _avg_week(week_data):
        out = {}
        for wk in sorted(week_data.keys()):
            bucket = week_data[wk]
            n = len(bucket["prog"])
            if n == 0:
                continue
            out[wk] = {
                "avg_progress_hours": round(sum(bucket["prog"]) / n, 2),
                "avg_review_hours": round(sum(bucket["rev"]) / n, 2),
                "avg_merge_hours": round(sum(bucket["mrg"]) / n, 2),
                "pr_count": n,
            }
        return out

    by_repo_out = {}
    for repo, bucket in by_repo.items():
        if not bucket["prog"]:
            continue
        by_repo_out[repo] = {
            "time_in_progress_hours": summarize_hours_metrics(bucket["prog"]),
            "time_in_review_hours": summarize_hours_metrics(bucket["rev"]),
            "time_to_merge_hours": summarize_hours_metrics(bucket["mrg"]),
        }

    return {
        "pr_cycle_breakdown": {
            "time_in_progress_hours": summarize_hours_metrics(prog),
            "time_in_review_hours": summarize_hours_metrics(rev),
            "time_to_merge_hours": summarize_hours_metrics(mrg),
            "no_approval_count": no_approval_count,
            "excluded": excluded,
        },
        "pr_cycle_breakdown_meta": PR_CYCLE_BREAKDOWN_META,
        "pr_cycle_breakdown_by_week": _avg_week(by_week),
        "pr_cycle_breakdown_by_repo": by_repo_out,
    }


def contributor_analysis(commits, pulls):
    """Bus factor, Gini coefficient, top contributors."""
    commit_counts = Counter()
    pr_authored = Counter()
    by_repo = defaultdict(Counter)

    for c in commits:
        author = (c.get("author") or {}).get("login") or (c.get("commit", {}).get("author") or {}).get("name", "unknown")
        commit_counts[author] += 1
        repo = c.get("_repo", "unknown")
        by_repo[repo][author] += 1

    for pr in pulls:
        if pr.get("merged_at"):
            author = (pr.get("user") or {}).get("login", "unknown")
            pr_authored[author] += 1

    def _bus_factor(counter):
        if not counter:
            return 0
        sorted_counts = sorted(counter.values(), reverse=True)
        total = sum(sorted_counts)
        threshold = total * 0.8
        cumulative = 0
        for i, v in enumerate(sorted_counts):
            cumulative += v
            if cumulative >= threshold:
                return i + 1
        return len(sorted_counts)

    bus_by_repo = {r: _bus_factor(c) for r, c in by_repo.items()}
    min_bus = min(bus_by_repo.values()) if bus_by_repo else 0

    now = datetime.now(timezone.utc)
    cutoff_90d = now - timedelta(days=90)
    active_90d = set()
    for c in commits:
        dt = parse_dt((c.get("commit", {}).get("author") or {}).get("date"))
        if dt and dt >= cutoff_90d:
            author = (c.get("author") or {}).get("login") or (c.get("commit", {}).get("author") or {}).get("name")
            if author:
                active_90d.add(author)

    top = sorted(commit_counts.items(), key=lambda x: -x[1])[:20]
    return {
        "contributors": {
            "total_contributors": len(commit_counts),
            "active_contributors_90d": len(active_90d),
            "bus_factor_by_repo": bus_by_repo,
            "min_bus_factor": min_bus,
            "contributor_gini": gini_coefficient(list(commit_counts.values())),
            "top_contributors": [{"login": k, "commits": v, "prs_authored": pr_authored.get(k, 0)} for k, v in top],
        }
    }


def work_pattern_analysis(commits):
    """Weekend / after-hours commit percentages, day/hour distributions."""
    by_day = [0] * 7   # 0=Mon .. 6=Sun
    by_hour = [0] * 24
    total = 0
    weekend = 0
    after_hours = 0

    for c in commits:
        dt = parse_dt((c.get("commit", {}).get("author") or {}).get("date"))
        if not dt:
            continue
        total += 1
        wd = dt.weekday()
        by_day[wd] += 1
        by_hour[dt.hour] += 1
        if wd >= 5:
            weekend += 1
        if dt.hour < 9 or dt.hour >= 18:
            after_hours += 1

    day_names = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
    peak_day = day_names[by_day.index(max(by_day))] if total else None
    peak_hour = by_hour.index(max(by_hour)) if total else None

    return {
        "work_patterns": {
            "weekend_commit_pct": round(weekend / max(total, 1) * 100, 1),
            "after_hours_pct": round(after_hours / max(total, 1) * 100, 1),
            "by_day": dict(zip(day_names, by_day)),
            "by_hour": dict(enumerate(by_hour)),
            "peak_day": peak_day,
            "peak_hour": peak_hour,
        }
    }


def coupling_analysis(pulls_with_files):
    """File co-change coupling from PRs."""
    pair_counts = Counter()
    dir_pair_counts = Counter()

    for pr_files in pulls_with_files:
        filenames = [f["filename"] for f in pr_files if f.get("filename")]
        if len(filenames) > 50:
            continue  # skip huge PRs
        for i in range(len(filenames)):
            for j in range(i + 1, len(filenames)):
                pair = tuple(sorted([filenames[i], filenames[j]]))
                pair_counts[pair] += 1
                dirs = tuple(sorted([os.path.dirname(filenames[i]) or "/", os.path.dirname(filenames[j]) or "/"]))
                if dirs[0] != dirs[1]:
                    dir_pair_counts[dirs] += 1

    top_pairs = []
    max_count = max(pair_counts.values(), default=1)
    for (a, b), count in pair_counts.most_common(30):
        if count < 3:
            break
        top_pairs.append({"file_a": a, "file_b": b, "count": count, "coupling_score": round(count / max_count, 2)})

    top_dir_pairs = []
    for (a, b), count in dir_pair_counts.most_common(15):
        if count < 3:
            break
        top_dir_pairs.append({"dir_a": a, "dir_b": b, "count": count})

    return {
        "coupling": {
            "top_coupled_pairs": top_pairs,
            "directory_coupling": top_dir_pairs,
        }
    }


def hotspot_analysis(commits):
    """Files with highest churn (lines changed)."""
    churn = Counter()
    commit_count = Counter()

    for c in commits:
        files = c.get("files", [])
        for f in files:
            fname = f.get("filename", "")
            changes = (f.get("additions", 0) or 0) + (f.get("deletions", 0) or 0)
            churn[fname] += changes
            commit_count[fname] += 1

    top = [(fname, churn[fname], commit_count[fname]) for fname in churn]
    top.sort(key=lambda x: -x[1])

    dir_churn = Counter()
    for fname, ch, _ in top:
        d = os.path.dirname(fname) or "/"
        dir_churn[d] += ch

    return {
        "hotspots": {
            "top_hotspots": [{"file": f, "churn": ch, "commit_count": cc} for f, ch, cc in top[:30]],
            "hotspot_by_directory": dict(dir_churn.most_common(20)),
        }
    }


_CHURN_IGNORE_RE = re.compile(
    r"(^|/)(package-lock\.json|yarn\.lock|pnpm-lock\.yaml|Pipfile\.lock|poetry\.lock"
    r"|Gemfile\.lock|composer\.lock|go\.sum|Cargo\.lock"
    r"|CHANGELOG(\.md)?|CHANGES(\.md)?|\.min\.(js|css))$",
    re.IGNORECASE,
)


def churn_instability_metrics(commits, window_days=14):
    """
    Measure code instability: percentage of files re-touched within `window_days`
    of their previous modification.  High values suggest poor requirements or
    unstable areas.

    Auto-generated files (lock files, changelogs, minified bundles) are excluded
    to avoid inflating the metric.
    """
    file_last_touched: dict[str, datetime] = {}
    total_touches = 0
    rapid_retouches = 0

    sorted_commits = sorted(
        commits,
        key=lambda c: (c.get("commit", {}).get("author") or {}).get("date", ""),
    )

    window = timedelta(days=window_days)
    for c in sorted_commits:
        raw_date = (c.get("commit", {}).get("author") or {}).get("date")
        if not raw_date:
            continue
        try:
            commit_dt = datetime.fromisoformat(raw_date.replace("Z", "+00:00"))
        except (ValueError, TypeError):
            continue

        for f in c.get("files", []):
            fname = f.get("filename", "")
            if not fname or _CHURN_IGNORE_RE.search(fname):
                continue
            total_touches += 1
            prev = file_last_touched.get(fname)
            if prev is not None and (commit_dt - prev) <= window:
                rapid_retouches += 1
            file_last_touched[fname] = commit_dt

    return {
        "churn_instability": {
            "window_days": window_days,
            "total_file_touches": total_touches,
            "rapid_retouches": rapid_retouches,
            "instability_pct": round(rapid_retouches / max(total_touches, 1) * 100, 1),
        }
    }


def revert_analysis(commits):
    """Detect reverts from commit messages."""
    revert_re = re.compile(r'^Revert\s+"', re.IGNORECASE)
    reverts_commit_re = re.compile(r"This reverts commit", re.IGNORECASE)
    total = len(commits)
    reverts = []
    for c in commits:
        msg = c.get("commit", {}).get("message", "")
        if revert_re.match(msg) or reverts_commit_re.search(msg):
            reverts.append({
                "sha": c.get("sha", "")[:7],
                "message": msg.split("\n")[0][:120],
                "date": (c.get("commit", {}).get("author") or {}).get("date"),
            })

    return {
        "reverts": {
            "total_merges": total,
            "revert_count": len(reverts),
            "revert_rate_pct": round(len(reverts) / max(total, 1) * 100, 2),
            "recent_reverts": reverts[:10],
        }
    }


def ownership_analysis(commits):
    """Per-directory primary contributor and coverage."""
    dir_authors = defaultdict(Counter)
    for c in commits:
        author = (c.get("author") or {}).get("login") or (c.get("commit", {}).get("author") or {}).get("name", "unknown")
        for f in c.get("files", []):
            d = os.path.dirname(f.get("filename", "")) or "/"
            dir_authors[d][author] += 1

    result = {}
    orphans = []
    for d, counter in dir_authors.items():
        total = sum(counter.values())
        top = counter.most_common(2)
        primary = top[0][0] if top else None
        primary_pct = round(top[0][1] / total * 100, 1) if top and total else 0
        secondary = top[1][0] if len(top) > 1 else None
        n_contributors = len(counter)
        result[d] = {
            "primary": primary,
            "secondary": secondary,
            "contributors_count": n_contributors,
            "primary_pct": primary_pct,
        }
        if n_contributors <= 1:
            orphans.append(d)

    return {
        "ownership": {
            "ownership_by_directory": result,
            "orphan_directories": orphans,
        }
    }


# ---------------------------------------------------------------------------
# Ported metrics from PowerShell scripts
# ---------------------------------------------------------------------------

def branch_drift_analysis(client, owner, repo, base_branch, target_branch):
    """
    Commits in base not in target (port from git_release_audit_report.ps1).
    Uses GitHub compare API.
    """
    try:
        data = client.compare(owner, repo, target_branch, base_branch)
        if not data:
            return {"total_missing": 0, "missing_commits": [], "subject_match_count": 0, "by_author": {}}
    except Exception as exc:
        log.warning("Branch drift compare failed for %s/%s: %s", owner, repo, exc)
        return {"total_missing": 0, "missing_commits": [], "subject_match_count": 0, "by_author": {}, "error": str(exc)}

    commits = data.get("commits", [])
    by_author = Counter()
    missing = []
    for c in commits:
        author = (c.get("author") or {}).get("login") or (c.get("commit", {}).get("author") or {}).get("name", "unknown")
        by_author[author] += 1
        missing.append({
            "sha": c.get("sha", "")[:7],
            "author": author,
            "date": (c.get("commit", {}).get("author") or {}).get("date"),
            "subject": c.get("commit", {}).get("message", "").split("\n")[0][:120],
        })

    return {
        "total_missing": len(missing),
        "missing_commits": missing[:50],
        "subject_match_count": 0,
        "by_author": dict(by_author),
    }


def tag_version_mapping(client, owner, repo):
    """
    Build bidirectional version->tag map (port from commit_to_prod_tracker.ps1 Get-GitTagsMap).
    Handles v-prefix variations: "1.2.3" -> "v1.2.3" and "v1.2.3" -> "v1.2.3".
    """
    tag_map = {}
    try:
        tags = client.list_tags(owner, repo)
        for tag in tags:
            name = tag["name"]
            tag_map[name] = name
            m = re.match(r"^v(\d+\.\d+\.\d+.*)$", name)
            if m:
                clean = m.group(1)
                if clean not in tag_map:
                    tag_map[clean] = name
    except Exception as exc:
        log.warning("Tag listing failed for %s/%s: %s", owner, repo, exc)
    return tag_map


def pending_changes_analysis(client, owner, repo, prod_tag, latest_tag):
    """
    Commits between prod and latest release (port from compare_latest_vs_prod.ps1).
    """
    if prod_tag == latest_tag:
        return {"pending_commit_count": 0, "pending_commits": [], "jira_keys_pending": []}

    try:
        data = client.compare(owner, repo, prod_tag, latest_tag)
    except requests.HTTPError:
        for base_tag, head_tag in [(f"v{prod_tag}", f"v{latest_tag}"), (prod_tag, latest_tag)]:
            try:
                data = client.compare(owner, repo, base_tag, head_tag)
                break
            except Exception:
                continue
        else:
            return {"pending_commit_count": 0, "pending_commits": [], "jira_keys_pending": [], "error": "compare failed"}

    if not data:
        return {"pending_commit_count": 0, "pending_commits": [], "jira_keys_pending": []}

    commits = data.get("commits", [])
    jira_keys = set()
    pending = []
    for c in commits:
        msg = c.get("commit", {}).get("message", "")
        keys = extract_jira_keys(msg)
        jira_keys.update(keys)
        pending.append({
            "sha": c.get("sha", "")[:7],
            "author": (c.get("commit", {}).get("author") or {}).get("name", ""),
            "date": (c.get("commit", {}).get("committer") or {}).get("date", ""),
            "message": msg.split("\n")[0][:120],
            "jira_keys": keys,
        })

    return {
        "pending_commit_count": len(pending),
        "pending_commits": pending[:50],
        "jira_keys_pending": sorted(jira_keys),
    }


def commit_count_by_repo(client, owner, repos_config, since, until):
    """
    Count commits per repo in date window (port from commit_counter.ps1).
    """
    results = {}
    total = 0

    for rc in repos_config:
        repo = rc["repo"]
        branch = rc.get("branch", "main")
        exclude_re = rc.get("exclude_regex")
        try:
            commits = client.get_commits(owner, repo, since=since, until=until, sha=branch)
            count = 0
            for c in commits:
                if exclude_re:
                    subject = c.get("commit", {}).get("message", "").split("\n")[0]
                    if re.match(exclude_re, subject):
                        continue
                count += 1
            results[repo] = {"count": count, "mode": "window-end-date", "branch": branch}
            total += count
        except Exception as exc:
            log.warning("Commit count failed for %s: %s", repo, exc)
            results[repo] = {"count": 0, "error": str(exc)}

    return {"by_repo": results, "total": total}


def _github_fetch_pr_detail_bundle(client, org, repo, pr, fetch_breakdown: bool):
    """
    Fetch reviews, optional commits+timeline for breakdown, files, and size fields.
    Returns: key, reviews, commits, timeline, files, detail_updates, error_message
    """
    key = f"{repo}:{pr['number']}"
    num = pr["number"]
    err = None
    detail_updates = {}
    try:
        detail = client.get_pull(org, repo, num)
        if detail:
            for k in ("additions", "deletions", "changed_files"):
                if k in detail:
                    detail_updates[k] = detail[k]
    except Exception as exc:
        err = str(exc)
        log.debug("get_pull failed %s: %s", key, exc)

    reviews = []
    try:
        reviews = client.get_pull_reviews(org, repo, num)
    except Exception as exc:
        log.debug("get_pull_reviews failed %s: %s", key, exc)

    files = []
    try:
        files = client.get_pull_files(org, repo, num)
    except Exception as exc:
        log.debug("get_pull_files failed %s: %s", key, exc)

    commits = []
    timeline = []
    if fetch_breakdown:
        try:
            commits = client.list_pull_commits(org, repo, num)
        except Exception as exc:
            log.debug("list_pull_commits failed %s: %s", key, exc)
        try:
            timeline = client.list_issue_timeline(org, repo, num)
        except Exception as exc:
            log.debug("list_issue_timeline failed %s: %s", key, exc)

    return key, reviews, commits, timeline, files, detail_updates, err


# ---------------------------------------------------------------------------
# main()
# ---------------------------------------------------------------------------

def main():
    load_env()

    provider = os.environ.get("GIT_PROVIDER", "github").lower()
    token = os.environ.get("GIT_TOKEN", "")
    org = os.environ.get("GIT_ORG", "")
    repos_raw = os.environ.get("GIT_REPOS", "*")
    lookback = int(os.environ.get("GIT_LOOKBACK_DAYS", "180"))
    output_dir = os.environ.get("OUTPUT_DIR")

    if not token:
        raise RuntimeError("GIT_TOKEN is required")
    if not org:
        raise RuntimeError("GIT_ORG is required")

    since = datetime.now(timezone.utc) - timedelta(days=lookback)

    if provider == "github":
        base_url = os.environ.get("GIT_BASE_URL", "https://api.github.com")
        client = GitHubClient(token, base_url)
    elif provider == "gitlab":
        base_url = os.environ.get("GIT_BASE_URL", "https://gitlab.com/api/v4")
        client = GitLabClient(token, base_url)
    else:
        raise RuntimeError(f"Unknown GIT_PROVIDER: {provider}")

    repo_config_list = _load_repo_config()
    repo_config_map = {rc["repo"]: rc for rc in repo_config_list}

    # Resolve repo list
    if repos_raw.strip() == "*":
        if repo_config_list:
            repo_names = [rc["repo"] for rc in repo_config_list]
        else:
            try:
                repo_names = client.list_repos(org) if provider == "github" else client.list_projects(org)
            except Exception as exc:
                log.warning("Auto-discovery failed (%s) and no REPO_CONFIG set", exc)
                repo_names = []
    else:
        repo_names = [r.strip() for r in repos_raw.split(",") if r.strip()]

    print(f"[git_analytics] Analyzing {len(repo_names)} repos in {org}, lookback={lookback}d")

    breakdown_enabled = os.environ.get("GIT_PR_BREAKDOWN_ENABLED", "1").lower() not in ("0", "false", "no")
    detail_max_raw = os.environ.get("GIT_PR_DETAIL_MAX", "0")
    fetch_workers = max(1, int(os.environ.get("GIT_FETCH_WORKERS", "6")))

    all_pulls = []
    all_commits = []
    reviews_map = {}
    commits_map = {}
    timeline_map = {}
    pulls_files_map = []
    tag_maps = {}
    branch_drift = {}
    repo_config_out = {}

    for repo in repo_names:
        rc = repo_config_map.get(repo, {})
        branch = rc.get("branch", "main")
        repo_config_out[repo] = {
            "owner": org,
            "default_branch": branch,
            "octopus_project": rc.get("octopus"),
        }

        print(f"  [{repo}] fetching PRs...")
        try:
            if provider == "github":
                pulls = client.list_pulls(org, repo, state="all", since=since)
                for pr in pulls:
                    pr["_repo"] = repo

                merged_prs = [p for p in pulls if p.get("merged_at")]
                try:
                    dm = int(detail_max_raw) if str(detail_max_raw).strip() else 0
                except ValueError:
                    dm = 0
                if dm <= 0:
                    dm = len(merged_prs)
                merged_for_detail = merged_prs[:dm]
                pr_by_key = {_pr_detail_key(p): p for p in merged_for_detail}

                if merged_for_detail:
                    with ThreadPoolExecutor(max_workers=fetch_workers) as pool:
                        futs = [
                            pool.submit(_github_fetch_pr_detail_bundle, client, org, repo, pr, breakdown_enabled)
                            for pr in merged_for_detail
                        ]
                        for fut in as_completed(futs):
                            key, reviews, commits, timeline, files, detail_updates, _err = fut.result()
                            reviews_map[key] = reviews
                            if breakdown_enabled:
                                commits_map[key] = commits
                                timeline_map[key] = timeline
                            if files:
                                pulls_files_map.append(files)
                            pr_obj = pr_by_key.get(key)
                            if pr_obj and detail_updates:
                                pr_obj.update(detail_updates)

                all_pulls.extend(pulls)
            else:
                mrs = client.list_merge_requests(f"{org}/{repo}", state="merged", since=since)
                for mr in mrs:
                    mr["_repo"] = repo
                    mr["merged_at"] = mr.get("merged_at")
                    mr["created_at"] = mr.get("created_at")
                    mr["number"] = mr.get("iid")
                all_pulls.extend(mrs)
        except Exception as exc:
            log.warning("PR fetch failed for %s: %s", repo, exc)

        print(f"  [{repo}] fetching commits...")
        try:
            if provider == "github":
                commits = client.get_commits(org, repo, since=since, sha=branch)
                for c in commits:
                    c["_repo"] = repo
                all_commits.extend(commits)
            else:
                pass  # GitLab commit fetching TBD
        except Exception as exc:
            log.warning("Commit fetch failed for %s: %s", repo, exc)

        # Tag mapping
        if provider == "github":
            print(f"  [{repo}] building tag map...")
            try:
                tag_maps[repo] = tag_version_mapping(client, org, repo)
            except Exception as exc:
                log.warning("Tag map failed for %s: %s", repo, exc)

        # Branch drift (main vs stable, only for repos with two branches)
        if provider == "github" and rc.get("branch") and rc["branch"] != "main":
            print(f"  [{repo}] checking branch drift (main -> {rc['branch']})...")
            try:
                drift = branch_drift_analysis(client, org, repo, "main", rc["branch"])
                if drift.get("total_missing", 0) > 0:
                    branch_drift[repo] = {
                        "base": "main",
                        "target": rc["branch"],
                        **drift,
                    }
            except Exception as exc:
                log.warning("Branch drift failed for %s: %s", repo, exc)

    # Aggregate metrics
    print("[git_analytics] Computing metrics...")

    merged_pulls = [p for p in all_pulls if p.get("merged_at")]

    results = {
        "run_iso_ts": datetime.now(timezone.utc).isoformat(),
        "provider": provider,
        "org": org,
        "repos_analyzed": repo_names,
        "lookback_days": lookback,
        "pr_count": len(all_pulls),
        "pr_merged_count": len(merged_pulls),
        "pr_open_count": sum(1 for p in all_pulls if p.get("state") == "open"),
        "pr_closed_not_merged_count": sum(1 for p in all_pulls if p.get("state") == "closed" and not p.get("merged_at")),
    }

    results.update(pr_cycle_time_metrics(all_pulls))
    results.update(pr_size_metrics(all_pulls))
    results.update(review_turnaround_metrics(all_pulls, reviews_map))
    results.update(merge_frequency_metrics(all_pulls))

    if provider == "github" and breakdown_enabled:
        results.update(pr_cycle_breakdown_metrics(merged_pulls, commits_map, timeline_map, reviews_map))
    elif provider == "gitlab":
        results["pr_cycle_breakdown"] = None
        results["pr_cycle_breakdown_meta"] = None
        results["pr_cycle_breakdown_by_week"] = {}
        results["pr_cycle_breakdown_by_repo"] = {}
        results["pr_cycle_breakdown_skip_reason"] = "gitlab_not_supported"
    else:
        results["pr_cycle_breakdown"] = None
        results["pr_cycle_breakdown_meta"] = None
        results["pr_cycle_breakdown_by_week"] = {}
        results["pr_cycle_breakdown_by_repo"] = {}
        results["pr_cycle_breakdown_skip_reason"] = "disabled_via_env"
    results.update(contributor_analysis(all_commits, all_pulls))
    results.update(work_pattern_analysis(all_commits))
    results.update(coupling_analysis(pulls_files_map))
    results.update(revert_analysis(all_commits))
    results.update(churn_instability_metrics(all_commits))
    results.update(ownership_analysis(all_commits))

    # Per-repo breakdowns
    by_repo = {}
    for repo in repo_names:
        repo_pulls = [p for p in all_pulls if p.get("_repo") == repo]
        repo_commits = [c for c in all_commits if c.get("_repo") == repo]
        by_repo[repo] = {}
        if repo_pulls:
            by_repo[repo].update(pr_cycle_time_metrics(repo_pulls))
            by_repo[repo].update(pr_size_metrics(repo_pulls))
            by_repo[repo].update(merge_frequency_metrics(repo_pulls))
            by_repo[repo].update(review_turnaround_metrics(repo_pulls, reviews_map))
            repo_merged = [p for p in repo_pulls if p.get("merged_at")]
            if provider == "github" and breakdown_enabled and repo_merged:

                def _prefixed(m):
                    prefix = f"{repo}:"
                    return {k: v for k, v in m.items() if k.startswith(prefix)}

                sub = pr_cycle_breakdown_metrics(
                    repo_merged,
                    _prefixed(commits_map),
                    _prefixed(timeline_map),
                    _prefixed(reviews_map),
                )
                by_repo[repo]["pr_cycle_breakdown"] = sub["pr_cycle_breakdown"]
                by_repo[repo]["pr_cycle_breakdown_meta"] = sub.get("pr_cycle_breakdown_meta")
                by_repo[repo]["pr_cycle_breakdown_by_week"] = sub["pr_cycle_breakdown_by_week"]
            by_repo[repo].update(revert_analysis(repo_commits))
        if repo_commits:
            by_repo[repo].update(churn_instability_metrics(repo_commits))
    results["by_repo"] = by_repo

    # Script-ported metrics
    if branch_drift:
        total_missing = sum(d.get("total_missing", 0) for d in branch_drift.values())
        results["branch_drift"] = {
            "by_repo": branch_drift,
            "total_missing_across_repos": total_missing,
        }

    results["tag_maps"] = tag_maps

    repos_config = [repo_config_map.get(r, {"repo": r, "branch": "main"}) for r in repo_names]
    results["commit_counts"] = commit_count_by_repo(client, org, repos_config, since, datetime.now(timezone.utc))

    results["repo_config"] = repo_config_out

    path = write_json(results, "git_analytics", output_dir)
    print(f"[git_analytics] Wrote {path}")
    print(f"  PRs analyzed: {results['pr_count']} (merged: {results['pr_merged_count']})")
    print(f"  Commits analyzed: {len(all_commits)}")
    if branch_drift:
        print(f"  Branch drift: {results['branch_drift']['total_missing_across_repos']} missing commits across {len(branch_drift)} repos")

    return results


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    main()
