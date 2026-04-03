"""
code_analytics.py -- Static code analysis collector.

Wraps lizard/radon for complexity, parses coverage reports, checks dependency
freshness via pip-audit/npm-audit, and optionally queries SonarQube.

Outputs ``code_analytics_latest.json`` (+ timestamped copy).
"""

import os
import json
import subprocess
import logging
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from collections import defaultdict

import requests

from analytics_utils import load_env, write_json

log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Complexity analysis
# ---------------------------------------------------------------------------

def complexity_analysis(repo_paths: list[str]) -> dict:
    """
    Run lizard (multi-language) or radon (Python) for cyclomatic complexity.
    Returns aggregate metrics.
    """
    all_files = []
    for repo_path in repo_paths:
        if not os.path.isdir(repo_path):
            continue
        try:
            result = subprocess.run(
                ["lizard", "--json", repo_path],
                capture_output=True, text=True, timeout=300,
            )
            if result.returncode == 0 and result.stdout.strip():
                data = json.loads(result.stdout)
                for entry in data:
                    for func in entry.get("functions", []) if isinstance(entry, dict) else []:
                        all_files.append({
                            "path": func.get("filename", ""),
                            "function": func.get("name", ""),
                            "complexity": func.get("cyclomatic_complexity", 0),
                            "nloc": func.get("nloc", 0),
                        })
        except FileNotFoundError:
            log.info("lizard not installed, trying radon...")
            try:
                result = subprocess.run(
                    ["radon", "cc", "--json", repo_path],
                    capture_output=True, text=True, timeout=300,
                )
                if result.returncode == 0 and result.stdout.strip():
                    data = json.loads(result.stdout)
                    for filepath, blocks in data.items():
                        for b in blocks:
                            all_files.append({
                                "path": filepath,
                                "function": b.get("name", ""),
                                "complexity": b.get("complexity", 0),
                                "nloc": b.get("endline", 0) - b.get("lineno", 0),
                            })
            except FileNotFoundError:
                log.warning("Neither lizard nor radon installed, skipping complexity")
        except (subprocess.TimeoutExpired, json.JSONDecodeError) as exc:
            log.warning("Complexity analysis error: %s", exc)

    if not all_files:
        return {"avg_complexity": None, "max_complexity": None, "files_above_threshold": 0}

    complexities = [f["complexity"] for f in all_files]
    threshold = 15
    above = [f for f in all_files if f["complexity"] > threshold]

    by_dir = defaultdict(list)
    for f in all_files:
        d = os.path.dirname(f["path"]) or "/"
        by_dir[d].append(f["complexity"])

    return {
        "avg_complexity": round(sum(complexities) / len(complexities), 1),
        "max_complexity": max(complexities),
        "files_above_threshold": len(above),
        "complex_files": sorted(above, key=lambda x: -x["complexity"])[:30],
        "by_directory": {d: round(sum(v) / len(v), 1) for d, v in sorted(by_dir.items())[:20]},
    }


# ---------------------------------------------------------------------------
# Test coverage
# ---------------------------------------------------------------------------

def _parse_cobertura(fpath: str):
    """Extract line-rate from a Cobertura-format coverage.xml."""
    try:
        tree = ET.parse(fpath)
        root = tree.getroot()
        rate = root.attrib.get("line-rate")
        if rate is not None:
            return round(float(rate) * 100, 1)
    except Exception as exc:
        log.warning("Failed to parse Cobertura %s: %s", fpath, exc)
    return None


def _parse_lcov(fpath: str):
    """Sum LF/LH records from an lcov.info file."""
    try:
        found = hit = 0
        with open(fpath, encoding="utf-8", errors="replace") as f:
            for line in f:
                try:
                    if line.startswith("LF:"):
                        found += int(line[3:].strip())
                    elif line.startswith("LH:"):
                        hit += int(line[3:].strip())
                except ValueError:
                    continue
        if found:
            return round(hit / found * 100, 1)
    except Exception as exc:
        log.warning("Failed to parse lcov %s: %s", fpath, exc)
    return None


def test_coverage_analysis(repo_paths: list[str], sonar_url=None, sonar_token=None, sonar_projects=None) -> dict:
    """Parse existing coverage reports or query SonarQube."""
    if sonar_url and sonar_token and sonar_projects:
        return _coverage_from_sonar(sonar_url, sonar_token, sonar_projects)

    by_module: dict[str, float] = {}
    for repo_path in repo_paths:
        repo_name = os.path.basename(repo_path)
        for report, parser in [
            ("coverage.xml", _parse_cobertura),
            ("coverage/lcov.info", _parse_lcov),
            ("lcov.info", _parse_lcov),
        ]:
            fpath = os.path.join(repo_path, report)
            if os.path.isfile(fpath):
                log.info("Found coverage report: %s", fpath)
                pct = parser(fpath)
                if pct is not None:
                    by_module[repo_name] = pct
                    break

    overall = round(sum(by_module.values()) / len(by_module), 1) if by_module else None
    return {"overall_coverage_pct": overall, "by_module": by_module, "uncovered_modules": []}


def _coverage_from_sonar(url, token, projects):
    session = requests.Session()
    session.auth = (token, "")
    results = {}
    for proj in projects.split(","):
        proj = proj.strip()
        try:
            resp = session.get(
                f"{url}/api/measures/component",
                params={"component": proj, "metricKeys": "coverage"},
                timeout=30,
            )
            if resp.status_code == 200:
                measures = resp.json().get("component", {}).get("measures", [])
                for m in measures:
                    if m["metric"] == "coverage":
                        results[proj] = float(m.get("value", 0))
        except Exception as exc:
            log.warning("SonarQube coverage fetch failed for %s: %s", proj, exc)

    overall = round(sum(results.values()) / max(len(results), 1), 1) if results else None
    return {"overall_coverage_pct": overall, "by_module": results, "uncovered_modules": []}


# ---------------------------------------------------------------------------
# Duplication
# ---------------------------------------------------------------------------

def duplication_analysis(repo_paths: list[str], sonar_url=None, sonar_token=None, sonar_projects=None) -> dict:
    if sonar_url and sonar_token and sonar_projects:
        session = requests.Session()
        session.auth = (sonar_token, "")
        total_dup = []
        for proj in sonar_projects.split(","):
            proj = proj.strip()
            try:
                resp = session.get(
                    f"{sonar_url}/api/measures/component",
                    params={"component": proj, "metricKeys": "duplicated_lines_density"},
                    timeout=30,
                )
                if resp.status_code == 200:
                    for m in resp.json().get("component", {}).get("measures", []):
                        if m["metric"] == "duplicated_lines_density":
                            total_dup.append(float(m.get("value", 0)))
            except Exception:
                pass
        avg = round(sum(total_dup) / max(len(total_dup), 1), 1) if total_dup else None
        return {"duplication_pct": avg, "duplicated_blocks_count": None}

    return {"duplication_pct": None, "duplicated_blocks_count": None}


# ---------------------------------------------------------------------------
# Dependency freshness & vulnerabilities
# ---------------------------------------------------------------------------

def dependency_freshness(repo_paths: list[str]) -> dict:
    """Check for outdated dependencies."""
    total = 0
    outdated = 0
    critical = []

    for repo_path in repo_paths:
        if os.path.isfile(os.path.join(repo_path, "requirements.txt")):
            try:
                result = subprocess.run(
                    ["pip", "list", "--outdated", "--format=json"],
                    capture_output=True, text=True, timeout=120, cwd=repo_path,
                )
                if result.returncode == 0 and result.stdout.strip():
                    pkgs = json.loads(result.stdout)
                    outdated += len(pkgs)
                    total += len(pkgs) + 10  # approximate
                    for p in pkgs[:5]:
                        critical.append(f"{p.get('name')} {p.get('version')} -> {p.get('latest_version')}")
            except (FileNotFoundError, subprocess.TimeoutExpired, json.JSONDecodeError):
                pass

        if os.path.isfile(os.path.join(repo_path, "package.json")):
            try:
                result = subprocess.run(
                    ["npm", "outdated", "--json"],
                    capture_output=True, text=True, timeout=120, cwd=repo_path,
                )
                if result.stdout.strip():
                    pkgs = json.loads(result.stdout)
                    outdated += len(pkgs)
                    total += len(pkgs) + 10
                    for name, info in list(pkgs.items())[:5]:
                        critical.append(f"{name} {info.get('current')} -> {info.get('latest')}")
            except (FileNotFoundError, subprocess.TimeoutExpired, json.JSONDecodeError):
                pass

    return {
        "total_dependencies": total,
        "outdated_count": outdated,
        "outdated_pct": round(outdated / max(total, 1) * 100, 1),
        "critical_outdated": critical[:10],
    }


def dependency_vulnerability_scan(repo_paths: list[str]) -> dict:
    """Run pip-audit / npm audit for vulnerability scanning."""
    all_vulns = []
    by_severity = defaultdict(int)

    for repo_path in repo_paths:
        if os.path.isfile(os.path.join(repo_path, "requirements.txt")):
            try:
                result = subprocess.run(
                    ["pip-audit", "-f", "json"],
                    capture_output=True, text=True, timeout=180, cwd=repo_path,
                )
                if result.stdout.strip():
                    data = json.loads(result.stdout)
                    for vuln in data.get("dependencies", []):
                        for v in vuln.get("vulns", []):
                            sev = v.get("fix_versions", ["unknown"])[0] if v.get("fix_versions") else "unknown"
                            all_vulns.append({"name": vuln.get("name"), "id": v.get("id"), "severity": sev})
            except (FileNotFoundError, subprocess.TimeoutExpired, json.JSONDecodeError):
                pass

        if os.path.isfile(os.path.join(repo_path, "package.json")):
            try:
                result = subprocess.run(
                    ["npm", "audit", "--json"],
                    capture_output=True, text=True, timeout=180, cwd=repo_path,
                )
                if result.stdout.strip():
                    data = json.loads(result.stdout)
                    for vuln_id, info in data.get("vulnerabilities", {}).items():
                        sev = info.get("severity", "unknown")
                        all_vulns.append({"name": vuln_id, "severity": sev})
            except (FileNotFoundError, subprocess.TimeoutExpired, json.JSONDecodeError):
                pass

    for v in all_vulns:
        by_severity[v.get("severity", "unknown")] += 1

    return {
        "total_vulns": len(all_vulns),
        "by_severity": dict(by_severity),
        "top_vulns": all_vulns[:20],
    }


# ---------------------------------------------------------------------------
# main()
# ---------------------------------------------------------------------------

def main():
    load_env()

    repos_raw = os.environ.get("CODE_REPOS_PATH", "")
    sonar_url = os.environ.get("CODE_SONAR_URL")
    sonar_token = os.environ.get("CODE_SONAR_TOKEN")
    sonar_projects = os.environ.get("CODE_SONAR_PROJECTS")
    output_dir = os.environ.get("OUTPUT_DIR")

    repo_paths = [p.strip() for p in repos_raw.split(",") if p.strip() and os.path.isdir(p.strip())]

    if not repo_paths and not sonar_url:
        print("[code_analytics] No CODE_REPOS_PATH or SonarQube configured, skipping.")
        return None

    print(f"[code_analytics] Analyzing {len(repo_paths)} repos")

    complexity = complexity_analysis(repo_paths) if repo_paths else {}
    coverage = test_coverage_analysis(repo_paths, sonar_url, sonar_token, sonar_projects)
    duplication = duplication_analysis(repo_paths, sonar_url, sonar_token, sonar_projects)
    freshness = dependency_freshness(repo_paths) if repo_paths else {}
    vulns = dependency_vulnerability_scan(repo_paths) if repo_paths else {}

    results = {
        "run_iso_ts": datetime.now(timezone.utc).isoformat(),
        "repos_analyzed": repo_paths,
        "complexity": complexity,
        "test_coverage": coverage,
        "duplication": duplication,
        "dependency_freshness": freshness,
        "vulnerabilities": vulns,
    }

    path = write_json(results, "code_analytics", output_dir)
    print(f"[code_analytics] Wrote {path}")

    return results


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    main()
