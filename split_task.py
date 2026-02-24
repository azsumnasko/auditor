#!/usr/bin/env python3
"""
Split one high-level task into small subtasks (Gas Town–style convoy).
Uses Ollama to break the goal into 3–10 concrete subtasks, then creates beads
(or task_queue.json entries) and links them with discovered-from so they act like a convoy.

Usage:
  py split_task.py "Add full Jira dashboard with cycle time, throughput, and WIP"
  py split_task.py "Improve dashboard" --max-subtasks 5
  py split_task.py --bead ozon-abc12   # use existing bead as parent, split its title/description

Requires: Ollama running (same model as dispatch_config.json, e.g. qwen2.5-coder:7b).
Works with or without Beads (falls back to task_queue.json).
"""
from __future__ import annotations

import argparse
import json
import re
import shutil
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent
DEFAULT_CONFIG_PATH = REPO_ROOT / "dispatch_config.json"
TASK_QUEUE_FILE = REPO_ROOT / "task_queue.json"
OLLAMA_URL = "http://localhost:11434/api/generate"


def use_beads() -> bool:
    return (REPO_ROOT / ".beads").exists() and (shutil.which("bd") is not None)


def load_config() -> dict:
    if not DEFAULT_CONFIG_PATH.exists():
        return {}
    with open(DEFAULT_CONFIG_PATH, encoding="utf-8") as f:
        return json.load(f)


def ollama_model() -> str:
    """Ollama model name (without 'ollama/' prefix)."""
    config = load_config()
    model = config.get("model", "ollama/qwen2.5-coder:7b")
    if model.startswith("ollama/"):
        return model.replace("ollama/", "", 1)
    return model


def split_with_ollama(goal: str, max_subtasks: int = 10) -> list[str]:
    """Call Ollama to split goal into subtask titles. Returns list of non-empty lines."""
    try:
        import urllib.request
    except ImportError:
        urllib.request = None  # type: ignore
    if urllib.request is None:
        return _fallback_split(goal, max_subtasks)

    prompt = f"""You are a task splitter for a coding project. Break this goal into 3 to {max_subtasks} concrete, small subtasks.

Rules:
- Each subtask must be INDEPENDENT: doable by one worker without depending on another worker's unfinished work. Prefer splitting by file or feature area so different workers rarely edit the same file.
- Keep subtasks SMALL: one clear change per task (e.g. "In generate_dashboard.py add X" or "In jira_analytics.py compute Y and add to JSON"), so merges stay clean and conflicts are rare.
- When the change touches the dashboard or report, mention the file: generate_dashboard.py (HTML report), jira_analytics.py (metrics/compute), or jira_dashboard.html only if editing static HTML directly.
- Output exactly one subtask title per line. No numbering, no bullets, no extra text. Only the titles.

Goal: {goal}
"""
    body = {
        "model": ollama_model(),
        "prompt": prompt,
        "stream": False,
    }
    req = urllib.request.Request(
        OLLAMA_URL,
        data=json.dumps(body).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=120) as resp:
            data = json.loads(resp.read().decode("utf-8"))
    except Exception as e:
        print(f"Ollama request failed: {e}. Using fallback split.", file=sys.stderr)
        return _fallback_split(goal, max_subtasks)

    text = (data.get("response") or "").strip()
    lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
    # Drop common prefixes like "1." or "- "
    cleaned = []
    for ln in lines:
        ln = re.sub(r"^[\d\-*\.]+\s*", "", ln).strip()
        if ln and len(cleaned) < max_subtasks:
            cleaned.append(ln)
    return cleaned[:max_subtasks] if cleaned else _fallback_split(goal, max_subtasks)


def _fallback_split(goal: str, max_subtasks: int) -> list[str]:
    """Simple heuristic when Ollama is not available."""
    # Split on common separators and trim
    for sep in (";", ". ", ", ", " and ", " then "):
        if sep in goal:
            parts = [p.strip() for p in goal.split(sep) if p.strip()][:max_subtasks]
            if len(parts) >= 2:
                return parts
    # Single phrase: treat as one subtask (user can add more manually)
    return [goal] if goal.strip() else []


def _bd_open_ids(repo_root: Path) -> set[str]:
    """Return set of open bead ids from bd list."""
    r = subprocess.run(
        ["bd", "list", "--status", "open", "--json"],
        cwd=repo_root,
        capture_output=True,
        text=True,
        timeout=15,
    )
    if r.returncode != 0 or not r.stdout.strip():
        return set()
    try:
        data = json.loads(r.stdout)
        issues = data if isinstance(data, list) else data.get("issues", data)
        if not isinstance(issues, list):
            return set()
        ids = set()
        for i in issues:
            bid = i.get("id") or i.get("hash") or i.get("key")
            if bid:
                ids.add(str(bid))
        return ids
    except json.JSONDecodeError:
        return set()


def bd_create(repo_root: Path, title: str, deps: list[str] | None = None) -> str | None:
    """Create bead; return new bead id (from list diff before/after)."""
    before = _bd_open_ids(repo_root)
    args = ["bd", "create", title]
    if deps:
        for dep in deps:
            args.extend(["--deps", dep])
    r = subprocess.run(args, cwd=repo_root, capture_output=True, text=True, timeout=15)
    if r.returncode != 0:
        return None
    after = _bd_open_ids(repo_root)
    new_ids = after - before
    return next(iter(new_ids), None) if new_ids else None


def bd_show(repo_root: Path, bead_id: str) -> str:
    r = subprocess.run(
        ["bd", "show", bead_id],
        cwd=repo_root,
        capture_output=True,
        text=True,
        timeout=10,
    )
    return (r.stdout or "").strip() if r.returncode == 0 else ""


def task_queue_add(repo_root: Path, tasks: list[dict]) -> None:
    path = repo_root / TASK_QUEUE_FILE
    if path.exists():
        data = json.loads(path.read_text(encoding="utf-8"))
    else:
        data = {"tasks": [], "next_id": 1}
    next_id = data["next_id"]
    for t in tasks:
        data["tasks"].append({
            "id": f"task-{next_id}",
            "title": t["title"],
            "status": "pending",
            "parent": t.get("parent"),
        })
        next_id += 1
    data["next_id"] = next_id
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")


def main() -> int:
    ap = argparse.ArgumentParser(
        description="Split one task into small subtasks (beads or task_queue) using Ollama."
    )
    ap.add_argument(
        "task",
        nargs="?",
        default="",
        help="High-level task to split (or use --bead to use an existing bead).",
    )
    ap.add_argument(
        "--bead",
        metavar="ID",
        help="Use this bead as parent; split its title/description into subtasks.",
    )
    ap.add_argument(
        "--max-subtasks",
        type=int,
        default=10,
        metavar="N",
        help="Max number of subtasks (default 10).",
    )
    ap.add_argument(
        "--no-llm",
        action="store_true",
        help="Skip Ollama; use simple heuristic split only.",
    )
    args = ap.parse_args()

    goal = (args.task or "").strip()
    if args.bead:
        if not use_beads():
            print("--bead requires Beads (bd) and .beads.", file=sys.stderr)
            return 1
        body = bd_show(REPO_ROOT, args.bead)
        goal = goal or body or args.bead
        parent_id = args.bead
    else:
        if not goal:
            print("Give a task: split_task.py \"Your big task\" or --bead <id>", file=sys.stderr)
            return 1
        parent_id = None

    if args.no_llm:
        subtask_titles = _fallback_split(goal, args.max_subtasks)
    else:
        subtask_titles = split_with_ollama(goal, args.max_subtasks)

    if not subtask_titles:
        print("No subtasks produced.", file=sys.stderr)
        return 1

    if use_beads():
        if not parent_id:
            parent_id = bd_create(REPO_ROOT, goal)
            if parent_id:
                print(f"Parent bead: {parent_id}")
        if parent_id:
            dep = f"discovered-from:{parent_id}"
            for title in subtask_titles:
                bid = bd_create(REPO_ROOT, title, deps=[dep])
                print(f"  {bid or '?'}: {title[:60]}")
        else:
            for title in subtask_titles:
                bd_create(REPO_ROOT, title)
                print(f"  created: {title[:60]}")
        subprocess.run(["bd", "sync"], cwd=REPO_ROOT, capture_output=True, timeout=30)
    else:
        path = REPO_ROOT / TASK_QUEUE_FILE
        if path.exists():
            data = json.loads(path.read_text(encoding="utf-8"))
            next_id = data["next_id"]
        else:
            next_id = 1
        parent_id = f"task-{next_id}"
        tasks = [{"title": goal, "parent": None}]
        for t in subtask_titles:
            tasks.append({"title": t, "parent": parent_id})
        task_queue_add(REPO_ROOT, tasks)
        print(f"Added 1 parent + {len(subtask_titles)} subtasks to {TASK_QUEUE_FILE}.")

    print(f"Done: {len(subtask_titles)} subtasks. Run dispatch_workers.py or (Path A) gt sling <ids> <rig>.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
