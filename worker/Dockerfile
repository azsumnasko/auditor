FROM python:3.12-alpine

WORKDIR /app
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

COPY analytics_utils.py jira_analytics.py git_analytics.py octopus_analytics.py \
     cicd_analytics.py code_analytics.py merge_evidence.py score_engine.py \
     generate_dashboard.py generate_scorecard.py generate_report.py \
     generate_interview_prep.py insights_by_project.py ./

COPY worker/run_next_job.py /app/run_next_job.py

ENV DATA_DIR=/data

# Poll for pending jobs every 60s; run analytics for claimed job
CMD while true; do python /app/run_next_job.py; sleep 60; done
