#!/usr/bin/env bash
# Gas Town custom agent wrapper: runs gt prime + gt hook, then Aider with local Qwen (Ollama).
# Use from WSL after: gt config agent set qwen "$HOME/bin/qwen-agent.sh" && gt config default-agent qwen
# Requires: gt, bd, aider-chat, Ollama. Default model: qwen2.5-coder:7b (set QWEN_AGENT_MODEL to override).
# If Ollama runs on Windows and the agent runs in WSL, the script auto-detects and uses the Windows host for OLLAMA_API_BASE.
# For rig work (so Aider sees your code): export GT_RIG_ROOT="$HOME/gt/ozon" before gt mayor attach

set -e
# gt/tmux often runs with minimal PATH; ensure common locations are checked
export PATH="${HOME}/.local/bin:${PATH}"
# Point Aider at local Ollama (gt-launched sessions may not inherit your env).
# If unset and we're in WSL, use Windows host so Ollama running on Windows is reachable.
if [ -z "$OLLAMA_API_BASE" ]; then
  if [ -f /proc/version ] && grep -qi microsoft /proc/version 2>/dev/null; then
    WSL_HOST=$(grep -m1 nameserver /etc/resolv.conf 2>/dev/null | awk '{print $2}')
    [ -n "$WSL_HOST" ] && export OLLAMA_API_BASE="http://${WSL_HOST}:11434"
  fi
  export OLLAMA_API_BASE="${OLLAMA_API_BASE:-http://127.0.0.1:11434}"
fi

# Use $1 as directory only if it looks like a path (gt sometimes passes a long message as $1).
# Prefer GT_RIG_ROOT when set so Aider sees the rig repo (e.g. ozon code), not the town (0 files).
AGENT_DIR="."
if [ -n "$GT_RIG_ROOT" ] && [ -d "$GT_RIG_ROOT" ]; then
  AGENT_DIR="$GT_RIG_ROOT"
elif [ -n "$1" ] && [ "${#1}" -lt 512 ] && [ -d "$1" ]; then
  AGENT_DIR="$1"
elif [ -n "$GT_TOWN_ROOT" ] && [ -d "$GT_TOWN_ROOT" ]; then
  AGENT_DIR="$GT_TOWN_ROOT"
fi
cd "$AGENT_DIR"

# Find aider
if [ -n "$AIDER_CMD" ]; then
  AIDER="$AIDER_CMD"
elif command -v aider >/dev/null 2>&1; then
  AIDER=aider
elif [ -x "$HOME/.local/bin/aider" ]; then
  AIDER="$HOME/.local/bin/aider"
else
  AIDER="python3 -m aider_chat"
fi

HOOK_FILE=".current_hook.txt"
MODEL="${QWEN_AGENT_MODEL:-ollama/qwen2.5-coder:7b}"

# Gas Town context: role + hooked work (GUPP: if work on hook, run it)
( gt prime 2>/dev/null; gt hook 2>/dev/null ) > "$HOOK_FILE" || true

# Suppress OLLAMA_API_BASE warning (we set it above)
AIDER_OPTS="--no-show-model-warnings"
if [ ! -s "$HOOK_FILE" ]; then
  echo "No hook content; waiting for work. Run gt sling <bead-id> <rig> to assign work."
  exec $AIDER $AIDER_OPTS --model "$MODEL"
fi

exec $AIDER $AIDER_OPTS --model "$MODEL" --message-file "$HOOK_FILE"
