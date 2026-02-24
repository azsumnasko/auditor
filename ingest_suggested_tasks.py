#!/usr/bin/env python3
"""
Self-improving: ingest suggested_tasks.txt into the task queue (or Beads).
Run from repo root after agents have appended lines to suggested_tasks.txt.
- If Beads is available: bd create "title" for each line.
- Else: append to task_queue.json as pending tasks.
"""
from __future__ import annotations

import json
import shutil
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent
SUGGESTED_FILE = REPO_ROOT / "suggested_tasks.txt"
TASK_QUEUE_FILE = REPO_ROOT / "task_queue.json"


def use_beads() -> bool:
    return (REPO_ROOT / ".beads").exists() and (shutil.which("bd") is not None)


def main() -> int:
    if not SUGGESTED_FILE.exists():
        print("No suggested_tasks.txt found. Agents can append follow-up task titles there.", file=sys.stderr)
        return 0

    lines = [ln.strip() for ln in SUGGESTED_FILE.read_text(encoding="utf-8").splitlines() if ln.strip()]
    if not lines:
        print("suggested_tasks.txt is empty.", file=sys.stderr)
        return 0

    if use_beads():
        for title in lines:
            subprocess.run(["bd", "create", title], cwd=REPO_ROOT, check=False)
        print(f"Created {len(lines)} beads from suggested_tasks.txt.", file=sys.stderr)
    else:
        path = TASK_QUEUE_FILE
        if path.exists():
            data = json.loads(path.read_text(encoding="utf-8"))
        else:
            data = {"tasks": [], "next_id": 1}
        next_id = data["next_id"]
        for title in lines:
            data["tasks"].append({"id": f"task-{next_id}", "title": title, "status": "pending"})
            next_id += 1
        data["next_id"] = next_id
        path.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
        print(f"Appended {len(lines)} tasks to task_queue.json.", file=sys.stderr)

    # Clear the file so the same lines aren't re-ingested
    SUGGESTED_FILE.write_text("", encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(main())
