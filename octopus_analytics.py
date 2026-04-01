"""
octopus_analytics.py -- Octopus Deploy analytics collector.

Ported from:
  - commit_to_prod_tracker.ps1  (deployment history, commit-to-prod lead time)
  - compare_latest_vs_prod.ps1  (pending changes, version gaps)

Outputs ``octopus_analytics_latest.json`` (+ timestamped copy).
"""

import os
import re
import json
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
    extract_jira_keys,
    extract_pr_number,
    write_json,
    read_json,
)

log = logging.getLogger(__name__)

def _build_repo_map_from_config() -> dict:
    """Build repo->octopus mapping from REPO_CONFIG env var.

    Falls back to OCTOPUS_REPO_MAP if present.
    """
    repo_map: dict[str, str] = {}
    raw = os.environ.get("REPO_CONFIG", "")
    if raw:
        try:
            parsed = json.loads(raw)
            if isinstance(parsed, list):
                for entry in parsed:
                    repo = entry.get("repo", "")
                    octopus = entry.get("octopus", "")
                    if repo and octopus:
                        repo_map[repo] = octopus
        except (json.JSONDecodeError, TypeError):
            pass
    return repo_map


# ---------------------------------------------------------------------------
# Octopus Deploy client  (ported from PS1 helper functions)
# ---------------------------------------------------------------------------

class OctopusClient:
    """
    Thin wrapper around the Octopus Deploy REST API.
    Mirrors the caching pattern from the PowerShell scripts.
    """

    def __init__(self, server_url: str, api_key: str):
        self.base = server_url.rstrip("/")
        self.session = requests.Session()
        self.session.headers["X-Octopus-ApiKey"] = api_key
        self._project_cache: dict[str, dict] = {}
        self._environment_cache: dict[str, dict] = {}
        self._release_cache: dict[str, str] = {}
        self._deployments_cache: dict[str, list] = {}

    def _get(self, url, params=None, timeout=60):
        full = url if url.startswith("http") else f"{self.base}{url}"
        resp = self.session.get(full, params=params, timeout=timeout)
        if resp.status_code >= 400:
            log.warning("Octopus %s -> %s", full, resp.status_code)
            resp.raise_for_status()
        return resp.json()

    # ---- Project resolution (cached) ----
    def resolve_project(self, name: str) -> dict | None:
        if name in self._project_cache:
            return self._project_cache[name]
        data = self._get("/api/projects", params={"partialName": name})
        for item in data.get("Items", []):
            if item["Name"] == name:
                self._project_cache[name] = item
                return item
        return None

    # ---- Environment resolution (cached) ----
    def resolve_environment(self, name: str) -> dict | None:
        if name in self._environment_cache:
            return self._environment_cache[name]
        data = self._get("/api/environments", params={"partialName": name})
        for item in data.get("Items", []):
            if item["Name"] == name:
                self._environment_cache[name] = item
                return item
        return None

    # ---- Deployments ----
    def get_deployments(self, project_id: str, environment_id: str, take: int = 500) -> list:
        cache_key = f"{project_id}:{environment_id}"
        if cache_key in self._deployments_cache:
            return self._deployments_cache[cache_key]
        data = self._get(
            "/api/deployments",
            params={"projects": project_id, "environments": environment_id, "take": take, "taskState": "Success"},
        )
        items = sorted(data.get("Items", []), key=lambda d: d.get("Created", ""))
        self._deployments_cache[cache_key] = items
        return items

    # ---- Release version (cached) ----
    def get_release_version(self, release_id: str) -> str | None:
        if release_id in self._release_cache:
            return self._release_cache[release_id]
        try:
            data = self._get(f"/api/releases/{release_id}")
            version = data.get("Version")
            self._release_cache[release_id] = version
            return version
        except Exception:
            return None

    # ---- Latest release for a project ----
    def get_latest_release(self, project_id: str, take: int = 500) -> dict | None:
        data = self._get(f"/api/projects/{project_id}/releases", params={"take": take})
        for item in data.get("Items", []):
            version = item.get("Version", "")
            if "-main" in version or "-rc" in version:
                continue
            return item
        return None


# ---------------------------------------------------------------------------
# Lightweight GitHub client (reuse token from git_analytics)
# ---------------------------------------------------------------------------

class _GitHubCompare:
    """Minimal GitHub client for compare API calls only."""

    def __init__(self, token: str, base_url: str = "https://api.github.com"):
        self.base = base_url.rstrip("/")
        self.session = requests.Session()
        self.session.headers.update({
            "Authorization": f"Bearer {token}",
            "Accept": "application/vnd.github+json",
        })

    def compare(self, owner, repo, base, head):
        url = f"{self.base}/repos/{owner}/{repo}/compare/{base}...{head}"
        resp = self.session.get(url, timeout=60)
        if resp.status_code >= 400:
            resp.raise_for_status()
        return resp.json()

    def get_pull(self, owner, repo, number):
        url = f"{self.base}/repos/{owner}/{repo}/pulls/{number}"
        resp = self.session.get(url, timeout=60)
        if resp.status_code >= 400:
            return None
        return resp.json()


# ---------------------------------------------------------------------------
# Metric functions
# ---------------------------------------------------------------------------

def _resolve_tag(version: str, tag_map: dict) -> str | None:
    """Try to resolve a version string to a git tag using the tag map."""
    if not tag_map:
        return version
    return tag_map.get(version) or tag_map.get(f"v{version}") or version


def deployment_history(octopus, github, org, repo_map, env_name, since, tag_maps):
    """
    For each repo, get Octopus deployments and map to GitHub commits.
    Returns deployment records with commit lists.
    """
    env = octopus.resolve_environment(env_name)
    if not env:
        log.error("Octopus environment '%s' not found", env_name)
        return {}

    env_id = env["Id"]
    history = {}

    for repo_name, octopus_project_name in repo_map.items():
        project = octopus.resolve_project(octopus_project_name)
        if not project:
            log.warning("Octopus project '%s' not found (repo=%s)", octopus_project_name, repo_name)
            continue

        deployments = octopus.get_deployments(project["Id"], env_id)
        if not deployments:
            continue

        tag_map = tag_maps.get(repo_name, {})
        repo_deploys = []

        for idx, dep in enumerate(deployments):
            dep_date = parse_dt(dep.get("Created"))
            if dep_date and dep_date < since:
                continue

            version = octopus.get_release_version(dep.get("ReleaseId", ""))
            if not version:
                continue

            prev_version = None
            if idx > 0:
                prev_version = octopus.get_release_version(deployments[idx - 1].get("ReleaseId", ""))

            commits = []
            commit_count = 0
            if prev_version and version != prev_version:
                current_tag = _resolve_tag(version, tag_map)
                prev_tag = _resolve_tag(prev_version, tag_map)
                try:
                    data = github.compare(org, repo_name, prev_tag, current_tag)
                    if data:
                        for c in data.get("commits", []):
                            commits.append({
                                "sha": c.get("sha", "")[:7],
                                "message": c.get("commit", {}).get("message", "").split("\n")[0][:120],
                                "date": (c.get("commit", {}).get("committer") or {}).get("date"),
                                "author": (c.get("commit", {}).get("author") or {}).get("name", ""),
                            })
                        commit_count = data.get("total_commits", len(commits))
                except Exception as exc:
                    log.debug("Compare failed %s %s..%s: %s", repo_name, prev_tag, current_tag, exc)

            repo_deploys.append({
                "version": version,
                "deploy_date": dep.get("Created"),
                "previous_version": prev_version,
                "commit_count": commit_count,
                "commits": commits[:50],
            })

        if repo_deploys:
            history[repo_name] = {
                "deployment_count": len(repo_deploys),
                "deployments": repo_deploys,
            }

    return history


def commit_to_prod_lead_time(history, github, org):
    """
    Compute lead time from commit/PR-merge to production deployment.
    Ported from commit_to_prod_tracker.ps1 core logic.
    """
    all_lead_times = []
    by_repo = defaultdict(list)
    by_week = defaultdict(list)
    details = []

    for repo_name, repo_data in history.items():
        for dep in repo_data.get("deployments", []):
            deploy_dt = parse_dt(dep.get("deploy_date"))
            if not deploy_dt:
                continue

            for commit in dep.get("commits", []):
                msg = commit.get("message", "")
                if msg.startswith("Merge branch"):
                    continue

                commit_dt = parse_dt(commit.get("date"))
                if not commit_dt:
                    continue

                data_source = "Commit Date"
                effective_dt = commit_dt

                pr_num = extract_pr_number(msg)
                if pr_num:
                    try:
                        pr_data = github.get_pull(org, repo_name, pr_num)
                        if pr_data and pr_data.get("merged_at"):
                            merged_dt = parse_dt(pr_data["merged_at"])
                            if merged_dt:
                                effective_dt = merged_dt
                                data_source = f"PR #{pr_num} Merge Date"
                    except Exception:
                        pass

                lead_days = (deploy_dt - effective_dt).total_seconds() / 86400
                if lead_days < 0:
                    continue

                all_lead_times.append(lead_days)
                by_repo[repo_name].append(lead_days)
                by_week[iso_week(deploy_dt)].append(lead_days)
                details.append({
                    "repo": repo_name,
                    "sha": commit.get("sha", ""),
                    "commit_date": effective_dt.isoformat(),
                    "deploy_date": deploy_dt.isoformat(),
                    "lead_time_days": round(lead_days, 2),
                    "data_source": data_source,
                })

    result = summarize_time_metrics(all_lead_times)
    result["by_repo"] = {r: summarize_time_metrics(v) for r, v in by_repo.items()}
    result["by_week"] = {w: round(sum(v) / len(v), 2) for w, v in sorted(by_week.items())}
    result["details"] = details[:200]
    return result


def pending_changes_per_repo(octopus, github, org, repo_map, env_name, tag_maps):
    """
    For each repo, compare prod version vs latest release.
    Ported from compare_latest_vs_prod.ps1.
    """
    env = octopus.resolve_environment(env_name)
    if not env:
        return {}

    env_id = env["Id"]
    result = {}
    total_pending_repos = 0
    total_pending_commits = 0

    for repo_name, octopus_project_name in repo_map.items():
        project = octopus.resolve_project(octopus_project_name)
        if not project:
            continue

        deployments = octopus.get_deployments(project["Id"], env_id)
        if not deployments:
            continue

        prod_version = octopus.get_release_version(deployments[-1].get("ReleaseId", ""))
        latest_rel = octopus.get_latest_release(project["Id"])
        latest_version = latest_rel.get("Version") if latest_rel else None

        if not prod_version or not latest_version:
            continue

        if prod_version == latest_version:
            result[repo_name] = {
                "prod_version": prod_version,
                "latest_version": latest_version,
                "status": "ok",
                "pending_count": 0,
            }
            continue

        tag_map = tag_maps.get(repo_name, {})
        prod_tag = _resolve_tag(prod_version, tag_map)
        latest_tag = _resolve_tag(latest_version, tag_map)
        pending_commits = []
        jira_keys = set()

        try:
            data = github.compare(org, repo_name, prod_tag, latest_tag)
            if data:
                for c in data.get("commits", []):
                    msg = c.get("commit", {}).get("message", "")
                    keys = extract_jira_keys(msg)
                    jira_keys.update(keys)
                    pending_commits.append({
                        "sha": c.get("sha", "")[:7],
                        "author": (c.get("commit", {}).get("author") or {}).get("name", ""),
                        "date": (c.get("commit", {}).get("committer") or {}).get("date", ""),
                        "message": msg.split("\n")[0][:120],
                        "jira_keys": keys,
                    })
        except Exception as exc:
            try:
                data = github.compare(org, repo_name, f"v{prod_tag}", f"v{latest_tag}")
                if data:
                    for c in data.get("commits", []):
                        msg = c.get("commit", {}).get("message", "")
                        keys = extract_jira_keys(msg)
                        jira_keys.update(keys)
                        pending_commits.append({
                            "sha": c.get("sha", "")[:7],
                            "author": (c.get("commit", {}).get("author") or {}).get("name", ""),
                            "date": (c.get("commit", {}).get("committer") or {}).get("date", ""),
                            "message": msg.split("\n")[0][:120],
                        })
            except Exception:
                log.debug("Pending compare failed for %s: %s", repo_name, exc)

        count = len(pending_commits)
        result[repo_name] = {
            "prod_version": prod_version,
            "latest_version": latest_version,
            "status": "pending",
            "pending_count": count,
            "jira_keys": sorted(jira_keys),
            "pending_commits": pending_commits[:50],
        }
        total_pending_repos += 1
        total_pending_commits += count

    return {
        "by_repo": result,
        "total_pending_repos": total_pending_repos,
        "total_pending_commits": total_pending_commits,
    }


def deployment_frequency(history):
    """Compute deployment frequency per repo from deployment history."""
    by_repo = {}
    all_weeks = Counter()

    for repo_name, repo_data in history.items():
        repo_weeks = Counter()
        for dep in repo_data.get("deployments", []):
            dt = parse_dt(dep.get("deploy_date"))
            if dt:
                w = iso_week(dt)
                repo_weeks[w] += 1
                all_weeks[w] += 1

        n_weeks = max(len(repo_weeks), 1)
        total = sum(repo_weeks.values())
        avg = round(total / n_weeks, 2)
        cat = _freq_category(avg)

        by_repo[repo_name] = {
            "avg_per_week": avg,
            "category": cat,
            "deploys_per_week": dict(sorted(repo_weeks.items())),
        }

    n_weeks_overall = max(len(all_weeks), 1)
    overall_total = sum(all_weeks.values())
    overall_avg = round(overall_total / n_weeks_overall, 2)

    return {
        "overall_avg_per_week": overall_avg,
        "overall_category": _freq_category(overall_avg),
        "by_repo": by_repo,
    }


def _freq_category(avg_per_week):
    if avg_per_week > 5:
        return "on_demand"
    elif avg_per_week >= 1:
        return "daily"
    elif avg_per_week >= 0.25:
        return "weekly"
    else:
        return "monthly"


# ---------------------------------------------------------------------------
# main()
# ---------------------------------------------------------------------------

def main():
    load_env()

    server_url = os.environ.get("OCTOPUS_SERVER_URL", "")
    api_key = os.environ.get("OCTOPUS_API_KEY", "")
    env_name = os.environ.get("OCTOPUS_ENVIRONMENT", "Ontario")
    git_token = os.environ.get("GIT_TOKEN", "")
    git_org = os.environ.get("GIT_ORG", "")
    lookback = int(os.environ.get("OCTOPUS_LOOKBACK_DAYS", "180"))
    output_dir = os.environ.get("OUTPUT_DIR")
    repo_map_raw = os.environ.get("OCTOPUS_REPO_MAP", "")

    if not server_url:
        print("[octopus_analytics] OCTOPUS_SERVER_URL not set, skipping.")
        return None
    if not api_key:
        raise RuntimeError("OCTOPUS_API_KEY is required when OCTOPUS_SERVER_URL is set")
    if not git_token:
        raise RuntimeError("GIT_TOKEN is required for GitHub compare calls")
    if not git_org:
        raise RuntimeError("GIT_ORG is required")

    repo_map = _build_repo_map_from_config()
    if repo_map_raw:
        try:
            repo_map.update(json.loads(repo_map_raw))
        except json.JSONDecodeError:
            log.warning("Invalid OCTOPUS_REPO_MAP JSON, ignoring")
    if not repo_map:
        log.warning("No repo-to-Octopus mapping found. Set REPO_CONFIG or OCTOPUS_REPO_MAP.")
        return None

    since = datetime.now(timezone.utc) - timedelta(days=lookback)

    octopus = OctopusClient(server_url, api_key)
    git_base = os.environ.get("GIT_BASE_URL", "https://api.github.com")
    github = _GitHubCompare(git_token, git_base)

    # Load tag maps from git_analytics if available
    git_data = read_json("git_analytics", output_dir)
    tag_maps = git_data.get("tag_maps", {}) if git_data else {}

    print(f"[octopus_analytics] Analyzing {len(repo_map)} repos, env={env_name}, lookback={lookback}d")

    # 1. Deployment history
    print("[octopus_analytics] Fetching deployment history...")
    history = deployment_history(octopus, github, git_org, repo_map, env_name, since, tag_maps)

    # 2. Commit-to-prod lead time
    print("[octopus_analytics] Computing commit-to-prod lead time...")
    lead_time = commit_to_prod_lead_time(history, github, git_org)

    # 3. Pending changes
    print("[octopus_analytics] Checking pending changes...")
    pending = pending_changes_per_repo(octopus, github, git_org, repo_map, env_name, tag_maps)

    # 4. Deployment frequency
    freq = deployment_frequency(history)

    results = {
        "run_iso_ts": datetime.now(timezone.utc).isoformat(),
        "server_url": server_url,
        "environment": env_name,
        "repos_analyzed": list(repo_map.keys()),
        "lookback_days": lookback,
        "deployment_history": {
            "total_deployments": sum(r["deployment_count"] for r in history.values()),
            "by_repo": history,
        },
        "commit_to_prod_lead_time": lead_time,
        "pending_changes": pending,
        "deployment_frequency": freq,
        "repo_octopus_map": repo_map,
    }

    path = write_json(results, "octopus_analytics", output_dir)
    print(f"[octopus_analytics] Wrote {path}")
    total_deps = results["deployment_history"]["total_deployments"]
    print(f"  Deployments: {total_deps}")
    print(f"  Lead time (p50): {lead_time.get('p50_days', 'N/A')} days")
    print(f"  Pending repos: {pending.get('total_pending_repos', 0)}")

    return results


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    main()
