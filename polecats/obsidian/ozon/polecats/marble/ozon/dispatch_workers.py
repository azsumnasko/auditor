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
SUGGESTED_FILE = "suggested_tasks.txt"

# Open null device once; used for worker stdout/stderr to avoid any pipe (and thus _readerthread) on Windows where pipe decoding can raise UnicodeDecodeError.
_NULL_DEV = open(os.devnull, "wb")  # noqa: SIM115
TASK_QUEUE_FILE = "task_queue.json"
MERGE_LOCK_FILE = ".dispatch_merge.lock"
PENDING_MERGE_RETRIES_FILE = ".dispatch_pending_merge_retries.json"
MERGE_SLOT_TIMEOUT_SECS = 120
RETRY_PENDING_INTERVAL_SECS = 45

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


# ---------- Merge slot (Gas Town-style: serialize merges) ----------
def _merge_lock_path(repo_root: Path) -> Path:
    return repo_root / MERGE_LOCK_FILE


def acquire_merge_slot(repo_root: Path, timeout_secs: float = MERGE_SLOT_TIMEOUT_SECS) -> bool:
    """Acquire the merge slot (file lock). Returns True if acquired. Blocks up to timeout_secs."""
    lock_path = _merge_lock_path(repo_root)
    deadline = time.monotonic() + timeout_secs
    while time.monotonic() < deadline:
        try:
            fd = os.open(lock_path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o644)
            os.write(fd, str(os.getpid()).encode())
            os.close(fd)
            return True
        except FileExistsError:
            time.sleep(1.0)
            continue
    return False


def release_merge_slot(repo_root: Path) -> None:
    lock_path = _merge_lock_path(repo_root)
    try:
        lock_path.unlink(missing_ok=True)
    except OSError:
        pass


# ---------- Pending merge retries (auto-retry when conflict bead is closed) ----------
def _pending_retries_path(repo_root: Path) -> Path:
    return repo_root / PENDING_MERGE_RETRIES_FILE


def load_pending_merge_retries(repo_root: Path) -> dict[str, str]:
    """Returns { branch_name: bead_or_task_id }."""
    p = _pending_retries_path(repo_root)
    if not p.exists():
        return {}
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
        return data.get("pending", data) if isinstance(data.get("pending"), dict) else {}
    except (json.JSONDecodeError, OSError):
        return {}


def save_pending_merge_retries(repo_root: Path, pending: dict[str, str]) -> None:
    p = _pending_retries_path(repo_root)
    p.write_text(json.dumps({"pending": pending}, indent=2), encoding="utf-8")


def _bd_open_id_set(repo_root: Path) -> set[str]:
    """Set of open bead IDs (for detecting newly created bead)."""
    beads = bd_list_open_json(repo_root)
    return {str(b.get("id") or b.get("bead_id") or b.get("hash") or "") for b in beads if b.get("id") or b.get("bead_id") or b.get("hash")}


def bd_is_closed(repo_root: Path, bead_id: str) -> bool:
    """True if the bead is closed/done."""
    r = subprocess.run(
        ["bd", "show", bead_id, "--json"],
        cwd=repo_root,
        capture_output=True,
        text=True,
        timeout=10,
        **_SUBPROCESS_ENCODING,
    )
    if r.returncode != 0:
        r = subprocess.run(
            ["bd", "list", "--status", "closed", "--json"],
            cwd=repo_root,
            capture_output=True,
            text=True,
            timeout=15,
            **_SUBPROCESS_ENCODING,
        )
        if r.returncode != 0 or not r.stdout.strip():
            return False
        try:
            data = json.loads(r.stdout)
            issues = data if isinstance(data, list) else data.get("issues", [])
            ids = {str(i.get("id") or i.get("hash") or i.get("key")) for i in issues if i}
            return bead_id in ids
        except json.JSONDecodeError:
            return False
    try:
        data = json.loads(r.stdout)
        # bd show --json may return a single object or a list
        if isinstance(data, list):
            obj = data[0] if data else {}
        else:
            obj = data
        return (obj.get("status") or "").lower() in ("closed", "done")
    except (json.JSONDecodeError, TypeError, IndexError, KeyError):
        return False


def task_queue_is_done(repo_root: Path, task_id: str) -> bool:
    """True if the task in task_queue.json is done."""
    data = load_task_queue(repo_root)
    for t in data["tasks"]:
        if t.get("id") == task_id:
            return (t.get("status") or "").lower() in ("done", "closed")
    return False


def retry_pending_merges(
    repo_root: Path,
    worktree_roots: list[Path],
    prefix: str,
    base_branch: str,
    beads_mode: bool,
    use_merge_slot: bool,
) -> None:
    """Check pending conflict-resolution tasks; if any are closed, retry merging that branch (Gas Town-style auto-retry)."""
    pending = load_pending_merge_retries(repo_root)
    if not pending:
        return
    # Match branch name to worktree: ozon-w3 -> index 2
    branch_re = re.compile(re.escape(prefix) + r"(\d+)$")
    to_remove: list[str] = []
    for branch_name, task_or_bead_id in list(pending.items()):
        is_closed = bd_is_closed(repo_root, task_or_bead_id) if beads_mode else task_queue_is_done(repo_root, task_or_bead_id)
        if not is_closed:
            continue
        m = branch_re.match(branch_name)
        if not m:
            to_remove.append(branch_name)
            continue
        slot_num = int(m.group(1))
        if slot_num < 1 or slot_num > len(worktree_roots):
            to_remove.append(branch_name)
            continue
        worktree_path = worktree_roots[slot_num - 1]
        if use_merge_slot and not acquire_merge_slot(repo_root, timeout_secs=30):
            continue
        try:
            ok, _ = merge_worktree_into_main(repo_root, worktree_path, branch_name, base_branch)
            if ok:
                to_remove.append(branch_name)
                print(f"[merge] retried and merged {branch_name} -> {base_branch} (conflict was resolved)", flush=True)
        finally:
            if use_merge_slot:
                release_merge_slot(repo_root)
    for branch_name in to_remove:
        pending.pop(branch_name, None)
    if to_remove:
        save_pending_merge_retries(repo_root, pending)


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


def prune_stale_worktrees(repo_root: Path) -> None:
    """Remove registered worktrees whose directories are missing (e.g. after Remove-Item worktrees)."""
    subprocess.run(
        ["git", "worktree", "prune"],
        cwd=repo_root,
        capture_output=True,
        timeout=15,
        **_SUBPROCESS_ENCODING,
    )


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

    # --message-file: process task, then exit (no chat mode). --yes: auto-accept all prompts so we don't block headless.
    aider_args = [
        aider_cmd,
        "--model",
        model,
        "--message-file",
        str(worktree_root / TASK_FILE),
        "--yes",
        "--no-show-model-warnings",
    ]
    if _USE_WRAPPER_WIN:
        # Run worker via a Python one-liner so we never attach to the real process's stdout/stderr (avoids _readerthread + cp1252 UnicodeDecodeError).
        real_cmd = aider_args
        wrapper_code = (
            "import subprocess,sys,os; "
            "i=sys.argv.index('--'); "
            "r=subprocess.run(sys.argv[i+1:], cwd=os.environ.get('_DISPATCH_CWD','.'), "
            "stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL); "
            "sys.exit(r.returncode)"
        )
        cmd = [sys.executable, "-c", wrapper_code, "--"] + real_cmd
    else:
        cmd = aider_args

    return subprocess.Popen(
        cmd,
        cwd=worktree_root if not _USE_WRAPPER_WIN else None,
        stdin=subprocess.DEVNULL,
        stdout=_NULL_DEV,
        stderr=_NULL_DEV,
        env=env,
    )


def merge_worktree_into_main(
    repo_root: Path,
    worktree_path: Path,
    branch_name: str,
    base_branch: str = "main",
) -> tuple[bool, str | None]:
    """Merge the worktree's branch into base_branch, then reset worktree to base for next task.
    Returns (True, None) on success, (False, error_message) on failure."""
    # Commit any uncommitted changes in the worktree so we don't lose them
    r = subprocess.run(
        ["git", "status", "--porcelain"],
        cwd=worktree_path,
        capture_output=True,
        text=True,
        timeout=5,
        **_SUBPROCESS_ENCODING,
    )
    if r.returncode == 0 and (r.stdout or "").strip():
        subprocess.run(["git", "add", "-A"], cwd=worktree_path, capture_output=True, timeout=10)
        # Don't commit dispatcher-only files (avoid add/add conflicts when merging into main)
        subprocess.run(
            ["git", "reset", "HEAD", TASK_FILE, SUGGESTED_FILE],
            cwd=worktree_path,
            capture_output=True,
            timeout=5,
        )
        subprocess.run(
            ["git", "commit", "-m", f"Dispatcher: capture work ({branch_name})"],
            cwd=worktree_path,
            capture_output=True,
            timeout=10,
            **_SUBPROCESS_ENCODING,
        )
    # Checkout base and merge
    r = subprocess.run(
        ["git", "checkout", base_branch],
        cwd=repo_root,
        capture_output=True,
        text=True,
        timeout=15,
        **_SUBPROCESS_ENCODING,
    )
    if r.returncode != 0:
        msg = (r.stderr or r.stdout or "").strip()
        print(f"[merge] git checkout {base_branch} failed: {msg}", file=sys.stderr)
        return False, msg
    r = subprocess.run(
        ["git", "merge", branch_name, "-m", f"Merge {branch_name} (dispatcher)"],
        cwd=repo_root,
        capture_output=True,
        text=True,
        timeout=60,
        **_SUBPROCESS_ENCODING,
    )
    if r.returncode != 0:
        # Try to resolve trivial conflicts (dispatcher-only files that we don't want in main)
        conflict_files = set()
        r2 = subprocess.run(
            ["git", "diff", "--name-only", "--diff-filter=U"],
            cwd=repo_root,
            capture_output=True,
            text=True,
            timeout=5,
            **_SUBPROCESS_ENCODING,
        )
        if r2.returncode == 0 and r2.stdout:
            conflict_files = {f.strip() for f in r2.stdout.splitlines() if f.strip()}
        trivial = {TASK_FILE, SUGGESTED_FILE, ".gitignore"}
        if conflict_files and conflict_files <= trivial:
            # Resolve: drop .current_task.txt and suggested_tasks.txt from merge; keep main's .gitignore
            for f in (TASK_FILE, SUGGESTED_FILE):
                if f in conflict_files:
                    subprocess.run(["git", "rm", "-f", f], cwd=repo_root, capture_output=True, timeout=5)
            if ".gitignore" in conflict_files:
                subprocess.run(["git", "checkout", "--ours", ".gitignore"], cwd=repo_root, capture_output=True, timeout=5)
                subprocess.run(["git", "add", ".gitignore"], cwd=repo_root, capture_output=True, timeout=5)
            subprocess.run(["git", "add", "-A"], cwd=repo_root, capture_output=True, timeout=5)
            r3 = subprocess.run(
                ["git", "commit", "-m", f"Merge {branch_name} (dispatcher, resolve trivial conflicts)"],
                cwd=repo_root,
                capture_output=True,
                timeout=10,
                **_SUBPROCESS_ENCODING,
            )
            if r3.returncode == 0:
                # Merge completed; reset worktree and return success
                subprocess.run(
                    ["git", "reset", "--hard", base_branch],
                    cwd=worktree_path,
                    capture_output=True,
                    timeout=10,
                    **_SUBPROCESS_ENCODING,
                )
                print(f"[merge] resolved trivial conflicts ({branch_name}) -> {base_branch}", flush=True)
                return True, None
        subprocess.run(
            ["git", "merge", "--abort"],
            cwd=repo_root,
            capture_output=True,
            timeout=10,
        )
        msg = (r.stderr or r.stdout or "").strip() or branch_name
        print(f"[merge] merge {branch_name} failed (conflict?): {msg}", file=sys.stderr)
        return False, msg
    # Reset worktree to base so next task starts clean
    r = subprocess.run(
        ["git", "reset", "--hard", base_branch],
        cwd=worktree_path,
        capture_output=True,
        text=True,
        timeout=10,
        **_SUBPROCESS_ENCODING,
    )
    if r.returncode != 0:
        print(f"[merge] reset worktree failed: {r.stderr or r.stdout}", file=sys.stderr)
    return True, None


def create_merge_conflict_task(
    repo_root: Path,
    branch_name: str,
    detail: str,
    beads_mode: bool,
) -> str | None:
    """Create a bead or queue task for resolving a merge conflict. Returns the created task/bead id for pending retry tracking."""
    title = f"Resolve merge conflict: {branch_name}"
    description = (
        f"Merge of branch {branch_name} into main failed. Resolve conflicts and complete the merge.\n\n"
        f"Steps: cd to repo root, run `git checkout main`, then `git merge {branch_name}`. "
        "Fix conflicts, then `git add` and `git commit`.\n\n"
        "The dispatcher will auto-retry the merge when this task is closed.\n\n"
        f"Git output:\n{detail[:1500]}"
    )
    if beads_mode:
        before_ids = _bd_open_id_set(repo_root)
        subprocess.run(
            ["bd", "create", title, "--description", description],
            cwd=repo_root,
            capture_output=True,
            timeout=15,
            **_SUBPROCESS_ENCODING,
        )
        after_ids = _bd_open_id_set(repo_root)
        new_id = next(iter(after_ids - before_ids), None)
        print(f"[merge] created bead for resolving conflict: {branch_name}", flush=True)
        return new_id
    path = task_queue_path(repo_root)
    if path.exists():
        data = json.loads(path.read_text(encoding="utf-8"))
    else:
        data = {"tasks": [], "next_id": 1}
    task_id = f"task-{data['next_id']}"
    data["tasks"].append({
        "id": task_id,
        "title": title,
        "status": "pending",
        "description": description,
    })
    data["next_id"] += 1
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"[merge] added to task_queue.json: {title}", flush=True)
    return task_id


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
    auto_merge_worktrees = config.get("auto_merge_worktrees", True)
    use_merge_slot = config.get("merge_slot", True)
    auto_retry_merge_on_conflict_close = config.get("auto_retry_merge_on_conflict_close", True)
    worker_timeout_secs = int(config.get("worker_timeout_secs", 1800) or 0)  # default 30 min; 0 = no timeout
    # Prune stale worktrees so we can recreate if user deleted worktrees/ with Remove-Item
    prune_stale_worktrees(repo_root)
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
                + "\n\nScope: Work only on the files needed for this task (keep tasks independent so other workers can merge cleanly). "
                "For dashboard/report tasks: add and edit the relevant code (e.g. generate_dashboard.py, jira_analytics.py, or jira_dashboard.html), not only ingest_suggested_tasks.py."
                + "\n\nWhen done: Make your edits, commit, then stop. Do not ask for more input or suggest further steps in chat; the session will end after your response."
                + "\n\nSelf-improving: If you think of 1–3 concrete follow-up improvements, append them one per line to suggested_tasks.txt in the repo root (create if missing). Run ingest_suggested_tasks.py later to add them as beads or queue tasks."
            )
        return (
            "You are a coding agent. Execute this task fully, then exit.\n\n"
            f"Task: {title}\n\n"
            "Scope: Implement only what this task needs (use jira_analytics.py, generate_dashboard.py, or jira_dashboard.html as needed). Keep changes to the minimum required so other workers can merge cleanly. "
            "For dashboard/report: add those code files to the chat and edit them; do not only add ingest_suggested_tasks.py. "
            "When done: Make your edits, commit, then stop. Do not ask for more input or suggest further steps in chat; the session will end after your response.\n\n"
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
        slots[slot_idx] = {"bead_id": bid, "process": proc, "started_at": time.monotonic()}
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
        # Auto-merge this worktree's branch into main (Gas Town-style: merge slot + conflict bead + pending retry)
        if auto_merge_worktrees:
            wt = worktree_roots[slot_idx]
            worker_branch = f"{prefix}{slot_idx + 1}"
            if use_merge_slot and not acquire_merge_slot(repo_root):
                print(f"[w{slot_idx + 1}] merge slot busy, skipping merge for {worker_branch}", flush=True)
            else:
                try:
                    ok, merge_err = merge_worktree_into_main(repo_root, wt, worker_branch, base_branch)
                    if ok:
                        print(f"[w{slot_idx + 1}] merged {worker_branch} -> {base_branch}", flush=True)
                    elif merge_err and config.get("create_bead_on_merge_conflict", True):
                        conflict_id = create_merge_conflict_task(repo_root, worker_branch, merge_err, beads_mode)
                        if conflict_id and auto_retry_merge_on_conflict_close:
                            pending = load_pending_merge_retries(repo_root)
                            pending[worker_branch] = conflict_id
                            save_pending_merge_retries(repo_root, pending)
                finally:
                    if use_merge_slot:
                        release_merge_slot(repo_root)

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

    last_retry_time = 0.0
    try:
        while True:
            now = time.monotonic()
            if auto_retry_merge_on_conflict_close and (now - last_retry_time) >= RETRY_PENDING_INTERVAL_SECS:
                retry_pending_merges(repo_root, worktree_roots, prefix, base_branch, beads_mode, use_merge_slot)
                last_retry_time = now
            for i in range(num_workers):
                if slots[i] is None:
                    assign_slot(i)
                    continue
                proc = slots[i]["process"]
                # Worker timeout: free the slot if Aider runs too long (e.g. never exits)
                if worker_timeout_secs > 0 and (now - slots[i]["started_at"]) >= worker_timeout_secs:
                    if proc.poll() is None:
                        print(f"[w{i + 1}] worker timeout ({worker_timeout_secs}s), terminating", flush=True)
                        proc.terminate()
                        try:
                            proc.wait(timeout=10)
                        except subprocess.TimeoutExpired:
                            proc.kill()
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
