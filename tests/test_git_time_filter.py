"""
Unit tests for:
  1. review_turnaround_by_merge_week – new field from git_analytics.review_turnaround_metrics.
  2. Weighted-mean math that applyGitTimeScope (JS) performs client-side.
     These Python tests serve as a canonical reference spec for the JS implementation;
     the comment 'JS must stay in sync' is intentional.
"""

import unittest

import git_analytics


def _pr(number, created, merged, author="u"):
    return {"number": number, "created_at": created, "merged_at": merged, "user": {"login": author}, "_repo": "r"}


def _review(user, submitted):
    return {"user": {"login": user}, "submitted_at": submitted}


class ReviewTurnaroundByMergeWeekTests(unittest.TestCase):
    def test_by_merge_week_key_is_merge_week_not_review_week(self):
        # PR created Mon Jan 5 (2026-W02), first review 1 hour later (still W02),
        # merged Sun Jan 18 (2026-W03).
        # review_turnaround_by_week  → keyed by W02 (week of the review event)
        # review_turnaround_by_merge_week → keyed by W03 (week of the merge event)
        pr = _pr(1, "2026-01-05T08:00:00Z", "2026-01-18T10:00:00Z")
        reviews_map = {
            "r:1": [_review("rev", "2026-01-05T09:00:00Z")],  # 1h after creation, still in W02
        }
        out = git_analytics.review_turnaround_metrics([pr], reviews_map)

        rby_week = out["review_turnaround_by_week"]
        rby_merge = out["review_turnaround_by_merge_week"]

        self.assertIn("2026-W02", rby_week, "review-week key should be the week of the first review")
        self.assertNotIn("2026-W03", rby_week)

        self.assertIn("2026-W03", rby_merge, "merge-week key should be the week the PR was merged")
        self.assertNotIn("2026-W02", rby_merge)

        entry = rby_merge["2026-W03"]
        self.assertIn("avg_hours", entry)
        self.assertIn("n", entry)
        self.assertEqual(entry["n"], 1)
        self.assertAlmostEqual(entry["avg_hours"], 1.0, places=1)

    def test_by_merge_week_averages_multiple_prs_in_same_merge_week(self):
        # Two PRs both merged in 2026-W03; review turnarounds are 1h and 3h → avg 2.0h
        pr1 = _pr(1, "2026-01-05T08:00:00Z", "2026-01-12T10:00:00Z")
        pr2 = _pr(2, "2026-01-07T08:00:00Z", "2026-01-14T10:00:00Z")
        reviews_map = {
            "r:1": [_review("rev", "2026-01-05T09:00:00Z")],  # 1h after creation
            "r:2": [_review("rev", "2026-01-07T11:00:00Z")],  # 3h after creation
        }
        out = git_analytics.review_turnaround_metrics([pr1, pr2], reviews_map)
        rby_merge = out["review_turnaround_by_merge_week"]
        # Both land in 2026-W03
        week = "2026-W03"
        self.assertIn(week, rby_merge)
        self.assertEqual(rby_merge[week]["n"], 2)
        self.assertAlmostEqual(rby_merge[week]["avg_hours"], 2.0, places=1)

    def test_no_reviewer_prs_excluded_from_merge_week(self):
        # A PR with no reviewer should not appear in review_turnaround_by_merge_week.
        pr = _pr(1, "2026-01-05T08:00:00Z", "2026-01-12T10:00:00Z")
        out = git_analytics.review_turnaround_metrics([pr], {})
        self.assertEqual(out["review_turnaround_by_merge_week"], {})

    def test_existing_review_turnaround_fields_unchanged(self):
        # Confirm backward-compatible fields are still present and correct.
        pr = _pr(1, "2026-01-05T08:00:00Z", "2026-01-12T10:00:00Z")
        reviews_map = {"r:1": [_review("rev", "2026-01-05T10:00:00Z")]}
        out = git_analytics.review_turnaround_metrics([pr], reviews_map)
        self.assertIn("review_turnaround", out)
        self.assertIn("review_turnaround_by_week", out)
        self.assertIn("review_turnaround_by_merge_week", out)
        rt = out["review_turnaround"]
        self.assertEqual(rt["count"], 1)
        self.assertAlmostEqual(rt["avg_hours"], 2.0, places=1)


# ---------------------------------------------------------------------------
# JS applyGitTimeScope math mirror tests
# These tests verify the weighted-mean formulas that the JS function applies.
# Keep in sync with applyGitTimeScope in generate_dashboard.py.
# ---------------------------------------------------------------------------

def _weighted_merge_mean(cycle_by_week, merges_by_week, from_date, to_date):
    """
    Python mirror of the JS weighted-mean PR cycle computation in applyGitTimeScope.
    cycle_by_week: { "YYYY-Www": avg_days }
    merges_by_week: { "YYYY-Www": count }
    Returns (total_merges, merges_per_active_week, weighted_mean_cycle_days).
    """
    from analytics_utils import iso_week
    total, wk_count, num, den = 0, 0, 0.0, 0
    all_weeks = set(list(cycle_by_week) + list(merges_by_week))
    for w in all_weeks:
        # simple string comparison (YYYY-Www sorts lexicographically as dates)
        if from_date and w < from_date:
            continue
        if to_date and w > to_date:
            continue
        n = merges_by_week.get(w, 0)
        if n > 0:
            total += n
            wk_count += 1
            if w in cycle_by_week:
                num += cycle_by_week[w] * n
                den += n
    mean = round(num / den, 2) if den else 0
    avg_per_wk = round(total / wk_count, 1) if wk_count else 0
    return total, avg_per_wk, mean


class ApplyGitTimeScopeMathTests(unittest.TestCase):
    """
    Mirror of the JS applyGitTimeScope weighted-math.
    JS must stay in sync – these tests define the expected contract.
    """

    def test_total_merges_is_sum_of_weeks_in_range(self):
        merges = {"2026-W01": 5, "2026-W02": 10, "2026-W03": 3}
        cycle = {"2026-W01": 1.0, "2026-W02": 2.0, "2026-W03": 3.0}
        total, _, _ = _weighted_merge_mean(cycle, merges, "2026-W01", "2026-W02")
        self.assertEqual(total, 15)  # 5 + 10, not 3

    def test_merges_per_week_uses_active_weeks_only(self):
        merges = {"2026-W01": 10, "2026-W03": 10}  # W02 has no merges
        cycle = {}
        total, avg, _ = _weighted_merge_mean(cycle, merges, "2026-W01", "2026-W03")
        # 2 active weeks (W01 and W03), total 20 → avg 10.0
        self.assertEqual(total, 20)
        self.assertEqual(avg, 10.0)

    def test_weighted_mean_cycle_time(self):
        # W01: avg 1d, 10 merges; W02: avg 3d, 10 merges → weighted mean = 2d
        merges = {"2026-W01": 10, "2026-W02": 10}
        cycle = {"2026-W01": 1.0, "2026-W02": 3.0}
        _, _, mean = _weighted_merge_mean(cycle, merges, "2026-W01", "2026-W02")
        self.assertAlmostEqual(mean, 2.0, places=2)

    def test_empty_range_returns_zeros(self):
        merges = {"2026-W01": 5}
        cycle = {"2026-W01": 2.0}
        total, avg, mean = _weighted_merge_mean(cycle, merges, "2026-W05", "2026-W06")
        self.assertEqual(total, 0)
        self.assertEqual(avg, 0)
        self.assertEqual(mean, 0)

    def test_no_upper_bound_includes_all_weeks_from_from(self):
        merges = {"2026-W01": 2, "2026-W02": 3, "2026-W10": 5}
        cycle = {}
        total, _, _ = _weighted_merge_mean(cycle, merges, "2026-W02", None)
        self.assertEqual(total, 8)  # W02 + W10; W01 excluded


if __name__ == "__main__":
    unittest.main()
