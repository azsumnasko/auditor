# Set up this project and use Gas Town with a local model

This guide gets you from zero to running **Gas Town–style workers** (Beads + worktrees + Aider) using a **local Ollama model** (Qwen) on Windows. No cloud API keys required.

---

## 1. Prerequisites

Install the following (once). See [INSTALL.md](INSTALL.md) for detailed options.

| What | Why | Verify |
|------|-----|--------|
| **Python 3** | Runs the dispatcher | `py --version` or `python --version` |
| **Git** | Worktrees (one dir per worker) | `git --version` |
| **Ollama** | Local LLM (Qwen) | [ollama.com](https://ollama.com) → `ollama list` |
| **Aider** | Coding agent the workers run | `pip install aider-chat` → `aider --version` |
| **Beads (`bd`)** | Task ledger (optional) | [Install Beads](https://github.com/steveyegge/beads) → `bd --version` |

Without Beads you can still run; the dispatcher will use `task_queue.json` instead.

---

## 2. One-time project setup

In PowerShell, from the repo root (e.g. `c:\Work\ozon`):

```powershell
cd c:\Work\ozon
```

### 2.1 Pull the local model

Pick one (7b is lighter; 30b is stronger but needs ~35 GB RAM):

```powershell
ollama pull qwen2.5-coder:7b
# or
ollama pull qwen3-coder:30b
```

### 2.2 (Optional) Initialize Beads

If you installed Beads:

```powershell
bd init
```

Then create a few tasks to try:

```powershell
bd create "Add a cycle time chart to the dashboard"
bd create "Add tooltip to sprint commitment ratio"
```

Without Beads, skip this; the dispatcher will create `task_queue.json` on first run and seed it from [BEADS_FOR_ANALYSIS.md](BEADS_FOR_ANALYSIS.md).

### 2.3 Config (optional)

Edit **`dispatch_config.json`** in the repo root if you need to change defaults:

| Key | Meaning | Example |
|-----|---------|--------|
| `model` | Ollama model Aider uses | `"ollama/qwen2.5-coder:7b"` or `"ollama/qwen3-coder:30b"` |
| `num_workers` | How many workers (worktrees) | `14` (or fewer if low on RAM) |
| `worktree_placement` | Where worktrees live | `"inside"` → `worktrees/w1` … `worktrees/w14` |
| `branch` | Base branch for worktrees | `"main"` |
| `worker_timeout_secs` | Max seconds per worker (then kill) | `1800` (30 min); `0` = no timeout |

Leave other keys as-is unless you know you need them.

---

## 3. Run Gas Town with the local model

### 3.1 Start Ollama (leave this terminal open)

```powershell
$env:OLLAMA_NUM_PARALLEL = 14   # optional: allow 14 parallel requests
ollama serve
```

If port 11434 is blocked on Windows, see [INSTALL.md – "bind: access forbidden"](INSTALL.md) (use another port and set `OLLAMA_HOST` / `OLLAMA_API_BASE` when running the dispatcher).

### 3.2 Open a second terminal – repo and work

```powershell
cd c:\Work\ozon
bd ready
```

If you see no ready beads, add work:

```powershell
bd create "Your task title"
# or split a big goal into small tasks:
py split_task.py "Add full Jira dashboard with cycle time and WIP"
```

### 3.3 Start the dispatcher

```powershell
py dispatch_workers.py
```

- The dispatcher creates worktrees (e.g. `worktrees/w1` … `worktrees/w14`) if needed.
- It assigns one bead (or task from `task_queue.json`) per slot, writes the task into each worktree’s `.current_task.txt`, and runs **Aider** with your **local model** (`--message-file` + `--yes`).
- When a worker exits (or hits `worker_timeout_secs`), the dispatcher merges that worktree’s branch into `main` and assigns the next task to that slot.
- Stop with **Ctrl+C** (all workers are terminated).

### 3.4 (Optional) Ingest agent suggestions

Agents can append follow-up ideas to `suggested_tasks.txt`. To turn them into new beads (or queue tasks):

```powershell
py ingest_suggested_tasks.py
```

Run this periodically so the backlog grows from agent suggestions.

---

## 4. Quick reference

| Goal | Command |
|------|--------|
| Add one task | `bd create "Task title"` |
| Split a big goal into small tasks | `py split_task.py "Your big goal"` |
| See ready work | `bd ready` |
| Run workers (local model) | Start Ollama, then `py dispatch_workers.py` |
| Ingest suggested tasks | `py ingest_suggested_tasks.py` |
| Worker logs (if enabled) | `.dispatch_worker_logs/w1.log` … `w14.log` |
| Per-worktree Aider history | `worktrees/w1/.aider.chat.history.md` |

---

## 5. Path A: Full Gas Town on WSL (optional)

If you use **WSL** and want the full **Gas Town** stack (Mayor, `gt sling`, Witness, Refinery):

1. Install in WSL: `gt`, `bd`, Dolt, Ollama, Aider (see [ORCHESTRATOR_README.md – Path A](ORCHESTRATOR_README.md#path-a-full-gas-town-on-wsl-recommended-if-you-use-wsl)).
2. Copy and register the Qwen wrapper: `scripts/qwen-agent.sh` → `~/bin/`, then `gt config agent set qwen "$HOME/bin/qwen-agent.sh"` and `gt config default-agent qwen`.
3. Create beads and sling: `gt sling <bead-id> <rig>` or use the Mayor to create a convoy and sling.

The same local model (Ollama + Qwen) is used via the wrapper; see [ORCHESTRATOR_README.md](ORCHESTRATOR_README.md) and [GASTOWN_HOW_IT_WORKS.md](GASTOWN_HOW_IT_WORKS.md) for details.

---

## 6. Troubleshooting

- **"model 'qwen3-coder:30b' not found"** – Start Ollama before the dispatcher and run `ollama pull qwen3-coder:30b` (or the model in your config). If you use a custom port, set `OLLAMA_API_BASE` in the same environment as `py dispatch_workers.py`.
- **Out of memory** – Use a smaller model (e.g. `ollama/qwen2.5-coder:7b`) or reduce `num_workers` in `dispatch_config.json`.
- **Workers never exit** – Dispatcher uses a 30‑minute timeout by default (`worker_timeout_secs`); the slot is freed and the next task is assigned. Set to `0` to disable.
- **Merge conflicts** – The dispatcher creates a bead "Resolve merge conflict: ozon-wN". Resolve in the repo, then close that bead; the dispatcher will retry the merge.

More: [ORCHESTRATOR_README.md – Troubleshooting](ORCHESTRATOR_README.md#1-check-aiders-chat-history-per-worktree).
