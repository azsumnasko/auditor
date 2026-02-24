# Gas Town Concept + 14 Local Qwen Agents

This folder contains two ways to run **14 concurrent local Qwen coding agents** using Gas Town-style orchestration (Beads, work assignment, worktrees).

**New to this repo?** Install prerequisites first: see **[INSTALL.md](INSTALL.md)** (Beads, Python, Ollama, Aider, Git). You can run **without Beads**: the dispatcher will create and use `task_queue.json` and seed it from [BEADS_FOR_ANALYSIS.md](BEADS_FOR_ANALYSIS.md).

**Give one task and get small tasks?** See [GASTOWN_HOW_IT_WORKS.md](GASTOWN_HOW_IT_WORKS.md). On Path B run `py split_task.py "Your big goal"` to split into beads/queue; on Path A tell the Mayor and it creates a convoy.

---

## Start everything (Windows – Path B)

Run these in order each time you want to run the agents:

1. **Start Ollama** (in a terminal you leave open; optional: set concurrency first):
   ```powershell
   $env:OLLAMA_NUM_PARALLEL = 14   # optional, for 14 parallel workers
   ollama serve
   ```

2. **In a new terminal**, go to the repo and ensure there is work:
   ```powershell
   cd c:\Work\ozon
   bd ready                    # see if you have open beads (or use task_queue.json)
   # If empty, add work: bd create "Task title"  OR  py split_task.py "One big goal"
   ```

3. **Start the dispatcher** (assigns beads/tasks to workers; stop with Ctrl+C):
   ```powershell
   py dispatch_workers.py
   ```

4. **(Optional)** After some workers finish, ingest agent suggestions as new tasks:
   ```powershell
   py ingest_suggested_tasks.py
   ```

---

## How to start and prompt (quick reference)

**Prompting** = giving work to the agents. Work is expressed as **beads** (tasks). You create beads with short titles and optional details; agents pick them up and execute.

### Path B (Windows – this repo)

1. **One-time setup**: install Beads, Ollama, Aider, Python; run `bd init` in this repo; set `OLLAMA_NUM_PARALLEL=14` before starting Ollama.
2. **Create work (prompt the queue)**:
   ```powershell
   cd c:\Work\ozon
   bd create "Add a cycle time chart to the dashboard"
   bd create "Fix WIP aging calculation in jira_analytics.py"
   bd create "Add tooltip to sprint commitment ratio"
   # Add as many as you want; the dispatcher feeds 14 at a time.
   ```
3. **Start the dispatcher** (and ensure Ollama is running):
   ```powershell
   py dispatch_workers.py
   ```
   If `py` is not found, try `python dispatch_workers.py` or `python3 dispatch_workers.py`. On Windows, the Python Launcher (`py`) is often available when `python` is not in PATH.
   The dispatcher assigns ready beads to 14 workers. Each worker gets the bead text (from `bd show`) as its prompt in `.current_task.txt` and runs Aider + Qwen on it. When one finishes, the next bead is assigned to that slot. Stop with **Ctrl+C**.
4. **Richer prompts**: use `bd create "Title"` then `bd show <id>` and `bd update <id> --description "Long instructions here"` if your Beads version supports it, or put the full instructions in the title.
5. **Ready-made beads for this repo**: see [BEADS_FOR_ANALYSIS.md](BEADS_FOR_ANALYSIS.md) for copy-paste tasks that improve the Jira analytics and dashboard.
6. **No Beads?** Run `py dispatch_workers.py` anyway; it creates `task_queue.json` with the analysis tasks and runs the same way.

### Self-improving flow

Agents are prompted to append **follow-up task ideas** (one per line) to **`suggested_tasks.txt`** in the repo root when they finish a task. To turn those into new work:

- **With Beads:** run `py ingest_suggested_tasks.py` — it runs `bd create "title"` for each line, then clears the file.
- **Without Beads:** run `py ingest_suggested_tasks.py` — it appends the lines to `task_queue.json` as pending tasks, then clears the file.

Run `ingest_suggested_tasks.py` periodically (e.g. after a batch of workers finish) so the backlog grows from agent suggestions.

### Path A (WSL + Gas Town)

1. **Start Ollama** (with `OLLAMA_NUM_PARALLEL=14`), then from your Gas Town HQ:
2. **Create beads and sling** (this is how you “prompt”):
   ```bash
   cd ~/gt/ozon   # or your rig path
   bd create "Add cycle time chart"
   bd create "Fix WIP aging"
   # ... create 14 or more
   gt sling gt-abc12 gt-def34 gt-ghi56 ... ozon
   ```
   Or **tell the Mayor** and let it create and sling:
   ```bash
   gt mayor attach
   # In the Mayor session, say: "Create a convoy of tasks for adding a cycle time chart and fixing WIP aging, then sling them to ozon."
   ```
3. Each sling spawns a worker that runs the Qwen wrapper; the worker’s “prompt” is the hooked bead (from `gt hook`).

---

## Path A: Full Gas Town on WSL (recommended if you use WSL)

Uses the real `gt` binary; all workers run the custom Qwen wrapper. You get convoys, sling, Witness, Refinery.

### Prerequisites (in WSL)

- Go 1.23+, Git 2.25+ (worktree support), tmux 3.0+
- [Beads](https://github.com/steveyegge/beads): `go install github.com/steveyegge/beads/cmd/bd@latest`
- [Gas Town](https://github.com/steveyegge/gastown): `go install github.com/steveyegge/gastown/cmd/gt@latest`
- Dolt (Beads backend)
- Ollama: `ollama pull qwen2.5-coder:7b`
- Aider: `pip install aider-chat`

### Setup

1. **Ollama concurrency** (in WSL, before `ollama serve`):
   ```bash
   export OLLAMA_NUM_PARALLEL=14
   ollama serve
   ```

2. **Copy and register the Qwen agent wrapper**:
   ```bash
   mkdir -p ~/bin
   cp /mnt/c/Work/ozon/scripts/qwen-agent.sh ~/bin/
   chmod +x ~/bin/qwen-agent.sh
   ```
   Then in your Gas Town HQ:
   ```bash
   gt config agent set qwen "$HOME/bin/qwen-agent.sh"
   gt config default-agent qwen
   ```

3. **Gas Town install and rig** (from WSL):
   ```bash
   gt install ~/gt --git
   cd ~/gt
   gt rig add ozon /path/to/ozon/repo
   gt crew add yourname --rig ozon
   ```

4. **Run 14 agents**: create 14 beads, then sling them to the rig:
   ```bash
   gt sling bead-1 bead-2 ... bead-14 ozon
   ```
   Or create a convoy and sling the convoy.

---

## Path B: Lightweight dispatcher on Windows (no WSL)

Beads + 14 worktrees + a Python dispatcher that assigns beads to Aider+Qwen workers. No `gt` or tmux.

### Prerequisites (Windows)

- Git (worktree support)
- [Beads](https://github.com/steveyegge/beads): `bd` on PATH (npm: `npm i -g @beads/bd` or Go install)
- [Ollama](https://ollama.com) for Windows: `ollama pull qwen2.5-coder:7b`
- Aider: `pip install aider-chat`
- Python 3 (for the dispatcher)

### Setup

1. **Beads in this repo** (once):
   ```powershell
   cd c:\Work\ozon
   bd init
   ```
   Create work as beads, e.g.:
   ```powershell
   bd create "Add cycle time chart to dashboard"
   bd create "Fix WIP aging calculation"
   ```

2. **Ollama concurrency** (before starting Ollama):
   - Set environment variable: `OLLAMA_NUM_PARALLEL=14`
   - Or in PowerShell (current session): `$env:OLLAMA_NUM_PARALLEL=14`

3. **Config**  
   Edit [dispatch_config.json](dispatch_config.json) if needed:
   - `num_workers`: 14
   - `worktree_placement`: `"inside"` = worktrees in repo `worktrees/w1` … (recommended if "Failed to create worktree" for sibling path); `"sibling"` = `../ozon-w1` …
   - `worktree_prefix`: used when placement is `sibling` (e.g. `ozon-w` → `ozon-w1` .. `ozon-w14`)
   - `branch`: branch to use for worktrees (must exist: use `main` or `master` per your repo — run `git branch` to see)
   - `auto_merge_worktrees`: when `true` (default), after each worker exits the dispatcher merges that worktree's branch into `main` so changes appear in the repo root; set to `false` to merge manually
   - `create_bead_on_merge_conflict`: when `true` (default), if a merge fails (e.g. conflict), the dispatcher creates a bead (or task_queue entry) "Resolve merge conflict: ozon-wN" so you or a worker can fix it
   - `merge_slot`: when `true` (default), only one merge runs at a time (file lock), Gas Town–style
   - `auto_retry_merge_on_conflict_close`: when `true` (default), after you close the "Resolve merge conflict: ozon-wN" bead, the dispatcher automatically retries merging that branch into main
   - `model`: e.g. `ollama/qwen2.5-coder:7b`
   - `aider_cmd`: `aider` (or full path)
   - `repo_root`: `.` (repo root = directory of this file)

### Run the dispatcher

From the repo root (where `.beads` exists):

```powershell
cd c:\Work\ozon
py dispatch_workers.py
```

If you see "Python was not found": use `py` (Windows Python Launcher), or add Python to PATH from [python.org](https://www.python.org/downloads/) (check "Add Python to PATH" during install).

- The script creates 14 worktrees (e.g. `c:\Work\ozon-w1` .. `c:\Work\ozon-w14`) if they don't exist.
- It reads `bd ready`, assigns one bead per slot, writes `.current_task.txt` in each worktree, and starts Aider with `--message-file .current_task.txt`.
- When a worker (Aider) exits, the dispatcher closes that bead, runs `bd sync`, and assigns the next ready bead to that slot.
- Stop with Ctrl+C; the dispatcher will terminate all worker processes.

---

## Summary

| Item            | Path A (WSL + gt)                    | Path B (Windows)                |
|-----------------|--------------------------------------|---------------------------------|
| Wrapper/script  | [scripts/qwen-agent.sh](scripts/qwen-agent.sh) | [dispatch_workers.py](dispatch_workers.py) |
| Config          | `gt config`                          | [dispatch_config.json](dispatch_config.json) |
| Concurrency     | `OLLAMA_NUM_PARALLEL=14`             | Same                            |
| Work assignment | `gt sling`, hooks                    | Dispatcher + `.current_task.txt` |

No changes to [generate_dashboard.py](generate_dashboard.py) or [jira_dashboard.html](jira_dashboard.html) are required; agents work on whatever tasks you put in Beads.
