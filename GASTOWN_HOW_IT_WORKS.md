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
