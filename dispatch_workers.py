#!/usr/bin/env python3
"""
Path B: Lightweight Gas Town-style dispatcher for 14 local Qwen agents.
- Maintains a pool of worktrees (ozon-w1 .. ozon-w14).
- Task source: Beads (bd) if installed and .beads exists; else file-based task_queue.json (no bd required).
- When a worker exits, marks task done and assigns the next to that slot.
- If using file queue and task_queue.json is missing, seeds from built-in list (self-improving).

Usage:
  From repo root: python dispatch_workers.py
  With Beads: bd init, bd create "Task"; then run. Without Beads: run anyway; task_queue.json is used (created from BEADS_FOR_ANALYSIS if missing).
"""
from __future__ import annotations

import json
import os
import re
import subprocess
import shutil
import sys
import time
from pathlib import Path
from typing import Any

# Default config path next to this script
DEFAULT_CONFIG_PATH = Path(__file__).resolve().parent / "dispatch_config.json"
TASK_FILE = ".current_task.txt"

# Open null device once; used for worker stdout/stderr to avoid any pipe (and thus _readerthread) on Windows where pipe decoding can raise UnicodeDecodeError.
_NULL_DEV = open(os.devnull, "wb")  # noqa: SIM115
TASK_QUEUE_FILE = "task_queue.json"

# On Windows, run worker via a tiny wrapper so we never attach to the real process's stdout/stderr (avoids _readerthread + cp1252 decode errors).
_USE_WRAPPER_WIN = sys.platform == "win32"

# Use UTF-8 for all subprocess output so bd/git/aider output never triggers UnicodeDecodeError (cp1252 on Windows).
_SUBPROCESS_ENCODING = {"encoding": "utf-8", "errors": "replace"} if sys.platform == "win32" else {}

# Built-in tasks to seed task_queue.json when Beads is not used (from BEADS_FOR_ANALYSIS).
DEFAULT_TASKS = [
    "Add cycle time distribution chart to dashboard",
    "Add throughput trend chart (last 12 weeks)",
    "Compute and show flow efficiency in analytics and dashboard",
    "Add scope creep metric per sprint (added/removed after start)",
    "Compute change failure rate by project and add to dashboard",
    "Add WIP by age bands (0-7d, 7-30d, 30-90d, 90d+) to dashboard",
    "Add tooltips to all dashboard metric cards",
    "Add project filter dropdown to dashboard",
    "Add drill-down: Jira filter links for bugs and WIP",
    "Add CSV export for WIP and throughput tables",
    "Handle missing story points in velocity and commitment ratio",
    "Add retry and backoff for Jira API 429/5xx in jira_analytics.py",
    "Add sprint predictability chart (commitment vs done last N sprints)",
    "Add blocked-issue table with one-click Jira link on dashboard",
    "Add oldest WIP table (top 20) with Jira links on dashboard",
]


def load_config(path: Path) -> dict[str, Any]:
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def get_repo_root(config: dict[str, Any]) -> Path:
    root = config.get("repo_root", ".")
    if root == ".":
        root = Path(__file__).resolve().parent
    else:
        root = Path(root).resolve()
    return root


def use_beads(repo_root: Path) -> bool:
    """True if Beads is available and .beads exists."""
    return (repo_root / ".beads").exists() and (shutil.which("bd") is not None)


# ---------- File-based task queue (no Beads required) ----------
def task_queue_path(repo_root: Path) -> Path:
    return repo_root / TASK_QUEUE_FILE


def load_task_queue(repo_root: Path) -> dict[str, Any]:
    path = task_queue_path(repo_root)
    if not path.exists():
        return {"tasks": [], "next_id": 1}
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def save_task_queue(repo_root: Path, data: dict[str, Any]) -> None:
    path = task_queue_path(repo_root)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)


def get_next_pending_from_queue(repo_root: Path) -> dict[str, Any] | None:
    data = load_task_queue(repo_root)
    for t in data["tasks"]:
        if t.get("status") == "pending":
            return {"id": t["id"], "title": t.get("title", t["id"])}
    return None


def mark_task_status(repo_root: Path, task_id: str, status: str) -> None:
    data = load_task_queue(repo_root)
    for t in data["tasks"]:
        if t["id"] == task_id:
            t["status"] = status
            break
    save_task_queue(repo_root, data)


def seed_task_queue_if_missing(repo_root: Path) -> None:
    path = task_queue_path(repo_root)
    if path.exists():
        return
    next_id = 1
    tasks = []
    for title in DEFAULT_TASKS:
        tasks.append({"id": f"task-{next_id}", "title": title, "status": "pending"})
        next_id += 1
    save_task_queue(repo_root, {"tasks": tasks, "next_id": next_id})
    print(f"Created {path} with {len(tasks)} tasks (no Beads required).", file=sys.stderr)


def _parse_bd_bead_lines(stdout: str) -> list[dict[str, Any]]:
    """Parse bd output for bead IDs (e.g. ozon-4id, bd-1a2b3)."""
    bead_pattern = re.compile(r"\b([a-z]+-[a-zA-Z0-9]+)\b")
    seen = set()
    beads = []
    for line in (stdout or "").splitlines():
        for m in bead_pattern.finditer(line):
            bid = m.group(1)
            if bid not in seen and "-" in bid:
                seen.add(bid)
                beads.append({"id": bid, "title": line.strip() or bid})
    return beads


def _beads_from_list(data: Any) -> list[dict[str, Any]]:
    """Normalize bd list / list --json output to list of {id, title}."""
    if isinstance(data, list):
        out = []
        for b in data:
            if not isinstance(b, dict):
                continue
            bid = b.get("id") or b.get("hash") or b.get("key")
            if not bid:
                continue
            status = (b.get("status") or "").lower()
            if status == "closed" or status == "done":
                continue
            out.append({"id": str(bid), "title": b.get("title") or b.get("summary") or str(bid)})
        return out
    if isinstance(data, dict) and "issues" in data:
        return _beads_from_list(data["issues"])
    return []


def bd_list_open_json(repo_root: Path) -> list[dict[str, Any]]:
    """Return open beads (no dependency check). Used when bd ready is empty."""
    for args in (
        ["bd", "list", "--status", "open", "--json"],
        ["bd", "list", "--json"],
        ["bd", "list", "--status", "open"],
        ["bd", "list"],
    ):
        r = subprocess.run(args, cwd=repo_root, capture_output=True, text=True, timeout=30, **_SUBPROCESS_ENCODING)
        if r.returncode != 0:
            continue
        raw = (r.stdout or "").strip()
        if not raw:
            continue
        try:
            data = json.loads(raw)
            beads = _beads_from_list(data)
            if beads:
                return beads
        except json.JSONDecodeError:
            beads = _parse_bd_bead_lines(raw)
            if beads:
                return beads
    return []


def bd_ready_json(repo_root: Path) -> list[dict[str, Any]]:
    """Return list of ready beads from `bd ready --json`. Fallback to parsing `bd ready` lines."""
    try:
        r = subprocess.run(
            ["bd", "ready", "--json"],
            cwd=repo_root,
            capture_output=True,
            text=True,
            timeout=30,
            **_SUBPROCESS_ENCODING,
        )
        if r.returncode == 0 and r.stdout.strip():
            return json.loads(r.stdout)
    except (json.JSONDecodeError, FileNotFoundError):
        pass
    r = subprocess.run(
        ["bd", "ready"],
        cwd=repo_root,
        capture_output=True,
        text=True,
        timeout=30,
        **_SUBPROCESS_ENCODING,
    )
    if r.returncode != 0:
        return []
    return _parse_bd_bead_lines(r.stdout)


def bd_show(repo_root: Path, bead_id: str) -> str:
    """Return full bead description for task file."""
    r = subprocess.run(
        ["bd", "show", bead_id],
        cwd=repo_root,
        capture_output=True,
        text=True,
        timeout=10,
        **_SUBPROCESS_ENCODING,
    )
    if r.returncode != 0:
        return f"Task: {bead_id}\n( Run bd show {bead_id} in repo for details. )"
    return r.stdout or f"Task: {bead_id}"


def bd_claim(repo_root: Path, bead_id: str) -> bool:
    """Mark bead in_progress (claim)."""
    r = subprocess.run(
        ["bd", "update", bead_id, "--status=in_progress"],
        cwd=repo_root,
        capture_output=True,
        timeout=10,
        **_SUBPROCESS_ENCODING,
    )
    return r.returncode == 0


def bd_close(repo_root: Path, bead_id: str) -> bool:
    """Close bead and sync."""
    r = subprocess.run(
        ["bd", "close", bead_id],
        cwd=repo_root,
        capture_output=True,
        timeout=10,
        **_SUBPROCESS_ENCODING,
    )
    if r.returncode != 0:
        return False
    subprocess.run(["bd", "sync"], cwd=repo_root, capture_output=True, timeout=30, **_SUBPROCESS_ENCODING)
    return True


def write_task_file(worktree_root: Path, content: str) -> None:
    (worktree_root / TASK_FILE).write_text(content, encoding="utf-8")


def ensure_worktree(
    repo_root: Path,
    worktree_path: Path,
    worktree_branch: str,
    base_branch: str = "main",
) -> bool:
    """Create worktree if it doesn't exist. Uses a dedicated branch per worktree so main isn't checked out twice."""
    if worktree_path.exists():
        return True
    # Ensure the worktree branch exists (create from base_branch if not)
    r = subprocess.run(
        ["git", "rev-parse", "--verify", worktree_branch],
        cwd=repo_root,
        capture_output=True,
        text=True,
        timeout=10,
        **_SUBPROCESS_ENCODING,
    )
    if r.returncode != 0:
        r2 = subprocess.run(
            ["git", "branch", worktree_branch, base_branch],
            cwd=repo_root,
            capture_output=True,
            text=True,
            timeout=10,
            **_SUBPROCESS_ENCODING,
        )
        if r2.returncode != 0:
            err = (r2.stderr or r2.stdout or "").strip()
            if err:
                print(err, file=sys.stderr)
            return False
    r = subprocess.run(
        ["git", "worktree", "add", str(worktree_path), worktree_branch],
        cwd=repo_root,
        capture_output=True,
        text=True,
        timeout=30,
        **_SUBPROCESS_ENCODING,
    )
    if r.returncode != 0:
        err = (r.stderr or r.stdout or "").strip()
        if err:
            print(err, file=sys.stderr)
    return r.returncode == 0


def run_worker(
    worktree_root: Path,
    task_content: str,
    aider_cmd: str,
    model: str,
) -> subprocess.Popen:
    """Start Aider in worktree with task file; return Popen."""
    write_task_file(worktree_root, task_content)
    env = os.environ.copy()
    if sys.platform == "win32":
        env.setdefault("PYTHONIOENCODING", "utf-8")
        env["_DISPATCH_CWD"] = str(worktree_root)

    if _USE_WRAPPER_WIN:
        # Run worker via a Python one-liner so we never attach to the real process's stdout/stderr (avoids _readerthread + cp1252 UnicodeDecodeError).
        real_cmd = [
            aider_cmd,
            "--model",
            model,
            "--message-file",
            str(worktree_root / TASK_FILE),
        ]
        wrapper_code = (
            "import subprocess,sys,os; "
            "i=sys.argv.index('--'); "
            "r=subprocess.run(sys.argv[i+1:], cwd=os.environ.get('_DISPATCH_CWD','.'), "
            "stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL); "
            "sys.exit(r.returncode)"
        )
        cmd = [sys.executable, "-c", wrapper_code, "--"] + real_cmd
    else:
        cmd = [
            aider_cmd,
            "--model",
            model,
            "--message-file",
            str(worktree_root / TASK_FILE),
        ]

    return subprocess.Popen(
        cmd,
        cwd=worktree_root if not _USE_WRAPPER_WIN else None,
        stdin=subprocess.DEVNULL,
        stdout=_NULL_DEV,
        stderr=_NULL_DEV,
        env=env,
    )


def main() -> int:
    config_path = Path(sys.argv[1]) if len(sys.argv) > 1 else DEFAULT_CONFIG_PATH
    if not config_path.exists():
        print("Config not found:", config_path, file=sys.stderr)
        return 1
    config = load_config(config_path)
    repo_root = get_repo_root(config)
    beads_mode = use_beads(repo_root)

    if not beads_mode:
        seed_task_queue_if_missing(repo_root)

    num_workers = int(config.get("num_workers", 14))
    prefix = config.get("worktree_prefix", "ozon-w")
    # Worktrees: sibling dirs repo_root/../ozon-w1, ... or repo_root/worktrees/w1
    model = config.get("model", "ollama/qwen2.5-coder:7b")
    aider_cmd = config.get("aider_cmd", "aider")

    # worktree_placement: "sibling" = repo_root/../ozon-w1, "inside" = repo_root/worktrees/w1
    placement = config.get("worktree_placement", "sibling")
    if placement == "inside":
        worktree_base = repo_root / "worktrees"
        worktree_base.mkdir(exist_ok=True)
        worktree_roots = [worktree_base / f"w{i}" for i in range(1, num_workers + 1)]
    else:
        parent = repo_root.parent
        worktree_roots = [parent / f"{prefix}{i}" for i in range(1, num_workers + 1)]
    base_branch = config.get("branch", "main")
    # Each worktree gets its own branch (worker-w1, worker-w2, ...) so we don't check out main twice
    for i, wt in enumerate(worktree_roots, start=1):
        worktree_branch = f"{prefix}{i}"
        if not ensure_worktree(repo_root, wt, worktree_branch=worktree_branch, base_branch=base_branch):
            print("Failed to create worktree:", wt, file=sys.stderr)
            return 1

    slots: list[dict[str, Any] | None] = [None] * num_workers
    assigned_beads: set[str] = set()

    def get_next_ready_bead() -> dict[str, Any] | None:
        if beads_mode:
            beads = bd_ready_json(repo_root)
            if not beads:
                beads = bd_list_open_json(repo_root)  # fallback: open issues when none are "ready" (e.g. all have blocking deps)
            for b in beads:
                bid = b.get("id") or b.get("bead_id") or b.get("hash") or (b if isinstance(b, str) else None)
                if not bid:
                    continue
                if isinstance(b, dict):
                    bid = str(bid)
                if bid not in assigned_beads:
                    return {"id": bid, "title": b.get("title", bid)}
            return None
        task = get_next_pending_from_queue(repo_root)
        if not task or task["id"] in assigned_beads:
            return None
        return task

    def task_content(bead_or_task: dict[str, Any]) -> str:
        title = bead_or_task.get("title", bead_or_task["id"])
        if beads_mode:
            body = bd_show(repo_root, bead_or_task["id"])
            return (
                "You are a coding agent in a Gas Town-style workflow. Execute this task fully, then exit.\n\n"
                + body
                + "\n\nSelf-improving: If you think of 1–3 concrete follow-up improvements, append them one per line to suggested_tasks.txt in the repo root (create if missing). Run ingest_suggested_tasks.py later to add them as beads or queue tasks."
            )
        return (
            "You are a coding agent. Execute this task fully, then exit.\n\n"
            f"Task: {title}\n\n"
            "Implement it in this repo (jira_analytics.py, generate_dashboard.py, jira_dashboard.html as needed).\n\n"
            "Self-improving: If you think of 1–3 concrete follow-up improvements (new metrics, UX, or code quality), "
            "append them one per line to suggested_tasks.txt in the repo root (create the file if missing). "
            "Each line = one task title. These can be ingested later to grow the backlog."
        )

    def assign_slot(slot_idx: int) -> bool:
        bead = get_next_ready_bead()
        if not bead:
            return False
        bid = bead["id"]
        title = (bead.get("title") or bid)[:60]
        assigned_beads.add(bid)
        if beads_mode:
            if not bd_claim(repo_root, bid):
                assigned_beads.discard(bid)
                return False
        else:
            mark_task_status(repo_root, bid, "in_progress")
        content = task_content(bead)
        wt = worktree_roots[slot_idx]
        proc = run_worker(wt, content, aider_cmd, model)
        slots[slot_idx] = {"bead_id": bid, "process": proc}
        print(f"[w{slot_idx + 1}] started {bid}: {title}", flush=True)
        return True

    def on_worker_done(slot_idx: int) -> None:
        bid = slots[slot_idx]["bead_id"]
        if beads_mode:
            bd_close(repo_root, bid)
        else:
            mark_task_status(repo_root, bid, "done")
        assigned_beads.discard(bid)
        print(f"[w{slot_idx + 1}] done   {bid}", flush=True)
        slots[slot_idx] = None

    mode_str = "Beads" if beads_mode else "task_queue.json"
    print(f"Dispatcher: {num_workers} workers, {mode_str}. Press Ctrl+C to stop.", flush=True)

    # Startup check: how much ready work?
    if beads_mode:
        ready_list = bd_ready_json(repo_root)
        n_ready = len(ready_list)
        if n_ready == 0:
            open_list = bd_list_open_json(repo_root)
            n_open = len(open_list)
            if n_open > 0:
                print(f"No ready beads (deps blocking); using {n_open} open issue(s) instead. Assigning to workers...", flush=True)
            else:
                print("No ready or open beads. Run 'bd list' in the repo to see issues. Create: 'bd create \"Task title\"'. To unblock: 'bd update <id> --status open' (if stuck in progress).", flush=True)
        else:
            print(f"Ready beads: {n_ready}. Assigning to workers...", flush=True)
    else:
        data = load_task_queue(repo_root)
        n_pending = sum(1 for t in data["tasks"] if t.get("status") == "pending")
        if n_pending == 0:
            print("No pending tasks in task_queue.json. Add entries or run with Beads.", flush=True)
        else:
            print(f"Pending tasks: {n_pending}. Assigning to workers...", flush=True)

    for i in range(num_workers):
        assign_slot(i)

    try:
        while True:
            for i in range(num_workers):
                if slots[i] is None:
                    assign_slot(i)
                    continue
                proc = slots[i]["process"]
                if proc.poll() is not None:
                    on_worker_done(i)
                    assign_slot(i)
            time.sleep(2)
    except KeyboardInterrupt:
        for i in range(num_workers):
            if slots[i] and slots[i]["process"].poll() is None:
                slots[i]["process"].terminate()
        return 0
    return 0


if __name__ == "__main__":
    sys.exit(main())
