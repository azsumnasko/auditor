#!/usr/bin/env python3
"""
Poll SQLite for a pending job, run jira_analytics + generate_dashboard for that user.
Set env from config *before* importing jira_analytics (it reads env at import).
"""
import logging
import os
import socket
import sqlite3
import sys
import uuid

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
    CODE_ANALYZE = "Analyzing code quality…"
    CODE_SKIP = "Skipping code analytics (not configured)…"
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


def ensure_worker_instances_schema(conn):
    """Match Node: worker heartbeats for admin visibility and stop/resume."""
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS worker_instances (
            id TEXT PRIMARY KEY,
            hostname TEXT NOT NULL,
            first_seen TEXT NOT NULL DEFAULT (datetime('now')),
            last_seen TEXT NOT NULL DEFAULT (datetime('now')),
            state TEXT NOT NULL CHECK(state IN ('idle','busy')) DEFAULT 'idle',
            stop_requested INTEGER NOT NULL DEFAULT 0 CHECK(stop_requested IN (0, 1)),
            current_job_id INTEGER
        )
        """
    )
    conn.commit()


def get_worker_id():
    """Stable id per container (file under DATA_DIR)."""
    path = os.path.join(DATA_DIR, ".worker_instance_id")
    if os.path.exists(path):
        with open(path, encoding="utf-8") as f:
            wid = f.read().strip()
            if wid:
                return wid
    os.makedirs(DATA_DIR, exist_ok=True)
    wid = str(uuid.uuid4())
    with open(path, "w", encoding="utf-8") as f:
        f.write(wid)
    return wid


def register_worker_instance(conn, worker_id, hostname):
    conn.execute(
        """
        INSERT INTO worker_instances (id, hostname, first_seen, last_seen, state, stop_requested, current_job_id)
        VALUES (?, ?, datetime('now'), datetime('now'), 'idle', 0, NULL)
        ON CONFLICT(id) DO UPDATE SET
            last_seen = datetime('now'),
            hostname = excluded.hostname,
            state = 'idle',
            current_job_id = NULL
        """,
        (worker_id, hostname),
    )
    conn.commit()


def worker_is_stop_requested(conn, worker_id):
    cur = conn.execute("SELECT stop_requested FROM worker_instances WHERE id = ?", (worker_id,))
    row = cur.fetchone()
    return bool(row and row[0])


def set_worker_busy(conn, worker_id, job_id):
    conn.execute(
        """
        UPDATE worker_instances
        SET state = 'busy', current_job_id = ?, last_seen = datetime('now')
        WHERE id = ?
        """,
        (job_id, worker_id),
    )
    conn.commit()


def set_worker_idle(conn, worker_id):
    conn.execute(
        """
        UPDATE worker_instances
        SET state = 'idle', current_job_id = NULL, last_seen = datetime('now')
        WHERE id = ?
        """,
        (worker_id,),
    )
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
        ensure_worker_instances_schema(conn)
        cleanup_stale_running_jobs(conn)

        worker_id = get_worker_id()
        register_worker_instance(conn, worker_id, socket.gethostname())
        if worker_is_stop_requested(conn, worker_id):
            return 0

        row = claim_next_job(conn)
        if not row:
            return 0
        job_id, user_id = row
        set_worker_busy(conn, worker_id, job_id)
        try:
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
                          "CICD_PROVIDER", "CICD_DEPLOY_WORKFLOW", "REPO_CONFIG",
                          "CODE_REPOS_PATH", "CODE_SONAR_URL", "CODE_SONAR_TOKEN", "CODE_SONAR_PROJECTS"):
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

            # Code analytics config
            code_repos_path = config.get("code_repos_path") or ""
            if code_repos_path:
                os.environ["CODE_REPOS_PATH"] = code_repos_path
            if config.get("code_sonar_url"):
                os.environ["CODE_SONAR_URL"] = config["code_sonar_url"]
            if config.get("code_sonar_token"):
                os.environ["CODE_SONAR_TOKEN"] = config["code_sonar_token"]
            if config.get("code_sonar_projects"):
                os.environ["CODE_SONAR_PROJECTS"] = config["code_sonar_projects"]

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

                # 5. Code analytics (optional)
                if code_repos_path or config.get("code_sonar_url"):
                    set_job_progress(conn, job_id, ProgressLabel.CODE_ANALYZE)
                    try:
                        import code_analytics
                        code_analytics.main()
                    except Exception as e:
                        logging.exception("code_analytics failed")
                        _append_stage_warning(pipeline_warnings, "code_analytics", e)
                else:
                    set_job_progress(conn, job_id, ProgressLabel.CODE_SKIP)

                from analytics_utils import write_json

                write_json({"warnings": pipeline_warnings}, "pipeline_warnings", output_dir)

                set_job_progress(conn, job_id, ProgressLabel.MERGE)
                # 6. Merge evidence (always -- works with whatever data is available)
                import merge_evidence
                merge_evidence.main()

                set_job_progress(conn, job_id, ProgressLabel.SCORES)
                # 7. Score engine
                import score_engine
                score_engine.main()

                set_job_progress(conn, job_id, ProgressLabel.DASHBOARD)
                # 8. Output generators
                import generate_dashboard
                generate_dashboard.main()

                set_job_progress(conn, job_id, ProgressLabel.SCORECARD)
                import generate_scorecard

                scorecard_mode = generate_scorecard.main()
                if scorecard_mode == "placeholder":
                    from analytics_utils import read_json, write_json

                    pw = read_json("pipeline_warnings", output_dir)
                    wl = list(pw.get("warnings", [])) if isinstance(pw, dict) else []
                    wl.append(
                        "generate_scorecard: placeholder scorecard.html written (scorecard.json missing). "
                        "Ensure merge_evidence produced unified_evidence.json and score_engine wrote scorecard.json; "
                        "deploy all HTML from OUTPUT_DIR."
                    )
                    write_json({"warnings": wl}, "pipeline_warnings", output_dir)

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
            set_worker_idle(conn, worker_id)
    finally:
        conn.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
