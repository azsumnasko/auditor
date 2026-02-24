# How Gas Town Works in This Project

You can **give one high-level task** and have it **split into small tasks** and **generate new tasks** in two ways: use [Gas Town](https://github.com/steveyegge/gastown) (Path A) or the local task splitter (Path B).

---

## What We Reuse from Gas Town

From [steveyegge/gastown](https://github.com/steveyegge/gastown):

| Concept | In this repo |
|--------|---------------|
| **Beads** | Same: we use `bd` (beads) for all tasks. Bead IDs (e.g. `ozon-4id`) are created with `bd create` and consumed by the dispatcher or by `gt sling`. |
| **Convoy** | Group of beads for one “mission”. In Gas Town: `gt convoy create "Name" gt-abc gt-def`. Here (Path B): subtasks from one parent are linked with `discovered-from:<parent-id>`. |
| **Sling** | Assign work to an agent. Path A: `gt sling <bead-id> <rig>`. Path B: `dispatch_workers.py` assigns beads from `bd ready` to workers. |
| **The Mayor** | AI coordinator that splits a goal into beads and creates convoys. **Path A only**: you run `gt mayor attach` and say e.g. “Create a convoy for adding a cycle time chart and fixing WIP aging, then sling to ozon.” |
| **Task splitting** | **Path A**: the Mayor does it. **Path B**: use `split_task.py` (see below). |
| **Generate new tasks** | Agents append to `suggested_tasks.txt`; `ingest_suggested_tasks.py` turns them into beads or `task_queue.json` entries. Same on both paths. |

---

## Path A: Full Gas Town (WSL)

1. Install: `gt`, `bd`, Dolt, Ollama, Aider (see [ORCHESTRATOR_README.md](ORCHESTRATOR_README.md)).
2. **Give one task and let the Mayor split it:**
   ```bash
   gt mayor attach
   ```
   In the Mayor session, say something like:
   - *“Create a convoy of tasks for adding a cycle time chart and fixing WIP aging, then sling them to ozon.”*
3. The Mayor will create beads (and optionally a convoy), then you can sling those beads to your rig. Each sling spawns a worker (e.g. your Qwen wrapper from `scripts/qwen-agent.sh`).

So **task splitting** and **generating tasks** in Path A are done by **the Mayor**: you describe the goal, it produces the beads and assigns them.

---

## Path B: Windows + Local Dispatcher (No `gt`)

You don’t have the Mayor, so:

1. **Split one task into small tasks**  
   Use the local script:
   ```powershell
   py split_task.py "Add a full Jira analytics dashboard with cycle time, throughput, and WIP"
   ```
   This calls Ollama to break the goal into 3–10 concrete subtasks, then creates beads (or appends to `task_queue.json`). Subtasks are linked to a parent bead with `discovered-from` so they act like a convoy.

2. **Generate new tasks from agent suggestions**  
   Agents already append follow-up ideas to `suggested_tasks.txt`. Run:
   ```powershell
   py ingest_suggested_tasks.py
   ```
   to create beads (or queue entries) from those lines.

3. **Run workers**  
   Same as now:
   ```powershell
   py dispatch_workers.py
   ```

---

## Quick Reference

| Goal | Path A (Gas Town) | Path B (Windows) |
|------|-------------------|------------------|
| Give one task, get small tasks | Tell the Mayor; it creates convoy + beads | `py split_task.py "Your big task"` |
| Generate new tasks | Mayor or agents → `suggested_tasks.txt` → ingest | `ingest_suggested_tasks.py` |
| Run workers | `gt sling <bead-ids> ozon` (or Mayor slings) | `py dispatch_workers.py` |

So: **we reuse Gas Town’s ideas (beads, convoys, sling) and, on Path A, the Mayor for splitting**. On Path B we reuse the same beads and dispatcher and add **split_task.py** to mimic the Mayor’s “one goal → many beads” step.

---

## How Gas Town Solves Merge Conflicts (and how we compare)

In full Gas Town, a dedicated **Refinery** (merge-queue processor) handles merging Polecat branches into main. When a merge **fails** (e.g. conflict), Gas Town does the following (from [internal/refinery/engineer.go](https://github.com/steveyegge/gastown/blob/main/internal/refinery/engineer.go)):

1. **Sends `MERGE_FAILED` to the Witness** – so the overseer agent knows and can react.
2. **Creates a conflict-resolution task (bead)** – title like `"Resolve merge conflicts: <branch>"` with a description that includes branch, target (main), conflict SHA, and steps: checkout branch, pull/merge main, resolve conflicts, force-push; "The Refinery will automatically retry the merge after you force-push."
3. **Blocks the MR on that task** – the merge-request bead gets a dependency on the new conflict-resolution bead, so the queue does not retry the same MR until the conflict is resolved.
4. **Merge slot** – only one merge (or conflict resolution) runs at a time per rig; conflict resolution acquires the same slot so pushes to main are serialized.
5. **Config** – `merge_queue.on_conflict` can be `"assign_back"` (create task, assign back) or `"auto_rebase"`.

So Gas Town **does create beads for resolving merge conflicts**, and integrates them with the merge queue (block MR until conflict bead is done) and with the Witness.

**In this repo (Path B):** We now mirror more of this:
- **Merge slot** – `merge_slot: true` (default) uses a file lock (`.dispatch_merge.lock`) so only one merge runs at a time.
- **Conflict bead** – On merge failure we create `"Resolve merge conflict: ozon-wN"` and record it in `.dispatch_pending_merge_retries.json`.
- **Auto-retry** – `auto_retry_merge_on_conflict_close: true` (default): the dispatcher periodically checks whether that bead is closed; when it is, it retries merging that branch into main (Gas Town–style).
We still do not have a Witness or MR-bead blocking; we avoid `.current_task.txt` / `suggested_tasks.txt` conflicts via `.gitignore`.
