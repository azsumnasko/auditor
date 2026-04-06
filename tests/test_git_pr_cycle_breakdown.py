"""Unit tests for PR cycle breakdown and review map keys."""

import unittest

import git_analytics


class PrCycleBreakdownTests(unittest.TestCase):
    def test_compute_phase_hours_sequential(self):
        pr = {
            "created_at": "2026-01-01T10:00:00Z",
            "merged_at": "2026-01-03T10:00:00Z",
            "user": {"login": "author"},
        }
        commits = [{"commit": {"author": {"date": "2026-01-01T09:00:00Z"}, "committer": {"date": "2026-01-01T09:00:00Z"}}}]
        timeline = [{"event": "review_requested", "created_at": "2026-01-01T12:00:00Z"}]
        reviews = [
            {"user": {"login": "rev"}, "state": "APPROVED", "submitted_at": "2026-01-02T10:00:00Z"},
        ]
        r = git_analytics.compute_phase_hours_for_pr(pr, commits, timeline, reviews)
        self.assertIsNotNone(r)
        self.assertAlmostEqual(r["time_in_progress_hours"], 3.0, places=3)
        self.assertAlmostEqual(r["time_in_review_hours"], 22.0, places=3)
        self.assertAlmostEqual(r["time_to_merge_hours"], 24.0, places=3)
        self.assertFalse(r["no_approval"])

    def test_compute_phase_hours_no_review_activity(self):
        pr = {
            "created_at": "2026-01-01T10:00:00Z",
            "merged_at": "2026-01-02T10:00:00Z",
            "user": {"login": "author"},
        }
        r = git_analytics.compute_phase_hours_for_pr(pr, [], [], [])
        self.assertIsNotNone(r)
        self.assertEqual(r["time_in_review_hours"], 0.0)
        self.assertEqual(r["time_to_merge_hours"], 0.0)
        self.assertTrue(r["no_approval"])

    def test_review_turnaround_uses_repo_scoped_key(self):
        pulls = [
            {"merged_at": "2026-01-01T12:00:00Z", "created_at": "2026-01-01T10:00:00Z", "number": 1, "_repo": "a", "user": {"login": "u"}},
            {"merged_at": "2026-01-01T12:00:00Z", "created_at": "2026-01-01T10:00:00Z", "number": 1, "_repo": "b", "user": {"login": "u"}},
        ]
        reviews_map = {
            "a:1": [{"user": {"login": "r"}, "submitted_at": "2026-01-01T11:00:00Z"}],
            "b:1": [{"user": {"login": "r2"}, "submitted_at": "2026-01-01T11:30:00Z"}],
        }
        out = git_analytics.review_turnaround_metrics(pulls, reviews_map)
        self.assertEqual(out["review_turnaround"]["count"], 2)


if __name__ == "__main__":
    unittest.main()
