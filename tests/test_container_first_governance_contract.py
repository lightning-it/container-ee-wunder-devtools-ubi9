import json
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class ContainerFirstGovernanceContractTests(unittest.TestCase):
    def test_local_ai_is_disabled_and_pipeline_review_is_authoritative(self):
        config = json.loads(
            (ROOT / ".lit/push-ready.json").read_text(encoding="utf-8")
        )
        self.assertEqual(
            {
                "copilot": False,
                "codex": False,
            },
            {
                name: value["enabled"]
                for name, value in config["agents"].items()
            },
        )
        remote_checks = {
            item["id"]: item for item in config["remote_only_checks"]
        }
        self.assertEqual(
            ".github/workflows/container-ci.yml",
            remote_checks["github-actions-service-boundary"]["workflow"],
        )
        self.assertEqual(
            "verify-current-revision-policy",
            remote_checks["copilot-current-head-review"]["job"],
        )

    def test_exact_repository_root_is_the_only_git_safe_directory(self):
        engine = (ROOT / "scripts/lit-push-ready.py").read_text(
            encoding="utf-8"
        )
        self.assertIn('"GIT_CONFIG_KEY_0": "safe.directory"', engine)
        self.assertIn('"GIT_CONFIG_VALUE_0": str(ROOT)', engine)
        self.assertNotIn('safe.directory=*', engine)

    def test_instruction_binding_runs_inside_the_container_boundary(self):
        profile = (ROOT / "scripts/lit-ci-profile.sh").read_text(
            encoding="utf-8"
        )
        self.assertIn(
            '"$DEVTOOLS_WRAPPER" \\\n'
            "  env \\\n"
            "  LC_ALL=C \\\n"
            "  python3 scripts/lit-push-ready.py instructions",
            profile,
        )

    def test_documented_boundary_has_no_host_runtime_fallback(self):
        readme = (ROOT / "README.md").read_text(encoding="utf-8")
        self.assertIn(
            "The host supplies only Git, the container engine, and the wrapper",
            readme,
        )
        self.assertIn("do not depend on host language runtimes", readme)
        agents = (ROOT / "AGENTS.md").read_text(encoding="utf-8")
        self.assertIn("Host fallbacks,", agents)
        self.assertIn(
            "ad-hoc virtual environments, and unpinned helper images",
            agents,
        )


if __name__ == "__main__":
    unittest.main()
