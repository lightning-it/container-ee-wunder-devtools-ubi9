import importlib.util
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

    def test_https_base_fetch_uses_scoped_header_not_argv(self):
        completed = object()
        runner = mock.Mock(return_value=completed)
        with mock.patch.object(
            PUSH_READY,
            "git_output",
            side_effect=[
                "https://github.com/lightning-it/example.git\n",
                "https://github.com/lightning-it/example.git\n",
            ],
        ), mock.patch.object(
            PUSH_READY,
            "github_https_authorization",
            return_value="AUTHORIZATION: basic masked-value",
        ), mock.patch.object(PUSH_READY.subprocess, "run", runner):
            result = PUSH_READY.fetch_authoritative_base(
                "develop", "refs/remotes/origin/develop"
            )
        self.assertIs(result, completed)
        self.assertNotIn("masked-value", " ".join(runner.call_args.args[0]))
        self.assertEqual(
            "AUTHORIZATION: basic masked-value",
            runner.call_args.kwargs["env"]["GIT_CONFIG_VALUE_0"],
        )

    def test_base_fetch_rejects_mismatched_fetch_and_push_repositories(self):
        with mock.patch.object(
            PUSH_READY,
            "git_output",
            side_effect=[
                "git@github.com:lightning-it/other.git",
                "https://github.com/lightning-it/example.git",
            ],
        ):
            with self.assertRaisesRegex(RuntimeError, "same governed repository"):
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
