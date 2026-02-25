# Code review: dispatch_workers.py (orchestrator)

## Summary

Review of the dispatcher, merge/conflict handling, worker summary, and beads/task-queue integration. One bug was fixed; everything else behaves as expected.

---

## Fix applied

### 1. **bd_ready_json return shape**

- **Issue:** `bd ready --json` can return a wrapper (e.g. `{"ready": [...]}`) or a bare list. The code returned `json.loads(r.stdout)` as-is. If the CLI returned a dict, `get_next_ready_bead()` iterated over dict keys, so `b.get("id")` was always `None` and no work was assigned.
- **Fix:** In `bd_ready_json()`, unwrap `data["ready"]` when present, then normalize with `_beads_from_list(data)` so callers always get a list of `{id, title}`. If normalization yields nothing but `data` is a list, return `data` so existing list-of-dicts output still works.

---

## Verified behavior

### Startup and config

- **Config path:** Optional `sys.argv[1]`; falls back to `dispatch_config.json`. Missing config exits with clear error.
- **Repo root:** From `config.repo_path` or `git rev-parse --show-toplevel`; `use_beads(repo_root)` checks `.beads` and `beads_ozon` so beads vs task_queue mode is correct.
- **Stale worktrees:** `prune_stale_worktrees(repo_root)` runs at startup so after manual `Remove-Item worktrees`, worktrees can be recreated without “missing but already registered” errors.
- **Worktree placement:** `worktree_placement: "sibling"` vs `"inside"` correctly sets `worktree_roots` and creates `worktrees/` when inside.

### Assign / capture / summary / merge order

1. **assign_slot:** Picks next ready bead (or queue task), writes `.current_task.txt`, starts aider in the worktree. Slot is stored with `branch_name`, `bead_id`, `process`.
2. **on_worker_done:**  
   - **Capture first:** `commit_worktree_to_branch(worktree_path, branch_name)` commits uncommitted work (after `git reset HEAD .current_task.txt suggested_tasks.txt` so dispatcher-only files are not committed).  
   - **Summary next:** `get_worker_summary(worktree, branch, base)` uses `git diff --name-only base...branch` and `git log --oneline base..branch`, so it sees the new capture commit.  
   - **Merge last:** `merge_worktree_into_main()` runs (with merge slot when enabled). Inside merge, `commit_worktree_to_branch` is called again; if the worktree is already clean, it no-ops, so no double commit.

Order is correct: capture → summary → merge.

### Merge and conflict handling

- **merge_worktree_into_main:** Checkout `base_branch`, `git merge branch_name`. On success, resets worktree to `base_branch`.
- **Trivial conflicts:** If the only conflicted paths are in `{ .current_task.txt, suggested_tasks.txt, .gitignore }`, the code resolves them (remove task/suggested files, keep main’s `.gitignore`), completes the merge, resets the worktree, returns success. No conflict bead is created.
- **Real conflicts:** Merge is aborted; if `create_bead_on_merge_conflict` is true, `create_merge_conflict_task()` creates a bead (or task_queue entry) and the branch is added to `pending` for auto-retry. Merge slot is released in `finally`.

### Merge slot (serialized merges)

- **acquire_merge_slot:** Creates `.dispatch_merge.lock` with `O_CREAT | O_EXCL`; blocks up to `MERGE_SLOT_TIMEOUT_SECS` (e.g. 300s), then returns False.
- **release_merge_slot:** Unlinks the lock file. Used in `finally` so the slot is always released after merge or retry.
- **Usage:** Both “merge after worker done” and `retry_pending_merges()` use the slot when `merge_slot: true`, so only one merge runs at a time.

### Auto-retry when conflict is resolved

- **Pending file:** `.dispatch_pending_merge_retries.json` stores `{ branch_name: bead_or_task_id }`.
- **retry_pending_merges:** Every 45s (or as configured), loads pending; for each entry, checks `bd_is_closed(repo_root, task_or_bead_id)` (or `task_queue_is_done` in queue mode). If closed, acquires merge slot, calls `merge_worktree_into_main(repo_root, worktree_path, branch_name, base_branch)`, then removes the branch from pending. Branch name is parsed to get worktree index (`ozon-w3` → index 2); invalid or out-of-range indices are removed from pending without retry.
- **bd_is_closed:** Handles `bd show --json` returning a single object or a list (takes first element); uses `.get("status")`; fallback to `bd list --status closed --json` if `bd show` fails. Safe against missing keys and JSON errors.

### Worker summary

- **worker_summary:** When true, after capture the script prints task title, up to 12 changed files, and commit count (or “(no file changes or commits on branch)”).
- **worker_summary_log:** When set (e.g. `.dispatch_worker_log.md`), the same info is appended in Markdown. Files are written with UTF-8.

### Beads / task queue

- **get_next_ready_bead:** Uses `bd_ready_json`, then fallback to `bd_list_open_json` when no ready beads; skips already-assigned IDs; returns `{"id", "title"}`. Task-queue path uses `get_next_pending_from_queue` and skips assigned.
- **bd_list_open_json:** Normalizes with `_beads_from_list` so wrapper formats (`{"issues": [...]}`) and list-of-dicts both yield a list of `{id, title}`; filters out closed/done.
- **create_merge_conflict_task:** Beads: diff open IDs before/after `bd create` to get new id. Task queue: appends to `task_queue.json` with `next_id`, returns `task-{id}`. Both paths return an id for pending retry.

### Subprocess and encoding

- **Windows:** All subprocess calls that capture text use `encoding="utf-8", errors="replace"` (`_SUBPROCESS_ENCODING`) so `bd`/git output does not cause `UnicodeDecodeError` on cp1252.

### Main loop and shutdown

- **Loop:** Every 2s, for each slot: if slot is free, `assign_slot(i)`; else if process has exited, `on_worker_done(i)` then `assign_slot(i)`. Every 45s (when enabled), `retry_pending_merges(...)`.
- **KeyboardInterrupt:** Terminates any running worker processes, then exits 0. Pending merges and lock file are left for the next run (lock is per-process; next run can acquire).

---

## Edge cases and robustness

- **Empty ready list:** Fallback to open list is correct; startup message explains “no ready beads (deps blocking)” or “no pending tasks.”
- **Merge slot timeout:** If a merge hangs or another process holds the lock, the dispatcher gives up after the timeout and does not merge that branch this cycle; it can retry later or the user can resolve manually.
- **Branch name regex:** `retry_pending_merges` uses `prefix + r"(\d+)$"`; branch names that don’t match (e.g. typos) are removed from pending so they don’t block forever.
- **task_queue_is_done:** Only considers status `"done"` or `"closed"`; other statuses are not treated as done. Matches intended semantics.

---

## Not changed (acceptable)

- **Lock file content:** Lock file stores PID; no cross-process “who holds it” logic. Unlink on release is enough for single-machine use.
- **No in-process retry of merge:** After a failed merge (non-trivial conflict), the code does not retry in the same run; it relies on the periodic retry when the conflict bead/task is closed. This is intentional (Gas Town-style).
- **Trivial conflict set:** Only `.current_task.txt`, `suggested_tasks.txt`, and `.gitignore` are auto-resolved. Adding more would be a deliberate config/change.

---

## Recommendations for later

1. **Optional merge slot timeout config:** Expose `merge_slot_timeout_secs` in `dispatch_config.json` instead of a constant.
2. **Logging:** Consider structured logging (e.g. JSON lines) for worker start/done and merge success/fail to simplify debugging and metrics.
3. **Tests:** Add small unit tests for `_beads_from_list`, `bd_is_closed` (mocked subprocess), `load_pending_merge_retries` / `save_pending_merge_retries`, and trivial conflict detection (mock `git diff --name-only --diff-filter=U`).

---

## How to re-verify

- Run with 1–2 workers and beads: create a bead, run dispatcher, confirm assignment, edit in worktree, let worker “finish” (exit), confirm capture commit, summary line, and merge into main.
- Force a merge conflict (e.g. edit same file on main and in worktree), confirm conflict bead and entry in `.dispatch_pending_merge_retries.json`, then close the bead and wait for the next retry cycle; confirm merge succeeds and branch is removed from pending.
- Run with `merge_slot: true` and two workers finishing close together; confirm only one merge runs at a time (e.g. by temporary logging in `acquire_merge_slot` / `release_merge_slot`).

---

## Quality gates (Gas Town Refinery–style) – review and fix

### Fix applied

- **gates_parallel was not parallel:** When `gates_parallel: true`, the code iterated over gates and called `_run_one_gate` sequentially, then collected results. So “parallel” did nothing. **Fix:** Use `concurrent.futures.ThreadPoolExecutor` and `as_completed` to run all gate commands concurrently when `gates_parallel` is true; aggregate failures and return the same (False, error_message) shape.

### Verified behavior

- **Order:** In `on_worker_done`, after capture and summary we run quality gates (if `quality_gates` is true) then merge. So: capture → summary → gates → merge.
- **Slot release on gate failure:** When gates fail we `continue` inside the `try`; the `finally` runs and releases the merge slot. No slot leak.
- **Gate commands:** Run in the worktree with `cwd=worktree_path`; on Windows use `shell=True` so compound commands work; timeout and `_SUBPROCESS_ENCODING` applied. Empty cmd is rejected and reported.
- **Config:** `gates` (map) takes precedence; when non-empty, legacy `run_tests` / `test_command` are ignored. Legacy path used when `gates` is empty and `run_tests` is true and `test_command` is set.
- **Gate failure flow:** Create “Fix failing tests/gates: ozon-wN” bead (or task_queue entry), add branch to `.dispatch_pending_gate_retries.json` when `auto_retry_merge_on_gate_close` is true. No merge this cycle.
- **retry_pending_gate_merges:** Same structure as `retry_pending_merges`: branch name → worktree index; only when bead/task is closed do we re-run gates; if gates pass we acquire slot, merge, remove from pending; slot released in `finally`. Invalid branch names or out-of-range indices are removed from pending.

### Edge cases

- **Same branch in both pending files:** A branch could in theory be in both merge retries (conflict) and gate retries if conflict was resolved but gates then failed. The two retry loops are independent; conflict retry merges without re-running gates, gate retry runs gates then merges. So if a branch is in both, conflict retry might merge it first (and merge_worktree_into_main will succeed); gate retry would then see the same branch in pending and try to run gates and merge again – the merge would be a no-op (already merged). No incorrect behavior; we could add “remove from gate pending when merge succeeds” in conflict retry for cleanliness but it’s optional.
- **Worktree reused after gate failure:** When gates fail we don’t merge and don’t reset the worktree. The same slot gets a new task; the new worker runs in the same worktree on the same branch, so the branch accumulates more commits until the “Fix failing tests” bead is closed and gate retry runs (then we merge). Intentional: branch stays until gates pass.

### Not changed (acceptable)

- **No Witness:** We don’t send MERGE_FAILED or GATES_FAILED to any overseer; we only log and create beads. Sufficient for Path B.
- **Timeout from config:** `timeout_secs` per gate and `test_timeout_secs` for legacy; missing or 0 fall back to `DEFAULT_GATE_TIMEOUT_SECS`. `int()` used so float from JSON is fine.
