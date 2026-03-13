#!/usr/bin/env python3
"""
Poll SQLite for a pending job, run jira_analytics + generate_dashboard for that user.
Set env from config *before* importing jira_analytics (it reads env at import).
"""
import os
import sqlite3
import sys

DATA_DIR = os.environ.get("DATA_DIR", "/data")
DB_PATH = os.path.join(DATA_DIR, "app.db")


def claim_next_job(conn):
    conn.execute("BEGIN IMMEDIATE")
    try:
        cur = conn.execute(
            "SELECT id, user_id FROM jobs WHERE status = ? ORDER BY created_at ASC LIMIT 1",
            ("pending",),
        )
        row = cur.fetchone()
        if not row:
            conn.rollback()
            return None
        job_id, user_id = row[0], row[1]
        conn.execute("UPDATE jobs SET status = ?, updated_at = datetime('now') WHERE id = ?", ("running", job_id))
        conn.commit()
        return job_id, user_id
    except Exception:
        conn.rollback()
        raise


def get_config(conn, user_id):
    cur = conn.execute(
        "SELECT jira_base_url, jira_email, jira_token, jira_project_keys FROM config WHERE user_id = ?",
        (user_id,),
    )
    return cur.fetchone()


def set_job_done(conn, job_id):
    conn.execute("UPDATE jobs SET status = ?, updated_at = datetime('now') WHERE id = ?", ("done", job_id))
    conn.commit()


def set_job_failed(conn, job_id, error_message):
    conn.execute(
        "UPDATE jobs SET status = ?, updated_at = datetime('now'), error_message = ? WHERE id = ?",
        ("failed", error_message[:500] if error_message else None, job_id),
    )
    conn.commit()


def cleanup_stale_running_jobs(conn, stale_hours=1):
    """Mark jobs stuck in 'running' for too long as 'failed' so they can be retried."""
    conn.execute(
        """
        UPDATE jobs
        SET status = 'failed', updated_at = datetime('now'),
            error_message = ?
        WHERE status = 'running' AND updated_at < datetime('now', ?)
        """,
        (f"Stale (run exceeded {stale_hours} hour(s)); you can generate again.", f"-{stale_hours} hours"),
    )
    conn.commit()


def main():
    if not os.path.exists(DB_PATH):
        return 0
    conn = sqlite3.connect(DB_PATH)
    try:
        cleanup_stale_running_jobs(conn)
        row = claim_next_job(conn)
        if not row:
            return 0
        job_id, user_id = row
        config = get_config(conn, user_id)
        if not config:
            set_job_failed(conn, job_id, "No config for user")
            return 1
        jira_base_url, jira_email, jira_token, jira_project_keys = config
        output_dir = os.path.join(DATA_DIR, "users", str(user_id))
        os.makedirs(output_dir, exist_ok=True)
        os.environ["JIRA_BASE_URL"] = jira_base_url
        os.environ["JIRA_EMAIL"] = jira_email
        os.environ["JIRA_TOKEN"] = jira_token
        os.environ["JIRA_PROJECT_KEYS"] = jira_project_keys
        os.environ["OUTPUT_DIR"] = output_dir
        # Do not set DOTENV_PATH so jira_analytics uses env vars we just set
        sys.path.insert(0, "/app")
        import jira_analytics
        import generate_dashboard
        try:
            jira_analytics.main()
            generate_dashboard.main()
            set_job_done(conn, job_id)
        except Exception as e:
            set_job_failed(conn, job_id, str(e))
            raise
    finally:
        conn.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
