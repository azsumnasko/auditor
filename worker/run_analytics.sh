#!/bin/sh
set -e
export PATH="/usr/local/bin:$PATH"
export DOTENV_PATH=/data/.env
export OUTPUT_DIR=/data
cd /app
if [ -f /data/.env ]; then
  python jira_analytics.py && python generate_dashboard.py
else
  echo "No /data/.env yet; skip analytics run."
fi
