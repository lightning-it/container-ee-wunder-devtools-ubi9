import json
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class CopilotReviewRefreshContractTests(unittest.TestCase):
    def test_late_review_refresh_is_managed_and_ai_request_free(self):
        workflow_path = ROOT / ".github/workflows/copilot-review-refresh.yml"
        self.assertTrue(workflow_path.is_file())
        workflow = workflow_path.read_text(encoding="utf-8")
        self.assertIn("pull_request_review:", workflow)
        self.assertIn("pull_request_review_comment:", workflow)
        self.assertIn("actions: write", workflow)
        self.assertIn("checks: write", workflow)
        self.assertNotIn("requested_reviewers", workflow)

        renovate = json.loads(
            (ROOT / "renovate.json").read_text(encoding="utf-8")
        )
        managed_files = {
            file_name
            for package_rule in renovate["packageRules"]
            if package_rule.get("enabled") is False
            for file_name in package_rule.get("matchFileNames", [])
        }
        self.assertIn(
            ".github/workflows/copilot-review-refresh.yml",
            managed_files,
        )


if __name__ == "__main__":
    unittest.main()
