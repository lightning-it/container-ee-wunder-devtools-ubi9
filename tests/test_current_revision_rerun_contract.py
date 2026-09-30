from __future__ import annotations

import unittest
from pathlib import Path


WORKFLOW = (
    Path(__file__).parents[1]
    / ".github"
    / "workflows"
    / "current-revision-rerun.yml"
)


class RequiredWorkflowDiscoveryContractTests(unittest.TestCase):
    def test_lists_by_exact_head_and_validates_event_from_payload(self) -> None:
        source = WORKFLOW.read_text(encoding="utf-8")

        self.assertIn(
            "actions/runs?head_sha=${EXPECTED_HEAD}&per_page=100", source
        )
        self.assertNotIn("actions/runs?event=pull_request_target", source)
        self.assertIn('select(.event == "pull_request_target")', source)


if __name__ == "__main__":
    unittest.main()
