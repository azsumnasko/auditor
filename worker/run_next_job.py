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
    cur = conn.execute("SELECT * FROM config WHERE user_id = ?", (user_id,))
    row = cur.fetchone()
    if not row:
        return None
    cols = [desc[0] for desc in cur.description]
    return dict(zip(cols, row))


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
        output_dir = os.path.join(DATA_DIR, "users", str(user_id))
        os.makedirs(output_dir, exist_ok=True)
        os.environ["OUTPUT_DIR"] = output_dir

        # Clear any leftover env from a prior run (defensive)
        for _key in ("GIT_TOKEN", "GIT_PROVIDER", "GIT_ORG", "GIT_BASE_URL", "GIT_REPOS",
                      "OCTOPUS_SERVER_URL", "OCTOPUS_API_KEY", "OCTOPUS_ENVIRONMENT", "OCTOPUS_REPO_MAP",
                      "CICD_PROVIDER", "CICD_DEPLOY_WORKFLOW", "REPO_CONFIG"):
            os.environ.pop(_key, None)

        # Jira config (always required)
        os.environ["JIRA_BASE_URL"] = config["jira_base_url"]
        os.environ["JIRA_EMAIL"] = config["jira_email"]
        os.environ["JIRA_TOKEN"] = config["jira_token"]
        os.environ["JIRA_PROJECT_KEYS"] = config["jira_project_keys"]

        # Git config
        git_token = config.get("git_token") or ""
        git_org = config.get("git_org") or ""
        if git_token:
            os.environ["GIT_TOKEN"] = git_token
            os.environ["GIT_PROVIDER"] = config.get("git_provider") or "github"
            os.environ["GIT_ORG"] = git_org
            if config.get("git_base_url"):
                os.environ["GIT_BASE_URL"] = config["git_base_url"]
            os.environ["GIT_REPOS"] = config.get("git_repos") or "*"

        # Repo config (shared by git_analytics, octopus_analytics, cicd_analytics)
        repo_config_json = config.get("repo_config") or ""
        if repo_config_json:
            os.environ["REPO_CONFIG"] = repo_config_json

        # Octopus config
        octopus_url = config.get("octopus_server_url") or ""
        octopus_key = config.get("octopus_api_key") or ""
        if octopus_url and octopus_key:
            os.environ["OCTOPUS_SERVER_URL"] = octopus_url
            os.environ["OCTOPUS_API_KEY"] = octopus_key
            os.environ["OCTOPUS_ENVIRONMENT"] = config.get("octopus_environment") or "Ontario"
            if config.get("octopus_repo_map"):
                os.environ["OCTOPUS_REPO_MAP"] = config["octopus_repo_map"]

        # CI/CD config
        cicd_provider = config.get("cicd_provider") or "none"
        if cicd_provider != "none":
            os.environ["CICD_PROVIDER"] = cicd_provider
            if config.get("cicd_deploy_workflow"):
                os.environ["CICD_DEPLOY_WORKFLOW"] = config["cicd_deploy_workflow"]

        sys.path.insert(0, "/app")
        try:
            # 1. Jira analytics (always)
            import jira_analytics
            jira_analytics.main()

            # 2. Git analytics (if configured)
            if git_token and git_org:
                import git_analytics
                git_analytics.main()

            # 3. Octopus Deploy analytics (if configured)
            if octopus_url and octopus_key:
                import octopus_analytics
                octopus_analytics.main()

            # 4. CI/CD analytics (if configured)
            if cicd_provider != "none":
                import cicd_analytics
                cicd_analytics.main()

            # 5. Merge evidence (always -- works with whatever data is available)
            import merge_evidence
            merge_evidence.main()

            # 6. Score engine
            import score_engine
            score_engine.main()

            # 7. Output generators
            import generate_dashboard
            generate_dashboard.main()

            import generate_scorecard
            generate_scorecard.main()

            import generate_report
            generate_report.main()

            import generate_interview_prep
            generate_interview_prep.main()

            import insights_by_project
            insights_by_project.main()

            set_job_done(conn, job_id)
        except Exception as e:
            set_job_failed(conn, job_id, str(e))
            raise
    finally:
        conn.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
