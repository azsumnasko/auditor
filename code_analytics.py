"""
code_analytics.py -- Static code analysis collector.

Wraps lizard/radon for complexity, parses coverage reports, checks dependency
freshness via pip-audit/npm-audit, and optionally queries SonarQube.

Outputs ``code_analytics_latest.json`` (+ timestamped copy).
"""

import os
import glob as _glob
import json
import shutil
import subprocess
import logging
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from collections import defaultdict

import requests

from analytics_utils import load_env, write_json

log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# On-demand tool installation
# ---------------------------------------------------------------------------

_INSTALL_RECIPES: dict[str, list[list[str]]] = {
    "npm":       [["apk", "add", "--no-cache", "nodejs", "npm"]],
    "node":      [["apk", "add", "--no-cache", "nodejs", "npm"]],
    "composer":  [
        ["apk", "add", "--no-cache", "curl", "php", "php-phar", "php-json",
         "php-mbstring", "php-openssl", "php-curl", "php-iconv", "php-dom",
         "php-xml", "php-tokenizer"],
        ["sh", "-c",
         "curl -sS https://getcomposer.org/installer | php -- --install-dir=/usr/local/bin --filename=composer"],
    ],
    "lizard":    [["pip", "install", "--quiet", "lizard"]],
    "radon":     [["pip", "install", "--quiet", "radon"]],
    "pip-audit": [["pip", "install", "--quiet", "pip-audit"]],
}

_install_attempted: set[str] = set()


def _ensure_tool(cmd: str) -> bool:
    """Return True if `cmd` is available. Try to install it on first miss."""
    if shutil.which(cmd):
        return True
    if cmd in _install_attempted:
        return False
    _install_attempted.add(cmd)

    recipes = _INSTALL_RECIPES.get(cmd)
    if not recipes:
        log.info("Tool '%s' not found and no install recipe available", cmd)
        return False

    log.info("Tool '%s' not found -- attempting on-demand install...", cmd)
    for step in recipes:
        try:
            subprocess.run(step, check=True, capture_output=True, text=True, timeout=120)
        except (subprocess.CalledProcessError, FileNotFoundError, subprocess.TimeoutExpired) as exc:
            log.warning("On-demand install of '%s' failed at step %s: %s", cmd, step[:3], exc)
            return False

    found = shutil.which(cmd) is not None
    if found:
        log.info("Tool '%s' installed successfully", cmd)
    return found


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
        if _ensure_tool("lizard"):
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
            except (subprocess.TimeoutExpired, json.JSONDecodeError) as exc:
                log.warning("lizard error for %s: %s", repo_path, exc)
        elif _ensure_tool("radon"):
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
            except (subprocess.TimeoutExpired, json.JSONDecodeError) as exc:
                log.warning("radon error for %s: %s", repo_path, exc)
        else:
            log.warning("Neither lizard nor radon available, skipping complexity")
            break

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
    """Extract line-rate from a Cobertura-format coverage.xml (.NET, Python, generic)."""
    try:
        tree = ET.parse(fpath)
        root = tree.getroot()
        rate = root.attrib.get("line-rate")
        if rate is not None:
            return round(float(rate) * 100, 1)
    except Exception as exc:
        log.warning("Failed to parse Cobertura %s: %s", fpath, exc)
    return None


def _parse_jacoco(fpath: str):
    """Extract line coverage from a JaCoCo XML report (Java/Kotlin)."""
    try:
        tree = ET.parse(fpath)
        root = tree.getroot()
        for counter in root.findall("counter"):
            if counter.attrib.get("type") == "LINE":
                missed = int(counter.attrib.get("missed", 0))
                covered = int(counter.attrib.get("covered", 0))
                total = missed + covered
                if total:
                    return round(covered / total * 100, 1)
    except Exception as exc:
        log.warning("Failed to parse JaCoCo %s: %s", fpath, exc)
    return None


def _parse_clover(fpath: str):
    """Extract line coverage from a Clover XML report (Java, PHP)."""
    try:
        tree = ET.parse(fpath)
        root = tree.getroot()
        project = root.find(".//project/metrics") or root.find(".//metrics")
        if project is not None:
            stmts = int(project.attrib.get("statements", 0))
            covered = int(project.attrib.get("coveredstatements", 0))
            if stmts:
                return round(covered / stmts * 100, 1)
    except Exception as exc:
        log.warning("Failed to parse Clover %s: %s", fpath, exc)
    return None


def _parse_istanbul_json(fpath: str):
    """Extract line coverage from Istanbul/NYC coverage-final.json (JS/TS/React/Node)."""
    try:
        with open(fpath, encoding="utf-8") as f:
            data = json.load(f)
        total_stmts = 0
        covered_stmts = 0
        for file_cov in data.values():
            stmt_map = file_cov.get("s", {})
            for count in stmt_map.values():
                total_stmts += 1
                if count > 0:
                    covered_stmts += 1
        if total_stmts:
            return round(covered_stmts / total_stmts * 100, 1)
    except Exception as exc:
        log.warning("Failed to parse Istanbul JSON %s: %s", fpath, exc)
    return None


def _parse_lcov(fpath: str):
    """Sum LF/LH records from an lcov.info file (JS/TS/React/Node/C++)."""
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


# Ordered by specificity: try the most common CI output paths first.
_COVERAGE_REPORT_CANDIDATES = [
    # Cobertura XML -- .NET (coverlet), Python (pytest-cov), generic
    ("coverage.xml", _parse_cobertura),
    ("TestResults/coverage.xml", _parse_cobertura),
    ("TestResults/coverage.cobertura.xml", _parse_cobertura),
    # JaCoCo -- Java, Kotlin (Maven/Gradle)
    ("target/site/jacoco/jacoco.xml", _parse_jacoco),
    ("build/reports/jacoco/test/jacocoTestReport.xml", _parse_jacoco),
    ("jacoco.xml", _parse_jacoco),
    # Clover -- Java (Atlassian), PHP (PHPUnit)
    ("target/site/clover/clover.xml", _parse_clover),
    ("build/logs/clover.xml", _parse_clover),
    ("coverage/clover.xml", _parse_clover),
    ("clover.xml", _parse_clover),
    # Istanbul/NYC JSON -- JS, TS, React, Node
    ("coverage/coverage-final.json", _parse_istanbul_json),
    (".nyc_output/coverage-final.json", _parse_istanbul_json),
    ("coverage-final.json", _parse_istanbul_json),
    # lcov -- JS/TS (Jest, Vitest), C/C++, generic
    ("coverage/lcov.info", _parse_lcov),
    ("lcov.info", _parse_lcov),
]


def test_coverage_analysis(repo_paths: list[str], sonar_url=None, sonar_token=None, sonar_projects=None) -> dict:
    """Parse existing coverage reports or query SonarQube.

    Supports Cobertura (.NET/Python), JaCoCo (Java/Kotlin), Clover (Java/PHP),
    Istanbul/NYC JSON (JS/TS/React/Node), and lcov (generic).
    """
    if sonar_url and sonar_token and sonar_projects:
        return _coverage_from_sonar(sonar_url, sonar_token, sonar_projects)

    by_module: dict[str, float] = {}
    for repo_path in repo_paths:
        repo_name = os.path.basename(repo_path)
        for report, parser in _COVERAGE_REPORT_CANDIDATES:
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
    """Check for outdated dependencies across Python, Node, PHP, .NET, and Java."""
    total = 0
    outdated = 0
    critical = []

    for repo_path in repo_paths:
        # Python
        if _has_file(repo_path, "requirements.txt", "Pipfile", "pyproject.toml") and _ensure_tool("pip"):
            try:
                result = subprocess.run(
                    ["pip", "list", "--outdated", "--format=json"],
                    capture_output=True, text=True, timeout=120, cwd=repo_path,
                )
                if result.returncode == 0 and result.stdout.strip():
                    pkgs = json.loads(result.stdout)
                    outdated += len(pkgs)
                    total += len(pkgs) + 10
                    for p in pkgs[:5]:
                        critical.append(f"[py] {p.get('name')} {p.get('version')} -> {p.get('latest_version')}")
            except (subprocess.TimeoutExpired, json.JSONDecodeError):
                pass

        # Node / React / TS
        if _has_file(repo_path, "package.json") and _ensure_tool("npm"):
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
                        critical.append(f"[npm] {name} {info.get('current')} -> {info.get('latest')}")
            except (subprocess.TimeoutExpired, json.JSONDecodeError):
                pass

        # PHP -- composer outdated
        if _has_file(repo_path, "composer.json") and _ensure_tool("composer"):
            try:
                result = subprocess.run(
                    ["composer", "outdated", "--direct", "--format=json"],
                    capture_output=True, text=True, timeout=120, cwd=repo_path,
                )
                if result.stdout.strip():
                    data = json.loads(result.stdout)
                    pkgs = data.get("installed", []) if isinstance(data, dict) else data if isinstance(data, list) else []
                    for p in pkgs:
                        total += 1
                        cur = p.get("version", "")
                        latest = p.get("latest", "")
                        if cur != latest and latest:
                            outdated += 1
                            if len(critical) < 10:
                                critical.append(f"[composer] {p.get('name', '')} {cur} -> {latest}")
            except (subprocess.TimeoutExpired, json.JSONDecodeError):
                pass

        # .NET -- dotnet list package --outdated (no on-demand install; SDK too large)
        if _ensure_tool("dotnet"):
            for csproj in _find_files(repo_path, "*.sln") or _find_files(repo_path, "*.csproj"):
                try:
                    result = subprocess.run(
                        ["dotnet", "list", csproj, "package", "--outdated", "--format", "json"],
                        capture_output=True, text=True, timeout=180, cwd=repo_path,
                    )
                    if result.stdout.strip():
                        data = json.loads(result.stdout)
                        for proj in data.get("projects", []):
                            for fw in proj.get("frameworks", []):
                                for pkg in fw.get("topLevelPackages", []):
                                    total += 1
                                    resolved = pkg.get("resolvedVersion", "")
                                    latest = pkg.get("latestVersion", "")
                                    if resolved != latest and latest:
                                        outdated += 1
                                        if len(critical) < 10:
                                            critical.append(f"[dotnet] {pkg.get('id', '')} {resolved} -> {latest}")
                except (subprocess.TimeoutExpired, json.JSONDecodeError):
                    pass
                break

        # Java (Maven) -- mvn versions:display-dependency-updates (no on-demand install)
        if _has_file(repo_path, "pom.xml") and _ensure_tool("mvn"):
            try:
                result = subprocess.run(
                    ["mvn", "versions:display-dependency-updates", "-q", "-DprocessDependencyManagement=false"],
                    capture_output=True, text=True, timeout=300, cwd=repo_path,
                )
                if result.stdout:
                    import re as _re
                    for m in _re.finditer(r"(\S+:\S+)\s+\.*\s*(\S+)\s+->\s+(\S+)", result.stdout):
                        total += 1
                        outdated += 1
                        if len(critical) < 10:
                            critical.append(f"[mvn] {m.group(1)} {m.group(2)} -> {m.group(3)}")
            except (subprocess.TimeoutExpired,):
                pass

        # Java (Gradle) -- gradle dependencyUpdates (no on-demand install)
        if _has_file(repo_path, "build.gradle", "build.gradle.kts") and _ensure_tool("gradle"):
            try:
                result = subprocess.run(
                    ["gradle", "dependencyUpdates", "-Drevision=release", "-q",
                     "--output-formatter", "json"],
                    capture_output=True, text=True, timeout=300, cwd=repo_path,
                )
                report = os.path.join(repo_path, "build", "dependencyUpdates", "report.json")
                if os.path.isfile(report):
                    with open(report, encoding="utf-8") as f:
                        data = json.load(f)
                    for dep in data.get("outdated", {}).get("dependencies", []):
                        total += 1
                        outdated += 1
                        cur = dep.get("version", "")
                        avail = (dep.get("available", {}).get("release")
                                 or dep.get("available", {}).get("milestone") or "?")
                        if len(critical) < 10:
                            critical.append(f"[gradle] {dep.get('group')}:{dep.get('name')} {cur} -> {avail}")
                    total += data.get("count", 0) - len(data.get("outdated", {}).get("dependencies", []))
            except (subprocess.TimeoutExpired, json.JSONDecodeError):
                pass

    return {
        "total_dependencies": total,
        "outdated_count": outdated,
        "outdated_pct": round(outdated / max(total, 1) * 100, 1),
        "critical_outdated": critical[:10],
    }


def _has_file(repo_path: str, *names: str) -> bool:
    """True if any of the literal filenames or glob patterns exist under repo_path."""
    for n in names:
        if "*" in n or "?" in n:
            if _glob.glob(os.path.join(repo_path, n)):
                return True
        elif os.path.isfile(os.path.join(repo_path, n)):
            return True
    return False


def _find_files(repo_path: str, *names: str) -> list[str]:
    """Return existing paths for literal filenames or glob patterns under repo_path."""
    found = []
    for n in names:
        if "*" in n or "?" in n:
            found.extend(_glob.glob(os.path.join(repo_path, n)))
        else:
            p = os.path.join(repo_path, n)
            if os.path.isfile(p):
                found.append(p)
    return found


def dependency_vulnerability_scan(repo_paths: list[str]) -> dict:
    """Run vulnerability scanners for Python, Node, PHP, .NET, and Java/Gradle projects."""
    all_vulns = []
    by_severity = defaultdict(int)

    for repo_path in repo_paths:
        # Python -- pip-audit
        if _has_file(repo_path, "requirements.txt", "Pipfile", "pyproject.toml") and _ensure_tool("pip-audit"):
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
                            all_vulns.append({"name": vuln.get("name"), "id": v.get("id"),
                                              "severity": sev, "ecosystem": "python"})
            except (subprocess.TimeoutExpired, json.JSONDecodeError):
                pass

        # Node / React / TS -- npm audit
        if _has_file(repo_path, "package.json") and _ensure_tool("npm"):
            try:
                result = subprocess.run(
                    ["npm", "audit", "--json"],
                    capture_output=True, text=True, timeout=180, cwd=repo_path,
                )
                if result.stdout.strip():
                    data = json.loads(result.stdout)
                    for vuln_id, info in data.get("vulnerabilities", {}).items():
                        sev = info.get("severity", "unknown")
                        all_vulns.append({"name": vuln_id, "severity": sev, "ecosystem": "node"})
            except (subprocess.TimeoutExpired, json.JSONDecodeError):
                pass

        # PHP -- composer audit
        if _has_file(repo_path, "composer.lock") and _ensure_tool("composer"):
            try:
                result = subprocess.run(
                    ["composer", "audit", "--format=json"],
                    capture_output=True, text=True, timeout=180, cwd=repo_path,
                )
                if result.stdout.strip():
                    data = json.loads(result.stdout)
                    advisories = data.get("advisories", {})
                    for pkg_name, advs in advisories.items():
                        for adv in (advs if isinstance(advs, list) else [advs]):
                            sev = adv.get("severity", "unknown").lower() if isinstance(adv, dict) else "unknown"
                            cve = adv.get("cve", "") if isinstance(adv, dict) else ""
                            all_vulns.append({"name": pkg_name, "id": cve,
                                              "severity": sev, "ecosystem": "php"})
            except (subprocess.TimeoutExpired, json.JSONDecodeError):
                pass

        # .NET -- dotnet list package --vulnerable (no on-demand install)
        if _ensure_tool("dotnet"):
            for csproj in _find_files(repo_path, "*.sln") or _find_files(repo_path, "*.csproj"):
                try:
                    result = subprocess.run(
                        ["dotnet", "list", csproj, "package", "--vulnerable", "--format", "json"],
                        capture_output=True, text=True, timeout=180, cwd=repo_path,
                    )
                    if result.stdout.strip():
                        data = json.loads(result.stdout)
                        for proj in data.get("projects", []):
                            for fw in proj.get("frameworks", []):
                                for pkg in fw.get("topLevelPackages", []):
                                    for v in pkg.get("vulnerabilities", []):
                                        sev = v.get("severity", "unknown").lower()
                                        all_vulns.append({"name": pkg.get("id", ""),
                                                          "severity": sev, "ecosystem": "dotnet"})
                except (subprocess.TimeoutExpired, json.JSONDecodeError):
                    pass
                break

        # Java (Maven) -- OWASP dependency-check (no on-demand install)
        if _has_file(repo_path, "pom.xml") and _ensure_tool("mvn"):
            try:
                result = subprocess.run(
                    ["mvn", "org.owasp:dependency-check-maven:check",
                     "-DfailBuildOnCVSS=11", "-Dformat=JSON", "-q"],
                    capture_output=True, text=True, timeout=600, cwd=repo_path,
                )
                report = os.path.join(repo_path, "target", "dependency-check-report.json")
                if os.path.isfile(report):
                    with open(report, encoding="utf-8") as f:
                        data = json.load(f)
                    for dep in data.get("dependencies", []):
                        for v in dep.get("vulnerabilities", []):
                            sev = v.get("severity", "unknown").lower()
                            all_vulns.append({"name": dep.get("fileName", ""),
                                              "id": v.get("name", ""),
                                              "severity": sev, "ecosystem": "java"})
            except (subprocess.TimeoutExpired, json.JSONDecodeError):
                pass

        # Java (Gradle) -- dependencyCheckAnalyze (no on-demand install)
        if _has_file(repo_path, "build.gradle", "build.gradle.kts") and _ensure_tool("gradle"):
            try:
                result = subprocess.run(
                    ["gradle", "dependencyCheckAnalyze", "-q"],
                    capture_output=True, text=True, timeout=600, cwd=repo_path,
                )
                report = os.path.join(repo_path, "build", "reports", "dependency-check-report.json")
                if os.path.isfile(report):
                    with open(report, encoding="utf-8") as f:
                        data = json.load(f)
                    for dep in data.get("dependencies", []):
                        for v in dep.get("vulnerabilities", []):
                            sev = v.get("severity", "unknown").lower()
                            all_vulns.append({"name": dep.get("fileName", ""),
                                              "id": v.get("name", ""),
                                              "severity": sev, "ecosystem": "java"})
            except (subprocess.TimeoutExpired, json.JSONDecodeError):
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
