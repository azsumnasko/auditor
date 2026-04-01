"""
cicd_analytics.py -- CI/CD metrics collector (GitHub Actions + Jenkins).

Collects build success rate, build time trends, deployment frequency,
MTTR, and change failure rate.

Outputs ``cicd_analytics_latest.json`` (+ timestamped copy).
"""

import os
import re
import time
import logging
from datetime import datetime, timezone, timedelta
from collections import Counter, defaultdict

import requests

from analytics_utils import (
    load_env,
    parse_dt,
    iso_week,
    percentile,
    summarize_time_metrics,
    write_json,
)

log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# GitHub Actions client
# ---------------------------------------------------------------------------

class GitHubActionsClient:
    """Fetch workflow runs from the GitHub Actions API."""

    def __init__(self, token: str, base_url: str = "https://api.github.com"):
        self.base = base_url.rstrip("/")
        self.session = requests.Session()
        self.session.headers.update({
            "Authorization": f"Bearer {token}",
            "Accept": "application/vnd.github+json",
        })

    def _get(self, url, params=None):
        full = url if url.startswith("http") else f"{self.base}{url}"
        resp = self.session.get(full, params=params, timeout=60)
        if resp.status_code >= 400:
            log.warning("GH Actions %s -> %s", full, resp.status_code)
            resp.raise_for_status()
        return resp.json()

    def list_workflow_runs(self, owner, repo, created_filter=None, per_page=100):
        """Paginate through /actions/runs."""
        runs = []
        page = 1
        while True:
            params = {"per_page": per_page, "page": page}
            if created_filter:
                params["created"] = created_filter
            data = self._get(f"/repos/{owner}/{repo}/actions/runs", params)
            items = data.get("workflow_runs", [])
            if not items:
                break
            runs.extend(items)
            if len(items) < per_page:
                break
            page += 1
            time.sleep(0.1)
        return runs


# ---------------------------------------------------------------------------
# Jenkins client
# ---------------------------------------------------------------------------

class JenkinsClient:
    """Fetch build data from Jenkins JSON API."""

    def __init__(self, base_url: str, user: str = "", token: str = ""):
        self.base = base_url.rstrip("/")
        self.session = requests.Session()
        if user and token:
            self.session.auth = (user, token)

    def get_builds(self, job_name: str, limit: int = 500):
        url = f"{self.base}/job/{job_name}/api/json"
        params = {"tree": f"builds[number,result,duration,timestamp]{{0,{limit}}}"}
        resp = self.session.get(url, params=params, timeout=60)
        resp.raise_for_status()
        return resp.json().get("builds", [])


# ---------------------------------------------------------------------------
# Metric functions
# ---------------------------------------------------------------------------

def build_metrics(runs):
    """Build success rate, average time, trend, flakiness."""
    completed = [r for r in runs if r.get("status") == "completed"]
    if not completed:
        return {"success_rate": None, "total_runs": 0}

    successes = sum(1 for r in completed if r.get("conclusion") == "success")
    total = len(completed)
    success_rate = round(successes / total * 100, 1)

    build_times = []
    by_week = defaultdict(list)
    failure_reasons = Counter()
    retries = 0

    for r in completed:
        started = parse_dt(r.get("run_started_at"))
        updated = parse_dt(r.get("updated_at"))
        if started and updated:
            minutes = (updated - started).total_seconds() / 60
            build_times.append(minutes)
            by_week[iso_week(updated)].append(minutes)

        conclusion = r.get("conclusion", "unknown")
        if conclusion != "success":
            failure_reasons[conclusion] += 1

        if (r.get("run_attempt") or 1) > 1:
            retries += 1

    return {
        "success_rate": success_rate,
        "avg_build_time_minutes": round(sum(build_times) / max(len(build_times), 1), 1),
        "build_time_trend_by_week": {w: round(sum(v) / len(v), 1) for w, v in sorted(by_week.items())},
        "failure_reasons": dict(failure_reasons.most_common(10)),
        "flakiness_rate": round(retries / max(total, 1) * 100, 1),
        "total_runs": total,
    }


def deployment_metrics(runs, deploy_workflow=None):
    """Deployment frequency from workflow runs."""
    deploy_runs = runs
    if deploy_workflow:
        deploy_runs = [r for r in runs if (r.get("path") or "").endswith(deploy_workflow)]

    successful = [r for r in deploy_runs if r.get("conclusion") == "success"]
    by_week = Counter()
    for r in successful:
        dt = parse_dt(r.get("run_started_at") or r.get("created_at"))
        if dt:
            by_week[iso_week(dt)] += 1

    n_weeks = max(len(by_week), 1)
    total = sum(by_week.values())
    avg = round(total / n_weeks, 2)

    if avg > 5:
        category = "on_demand"
    elif avg >= 1:
        category = "daily"
    elif avg >= 0.25:
        category = "weekly"
    else:
        category = "monthly"

    return {
        "deploy_count": total,
        "deploy_frequency_per_week": dict(sorted(by_week.items())),
        "avg_deploys_per_week": avg,
        "deploy_frequency_category": category,
    }


def mttr_metrics(runs):
    """Mean time to recovery: time from failure to next success on same workflow."""
    by_workflow = defaultdict(list)
    for r in runs:
        if r.get("status") != "completed":
            continue
        wf = r.get("workflow_id") or r.get("path", "")
        by_workflow[wf].append(r)

    recovery_times = []
    for wf, wf_runs in by_workflow.items():
        sorted_runs = sorted(wf_runs, key=lambda r: r.get("run_started_at", ""))
        for i, r in enumerate(sorted_runs):
            if r.get("conclusion") != "failure":
                continue
            fail_dt = parse_dt(r.get("run_started_at"))
            if not fail_dt:
                continue
            for j in range(i + 1, len(sorted_runs)):
                if sorted_runs[j].get("conclusion") == "success":
                    recovery_dt = parse_dt(sorted_runs[j].get("run_started_at"))
                    if recovery_dt:
                        hours = (recovery_dt - fail_dt).total_seconds() / 3600
                        recovery_times.append(hours)
                    break

    if not recovery_times:
        return {"avg_mttr_hours": None, "p50_mttr_hours": None, "p85_mttr_hours": None}

    return {
        "avg_mttr_hours": round(sum(recovery_times) / len(recovery_times), 1),
        "p50_mttr_hours": round(percentile(recovery_times, 50) or 0, 1),
        "p85_mttr_hours": round(percentile(recovery_times, 85) or 0, 1),
    }


def change_failure_rate(runs, deploy_workflow=None):
    """Percentage of deployments that fail."""
    deploy_runs = runs
    if deploy_workflow:
        deploy_runs = [r for r in runs if (r.get("path") or "").endswith(deploy_workflow)]

    completed = [r for r in deploy_runs if r.get("status") == "completed"]
    total = len(completed)
    failed = sum(1 for r in completed if r.get("conclusion") == "failure")

    return {
        "total_deploys": total,
        "failed_deploys": failed,
        "cfr_pct": round(failed / max(total, 1) * 100, 1),
    }


# ---------------------------------------------------------------------------
# main()
# ---------------------------------------------------------------------------

def main():
    load_env()

    provider = os.environ.get("CICD_PROVIDER", "github_actions").lower()
    output_dir = os.environ.get("OUTPUT_DIR")
    lookback = int(os.environ.get("CICD_LOOKBACK_DAYS", "90"))
    deploy_workflow = os.environ.get("CICD_DEPLOY_WORKFLOW")

    if provider == "none":
        print("[cicd_analytics] CICD_PROVIDER=none, skipping.")
        return None

    since = datetime.now(timezone.utc) - timedelta(days=lookback)
    since_str = since.strftime("%Y-%m-%dT%H:%M:%SZ")

    all_runs = []
    repos_analyzed = []

    if provider == "github_actions":
        token = os.environ.get("CICD_TOKEN") or os.environ.get("GIT_TOKEN", "")
        org = os.environ.get("CICD_ORG") or os.environ.get("GIT_ORG", "")
        repos_raw = os.environ.get("CICD_REPOS") or os.environ.get("GIT_REPOS", "")
        base_url = os.environ.get("GIT_BASE_URL", "https://api.github.com")

        if not token or not org:
            print("[cicd_analytics] Missing token/org for GitHub Actions, skipping.")
            return None

        client = GitHubActionsClient(token, base_url)

        if repos_raw.strip() == "*" or not repos_raw:
            rc_raw = os.environ.get("REPO_CONFIG", "")
            if rc_raw:
                try:
                    import json as _json
                    parsed = _json.loads(rc_raw)
                    repo_names = [r["repo"] for r in parsed if isinstance(r, dict) and r.get("repo")]
                except (ValueError, TypeError):
                    repo_names = []
            else:
                repo_names = []
            if not repo_names:
                print("[cicd_analytics] No REPO_CONFIG and GIT_REPOS=*, cannot determine repos. Skipping.")
                return None
        else:
            repo_names = [r.strip() for r in repos_raw.split(",") if r.strip()]

        for repo in repo_names:
            print(f"  [{repo}] fetching workflow runs...")
            try:
                runs = client.list_workflow_runs(org, repo, created_filter=f">={since_str[:10]}")
                for r in runs:
                    r["_repo"] = repo
                all_runs.extend(runs)
                repos_analyzed.append(repo)
            except Exception as exc:
                log.warning("Workflow runs fetch failed for %s: %s", repo, exc)

    elif provider == "jenkins":
        base_url = os.environ.get("CICD_BASE_URL", "")
        user = os.environ.get("CICD_USER", "")
        token = os.environ.get("CICD_TOKEN", "")
        jobs_raw = os.environ.get("CICD_JENKINS_JOBS", "")

        if not base_url:
            print("[cicd_analytics] CICD_BASE_URL required for Jenkins, skipping.")
            return None

        client = JenkinsClient(base_url, user, token)
        job_names = [j.strip() for j in jobs_raw.split(",") if j.strip()]

        for job in job_names:
            print(f"  [{job}] fetching builds...")
            try:
                builds = client.get_builds(job)
                for b in builds:
                    ts = b.get("timestamp", 0) / 1000
                    dt = datetime.fromtimestamp(ts, tz=timezone.utc)
                    if dt < since:
                        continue
                    all_runs.append({
                        "status": "completed",
                        "conclusion": (b.get("result") or "unknown").lower(),
                        "run_started_at": dt.isoformat(),
                        "updated_at": (dt + timedelta(milliseconds=b.get("duration", 0))).isoformat(),
                        "_repo": job,
                    })
                repos_analyzed.append(job)
            except Exception as exc:
                log.warning("Jenkins build fetch failed for %s: %s", job, exc)

    print(f"[cicd_analytics] Collected {len(all_runs)} runs from {len(repos_analyzed)} repos")

    builds = build_metrics(all_runs)
    deploys = deployment_metrics(all_runs, deploy_workflow)
    mttr = mttr_metrics(all_runs)
    cfr = change_failure_rate(all_runs, deploy_workflow)

    by_repo = {}
    for repo in repos_analyzed:
        repo_runs = [r for r in all_runs if r.get("_repo") == repo]
        by_repo[repo] = {
            "builds": build_metrics(repo_runs),
            "deployments": deployment_metrics(repo_runs, deploy_workflow),
        }

    results = {
        "run_iso_ts": datetime.now(timezone.utc).isoformat(),
        "provider": provider,
        "repos_analyzed": repos_analyzed,
        "builds": builds,
        "deployments": deploys,
        "mttr": mttr,
        "change_failure_rate": cfr,
        "by_repo": by_repo,
    }

    path = write_json(results, "cicd_analytics", output_dir)
    print(f"[cicd_analytics] Wrote {path}")
    print(f"  Build success rate: {builds.get('success_rate')}%")
    print(f"  Deploy frequency: {deploys.get('deploy_frequency_category')}")

    return results


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    main()
