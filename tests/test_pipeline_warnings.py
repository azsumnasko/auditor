"""Tests for non-blocking optional analytics (pipeline warnings, Octopus soft-skip)."""

import json
import os
import sys
import tempfile
import unittest
from unittest import mock

# Repo root on path for `import merge_evidence`, `import octopus_analytics`
_REPO_ROOT = os.path.normpath(os.path.join(os.path.dirname(__file__), ".."))
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)

import merge_evidence  # noqa: E402
import octopus_analytics  # noqa: E402


class PipelineWarningsTests(unittest.TestCase):
    def test_octopus_returns_none_without_git_credentials(self):
        with tempfile.TemporaryDirectory() as tmp:
            with mock.patch.dict(
                os.environ,
                {
                    "OCTOPUS_SERVER_URL": "https://octopus.example",
                    "OCTOPUS_API_KEY": "secret",
                    "OUTPUT_DIR": tmp,
                },
                clear=False,
            ):
                os.environ.pop("GIT_TOKEN", None)
                os.environ.pop("GIT_ORG", None)
                self.assertIsNone(octopus_analytics.main())

    def test_merge_evidence_includes_pipeline_warnings_from_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            with open(os.path.join(tmp, "jira_analytics_latest.json"), "w", encoding="utf-8") as f:
                json.dump({"run_iso_ts": "2026-01-01T00:00:00+00:00"}, f)
            with open(os.path.join(tmp, "pipeline_warnings_latest.json"), "w", encoding="utf-8") as f:
                json.dump({"warnings": ["git_analytics: connection reset"]}, f)
            with mock.patch.dict(os.environ, {"OUTPUT_DIR": tmp}, clear=False):
                out = merge_evidence.main()
            self.assertIsNotNone(out)
            self.assertEqual(out.get("pipeline_warnings"), ["git_analytics: connection reset"])


if __name__ == "__main__":
    unittest.main()
