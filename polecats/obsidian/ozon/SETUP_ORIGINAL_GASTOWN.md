# Set up the original Gas Town with a local model

This guide covers installing and using **[github.com/steveyegge/gastown](https://github.com/steveyegge/gastown)** (the original Gas Town) with a **local Ollama model** (Qwen) instead of Claude Code. Gas Town runs on **macOS/Linux or WSL**; the agent that does the coding is our **Aider + Ollama** wrapper script from this repo.

---

## 1. What you get

- **Town** – workspace (e.g. `~/gt/`) with Mayor, rigs, and config  
- **Rig** – your project (this repo or any git repo)  
- **Mayor** – AI coordinator; you tell it what to build, it creates convoys and slings work  
- **Polecats** – worker agents (in our setup: Aider + Qwen via `scripts/qwen-agent.sh`)  
- **Beads** – tasks (e.g. `gt-abc12`); created with `bd create`, assigned with `gt sling`  
- **Convoys** – batches of beads; track progress with `gt convoy list`

---

## 2. Prerequisites

From the [official Gas Town README](https://github.com/steveyegge/gastown#prerequisites):

| Component | Purpose |
|-----------|---------|
| **Go 1.23+** | Build `gt` (if installing from source) |
| **Git 2.25+** | Worktree support |
| **Dolt 1.82.4+** | [dolthub/dolt](https://github.com/dolthub/dolt) – Beads backend |
| **Beads (`bd`) 0.55.4+** | [steveyegge/beads](https://github.com/steveyegge/beads) – task ledger |
| **tmux 3.0+** | Recommended for Mayor and polecat sessions |
| **sqlite3** | Convoy DB (often pre-installed on macOS/Linux) |

For the **local model** instead of Claude:

| Component | Purpose |
|-----------|---------|
| **Ollama** | Run Qwen locally; [ollama.com](https://ollama.com) |
| **Aider** | Coding agent: `pip install aider-chat` |
| **Qwen model** | e.g. `ollama pull qwen2.5-coder:7b` or `ollama pull qwen3-coder:30b` |

Use **WSL** on Windows so you can run `gt`, `bd`, tmux, and the bash agent script.

---

## 2a. Use WSL on Windows

If you’re on Windows, use **Windows Subsystem for Linux (WSL)** so you have a real Linux environment for Gas Town, bash, and tmux.

### Install WSL

1. **Open PowerShell as Administrator** (right‑click Start → “Windows PowerShell (Admin)” or “Terminal (Admin)”).
2. **Install WSL** (this turns on the feature and installs Ubuntu by default):
   ```powershell
   wsl --install
   ```
3. **Restart** your PC if prompted.
4. **Launch Ubuntu** from the Start menu (or run `wsl` in a normal terminal). On first run you’ll create a Linux username and password.

**Requirements:** Windows 10 version 2004+ (Build 19041+) or Windows 11. See [Install WSL](https://learn.microsoft.com/en-us/windows/wsl/install) if you need manual steps or another distro.

### Use your repo from WSL

Your Windows drives are under `/mnt/`. For example, if this repo is at `C:\Work\ozon`:

- In WSL that path is: **`/mnt/c/Work/ozon`**

Use that path when adding the rig (from `~/gt`): `gt rig add ozon /mnt/c/Work/ozon --adopt`.

### Optional: Open the repo in WSL from VS Code/Cursor

In Cursor/VS Code: **File → Open Folder**, then enter `\\wsl$\Ubuntu\home\<your-username>\...` if you cloned the repo inside WSL, or open `C:\Work\ozon` and use the integrated terminal with **“WSL: Ubuntu”** (or your distro) so commands run in Linux.

### WSL: “Network is unreachable” to archive.ubuntu.com

If `sudo apt update` or `sudo apt install ...` fail with **Cannot initiate the connection to archive.ubuntu.com (2620:2d:... / 2a06:bc80:...) - connect (101: Network is unreachable)**, apt is trying **IPv6** and your network (or WSL) doesn’t have working IPv6.

**Fix: force apt to use IPv4 only.** In WSL (Ubuntu):

```bash
# Permanent fix (recommended)
echo 'Acquire::ForceIPv4 "true";' | sudo tee /etc/apt/apt.conf.d/99force-ipv4

# Then run update/install as usual
sudo apt-get update
sudo apt-get install -y build-essential procps curl file git
```

One-time only (no config file):

```bash
sudo apt-get -o Acquire::ForceIPv4=true update
sudo apt-get -o Acquire::ForceIPv4=true install -y build-essential procps curl file git
```

### WSL: “Connection timed out” to archive.ubuntu.com (no outbound internet)

If you see **Could not connect to archive.ubuntu.com:80 (91.189.x.x), connection timed out** (even after forcing IPv4), WSL has no working outbound internet to Ubuntu’s servers. Try the following in order.

**1. Check connectivity from WSL**

In WSL:

```bash
ping -c 2 8.8.8.8
curl -I --connect-timeout 5 https://archive.ubuntu.com
```

If both fail, the issue is WSL networking or something blocking WSL (firewall, VPN, corporate proxy).

**2. Fix WSL DNS (often helps)**

WSL sometimes gets a bad resolv.conf. In WSL:

```bash
echo "nameserver 8.8.8.8" | sudo tee /etc/resolv.conf
```

Then try `ping archive.ubuntu.com` and `sudo apt-get update` again. If your `/etc/resolv.conf` is overwritten on each boot, add to `~/.bashrc`: `sudo sed -i 's/nameserver.*/nameserver 8.8.8.8/' /etc/resolv.conf` and run it once per session, or configure your Windows network to hand out a working DNS.

**3. Corporate proxy**

If Windows uses an HTTP proxy for the internet, WSL doesn’t use it by default. In WSL, set (replace with your proxy host:port):

```bash
export http_proxy=http://proxy.company.com:8080
export https_proxy=http://proxy.company.com:8080
```

For apt only:

```bash
echo 'Acquire::http::Proxy "http://proxy.company.com:8080";' | sudo tee /etc/apt/apt.conf.d/80proxy
echo 'Acquire::https::Proxy "http://proxy.company.com:8080";' | sudo tee -a /etc/apt/apt.conf.d/80proxy
```

**4. Try another mirror**

Switch to a different Ubuntu mirror (e.g. a local or regional one). Edit sources in WSL:

```bash
sudo sed -i 's/archive.ubuntu.com/mirror.yandex.ru\/mirrors\/ubuntu/' /etc/apt/sources.list
sudo sed -i 's/security.ubuntu.com/mirror.yandex.ru\/mirrors\/ubuntu/' /etc/apt/sources.list
sudo apt-get update
```

(Other options: `mirrors.kernel.org`, or pick a mirror from [Ubuntu mirror list](https://launchpad.net/ubuntu/+cdmirrors).)

**5. Skip apt: install Go and Gas Town without apt**

If you can’t get apt working (e.g. firewall blocks WSL), you can still get `gt` and `bd` without installing any packages via apt:

- **Go:** Download the Linux amd64 tarball from [go.dev/dl](https://go.dev/dl/), extract to `~/go-install`, and add `~/go-install/go/bin` to PATH.
- **gt:** `go install github.com/steveyegge/gastown/cmd/gt@latest` (requires Go).
- **bd:** Install Beads per [steveyegge/beads](https://github.com/steveyegge/beads) (e.g. from release binary or `go install` if you have Go).
- **Dolt:** Download from [dolthub/dolt releases](https://github.com/dolthub/dolt/releases).

You already have **git** and **curl** in WSL. For Homebrew you’d need `build-essential` from apt; if apt never works, use the Go + pre-built binary path above and skip Homebrew.

---

## 3. Install Gas Town (`gt`)

Pick one. Run in **WSL** (or macOS/Linux).

### Option A: Homebrew (macOS/Linux / WSL)

If you don’t have Homebrew yet (e.g. in WSL):

**Install Homebrew (WSL/Ubuntu):**
```bash
# Dependencies
sudo apt-get update
sudo apt-get install -y build-essential procps curl file git

# Install Homebrew (run the official script)
/bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"

# Add to PATH (script prints the exact lines; typically):
echo 'eval "$(/home/linuxbrew/.linuxbrew/bin/brew shellenv)"' >> ~/.bashrc
eval "$(/home/linuxbrew/.linuxbrew/bin/brew shellenv)"
```

Then install Gas Town:
```bash
brew install gastown
```

### Option B: From source (Go)

```bash
go install github.com/steveyegge/gastown/cmd/gt@latest
```

Ensure `$HOME/go/bin` is on your PATH (e.g. in `~/.bashrc` or `~/.zshrc`):

```bash
export PATH="$PATH:$HOME/go/bin"
```

### Option C: Pre-built Windows binary (if you run `gt` natively on Windows)

From the [releases](https://github.com/steveyegge/gastown/releases), download the Windows build (e.g. `gastown_*_windows_amd64.zip`), unzip, and put `gt.exe` on your PATH. Note: the **Qwen agent script** (`scripts/qwen-agent.sh`) is bash; for a local model on native Windows you’d need a Windows equivalent or run `gt` and agents under WSL.

### Verify

```bash
gt version
```

---

## 4. Install Beads and Dolt

```bash
# Beads
go install github.com/steveyegge/beads/cmd/bd@latest
# or: irm https://raw.githubusercontent.com/steveyegge/beads/main/install.ps1 | iex  (PowerShell)

# Dolt (Beads backend) – see https://github.com/dolthub/dolt
# macOS: brew install dolt
# Linux: install from https://github.com/dolthub/dolt/releases
```

Ensure `bd` and `dolt` are on PATH. Then:

```bash
bd --version
```

---

## 5. Create the Gas Town workspace (HQ)

Create the town and go into it (dolt identity must be configured first; see earlier step):

```bash
mkdir -p ~/gt
gt install ~/gt --git
cd ~/gt
```

This creates the Town layout (mayor, rigs, config). You’ll run most `gt` commands from `~/gt` or from a rig directory.

---

## 6. Add your project as a rig

**Run this from the town directory (`~/gt`), not from inside the repo.** Add this repo using `--adopt` and the absolute path:

```bash
cd ~/gt
# Adopt existing repo (use your actual path)
gt rig add ozon /mnt/c/Work/ozon --adopt
# or if the repo is under your home:
# gt rig add ozon ~/ozon --adopt
```

List rigs:

```bash
gt rig list
```

---

## 7. Register the local-model agent (Qwen + Aider)

Gas Town’s default runtime is Claude Code. To use **Ollama + Qwen + Aider** instead, register the wrapper script from this repo.

1. **Copy the script into your PATH** (e.g. `~/bin`):

   ```bash
   mkdir -p ~/bin
   cp /mnt/c/Work/ozon/scripts/qwen-agent.sh ~/bin/
   chmod +x ~/bin/qwen-agent.sh
   ```

2. **Tell Gas Town to use it** (from `~/gt` or any rig):

   ```bash
   gt config agent set qwen "$HOME/bin/qwen-agent.sh"
   gt config default-agent qwen
   ```

3. **(Optional)** Use a different model or port:

   ```bash
   export QWEN_AGENT_MODEL=ollama/qwen3-coder:30b
   # If Ollama is on a custom port:
   export OLLAMA_API_BASE=http://127.0.0.1:31434
   ```

   Then run `gt sling` / Mayor in the same shell (or set these in your shell profile).

The script runs `gt prime` and `gt hook` to get the current task, then starts Aider with `--model` and `--message-file` so the agent executes the hooked bead and exits when done.

---

## 8. Create a crew workspace (optional)

For your own hands-on work inside the rig:

```bash
gt crew add nasko --rig ozon
cd ozon/crew/nasko

```

You can then work in this directory and use `gt` commands from here. Polecats run in separate worktrees managed by Gas Town.

---

## 9. Create work and run agents

### Start Ollama (separate terminal)

```bash
export OLLAMA_NUM_PARALLEL=14
ollama serve
```

### Create beads (tasks)

From the **rig** directory (e.g. `~/gt/ozon` or the repo root), or from Town with the rig in context:

```bash
cd ~/gt/ozon   # or your rig path
bd init        # if not already inited
bd create "Add a cycle time chart to the dashboard"
bd create "Fix WIP aging in jira_analytics.py"
bd ready       # list ready beads
```

### Assign work to agents (sling)

Each `gt sling` spawns a worker (polecat) that runs your default agent (the Qwen script). The worker gets the bead content via `gt hook` and runs Aider with that as the message.

```bash
# Sling one bead to the rig (any free polecat slot)
gt sling gt-abc12 ozon

# Sling several beads
gt sling gt-abc12 gt-def34 gt-ghi56 ozon
```

Replace `gt-abc12` etc. with real bead IDs from `bd ready` or `bd list`.

### Or use the Mayor (recommended)

The Mayor creates convoys and slings for you:

```bash
gt mayor attach
```

In the Mayor session, say something like:

- *"Create a convoy of tasks for adding a cycle time chart and fixing WIP aging, then sling them to ozon."*

The Mayor will create beads (and a convoy), then sling them to the rig. Each sling starts a worker running `qwen-agent.sh` (Aider + Qwen).

### Track progress

```bash
gt convoy list
gt agents
```

---

## 10. Quick reference (original Gas Town + local model)

| Goal | Command |
|------|--------|
| Install Gas Town | `brew install gastown` or `go install github.com/steveyegge/gastown/cmd/gt@latest` (requires Go that supports the module’s `go` version; see troubleshooting if you get "invalid go version") |
| Create workspace | `gt install ~/gt --git && cd ~/gt` |
| Add this repo as rig | From `~/gt`: `gt rig add ozon /mnt/c/Work/ozon --adopt` (or your path) |
| Use local Qwen agent | Copy `scripts/qwen-agent.sh` to `~/bin`, then `gt config agent set qwen "$HOME/bin/qwen-agent.sh"` and `gt config default-agent qwen` |
| Create tasks | In rig: `bd create "Task title"` |
| Assign work | `gt sling <bead-id> ozon` |
| Let Mayor coordinate | `gt mayor attach` and describe what you want |
| Track convoys | `gt convoy list` |

---

## 11. Troubleshooting

### Convoy / sling fails: "agent bead required for polecat tracking"

Daemon logs show: `creating agent bead after 10 attempts: bd create --json --id=oz-ozon-polecat-obsidian ...`. The daemon needs this agent bead in the **town** DB (not the rig). From the town root:

```bash
cd ~/gt
bd create --id oz-ozon-polecat-obsidian --title "Polecat obsidian for ozon" --description "Polecat obsidian agent for ozon" --type agent --labels "gt:agent"
```

If the output says **"Created issue in rig 'ozon'"**, the bead was created in the rig; the daemon looks in the town DB. Try creating it from a town-only directory so `bd` uses the town store (e.g. `cd ~/gt/mayor` then run the same `bd create`). If your routing sends all `oz-*` IDs to the rig, you may need to create the bead in the town store via Gas Town’s own tooling or check `gt doctor --fix` / beads docs.

If creation fails with a UNIQUE constraint (ID already exists in town), add the label only:

```bash
bd update oz-ozon-polecat-obsidian --add-label "gt:agent"
```

Then try `gt daemon start` again.

**If you see "duplicate primary key" from `~/gt/mayor`:** The bead already exists (e.g. in the rig). The daemon only needs it to exist somewhere; once it’s there, the "agent bead required for polecat tracking" error should stop and the daemon can start.

### Sling fails: "bead already has 1 attached molecule(s)"

Logs show: `sling oz-kff failed: Error: bead oz-kff already has 1 attached molecule(s): oz-nqm`. The bead is already attached to a molecule (handoff/session), so the convoy won’t sling it again. Options:

- **Inspect:** `bd show oz-kff` (and `bd show oz-nqm` if needed) to see status. If the work is done, close the bead: `bd close oz-kff`.
- **Convoy:** `gt convoy list` and `gt convoy show hq-cv-dppi6` (use the convoy ID from the logs). You may be able to skip this bead or land/dismiss the convoy so it stops retrying.
- **Fresh work:** Create a new bead and a new convoy for that bead; sling the new one instead.

### Daemon won't start / Deacon in crash loop

If logs say **"Deacon is in crash loop, skipping restart"**, the daemon has stopped restarting the Deacon. The logs suggest `gt daemon clear-backoff deacon`, but that subcommand is **not present** in the current CLI (even in a freshly built `gt` from latest gastown — `gt daemon --help` only shows logs, start, status, stop, enable-supervisor). So you have to work around it:

1. **Stop and start again:** `gt daemon stop`, wait a few seconds, then `gt daemon start`.
2. **Restart WSL** (or reboot) so any in-memory backoff state is cleared, then `gt daemon start`.
3. **Clear backoff state by hand (if the daemon still won't become "ready"):** The daemon may store backoff or Deacon state under `~/gt/.runtime` (e.g. in `pids/` or `locks/` subdirs) or in beads. From WSL run:
   ```bash
   ls -la ~/gt/.runtime
   ls -la ~/gt/.runtime/pids
   ls -la ~/gt/.runtime/locks
   ```
   **Stop the daemon** (`gt daemon stop`; if that says "not running", run `pkill -f "gt.*daemon"` to kill any stray process). Back up first: `cp -r ~/gt/.runtime ~/gt/.runtime.bak`. Then remove only files (not subdirs) if you want to clear pids/locks: `rm -f ~/gt/.runtime/pids/*` and `find ~/gt/.runtime/locks -type f -delete` (since `locks` may contain subdirectories like `sling`). Then run `gt daemon start` again. Note: clearing .runtime does not always fix Deacon backoff — the state may be in the beads DB; upgrading `gt` to a version with `gt daemon clear-backoff deacon` is then the reliable fix.

After the daemon is running, watch `gt daemon logs`; if the Deacon crashes again, the next lines usually show the cause (e.g. Dolt not reachable, permission). Fix that and try starting again.

For other daemon failures, run `gt daemon logs` and address what you see (port in use, permission, missing bead, etc.). If `gt daemon start` always fails, run it once then immediately `gt daemon logs` and read the **last** lines — that usually shows the reason (e.g. backoff, port, Dolt). If the logs show **"Daemon starting (PID ...)"** but the CLI still says "daemon failed to start", the process may have started and the CLI timed out waiting for readiness. Run `gt daemon status` — if it says the daemon is running, you can use `gt mayor attach`; if not, try restarting WSL and then `gt daemon start` again.

### "config file not found: .../mayor/rigs.json" or "Dolt server unreachable at 127.0.0.1:3307"

You are running `gt` from the **rig** directory (e.g. `/mnt/c/Work/ozon`) instead of the **town**. The town is where you ran `gt install ~/gt`; rigs and beads are configured there. Always run daemon and Mayor from the town:

```bash
cd ~/gt
gt daemon status
gt mayor attach
```

If you use `GT_RIG_ROOT` so the agent sees the rig code, set it in the same shell **after** you’re in the town: `cd ~/gt`, then `export GT_RIG_ROOT="$HOME/gt/ozon"`, then `gt mayor attach`.

### "model 'qwen2.5-coder:7b' not found" (Ollama / Aider)

The agent script defaults to `ollama/qwen2.5-coder:7b`. Either pull that model in WSL or use one you already have:

```bash
# Option A: pull the default model
ollama pull qwen2.5-coder:7b

# Option B: use another model (e.g. qwen3-coder:30b) without changing the script
export QWEN_AGENT_MODEL="ollama/qwen3-coder:30b"
gt mayor attach
```

If you copy the agent script to `~/bin/qwen-agent.sh`, you can also edit it and set `MODEL` (or leave it and set `QWEN_AGENT_MODEL` in the environment before starting Mayor).

### Mayor exits immediately after attach

If you see "daemon start failed" then "Mayor restarted with context" and then "[exited]", the Mayor session is exiting because the daemon is not running. Fix the daemon first: run `gt daemon logs` to see why it fails, address that (e.g. port in use, missing agent bead), then `gt daemon start` and `gt daemon status`. Once the daemon is running, run `gt mayor attach` again.

### go install gastown fails: "invalid go version '1.25.6': must match format 1.23"

The upstream `go.mod` declares `go 1.25.6` (v0.8.0) or `go 1.24.2` (v0.7.0); older Go toolchains only accept a two-part version (e.g. `1.23`). Building from source with `go 1.23` in go.mod can then fail with **"package cmp/slices/maps/log/slog is not in GOROOT"** — the code needs **Go 1.22+** standard library. So you need a newer Go.

**Fix: install Go 1.23+ in WSL**, then install gt:

```bash
# In WSL: download and install Go 1.23 (or 1.24) from go.dev
cd /tmp
wget -q https://go.dev/dl/go1.23.4.linux-amd64.tar.gz
sudo rm -rf /usr/local/go
sudo tar -C /usr/local -xzf go1.23.4.linux-amd64.tar.gz
export PATH="/usr/local/go/bin:$PATH"
export GOROOT=/usr/local/go
go version   # should show go1.23.4 or similar
```

Add to `~/.bashrc` or `~/.profile`: `export PATH="/usr/local/go/bin:$PATH"` and `export GOROOT=/usr/local/go` (if needed). Then either:

- **Build from source with patched go.mod:** clone gastown, set `go 1.23` in go.mod, run `go build -o ~/bin/gt ./cmd/gt`.
- Or try **`go install ...@latest`** again; Go 1.23 may still reject the `1.25.6` format, in which case the build-from-source approach with `go 1.23` in go.mod is the way to go.

**If you get "beads@v0.56.1 requires go >= 1.25.6 (running go 1.23.4)":** The beads dependency requires Go 1.25.6. Two options:

1. **Install Go 1.25** and build with the **unmodified** gastown (no sed on go.mod), so both gastown and beads get Go 1.25:
   ```bash
   cd /tmp
   wget -q https://go.dev/dl/go1.25.0.linux-amd64.tar.gz
   sudo rm -rf /usr/local/go && sudo tar -C /usr/local -xzf go1.25.0.linux-amd64.tar.gz
   export PATH="/usr/local/go/bin:$PATH"
   cd /tmp/gastown
   git checkout go.mod   # restore original go 1.25.6
   go build -o ~/bin/gt ./cmd/gt
   ```
   With Go 1.25.0, running `go build` may trigger an automatic download of the **go1.25.6** toolchain to satisfy beads; the build then completes and `~/bin/gt` works. If the toolchain still refuses, try a newer 1.25.x build if available at [go.dev/dl](https://go.dev/dl/).

2. **Stay on Go 1.23 and pin an older beads** that supports 1.23: in gastown’s `go.mod`, change the beads require to an older version (e.g. `v0.55.4`) and ensure that version’s `go.mod` uses `go 1.22` or `go 1.23`. Then run `go mod tidy` and `go build -o ~/bin/gt ./cmd/gt`. Compatibility is not guaranteed; if the code expects beads APIs that changed in 0.56, the build or runtime may fail.

### "no wisp config for ozon - parked state may have been lost"

Informational: parked state may have been lost. Usually safe to ignore; wisp config is recreated when sessions run.

---

## 12. Differences from this repo’s “Path B” (Windows dispatcher)

| Aspect | Original Gas Town (Path A) | This repo’s Path B |
|--------|----------------------------|---------------------|
| Where it runs | WSL (or macOS/Linux) | Windows (or any OS with Python) |
| Orchestrator | `gt` (Mayor, Witness, Refinery) | `dispatch_workers.py` |
| Work assignment | `gt sling` / Mayor | Dispatcher assigns from `bd ready` to fixed worktree slots |
| Agent | Your wrapper (e.g. `qwen-agent.sh`) | Aider invoked by dispatcher with `--message-file` |
| Merge / conflicts | Refinery + conflict beads | Dispatcher merge slot + “Resolve merge conflict” bead |

The **same** local model (Ollama + Qwen) and **same** agent tool (Aider) can be used in both: in Gas Town you plug them in via `gt config agent set qwen ...`; in Path B the dispatcher calls Aider with the model from `dispatch_config.json`.

For more on how this repo mirrors Gas Town (beads, convoys, merge handling), see [GASTOWN_HOW_IT_WORKS.md](GASTOWN_HOW_IT_WORKS.md).
