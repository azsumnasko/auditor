#!/usr/bin/env bash
# Gas Town custom agent wrapper: runs gt prime + gt hook, then Aider with local Qwen (Ollama).
# Use from WSL after: gt config agent set qwen "$HOME/bin/qwen-agent.sh" && gt config default-agent qwen
# Requires: gt, bd, aider-chat, Ollama with qwen2.5-coder (e.g. ollama pull qwen2.5-coder:7b)

set -e
AGENT_DIR="${1:-.}"
cd "$AGENT_DIR"

HOOK_FILE=".current_hook.txt"
MODEL="${QWEN_AGENT_MODEL:-ollama/qwen2.5-coder:7b}"

# Gas Town context: role + hooked work (GUPP: if work on hook, run it)
( gt prime 2>/dev/null; gt hook 2>/dev/null ) > "$HOOK_FILE" || true

if [ ! -s "$HOOK_FILE" ]; then
  echo "No hook content; waiting for work. Run gt sling <bead-id> <rig> to assign work."
  # Still start Aider so user/agent can check mail or get work
  exec aider --model "$MODEL"
fi

# Run Aider with hook as initial instruction (execute work, then exit when done)
exec aider --model "$MODEL" --message-file "$HOOK_FILE"
