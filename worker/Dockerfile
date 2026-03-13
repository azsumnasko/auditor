FROM python:3.12-alpine

WORKDIR /app
COPY requirements.txt jira_analytics.py generate_dashboard.py ./
RUN pip install --no-cache-dir -r requirements.txt

COPY worker/run_next_job.py /app/run_next_job.py

ENV DATA_DIR=/data

# Poll for pending jobs every 60s; run analytics for claimed job
CMD while true; do python /app/run_next_job.py; sleep 60; done
