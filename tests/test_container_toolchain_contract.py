import json
import re
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class ContainerToolchainContractTests(unittest.TestCase):
    def test_language_dependent_repository_checks_are_pinned_in_image(self):
        dockerfile = (ROOT / "Dockerfile").read_text(encoding="utf-8")
        requirements = (ROOT / "requirements.txt").read_text(encoding="utf-8")
        package = json.loads((ROOT / "package.json").read_text(encoding="utf-8"))

        for name in ("mypy", "ruff", "types-PyYAML"):
            self.assertRegex(
                requirements,
                rf"(?m)^{re.escape(name)}==[^\s]+$",
                f"{name} must be directly and exactly pinned",
            )
        for name in ("renovate", "markdownlint-cli2"):
            version = package["devDependencies"][name]
            self.assertRegex(version, r"^\d+\.\d+\.\d+$")

        for argument in (
            "ARG NODE_VERSION=24.19.0",
            "ARG RENOVATE_VERSION=43.288.0",
            "ARG MARKDOWNLINT_CLI2_VERSION=0.23.0",
        ):
            self.assertIn(argument, dockerfile)
        self.assertEqual(1, dockerfile.count("ENV PATH=/opt/node/bin:$PATH"))
        self.assertIn('export PATH="/opt/node/bin:${PATH}"', dockerfile)
        for command in (
            "pre-commit --version",
            "ruff --version",
            "mypy --version",
            "renovate-config-validator --version",
            "markdownlint-cli2 --version",
        ):
            self.assertIn(command, dockerfile)

        renovate = json.loads(
            (ROOT / "renovate.json").read_text(encoding="utf-8")
        )
        serialized_managers = json.dumps(renovate["customManagers"])
        self.assertIn("RENOVATE_VERSION", serialized_managers)
        self.assertIn("MARKDOWNLINT_CLI2_VERSION", serialized_managers)

    def test_local_and_ci_contracts_probe_the_same_toolchain(self):
        required_commands = (
            "pre-commit --version",
            "ruff --version",
            "mypy --version",
            "renovate-config-validator --version",
            "markdownlint-cli2 --version",
        )
        for relative_path in (
            "scripts/devtools-container-ci.sh",
            "scripts/verify-host-parity.sh",
        ):
            content = (ROOT / relative_path).read_text(encoding="utf-8")
            for command in required_commands:
                self.assertIn(command, content, f"{command} missing from {relative_path}")

    def test_documented_boundary_has_no_host_runtime_fallback(self):
        readme = (ROOT / "README.md").read_text(encoding="utf-8")
        self.assertIn(
            "The host supplies only Git, the container engine, and the wrapper",
            readme,
        )
        self.assertIn(
            "do not depend on host language runtimes",
            readme,
        )

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


if __name__ == "__main__":
    unittest.main()
