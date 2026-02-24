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
gt crew add yourname --rig ozon
cd ozon/crew/yourname
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
| Install Gas Town | `brew install gastown` or `go install github.com/steveyegge/gastown/cmd/gt@latest` |
| Create workspace | `gt install ~/gt --git && cd ~/gt` |
| Add this repo as rig | From `~/gt`: `gt rig add ozon /mnt/c/Work/ozon --adopt` (or your path) |
| Use local Qwen agent | Copy `scripts/qwen-agent.sh` to `~/bin`, then `gt config agent set qwen "$HOME/bin/qwen-agent.sh"` and `gt config default-agent qwen` |
| Create tasks | In rig: `bd create "Task title"` |
| Assign work | `gt sling <bead-id> ozon` |
| Let Mayor coordinate | `gt mayor attach` and describe what you want |
| Track convoys | `gt convoy list` |

---

## 11. Differences from this repo’s “Path B” (Windows dispatcher)

| Aspect | Original Gas Town (Path A) | This repo’s Path B |
|--------|----------------------------|---------------------|
| Where it runs | WSL (or macOS/Linux) | Windows (or any OS with Python) |
| Orchestrator | `gt` (Mayor, Witness, Refinery) | `dispatch_workers.py` |
| Work assignment | `gt sling` / Mayor | Dispatcher assigns from `bd ready` to fixed worktree slots |
| Agent | Your wrapper (e.g. `qwen-agent.sh`) | Aider invoked by dispatcher with `--message-file` |
| Merge / conflicts | Refinery + conflict beads | Dispatcher merge slot + “Resolve merge conflict” bead |

The **same** local model (Ollama + Qwen) and **same** agent tool (Aider) can be used in both: in Gas Town you plug them in via `gt config agent set qwen ...`; in Path B the dispatcher calls Aider with the model from `dispatch_config.json`.

For more on how this repo mirrors Gas Town (beads, convoys, merge handling), see [GASTOWN_HOW_IT_WORKS.md](GASTOWN_HOW_IT_WORKS.md).
