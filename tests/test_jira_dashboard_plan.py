import os
import sys
import tempfile
import types
import unittest
from datetime import datetime, timezone

import insights_by_project

sys.modules.setdefault("requests", types.ModuleType("requests"))
sys.modules.setdefault("pandas", types.ModuleType("pandas"))

dateutil_mod = types.ModuleType("dateutil")
dateutil_parser_mod = types.ModuleType("dateutil.parser")


def _parse_dt(value):
    normalized = value.replace("Z", "+00:00")
    if normalized.endswith("+0000"):
        normalized = normalized[:-5] + "+00:00"
    return datetime.fromisoformat(normalized)


dateutil_parser_mod.parse = _parse_dt
dateutil_parser_mod.isoparse = _parse_dt
dateutil_mod.parser = dateutil_parser_mod
sys.modules.setdefault("dateutil", dateutil_mod)
sys.modules.setdefault("dateutil.parser", dateutil_parser_mod)

import jira_analytics


def make_issue(
    *,
    key="OZN-1",
    project="OZN",
    created="2026-01-01T00:00:00.000+0000",
    resolved=None,
    status="In Progress",
    issuetype="Task",
    components=None,
):
    return {
        "key": key,
        "fields": {
            "project": {"key": project},
            "created": created,
            "resolutiondate": resolved,
            "status": {"name": status},
            "issuetype": {"name": issuetype},
            "components": [{"name": c} for c in (components or [])],
            "summary": key,
            "comment": {"comments": []},
            "issuelinks": [],
            "worklog": {"worklogs": []},
        },
    }


class JiraDashboardPlanTests(unittest.TestCase):
    def test_scope_metrics_uses_created_list_for_created_by_week(self):
        created_a = make_issue(key="OZN-1", created="2026-01-05T00:00:00.000+0000")
        created_b = make_issue(key="OZN-2", created="2026-01-06T00:00:00.000+0000")
        wip_issue = make_issue(key="OZN-3", created="2026-02-01T00:00:00.000+0000")
        done_issue = make_issue(
            key="OZN-4",
            created="2026-02-02T00:00:00.000+0000",
            resolved="2026-02-03T00:00:00.000+0000",
            status="Done",
        )

        metrics = jira_analytics._scope_metrics(
            wip_list=[wip_issue],
            blocked_list=[],
            done_list=[done_issue],
            done_90_list=[],
            open_bug_list=[],
            created_list=[created_a, created_b],
            story_points_field=None,
            now=datetime(2026, 3, 1, tzinfo=timezone.utc),
            team_field_id=None,
        )

        expected = jira_analytics._created_by_week([created_a, created_b])
        self.assertEqual(metrics["created_by_week"], expected)
        self.assertNotEqual(metrics["created_by_week"], jira_analytics._created_by_week([wip_issue, done_issue]))

    def test_select_project_board_prefers_location_match_then_type(self):
        boards = [
            {"id": 10, "name": "Shared Scrum", "type": "scrum", "location": {"projectKey": "OTHER"}},
            {"id": 11, "name": "OZN Delivery", "type": "kanban", "location": {"projectKey": "OZN"}},
            {"id": 12, "name": "OZN Team Board", "type": "scrum", "location": {"projectKey": "OZN"}},
        ]
        selected = jira_analytics._select_project_board("OZN", boards)
        self.assertEqual(selected["id"], 12)

    def test_generate_insights_uses_live_bug_counts_not_hardcoded_text(self):
        fixture_path = os.path.join(os.path.dirname(__file__), "..", "jira_analytics_latest.json")
        data = insights_by_project.load_data(fixture_path)
        by_project = insights_by_project.build_by_project(data)

        with tempfile.TemporaryDirectory() as tmpdir:
            out_path = os.path.join(tmpdir, "INSIGHTS_AND_ACTIONS.md")
            insights_by_project.generate_insights_md(data, by_project, out_path)
            with open(out_path, encoding="utf-8") as fh:
                text = fh.read()

        self.assertNotIn("53 open; median age ~398 days", text)
        self.assertIn(f"**Open bugs:** {data.get('open_bugs_count', 0)}", text)

    def test_story_point_recommendation_depends_on_sp_history(self):
        data = {
            "run_iso_ts": "2026-03-12T00:00:00Z",
            "wip_count": 0,
            "wip_aging_days": {"p50_days": 0},
            "blocked_count": 0,
            "open_bugs_count": 0,
            "open_bugs_age_days": {"p50_days": 0},
            "throughput_by_week": {},
            "blocked_oldest": [],
            "oldest_open_bugs": [],
            "by_project": {
                "OZN": {"sp_trend": {"by_month": {}}},
                "PMBK": {"sp_trend": {"by_month": {"2026-01": {"avg_sp": 5, "count": 2}}}},
            },
        }
        by_project = {
            "OZN": {"blocked": [], "oldest_bugs": [], "sprint_metrics": [{"project": "OZN", "throughput_issues": 3}], "kanban": None},
            "PMBK": {"blocked": [], "oldest_bugs": [], "sprint_metrics": [{"project": "PMBK", "throughput_issues": 0}], "kanban": None},
        }

        with tempfile.TemporaryDirectory() as tmpdir:
            out_path = os.path.join(tmpdir, "INSIGHTS_AND_ACTIONS.md")
            insights_by_project.generate_insights_md(data, by_project, out_path)
            with open(out_path, encoding="utf-8") as fh:
                text = fh.read()

        self.assertIn("OZN", text)
        self.assertIn("no story point trend data", text)
        self.assertNotIn("PMBK:** Scrum: no story point trend data", text)


if __name__ == "__main__":
    unittest.main()
