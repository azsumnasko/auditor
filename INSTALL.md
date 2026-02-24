# Install: Gas Town concept + Beads (Windows)

Install these so you can run the full concept: **Beads** (task ledger), **Python**, **Ollama** + Qwen, **Aider**, and optionally **Git** (for worktrees). You can also run **without Beads** using a file-based task queue (see below).

---

## 1. Beads (`bd`) – task ledger (optional but recommended)

Beads is the git-backed task tracker that powers the Gas Town workflow. Install **one** of the following.

### Option A: PowerShell (Windows, recommended)

Run in PowerShell (as a one-time install):

```powershell
irm https://raw.githubusercontent.com/steveyegge/beads/main/install.ps1 | iex
```

Then **restart your terminal** (or open a new one) so `bd` is on PATH.

### Option B: npm (if you have Node.js)

```powershell
npm install -g @beads/bd
```

After install, `bd` may be at `%AppData%\npm\bd.cmd` or in your npm global bin; ensure that folder is on PATH.

### Option C: Go

If you have [Go](https://go.dev/dl/) installed:

```powershell
go install github.com/steveyegge/beads/cmd/bd@latest
```

Add Go’s bin directory to PATH (e.g. `%USERPROFILE%\go\bin`). Then run `bd --version` to confirm.

### After installing Beads

In your repo (e.g. `c:\Work\ozon`):

```powershell
cd c:\Work\ozon
bd init
```

Then create tasks with `bd create "Task title"`. The dispatcher will use `bd ready` to feed work to workers.

---

## 2. Run without Beads (file-based queue)

If you don’t install Beads, the dispatcher still works:

1. Do **not** run `bd init`.
2. Run from the repo root:

   ```powershell
   py dispatch_workers.py
   ```

   (Or `python dispatch_workers.py` if `py` is not available.)

The first run creates **`task_queue.json`** in the repo and seeds it with the tasks from [BEADS_FOR_ANALYSIS.md](BEADS_FOR_ANALYSIS.md). Workers pull from this file instead of Beads. You can edit `task_queue.json` to add or remove tasks (each task has `id`, `title`, `status`: `pending` / `in_progress` / `done`).

---

## 3. Python

You need Python 3 to run `dispatch_workers.py`.

- **Windows**: Install from [python.org](https://www.python.org/downloads/) and check “Add Python to PATH”, or use the Microsoft Store “Python 3.12”.
- In a new terminal, run:
  - `py dispatch_workers.py` (Python Launcher, common on Windows), or
  - `python dispatch_workers.py` or `python3 dispatch_workers.py` if that’s what’s on your PATH.

If you see “Python was not found”, either reinstall and select “Add to PATH” or use the full path to `python.exe` (e.g. `& "$env:LOCALAPPDATA\Programs\Python\Python312\python.exe" dispatch_workers.py`).

---

## 4. Ollama + Qwen (for local agents)

1. Install [Ollama for Windows](https://ollama.com).
2. In a terminal: `ollama pull qwen2.5-coder:7b`.
3. For 14 concurrent agents, set before starting Ollama (e.g. in the same terminal or System env vars):
   ```powershell
   $env:OLLAMA_NUM_PARALLEL = 14
   ollama serve
   ```

### If you see "bind: access forbidden" (port blocked)

Windows often reserves port ranges (e.g. for Hyper-V/WSL), so Ollama can't bind to 11434 (or nearby ports). Fix it in one of these ways:

**Option A – Use a port outside the reserved range**

1. In **PowerShell (Run as Administrator)** see reserved ranges:
   ```powershell
   netsh interface ipv4 show excludedportrange protocol=tcp
   ```
2. Pick a port **not** in any range (e.g. **31434** or **50001**). Set it and start Ollama:
   ```powershell
   $env:OLLAMA_HOST = "127.0.0.1:31434"
   ollama serve
   ```
   Leave that window open. In a **new** terminal (with the same `OLLAMA_HOST` set if needed):
   ```powershell
   $env:OLLAMA_HOST = "127.0.0.1:31434"
   ollama pull qwen2.5-coder:7b
   ```
3. When running the dispatcher, point Aider at Ollama on that port:
   ```powershell
   $env:OLLAMA_HOST = "127.0.0.1:31434"
   $env:OLLAMA_API_BASE = "http://127.0.0.1:31434"
   py dispatch_workers.py
   ```

**Option B – Free the default port (may affect WSL/Hyper-V)**

In **PowerShell (Run as Administrator)**:
```powershell
net stop winnat
```
Then start Ollama (no need to set `OLLAMA_HOST`). After reboot, WinNAT may reserve ports again; repeat if needed.

---

## 5. Aider (coding agent CLI)

```powershell
pip install aider-chat
```

Ensure `aider` is on PATH (same place as `pip`). Run `aider --version` to confirm.

---

## 6. Git (for worktrees)

The dispatcher uses `git worktree add` to create one directory per worker (e.g. `c:\Work\ozon-w1` … `ozon-w14`). Install [Git for Windows](https://git-scm.com/download/win) if you don’t have it.

---

## Quick checklist

| Component | Required for full concept | How to verify |
|-----------|---------------------------|----------------|
| Beads (`bd`) | Optional (use file queue otherwise) | `bd --version` |
| Python      | Yes                       | `py --version` or `python --version` |
| Ollama      | Yes (for local Qwen)      | `ollama list` |
| Aider       | Yes                       | `aider --version` |
| Git         | Yes (for worktrees)       | `git --version` |

After installation: with Beads, run `bd init` then `bd create "..."` and `py dispatch_workers.py`. Without Beads, run `py dispatch_workers.py` and it will create and use `task_queue.json`.

---

## 7. Gas Town CLI (`gt`) – optional, for Mayor/convoys

Only needed if you want **Path A** (Mayor, `gt sling`, convoys). For a full Path A setup with the original [Gas Town](https://github.com/steveyegge/gastown) and a local model, see [SETUP_ORIGINAL_GASTOWN.md](SETUP_ORIGINAL_GASTOWN.md). On Windows without WSL: **`go install ...@latest` does not work** (repo’s go.mod has `replace` directives). **`npm install -g @gastown/gt` returns 404** (package not published).

Use one of these:

- **Pre-built Windows binary (recommended):**  
  1. Download: [gastown_0.7.0_windows_amd64.zip](https://github.com/steveyegge/gastown/releases/download/v0.7.0/gastown_0.7.0_windows_amd64.zip)  
  2. Unzip, then move the `gt.exe` (or `gt`) inside to a folder on your PATH (e.g. `C:\Users\YourName\bin` and add that to PATH).  
  3. In a new terminal: `gt --version`
- **Build from source:** `git clone https://github.com/steveyegge/gastown.git` → `cd gastown` → `go build -o gt.exe ./cmd/gt` → move `gt.exe` to a folder on PATH.

If you don’t need the Mayor, use **Path B**: `py split_task.py "Goal"` and `py dispatch_workers.py` (see [GASTOWN_HOW_IT_WORKS.md](GASTOWN_HOW_IT_WORKS.md)).
