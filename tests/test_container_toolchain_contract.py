import json
import re
import unittest
from pathlib import Path

import yaml
from packaging.requirements import InvalidRequirement, Requirement
from packaging.utils import canonicalize_name
from packaging.version import Version


ROOT = Path(__file__).resolve().parents[1]


def parse_direct_requirement(raw_line: str) -> Requirement | None:
    stripped_line = raw_line.strip()
    if not stripped_line or stripped_line.startswith("#"):
        return None
    requirement_text = re.split(r"\s+#", raw_line, maxsplit=1)[0].strip()
    return Requirement(requirement_text)


class ContainerToolchainContractTests(unittest.TestCase):
    def test_requirement_comments_cannot_hide_malformed_content(self):
        self.assertIsNone(parse_direct_requirement("  # full-line comment"))
        self.assertEqual(
            "example",
            parse_direct_requirement("example==1.0  # inline comment").name,
        )
        with self.assertRaises(InvalidRequirement):
            parse_direct_requirement("example==1.0#tampered")

    def test_language_dependent_repository_checks_are_pinned_in_image(self):
        dockerfile = (ROOT / "Dockerfile").read_text(encoding="utf-8")
        requirements = (ROOT / "requirements.txt").read_text(encoding="utf-8")
        requirements_lock = (ROOT / "requirements.lock").read_text(encoding="utf-8")
        container_package = json.loads(
            (ROOT / "container-toolchain/package.json").read_text(encoding="utf-8")
        )
        pnpm_workspace = yaml.safe_load(
            (ROOT / "container-toolchain/pnpm-workspace.yaml").read_text(
                encoding="utf-8"
            )
        )

        locked_versions = {}
        for match in re.finditer(
            r"(?m)^(?P<name>[A-Za-z0-9_.-]+)==(?P<version>[^\s\\]+)(?:\s|$)",
            requirements_lock,
        ):
            normalized_name = canonicalize_name(match.group("name"))
            self.assertNotIn(
                normalized_name,
                locked_versions,
                f"{normalized_name} must occur only once in requirements.lock",
            )
            locked_versions[normalized_name] = Version(match.group("version"))

        direct_requirements = {}
        for raw_line in requirements.splitlines():
            requirement = parse_direct_requirement(raw_line)
            if requirement is None:
                continue
            normalized_name = canonicalize_name(requirement.name)
            self.assertNotIn(
                normalized_name,
                direct_requirements,
                f"{normalized_name} must occur only once in requirements.txt",
            )
            self.assertTrue(
                requirement.specifier,
                f"{requirement.name} must have an explicit version constraint",
            )
            direct_requirements[normalized_name] = requirement

        self.assertTrue(direct_requirements, "requirements.txt must not be empty")
        for normalized_name, requirement in direct_requirements.items():
            self.assertIn(
                normalized_name,
                locked_versions,
                f"{requirement.name} must be resolved in requirements.lock",
            )
            locked_version = locked_versions[normalized_name]
            self.assertIn(
                locked_version,
                requirement.specifier,
                f"{requirement.name} lock version {locked_version} must satisfy "
                f"the direct constraint {requirement.specifier}",
            )
        for name in ("renovate", "markdownlint-cli2", "prettier"):
            version = container_package["dependencies"][name]
            self.assertRegex(version, r"^\d+\.\d+\.\d+$")

        for argument in (
            "ARG NODE_VERSION=24.19.0",
            "ARG WEBSITE_NODE_VERSION=24.18.0",
            "ARG VNU_SOURCE_COMMIT=c4720cafffd1f93358ca824163fc5bbdb35fb0e0",
            "ARG VNU_RELEASE_ID=258370454",
            "ARG VNU_ASSET_ID=534958489",
            "ARG VNU_JAR_SHA256=6df33484013072856456a9c1fa32ae3da96c3069041d9b61c026f57b04bd23c3",
            "ARG VNU_JRE_VERSION=17.0.20_8",
            "ARG VNU_JRE_AMD64_ASSET_ID=488632381",
            "ARG VNU_JRE_AMD64_SHA256=ef491a51a46ef90cc47fbc4abb219fde32483ff91be5ec66ddc896df43524b27",
            "ARG VNU_JRE_ARM64_ASSET_ID=492545197",
            "ARG VNU_JRE_ARM64_SHA256=9d14a95e07c44bc48666625162baf40db9da4dcb192bfc3e43047790693061a2",
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
        self.assertEqual(
            "npm:npm@11.16.0", container_package["dependencies"]["npm-website"]
        )
        pnpm_version = container_package["dependencies"]["pnpm"]
        self.assertEqual(f"pnpm@{pnpm_version}", container_package["packageManager"])
        self.assertNotIn("ARG PNPM_VERSION=", dockerfile)
        self.assertIn("dependencies.pnpm", dockerfile)
        self.assertIn('corepack "pnpm@${pnpm_version}" install', dockerfile)
        self.assertEqual(
            "5.3.0",
            pnpm_workspace["overrides"]["markdownlint-cli2>js-yaml"],
        )
        for package in ("brace-expansion", "ip-address", "tar"):
            version = container_package["dependencies"][package]
            self.assertRegex(version, r"^\d+\.\d+\.\d+$")
            self.assertEqual(version, pnpm_workspace["overrides"][package])
            self.assertIn(package, dockerfile)
        for package, version in {"pacote": "21.5.1", "undici": "6.27.0"}.items():
            self.assertEqual(version, container_package["dependencies"][package])
            self.assertEqual(version, pnpm_workspace["overrides"][package])
        self.assertIn(
            "node_modules/npm-website/node_modules/${package}", dockerfile
        )
        self.assertEqual(1440, pnpm_workspace["minimumReleaseAge"])
        self.assertTrue(pnpm_workspace["minimumReleaseAgeStrict"])
        self.assertFalse(pnpm_workspace["trustLockfile"])
        self.assertTrue(pnpm_workspace["blockExoticSubdeps"])
        self.assertTrue(pnpm_workspace["ignoreScripts"])
        self.assertTrue(pnpm_workspace["strictPeerDependencies"])
        self.assertTrue(pnpm_workspace["verifyStoreIntegrity"])
        self.assertTrue(pnpm_workspace["strictStorePkgContentCheck"])
        self.assertIn("for npm_tree in npm npm-website", dockerfile)
        self.assertIn(
            "node_modules/${npm_tree}/node_modules/${package}",
            dockerfile,
        )
        self.assertEqual(
            1,
            dockerfile.count("PATH=/opt/java/bin:/opt/node/bin:$PATH"),
        )
        self.assertIn('export PATH="/opt/node/bin:${PATH}"', dockerfile)
        self.assertIn(
            "COPY --from=tools /opt/node-toolchain /opt/node-toolchain",
            dockerfile,
        )
        self.assertIn(
            "COPY --from=tools /opt/node-website /opt/node-website",
            dockerfile,
        )
        self.assertIn(
            "COPY scripts/devtools-node-selector.sh "
            "/usr/local/bin/devtools-node-selector.sh",
            dockerfile,
        )
        self.assertIn(
            'ENTRYPOINT ["/usr/local/bin/devtools-node-selector.sh"]', dockerfile
        )
        self.assertNotIn("java-17-openjdk-headless", dockerfile)
        self.assertIn("COPY --from=tools /opt/java /opt/java", dockerfile)
        self.assertIn(
            "COPY --from=tools /opt/vnu/vnu.jar /opt/vnu/vnu.jar",
            dockerfile,
        )
        self.assertIn("COPY scripts/vnu /usr/local/bin/vnu", dockerfile)
        self.assertIn("vnu --errors-only /tmp/vnu-fixtures/valid.html", dockerfile)
        self.assertIn("Nu accepted the intentionally invalid fixture", dockerfile)
        self.assertTrue((ROOT / "scripts/vnu").stat().st_mode & 0o111)
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
        for build_helper in (
            "scripts/container-build-go-tool.sh",
            "scripts/container-build-compose.sh",
        ):
            self.assertTrue(
                (ROOT / build_helper).stat().st_mode & 0o111,
                f"{build_helper} must remain executable in the image build context",
            )
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
        self.assertNotIn("ARG DOCKER_VERSION=", dockerfile)
        self.assertIn('docker_source_version="$(tr -d', dockerfile)
        self.assertIn(
            "version.Version=${docker_source_version}",
            dockerfile,
        )
        self.assertIn('"Docker version ${docker_source_version},"*', dockerfile)
        self.assertIn("dnf -y remove", dockerfile)
        self.assertNotIn("COPILOT_VERSION", dockerfile)
        self.assertNotIn("@github/copilot", dockerfile)
        for command in (
            "pre-commit --version",
            "ruff --version",
            "mypy --version",
            "uv --version",
            "renovate-config-validator --version",
            "markdownlint-cli2 --version",
            "prettier --version",
            "pnpm --version",
            "vnu --version",
        ):
            self.assertIn(command, dockerfile)

        renovate = json.loads((ROOT / "renovate.json").read_text(encoding="utf-8"))
        serialized_managers = json.dumps(renovate["customManagers"])
        for version_argument in (
            "TFLINT_VERSION",
            "TF_DOCS_VERSION",
            "GH_VERSION",
            "ACTIONLINT_VERSION",
            "COMPOSE_VERSION",
            "BUILDX_VERSION",
        ):
            self.assertIn(version_argument, serialized_managers)
        for atomic_or_derived_argument in (
            "GO_VERSION",
            "TF_VERSION",
            "DOCKER_VERSION",
            "MOBY_V2_VERSION",
            "PNPM_VERSION",
        ):
            self.assertNotIn(atomic_or_derived_argument, serialized_managers)

        container_lock = yaml.safe_load(
            (ROOT / "container-toolchain/pnpm-lock.yaml").read_text(encoding="utf-8")
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

    def test_node_selector_is_fail_closed_and_source_owned(self):
        selector = ROOT / "scripts/devtools-node-selector.sh"
        self.assertTrue(selector.stat().st_mode & 0o111)
        content = selector.read_text(encoding="utf-8")
        self.assertIn('default_node_bin="/opt/node/bin"', content)
        self.assertIn("/opt/node-website/bin", content)
        self.assertIn(
            'if [ -e "$version_file" ] || [ -L "$version_file" ]; then',
            content,
        )
        self.assertIn('[ -r "$version_file" ]', content)
        self.assertIn('"$default_node_bin/node"', content)
        self.assertIn('"$website_node_bin/node"', content)
        self.assertIn('exec 3<"$version_file"', content)
        self.assertNotIn("awk", content)
        self.assertIn("requested Node.js version is not bundled", content)
        self.assertIn('exec "$@"', content)

    def test_local_and_ci_contracts_probe_the_same_toolchain(self):
        required_commands = (
            "pre-commit --version",
            "ruff --version",
            "mypy --version",
            "uv --version",
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
                self.assertIn(
                    command, content, f"{command} missing from {relative_path}"
                )

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
        profile = (ROOT / "scripts/lit-ci-profile.sh").read_text(encoding="utf-8")
        self.assertIn(
            '"$DEVTOOLS_WRAPPER" \\\n'
            "  env \\\n"
            "  LC_ALL=C \\\n"
            "  python3 scripts/lit-push-ready.py instructions",
            profile,
        )


if __name__ == "__main__":
    unittest.main()
