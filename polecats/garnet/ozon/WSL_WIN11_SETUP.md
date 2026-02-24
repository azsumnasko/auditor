# WSL on Windows 11 — Setup Plan

A step-by-step plan to get WSL (Windows Subsystem for Linux) running on Windows 11 with everything you need for development.

---

## 1. Prerequisites

- **Windows 11** (build 22000 or later)
- **Administrator** access
- **Virtualization** enabled in BIOS (usually already on; check in Task Manager → Performance → CPU → "Virtualization: Enabled")

---

## 2. Enable WSL

### Option A — Recommended (single command)

Open **PowerShell as Administrator** and run:

```powershell
wsl --install
```

This enables:
- WSL 2
- Virtual Machine Platform
- Default Linux distro (Ubuntu)

Restart when prompted.

### Option B — Manual

If you prefer to enable components yourself:

```powershell
dism.exe /online /enable-feature /featurename:Microsoft-Windows-Subsystem-Linux /all /norestart
dism.exe /online /enable-feature /featurename:VirtualMachinePlatform /all /norestart
```

Restart, then set WSL 2 as default:

```powershell
wsl --set-default-version 2
```

---

## 3. Install a Linux Distribution

After reboot:

```powershell
wsl --install
```

Or install a specific distro from the Store or CLI:

```powershell
wsl --list --online
wsl --install -d Ubuntu
# or: Ubuntu-22.04, Debian, Fedora, etc.
```

Set default distro:

```powershell
wsl --set-default Ubuntu
```

---

## 4. First-Time Linux Setup

1. Launch your distro from Start menu or: `wsl`
2. Create a **username** and **password** when prompted
3. Update packages:

```bash
sudo apt update && sudo apt upgrade -y
```

---

## 5. Sessions and password (logging in)

You **don’t log in** each time you start WSL. Opening the distro or running `wsl` starts a session as your user automatically.

- **Start WSL again**: Start menu → Ubuntu (or your distro), or in any terminal run `wsl` or `wsl -d Ubuntu`. No username/password is asked.
- **When the password is used**: Only when a command needs **sudo** (e.g. `sudo apt install …`). Type your WSL user password and press Enter (nothing appears as you type).

### Forgot your WSL password?

1. Open **PowerShell** (no need for Admin).
2. Start WSL as root (replace `Ubuntu` with your distro name if different):
   ```powershell
   wsl -d Ubuntu -u root
   ```
3. Set a new password (replace `YourUsername` with your WSL username):
   ```bash
   passwd YourUsername
   ```
4. Enter the new password twice, then exit:
   ```bash
   exit
   ```
Use the new password whenever `sudo` asks for it.

---

## 6. Essential Tools Inside WSL

Install common dev tools in your WSL distro:

```bash
# Build essentials
sudo apt install -y build-essential git curl wget

# Optional but useful
sudo apt install -y ripgrep fd-find fzf tree jq
```

For **Python** (if you use it, e.g. with this repo):

```bash
sudo apt install -y python3 python3-pip python3-venv
# or use pyenv for version management
```

For **Node.js** (optional):

```bash
curl -fsSL https://deb.nodesource.com/setup_lts.x | sudo -E bash -
sudo apt install -y nodejs
```

---

## 7. Accessing Windows Files from WSL

- Windows drives are under `/mnt/`: e.g. `C:\` → `/mnt/c/`
- Your project: `c:\Work\ozon` → `/mnt/c/Work/ozon`

Best practice: keep project files either **all on Windows** (and use from WSL via `/mnt/c/...`) or **all in WSL** (e.g. `~/projects`) for better performance. Mixing is fine but Linux filesystem under WSL is faster.

---

## 8. Accessing WSL from Windows

- **File Explorer**: address bar → `\\wsl$\Ubuntu\home\<user>\`
- **VS Code / Cursor**: install "WSL" extension, then "Open Folder in WSL" or `code .` from WSL
- **Terminal**: Windows Terminal has a "Ubuntu" profile; or run `wsl` in PowerShell/CMD

---

## 9. Windows Terminal (Recommended)

1. Install **Windows Terminal** from Microsoft Store (or `winget install Microsoft.WindowsTerminal`)
2. Add a WSL profile: Settings → Add new → Profile → Command line: `wsl.exe -d Ubuntu`
3. Set it as default if you like

---

## 10. Useful WSL Commands (from PowerShell/CMD)

| Command | Description |
|--------|-------------|
| `wsl` | Start default distro |
| `wsl -d Ubuntu` | Start specific distro |
| `wsl --list --verbose` | List distros and versions |
| `wsl --shutdown` | Stop all WSL instances |
| `wsl --set-default-version 2` | Use WSL 2 by default |
| `wsl -e bash -c "command"` | Run a single Linux command |

---

## 11. Optional: Docker with WSL 2

- Install **Docker Desktop for Windows**
- Settings → Resources → WSL integration → enable integration with your distro
- Docker CLI and daemon can run in Windows; use `docker` from WSL terminal with same daemon

---

## 12. Optional: GPU / GUI Apps (WSLg)

Windows 11 supports **WSLg**: Linux GUI apps work without extra setup. Install a GUI app in WSL (e.g. `sudo apt install gedit`) and run it; the window appears on Windows.

---

## 13. Quick Checklist

- [ ] WSL 2 installed (`wsl --install` + reboot)
- [ ] Ubuntu (or other distro) installed and first-run (user/password)
- [ ] `sudo apt update && sudo apt upgrade`
- [ ] `build-essential`, `git`, `curl` installed
- [ ] Python/Node (or other runtimes) if needed
- [ ] Windows Terminal with WSL profile
- [ ] Cursor/VS Code WSL extension if you code in WSL
- [ ] Know paths: `/mnt/c/` = C:\, `\\wsl$\` = WSL from Windows

---

## 14. Troubleshooting

- **"WSL 2 requires an update to its kernel component"**: Download and install [WSL2 Linux kernel update](https://aka.ms/wsl2kernel).
- **Slow file access**: Prefer storing projects under WSL home (e.g. `~/projects`) instead of `/mnt/c/` when performance matters.
- **Networking issues**: WSL 2 uses a virtual NIC; localhost forwarding works. For firewall/port issues, check Windows Firewall and WSL docs.
- **Forgot WSL password**: See [§5 Sessions and password](#5-sessions-and-password-logging-in) for reset steps (`wsl -d Ubuntu -u root` then `passwd YourUsername`).
- **Reset distro**: `wsl --unregister Ubuntu` (deletes that distro and its data; reinstall with `wsl --install -d Ubuntu`).

---

You’re set once you can open `wsl`, run `ls /mnt/c/Work/ozon`, and use your usual dev tools from the WSL shell or via Cursor/VS Code in WSL.
