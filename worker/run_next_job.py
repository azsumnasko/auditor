#!/usr/bin/env python3
"""
Poll SQLite for a pending job, run jira_analytics + generate_dashboard for that user.
Set env from config *before* importing jira_analytics (it reads env at import).
"""
import logging
import os
import sqlite3
import sys

_USER_TEXT_MAX = 300  # max length for warning snippets and UI progress lines
_REPO_ROOT = os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))


def _append_stage_warning(warnings: list, stage: str, exc: BaseException) -> None:
    msg = (str(exc).strip() or type(exc).__name__)
    if len(msg) > _USER_TEXT_MAX:
        msg = msg[:_USER_TEXT_MAX] + "…"
    warnings.append(f"{stage}: {msg}")

DATA_DIR = os.environ.get("DATA_DIR", "/data")
DB_PATH = os.path.join(DATA_DIR, "app.db")


class ProgressLabel:
    """User-facing progress strings (single source; keep in sync with pipeline order)."""

    JIRA = "Fetching Jira data…"
    GIT_ANALYZE = "Analyzing Git repositories…"
    GIT_SKIP = "Skipping Git analytics (not configured)…"
    OCTOPUS_ANALYZE = "Analyzing Octopus Deploy…"
    OCTOPUS_SKIP_GIT = "Skipping Octopus (Git token and org required)…"
    OCTOPUS_SKIP_CFG = "Skipping Octopus (not configured)…"
    CICD_ANALYZE = "Analyzing CI/CD…"
    CICD_SKIP = "Skipping CI/CD (not configured)…"
    MERGE = "Merging evidence…"
    SCORES = "Computing scores…"
    DASHBOARD = "Building dashboard…"
    SCORECARD = "Generating scorecard…"
    REPORT = "Generating report…"
    INTERVIEW = "Generating interview prep…"
    INSIGHTS = "Generating project insights…"


def ensure_jobs_schema(conn):
    """Match Node `initSchema`: add `progress_message` if the DB predates it (worker may run first)."""
    cur = conn.execute("PRAGMA table_info(jobs)")
    cols = {row[1] for row in cur.fetchall()}
    if "progress_message" not in cols:
        conn.execute("ALTER TABLE jobs ADD COLUMN progress_message TEXT")
        conn.commit()


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


def set_job_progress(conn, job_id, message):
    if message is None:
        return
    text = str(message).strip()
    if not text:
        return
    if len(text) > _USER_TEXT_MAX:
        text = text[:_USER_TEXT_MAX] + "…"
    conn.execute(
        "UPDATE jobs SET progress_message = ?, updated_at = datetime('now') WHERE id = ?",
        (text, job_id),
    )
    conn.commit()


def set_job_done(conn, job_id):
    conn.execute(
        "UPDATE jobs SET status = ?, updated_at = datetime('now'), progress_message = NULL WHERE id = ?",
        ("done", job_id),
    )
    conn.commit()


def set_job_failed(conn, job_id, error_message):
    conn.execute(
        "UPDATE jobs SET status = ?, updated_at = datetime('now'), error_message = ?, progress_message = NULL WHERE id = ?",
        ("failed", error_message[:500] if error_message else None, job_id),
    )
    conn.commit()


def cleanup_stale_running_jobs(conn, stale_hours=1):
    """Mark jobs stuck in 'running' for too long as 'failed' so they can be retried."""
    conn.execute(
        """
        UPDATE jobs
        SET status = 'failed', updated_at = datetime('now'),
            error_message = ?, progress_message = NULL
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
        try:
            conn.execute("PRAGMA journal_mode=WAL")
        except sqlite3.Error:
            pass
        ensure_jobs_schema(conn)
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

        for p in ("/app", _REPO_ROOT):
            if p not in sys.path:
                sys.path.insert(0, p)

        try:
            logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
            pipeline_warnings: list[str] = []

            set_job_progress(conn, job_id, ProgressLabel.JIRA)
            # 1. Jira analytics (always — failure fails the job)
            import jira_analytics
            jira_analytics.main()

            # 2. Git analytics (optional)
            if git_token and git_org:
                set_job_progress(conn, job_id, ProgressLabel.GIT_ANALYZE)
                try:
                    import git_analytics
                    git_analytics.main()
                except Exception as e:
                    logging.exception("git_analytics failed")
                    _append_stage_warning(pipeline_warnings, "git_analytics", e)
            else:
                set_job_progress(conn, job_id, ProgressLabel.GIT_SKIP)

            # 3. Octopus Deploy analytics (optional; needs Git for compare)
            if octopus_url and octopus_key:
                if not git_token or not git_org:
                    pipeline_warnings.append(
                        "octopus_deploy: skipped (GIT_TOKEN and GIT_ORG are required for Octopus analytics)"
                    )
                    set_job_progress(conn, job_id, ProgressLabel.OCTOPUS_SKIP_GIT)
                else:
                    set_job_progress(conn, job_id, ProgressLabel.OCTOPUS_ANALYZE)
                    try:
                        import octopus_analytics
                        octopus_analytics.main()
                    except Exception as e:
                        logging.exception("octopus_analytics failed")
                        _append_stage_warning(pipeline_warnings, "octopus_analytics", e)
            else:
                set_job_progress(conn, job_id, ProgressLabel.OCTOPUS_SKIP_CFG)

            # 4. CI/CD analytics (optional)
            if cicd_provider != "none":
                set_job_progress(conn, job_id, ProgressLabel.CICD_ANALYZE)
                try:
                    import cicd_analytics
                    cicd_analytics.main()
                except Exception as e:
                    logging.exception("cicd_analytics failed")
                    _append_stage_warning(pipeline_warnings, "cicd_analytics", e)
            else:
                set_job_progress(conn, job_id, ProgressLabel.CICD_SKIP)

            from analytics_utils import write_json

            write_json({"warnings": pipeline_warnings}, "pipeline_warnings", output_dir)

            set_job_progress(conn, job_id, ProgressLabel.MERGE)
            # 5. Merge evidence (always -- works with whatever data is available)
            import merge_evidence
            merge_evidence.main()

            set_job_progress(conn, job_id, ProgressLabel.SCORES)
            # 6. Score engine
            import score_engine
            score_engine.main()

            set_job_progress(conn, job_id, ProgressLabel.DASHBOARD)
            # 7. Output generators
            import generate_dashboard
            generate_dashboard.main()

            set_job_progress(conn, job_id, ProgressLabel.SCORECARD)
            import generate_scorecard
            generate_scorecard.main()

            set_job_progress(conn, job_id, ProgressLabel.REPORT)
            import generate_report
            generate_report.main()

            set_job_progress(conn, job_id, ProgressLabel.INTERVIEW)
            import generate_interview_prep
            generate_interview_prep.main()

            set_job_progress(conn, job_id, ProgressLabel.INSIGHTS)
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
