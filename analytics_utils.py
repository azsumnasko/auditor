"""
Shared utility functions used across all analytics collectors.

Extracted from jira_analytics.py so that git_analytics, octopus_analytics,
cicd_analytics, merge_evidence, score_engine, and output generators can
reuse common logic without importing the full Jira module.
"""

import math
import re
import json as _json
import os
from datetime import datetime, timezone
from dateutil import parser as dtparser


# ---------------------------------------------------------------------------
# Date / time helpers
# ---------------------------------------------------------------------------

def parse_dt(s):
    """Parse an ISO-8601 string into a timezone-aware datetime, or None."""
    if not s:
        return None
    try:
        return dtparser.isoparse(s)
    except (TypeError, ValueError):
        return None


def iso_week(dt: datetime) -> str:
    """Return ISO-week string like '2025-W03'."""
    y, w, _ = dt.isocalendar()
    return f"{y}-W{w:02d}"


# ---------------------------------------------------------------------------
# Statistics helpers
# ---------------------------------------------------------------------------

def percentile(values, p):
    """Linear-interpolation percentile (same behaviour as numpy)."""
    if not values:
        return None
    values = sorted(values)
    k = (len(values) - 1) * (p / 100.0)
    f = math.floor(k)
    c = math.ceil(k)
    if f == c:
        return values[int(k)]
    return values[f] + (values[c] - values[f]) * (k - f)


def summarize_time_metrics(values):
    """Return {count, avg_days, p50/p85/p95_days} for a list of numeric day values."""
    values = [v for v in values if v is not None and v >= 0]
    if not values:
        return {}
    return {
        "count": len(values),
        "avg_days": round(sum(values) / len(values), 2),
        "p50_days": round(percentile(values, 50), 2),
        "p85_days": round(percentile(values, 85), 2),
        "p95_days": round(percentile(values, 95), 2),
    }


def gini_coefficient(counts):
    """Gini coefficient (0 = perfectly equal, 1 = one person does everything)."""
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


def velocity_cv(throughputs):
    """Coefficient of variation = std / mean.  Returns None if < 2 data points."""
    if len(throughputs) < 2:
        return None
    mean = sum(throughputs) / len(throughputs)
    if mean == 0:
        return None
    variance = sum((x - mean) ** 2 for x in throughputs) / len(throughputs)
    return round((variance ** 0.5) / mean, 3)


# ---------------------------------------------------------------------------
# Text / regex helpers
# ---------------------------------------------------------------------------

_JIRA_KEY_RE = re.compile(r"\b([A-Z][A-Z0-9]+-\d+)\b")


def extract_jira_keys(text: str) -> list[str]:
    """Extract all Jira issue keys (e.g. BETTY-1234) from a string."""
    if not text:
        return []
    return _JIRA_KEY_RE.findall(text)


_PR_NUMBER_RE = re.compile(r"(?:\(#|pull request #)(\d+)")


def extract_pr_number(commit_message: str):
    """Extract PR number from a commit message like 'fix: foo (#123)' or 'Merge pull request #123'."""
    if not commit_message:
        return None
    m = _PR_NUMBER_RE.search(commit_message)
    return int(m.group(1)) if m else None


# ---------------------------------------------------------------------------
# JSON output helpers
# ---------------------------------------------------------------------------

def json_default(obj):
    """json.dump default handler: NaN -> None, datetime -> ISO string."""
    if isinstance(obj, float) and math.isnan(obj):
        return None
    if isinstance(obj, datetime):
        return obj.isoformat()
    raise TypeError(f"Object of type {type(obj).__name__} is not JSON serializable")


def write_json(data: dict, basename: str, output_dir: str | None = None):
    """
    Write *data* to ``<output_dir>/<basename>_latest.json`` and a timestamped copy.
    Returns the path to the ``_latest`` file.
    """
    output_dir = output_dir or os.environ.get("OUTPUT_DIR", ".")
    os.makedirs(output_dir, exist_ok=True)

    latest_path = os.path.join(output_dir, f"{basename}_latest.json")
    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    ts_path = os.path.join(output_dir, f"{basename}_{ts}.json")

    payload = _json.dumps(data, indent=2, ensure_ascii=False, default=json_default)
    for path in (latest_path, ts_path):
        with open(path, "w", encoding="utf-8") as f:
            f.write(payload)

    return latest_path


def read_json(basename: str, output_dir: str | None = None):
    """Read ``<output_dir>/<basename>_latest.json`` or return None if missing."""
    output_dir = output_dir or os.environ.get("OUTPUT_DIR", ".")
    path = os.path.join(output_dir, f"{basename}_latest.json")
    if not os.path.isfile(path):
        return None
    with open(path, "r", encoding="utf-8") as f:
        return _json.load(f)


# ---------------------------------------------------------------------------
# Env-var / dotenv bootstrap
# ---------------------------------------------------------------------------

def load_env():
    """Load .env file if python-dotenv is installed (same pattern as jira_analytics)."""
    try:
        from dotenv import load_dotenv
        load_dotenv(os.environ.get("DOTENV_PATH", ".env"))
    except ImportError:
        pass
