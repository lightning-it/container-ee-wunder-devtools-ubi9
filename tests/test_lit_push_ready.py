import importlib.util
import hashlib
import io
import json
import os
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "lit_push_ready_container_tests",
    ROOT / "scripts" / "lit-push-ready.py",
)
assert SPEC is not None and SPEC.loader is not None
PUSH_READY = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(PUSH_READY)


class PushReadySecurityTests(unittest.TestCase):
    def test_repository_quality_timeout_matches_container_workflow_budget(self):
        workflow = (
            ROOT / ".github" / "workflows" / "container-ci.yml"
        ).read_text(encoding="utf-8")
        self.assertIn("timeout-minutes: 45", workflow)
        self.assertEqual(45 * 60, PUSH_READY.CHECK_TIMEOUT_SECONDS)

    def test_canonical_profile_is_the_single_full_container_ci_entrypoint(self):
        workflow = (
            ROOT / ".github" / "workflows" / "container-ci.yml"
        ).read_text(encoding="utf-8")
        pre_commit = (ROOT / ".pre-commit-config.yaml").read_text(
            encoding="utf-8"
        )
        profile = (ROOT / "scripts" / "lit-ci-profile.sh").read_text(
            encoding="utf-8"
        )
        self.assertEqual(
            1,
            workflow.count("scripts/lit-ci-profile.sh repository-quality"),
        )
        self.assertNotIn("scripts/devtools-container-ci.sh all", workflow)
        self.assertNotIn("container-ci-parity", pre_commit)
        self.assertNotIn(
            "entry: bash scripts/wunder-devtools-ee.sh "
            "scripts/devtools-container-ci.sh all",
            pre_commit,
        )
        self.assertNotIn(
            "entry: scripts/lit-ci-profile.sh repository-quality",
            pre_commit,
        )
        self.assertIn(
            '"$DEVTOOLS_WRAPPER" "$CONTAINER_CI_SCRIPT" all',
            profile,
        )
        for setting in (
            "WUNDER_DEVTOOLS_DOCKER_SOCKET=required",
            "WUNDER_DEVTOOLS_NETWORK=bridge",
            "WUNDER_DEVTOOLS_WORKSPACE_MODE=rw",
        ):
            self.assertIn(setting, profile)

    def test_https_base_fetch_uses_local_credential_helper_with_scoped_token(self):
        completed = subprocess.CompletedProcess([], 0, "", "")
        remote = subprocess.CompletedProcess(
            [], 0, "https://github.com/lightning-it/example.git\n", ""
        )
        remote_runner = mock.Mock(side_effect=[remote, remote])
        fetch_runner = mock.Mock(return_value=completed)
        with mock.patch.dict(
            os.environ,
            {
                **os.environ,
                "GH_TOKEN": "preferred-gh-token",
                "GITHUB_TOKEN": "actions-token-must-be-normalized",
                "COPILOT_GITHUB_TOKEN": "copilot-token-must-not-reach-git",
                "CODEX_API_KEY": "codex-key-must-not-reach-git",
                "AWS_SECRET_ACCESS_KEY": "aws-key-must-not-reach-git",
            },
            clear=True,
        ), mock.patch.object(
            PUSH_READY, "run", remote_runner
        ), mock.patch.object(
            PUSH_READY.subprocess, "run", fetch_runner
        ):
            result = PUSH_READY.fetch_authoritative_base(
                "develop", "refs/remotes/origin/develop"
            )
        self.assertIs(result, completed)
        self.assertEqual(2, remote_runner.call_count)
        fetch_runner.assert_called_once()
        command = fetch_runner.call_args.args[0]
        environment = fetch_runner.call_args.kwargs["env"]
        self.assertNotIn("preferred-gh-token", "\0".join(command))
        self.assertNotIn("actions-token-must-be-normalized", "\0".join(command))
        self.assertEqual("credential.helper", environment["GIT_CONFIG_KEY_0"])
        self.assertEqual("", environment["GIT_CONFIG_VALUE_0"])
        self.assertEqual("credential.helper", environment["GIT_CONFIG_KEY_1"])
        self.assertEqual(
            "!gh auth git-credential", environment["GIT_CONFIG_VALUE_1"]
        )
        self.assertEqual("safe.directory", environment["GIT_CONFIG_KEY_2"])
        self.assertEqual(str(ROOT.resolve()), environment["GIT_CONFIG_VALUE_2"])
        self.assertEqual("3", environment["GIT_CONFIG_COUNT"])
        self.assertEqual("preferred-gh-token", environment["GH_TOKEN"])
        self.assertNotIn("GITHUB_TOKEN", environment)
        for name in (
            "GITHUB_TOKEN",
            "COPILOT_GITHUB_TOKEN",
            "CODEX_API_KEY",
            "AWS_SECRET_ACCESS_KEY",
        ):
            self.assertNotIn(name, environment)
        for call in remote_runner.call_args_list:
            self.assertNotIn("GH_TOKEN", call.kwargs["env"])
            self.assertNotIn("GITHUB_TOKEN", call.kwargs["env"])

    def test_https_base_fetch_normalizes_actions_token_for_gh_helper(self):
        completed = subprocess.CompletedProcess([], 0, "", "")
        remote = subprocess.CompletedProcess(
            [], 0, "https://github.com/lightning-it/example.git\n", ""
        )
        remote_runner = mock.Mock(side_effect=[remote, remote])
        fetch_runner = mock.Mock(return_value=completed)
        with mock.patch.dict(
            os.environ,
            {"GITHUB_TOKEN": "actions-ephemeral-token"},
            clear=True,
        ), mock.patch.object(
            PUSH_READY, "run", remote_runner
        ), mock.patch.object(
            PUSH_READY.subprocess, "run", fetch_runner
        ):
            result = PUSH_READY.fetch_authoritative_base(
                "develop", "refs/remotes/origin/develop"
            )
        self.assertIs(result, completed)
        fetch_environment = fetch_runner.call_args.kwargs["env"]
        self.assertEqual("actions-ephemeral-token", fetch_environment["GH_TOKEN"])
        self.assertNotIn("GITHUB_TOKEN", fetch_environment)
        for call in remote_runner.call_args_list:
            self.assertNotIn("GH_TOKEN", call.kwargs["env"])
            self.assertNotIn("GITHUB_TOKEN", call.kwargs["env"])

    def test_https_base_fetch_rejects_empty_explicit_gh_token(self):
        remote = subprocess.CompletedProcess(
            [], 0, "https://github.com/lightning-it/example.git\n", ""
        )
        remote_runner = mock.Mock(side_effect=[remote, remote])
        fetch_runner = mock.Mock()
        with mock.patch.dict(
            os.environ,
            {"GH_TOKEN": "", "GITHUB_TOKEN": "must-not-be-used"},
            clear=True,
        ), mock.patch.object(
            PUSH_READY, "run", remote_runner
        ), mock.patch.object(
            PUSH_READY.subprocess, "run", fetch_runner
        ), self.assertRaisesRegex(
            RuntimeError, "GitHub HTTPS authentication token is invalid"
        ):
            PUSH_READY.fetch_authoritative_base(
                "develop", "refs/remotes/origin/develop"
            )
        self.assertEqual(2, remote_runner.call_count)
        fetch_runner.assert_not_called()

    def test_base_fetch_rejects_ungoverned_or_mismatched_origin_urls(self):
        for fetch_url, push_url in (
            ("/tmp/untrusted.git", "https://github.com/lightning-it/example.git"),
            (
                "git@github.com:lightning-it/other.git",
                "https://github.com/lightning-it/example.git",
            ),
        ):
            runner = mock.Mock(
                side_effect=[
                    subprocess.CompletedProcess([], 0, fetch_url, ""),
                    subprocess.CompletedProcess([], 0, push_url, ""),
                ]
            )
            with self.subTest(
                fetch_url=fetch_url, push_url=push_url
            ), mock.patch.object(PUSH_READY, "run", runner):
                with self.assertRaises(RuntimeError):
                    PUSH_READY.fetch_authoritative_base(
                        "develop", "refs/remotes/origin/develop"
                    )

    def change(
        self,
        *,
        diff: str = "safe\n",
        paths: tuple[str, ...] = ("safe.txt",),
    ):
        return PUSH_READY.PlannedChange(
            "refs/remotes/origin/develop",
            "1" * 40,
            "1" * 40,
            "2" * 40,
            diff,
            paths,
            {},
            "3" * 64,
        )

    def test_review_rejects_secret_paths_and_content(self):
        with self.assertRaisesRegex(RuntimeError, "secret-like paths"):
            PUSH_READY.ensure_review_safe(
                self.change(paths=("inventories/secrets/runtime.yml",))
            )
        with self.assertRaisesRegex(RuntimeError, "secret-like content"):
            PUSH_READY.ensure_review_safe(
                self.change(diff="+ token = ghp_" + "a" * 36 + "\n")
            )

    def test_streaming_secret_scanner_matches_governed_regexes_at_every_split(self):
        samples = (
            "-----BEGIN PRIVATE KEY-----",
            "client_secret = '" + "a" * 20 + "'",
            "ghp_" + "a" * 24,
            "github_pat_" + "a" * 24,
            "glpat-" + "a" * 24,
            "pypi-" + "a" * 24,
            "npm_" + "a" * 24,
            "sk_live_" + "a" * 20,
            "AKIA" + "A" * 16,
            "AIza" + "a" * 35,
            "xoxb-" + "a" * 24,
            "Bearer " + "a" * 24,
            "eyJ" + "a" * 12 + "." + "b" * 12 + "." + "c" * 12,
            "_authToken = " + "a" * 20,
            "safe content with token-like words only",
            "prefix\r\nnpm_" + "a" * 24 + "\r\nsuffix",
        )
        governed_patterns = (
            *PUSH_READY.SECRET_CONTENT_PATTERNS,
            PUSH_READY.NPMRC_AUTH_PATTERN,
        )
        for sample in samples:
            expected = sum(
                (1 << index) if pattern.search(sample) else 0
                for index, pattern in enumerate(governed_patterns)
            )
            for split in range(len(sample) + 1):
                with self.subTest(sample=sample[:24], split=split):
                    self.assertEqual(
                        expected,
                        PUSH_READY.scan_chunks((sample[:split], sample[split:])),
                    )

    def test_streaming_secret_scanner_preserves_chunk_boundary_and_masking(self):
        token = "npm_" + "a" * 24
        sample = "x" * (PUSH_READY.CHUNK_BYTES - 2) + "\r\n" + token + "\r\n"
        governed_patterns = (
            *PUSH_READY.SECRET_CONTENT_PATTERNS,
            PUSH_READY.NPMRC_AUTH_PATTERN,
        )
        expected = sum(
            (1 << index) if pattern.search(sample) else 0
            for index, pattern in enumerate(governed_patterns)
        )
        for split in (
            PUSH_READY.CHUNK_BYTES - 1,
            PUSH_READY.CHUNK_BYTES,
            PUSH_READY.CHUNK_BYTES + 1,
            len(sample) - 1,
        ):
            self.assertEqual(
                expected,
                PUSH_READY.scan_chunks((sample[:split], sample[split:])),
            )

        fixture = "token = " + "a" * 20
        documented = {
            "fixture.txt": {
                1: (hashlib.sha256(fixture.encode()).hexdigest(), fixture)
            }
        }
        masked = "".join(
            PUSH_READY.filtered_scan_chunks(
                (fixture + "\r\n",),
                documented,
                path="fixture.txt",
                redact=True,
            )
        )
        self.assertEqual("DOCUMENTED_SYNTHETIC_FIXTURE\n", masked)
        self.assertEqual(0, PUSH_READY.scan_chunks((masked,)))

    def test_planned_packer_attribute_stream_is_bounded_and_exact(self):
        output = b"image.pkr.hcl\0filter\0unspecified\0"
        with mock.patch.object(
            PUSH_READY,
            "stream_git",
            return_value=iter((output[:7], output[7:19], output[19:])),
        ):
            names, byte_count, triple_count = (
                PUSH_READY.planned_packer_attribute_names(
                    "image.pkr.hcl", max_bytes=len(output), max_triples=1
                )
            )
        self.assertEqual({"filter"}, names)
        self.assertEqual(len(output), byte_count)
        self.assertEqual(1, triple_count)

        with mock.patch.object(
            PUSH_READY, "stream_git", return_value=iter((output,))
        ):
            with self.assertRaisesRegex(RuntimeError, "byte resource budget"):
                PUSH_READY.planned_packer_attribute_names(
                    "image.pkr.hcl", max_bytes=len(output) - 1, max_triples=1
                )

        two_records = output + b"image.pkr.hcl\0diff\0set\0"
        with mock.patch.object(
            PUSH_READY, "stream_git", return_value=iter((two_records,))
        ):
            with self.assertRaisesRegex(RuntimeError, "triple resource budget"):
                PUSH_READY.planned_packer_attribute_names(
                    "image.pkr.hcl",
                    max_bytes=len(two_records),
                    max_triples=1,
                )

        wrong_path = b"other.pkr.hcl\0filter\0set\0"
        with mock.patch.object(
            PUSH_READY, "stream_git", return_value=iter((wrong_path,))
        ):
            with self.assertRaisesRegex(RuntimeError, "unexpected path"):
                PUSH_READY.planned_packer_attribute_names(
                    "image.pkr.hcl",
                    max_bytes=len(wrong_path),
                    max_triples=1,
                )

    def test_packer_masking_is_limited_to_bare_references_in_packer_files(self):
        reference = "password = var.this_is_a_long_variable_name"

        def scan(path, content, *, allow_packer=True):
            with tempfile.TemporaryDirectory() as directory:
                workspace = Path(directory)
                subprocess.run(
                    ["git", "init", "-q", str(workspace)], check=True
                )
                destination = workspace / path
                destination.parent.mkdir(parents=True, exist_ok=True)
                destination.write_text(content + "\n", encoding="utf-8")
                subprocess.run(
                    ["git", "-C", str(workspace), "add", path], check=True
                )
                PUSH_READY.streaming_workspace_safe(
                    workspace, {}, allow_packer=allow_packer
                )

        scan("image.pkr.hcl", reference)
        rejected = (
            ("image.pkr.hcl", "# " + reference),
            ("image.pkr.hcl", "value = <<EOF\n" + reference + "\nEOF"),
            ("variables.hcl", reference),
            ("image.pkr.hcl", "password = ghp_" + "a" * 24),
            ("image.pkr.hcl", "password = var.npm_" + "a" * 24),
            ("image.pkr.hcl", "password = var.xnpm_" + "a" * 24),
            ("image.pkr.hcl", "password = var.npm_" + "a" * 24 + "_suffix"),
        )
        for path, content in rejected:
            with self.subTest(path=path, content=content[:24]):
                with self.assertRaisesRegex(RuntimeError, "secret-like content"):
                    scan(path, content)

    def test_planned_diff_packer_masking_uses_the_complete_file_boundary(self):
        reference = "password = var.this_is_a_long_variable_name"

        def review(file_content, changed_line=reference):
            patch = (
                "diff --git a/image.pkr.hcl b/image.pkr.hcl\n"
                "--- a/image.pkr.hcl\n"
                "+++ b/image.pkr.hcl\n"
                "@@ -0,0 +1 @@\n"
                f"+{changed_line}\n"
            )
            with tempfile.TemporaryFile() as stream:
                stream.write((file_content + "\n").encode())
                stream.flush()

                def duplicate_file(*_args, **_kwargs):
                    stream.seek(0)
                    return os.dup(stream.fileno())

                with mock.patch.object(
                    PUSH_READY,
                    "open_repository_regular",
                    side_effect=duplicate_file,
                ), mock.patch.object(
                    PUSH_READY,
                    "stream_git",
                    return_value=iter(()),
                ), mock.patch.object(Path, "exists", return_value=True):
                    PUSH_READY.ensure_review_safe(
                        self.change(diff=patch, paths=("image.pkr.hcl",))
                    )

        review(reference)
        rejected = (
            ("# " + reference, "# " + reference),
            ("value = <<EOF\n" + reference + "\nEOF", reference),
            ("password = ghp_" + "a" * 24, "password = ghp_" + "a" * 24),
            (
                "password = var.npm_" + "a" * 24,
                "password = var.npm_" + "a" * 24,
            ),
            (
                "password = var.xnpm_" + "a" * 24,
                "password = var.xnpm_" + "a" * 24,
            ),
            (
                "password = var.npm_" + "a" * 24 + "_suffix",
                "password = var.npm_" + "a" * 24 + "_suffix",
            ),
        )
        for file_content, changed_line in rejected:
            with self.subTest(file_content=file_content[:24]):
                with self.assertRaisesRegex(RuntimeError, "secret-like content"):
                    review(file_content, changed_line)

    def test_documentation_fixture_authorization_is_path_and_purpose_bound(self):
        line = "password = " + "a" * 20

        def manifest(path, purpose, value=line):
            return json.dumps(
                {
                    "version": 1,
                    "fixtures": [
                        {
                            "path": path,
                            "line_hex": value.encode().hex(),
                            "line_number": 1,
                            "purpose": purpose,
                        }
                    ],
                }
            )

        allowed = (
            "README.md",
            "charts/service/README.md",
            "charts/service/README.md.gotmpl",
            "charts/service/values.yaml",
            "charts/parent/charts/child/README.md",
        )
        for path in allowed:
            with self.subTest(path=path):
                parsed = PUSH_READY.parse_secret_fixture_manifest(
                    manifest(path, "synthetic-documentation-example")
                )
                self.assertIn(path, parsed)

        rejected = (
            ("docs/README.md", "synthetic-documentation-example", line),
            ("tests/example.txt", "synthetic-documentation-example", line),
            ("README.md", "synthetic-test-fixture", line),
            (
                "README.md",
                "synthetic-documentation-example",
                "-----BEGIN PRIVATE KEY-----",
            ),
        )
        for path, purpose, value in rejected:
            with self.subTest(path=path, purpose=purpose, value=value[:24]):
                with self.assertRaisesRegex(RuntimeError, "unsafe path|PEM"):
                    PUSH_READY.parse_secret_fixture_manifest(
                        manifest(path, purpose, value)
                    )

    def test_fingerprint_hashing_enforces_file_and_aggregate_limits(self):
        class CountingStream(io.BytesIO):
            def __init__(self, value):
                super().__init__(value)
                self.read_sizes = []

            def read(self, size=-1):
                self.read_sizes.append(size)
                return super().read(size)

        stream = CountingStream(b"123456")
        with self.assertRaisesRegex(RuntimeError, "Fingerprint input exceeds 5 bytes"):
            PUSH_READY.hash_open_file(
                stream,
                max_bytes=5,
                purpose="Fingerprint",
            )
        self.assertEqual([6], stream.read_sizes)

        exhausted = CountingStream(b"x" * PUSH_READY.CHUNK_BYTES)
        with self.assertRaisesRegex(RuntimeError, "Fingerprint input exceeds 0 bytes"):
            PUSH_READY.hash_open_file(
                exhausted,
                max_bytes=0,
                purpose="Fingerprint",
            )
        self.assertEqual([1], exhausted.read_sizes)

        limits = []

        def bounded_hash(*_args, max_bytes, **_kwargs):
            limits.append(max_bytes)
            return "a" * 64, 100_000_000

        with mock.patch.object(
            PUSH_READY,
            "git_output_at",
            return_value=(
                "\0".join(f"file-{value}.bin" for value in range(6)) + "\0"
            ),
        ), mock.patch.object(
            PUSH_READY,
            "hash_repository_file",
            side_effect=bounded_hash,
        ), mock.patch.object(PUSH_READY, "fingerprint_stream") as fingerprint:
            with self.assertRaisesRegex(RuntimeError, "500000000 total bytes"):
                PUSH_READY.integration_worktree_fingerprint(ROOT)
        fingerprint.assert_not_called()
        self.assertEqual([100_000_000] * 5 + [0], limits)

        limits.clear()
        with mock.patch.object(
            PUSH_READY,
            "untracked_names",
            return_value=[f"file-{value}.bin" for value in range(6)],
        ), mock.patch.object(
            PUSH_READY,
            "hash_repository_file",
            side_effect=bounded_hash,
        ):
            with self.assertRaisesRegex(RuntimeError, "500000000 total bytes"):
                PUSH_READY.untracked_file_hashes()
        self.assertEqual([100_000_000] * 5 + [0], limits)

    def test_safe_open_refuses_symlink(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            target = root / "target"
            target.write_text("safe\n", encoding="utf-8")
            (root / "link").symlink_to(target)
            with self.assertRaisesRegex(RuntimeError, "safely inspect"):
                PUSH_READY.open_regular_below(
                    root,
                    "link",
                    purpose="Test",
                )

    def test_trusted_policy_rejects_a_changed_policy_entry(self):
        change = self.change()

        def tree_entry(commit, _path):
            return "base-entry" if commit == change.base_tip else "head-entry"

        with mock.patch.object(
            PUSH_READY,
            "git_tree_entry",
            side_effect=tree_entry,
        ):
            with self.assertRaisesRegex(
                RuntimeError,
                "executable check policy differs",
            ):
                PUSH_READY.require_trusted_check_policy(change)

    def test_pre_push_rejects_an_unreviewed_commit(self):
        remote_url = (
            "https://github.com/lightning-it/"
            "container-ee-wunder-devtools-ubi9.git"
        )
        branch = "refs/heads/feature/example"
        payload = {
            "push_remote": PUSH_READY.governed_push_remote_from_url(
                "origin",
                remote_url,
            ),
            "head_commit": "2" * 40,
            "local_branch_ref": branch,
        }
        update = f"{branch} {'4' * 40} {branch} {'0' * 40}\n"
        with mock.patch.object(
            PUSH_READY,
            "git_output",
            return_value="4" * 40,
        ):
            with self.assertRaisesRegex(RuntimeError, "not bound"):
                PUSH_READY.verify_pre_push_updates(
                    payload,
                    update,
                    remote_name="origin",
                    remote_url=remote_url,
                )


if __name__ == "__main__":
    unittest.main()
