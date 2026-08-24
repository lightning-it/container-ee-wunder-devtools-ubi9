import json
import re
import unittest
from pathlib import Path

import yaml


ROOT = Path(__file__).resolve().parents[1]


class ContainerToolchainContractTests(unittest.TestCase):
    def test_language_dependent_repository_checks_are_pinned_in_image(self):
        dockerfile = (ROOT / "Dockerfile").read_text(encoding="utf-8")
        requirements = (ROOT / "requirements.txt").read_text(encoding="utf-8")
        container_package = json.loads(
            (ROOT / "container-toolchain/package.json").read_text(encoding="utf-8")
        )
        pnpm_workspace = yaml.safe_load(
            (ROOT / "container-toolchain/pnpm-workspace.yaml").read_text(
                encoding="utf-8"
            )
        )

        for name in ("mypy", "ruff", "types-PyYAML"):
            self.assertRegex(
                requirements,
                rf"(?m)^{re.escape(name)}==[^\s]+$",
                f"{name} must be directly and exactly pinned",
            )
        for name in ("renovate", "markdownlint-cli2", "prettier"):
            version = container_package["dependencies"][name]
            self.assertRegex(version, r"^\d+\.\d+\.\d+$")

        for argument in (
            "ARG NODE_VERSION=24.19.0",
            "ARG GO_VERSION=1.26.7",
            "ARG GO_X_MOD_VERSION=0.40.0",
            "ARG GO_GRPC_VERSION=1.82.1",
            "ARG TF_SOURCE_COMMIT=87488977e32a400445e0c0b4d95c0713a5eee941",
            "ARG TF_SOURCE_SHA256=b4036b35e69a57e4a4b83bafba337a5c8e3ab2c0b1812df92528dec0958ed61e",
            "ARG DOCKER_SOURCE_COMMIT=a7dcaa6fdb6ed04aacbfdc76357fdae01605609e",
            "ARG DOCKER_SOURCE_SHA256=6e5c91d3a5a79db78cf989d07727d00e757aa0da4d135a3ce4b86061b83fb511",
            "ARG BUILDX_VERSION=0.36.1",
            "ARG MOBY_V2_VERSION=2.0.0-beta.21",
            "ARG MOBY_NAMESGENERATOR_SHA256=79ed19fb5afd19ccb3284213961335ec2f22ac9e8181971cab377de740361bbb",
        ):
            self.assertIn(argument, dockerfile)
        self.assertEqual("12.0.2", container_package["dependencies"]["npm"])
        pnpm_version = container_package["dependencies"]["pnpm"]
        self.assertEqual(f"pnpm@{pnpm_version}", container_package["packageManager"])
        self.assertIn(f"ARG PNPM_VERSION={pnpm_version}", dockerfile)
        self.assertEqual(
            "5.3.0",
            pnpm_workspace["overrides"]["markdownlint-cli2>js-yaml"],
        )
        for package in ("brace-expansion", "ip-address", "tar"):
            version = container_package["dependencies"][package]
            self.assertRegex(version, r"^\d+\.\d+\.\d+$")
            self.assertEqual(version, pnpm_workspace["overrides"][package])
            self.assertIn(package, dockerfile)
        self.assertEqual(1440, pnpm_workspace["minimumReleaseAge"])
        self.assertTrue(pnpm_workspace["minimumReleaseAgeStrict"])
        self.assertFalse(pnpm_workspace["trustLockfile"])
        self.assertTrue(pnpm_workspace["blockExoticSubdeps"])
        self.assertTrue(pnpm_workspace["ignoreScripts"])
        self.assertTrue(pnpm_workspace["strictPeerDependencies"])
        self.assertTrue(pnpm_workspace["verifyStoreIntegrity"])
        self.assertTrue(pnpm_workspace["strictStorePkgContentCheck"])
        self.assertIn(
            "node_modules/npm/node_modules/${package}",
            dockerfile,
        )
        self.assertEqual(1, dockerfile.count("ENV PATH=/opt/node/bin:$PATH"))
        self.assertIn('export PATH="/opt/node/bin:${PATH}"', dockerfile)
        self.assertIn(
            "COPY --from=tools /opt/node-toolchain /opt/node-toolchain",
            dockerfile,
        )
        self.assertIn("corepack pnpm@${PNPM_VERSION} install", dockerfile)
        self.assertIn("--frozen-lockfile", dockerfile)
        self.assertIn("--ignore-scripts", dockerfile)
        self.assertIn("--strict-peer-dependencies", dockerfile)
        self.assertIn("--store-dir /tmp/pnpm-store", dockerfile)
        self.assertIn("cp -aL", dockerfile)
        self.assertIn(
            "chmod 0755 /opt/node-toolchain/node_modules/pnpm/bin/pnpm.cjs",
            dockerfile,
        )
        self.assertIn("container-build-go-tool.sh", dockerfile)
        self.assertIn("container-build-compose.sh", dockerfile)
        self.assertIn(
            "node_modules/markdownlint-cli2/markdownlint-cli2-bin.mjs",
            dockerfile,
        )
        self.assertIn(
            "node_modules/prettier/bin/prettier.cjs",
            dockerfile,
        )
        self.assertIn("node_modules/pnpm/bin/pnpm.cjs", dockerfile)
        self.assertNotIn(
            "node_modules/markdownlint-cli2/markdownlint-cli2.mjs", dockerfile
        )
        self.assertNotIn("github.com/docker/docker@", dockerfile)
        self.assertIn('= "Terraform v${TF_VERSION}"', dockerfile)
        self.assertIn('"Docker version ${DOCKER_VERSION},"*', dockerfile)
        self.assertIn("dnf -y remove", dockerfile)
        self.assertNotIn("COPILOT_VERSION", dockerfile)
        self.assertNotIn("@github/copilot", dockerfile)
        for command in (
            "pre-commit --version",
            "ruff --version",
            "mypy --version",
            "renovate-config-validator --version",
            "markdownlint-cli2 --version",
            "prettier --version",
            "pnpm --version",
        ):
            self.assertIn(command, dockerfile)

        renovate = json.loads(
            (ROOT / "renovate.json").read_text(encoding="utf-8")
        )
        serialized_managers = json.dumps(renovate["customManagers"])
        for version_argument in (
            "GO_VERSION",
            "TF_VERSION",
            "TFLINT_VERSION",
            "TF_DOCS_VERSION",
            "GH_VERSION",
            "ACTIONLINT_VERSION",
            "DOCKER_VERSION",
            "COMPOSE_VERSION",
            "BUILDX_VERSION",
            "MOBY_V2_VERSION",
            "PNPM_VERSION",
        ):
            self.assertIn(version_argument, serialized_managers)

        container_lock = yaml.safe_load(
            (ROOT / "container-toolchain/pnpm-lock.yaml").read_text(
                encoding="utf-8"
            )
        )
        self.assertEqual("9.0", str(container_lock["lockfileVersion"]))
        self.assertEqual(pnpm_workspace["overrides"], container_lock["overrides"])
        locked_dependencies = container_lock["importers"]["."]["dependencies"]
        for name, version in container_package["dependencies"].items():
            self.assertEqual(version, locked_dependencies[name]["specifier"])
        for locked in container_lock["packages"].values():
            resolution = locked.get("resolution", {})
            self.assertIn("integrity", resolution)
            self.assertNotIn("tarball", resolution)

    def test_local_and_ci_contracts_probe_the_same_toolchain(self):
        required_commands = (
            "pre-commit --version",
            "ruff --version",
            "mypy --version",
            "renovate-config-validator --version",
            "markdownlint-cli2 --version",
            "prettier --version",
            "pnpm --version",
        )
        for relative_path in (
            "scripts/devtools-container-ci.sh",
            "scripts/verify-host-parity.sh",
        ):
            content = (ROOT / relative_path).read_text(encoding="utf-8")
            for command in required_commands:
                self.assertIn(command, content, f"{command} missing from {relative_path}")

        container_ci = (ROOT / "scripts/devtools-container-ci.sh").read_text(
            encoding="utf-8"
        )
        self.assertIn("docker buildx build --load", container_ci)
        self.assertIn("--pull", container_ci)
        self.assertIn("--no-cache", container_ci)

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
