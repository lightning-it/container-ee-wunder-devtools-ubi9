"""Materialize and re-verify the bounded MLX-90 exact-revision review input."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import stat
import subprocess
import sys
import tempfile
from collections.abc import Sequence
from pathlib import Path
from typing import Any, NoReturn

SHA1_PATTERN = re.compile(r"^[0-9a-f]{40}$")
REPOSITORY_PATTERN = re.compile(r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$")
RELEASE_BOT = "lightning-it-release-automation[bot]"
MAX_REVIEW_BYTES = 200_000
MAX_PROTECTED_ASSET_BYTES = 1_000_000
ASSET_ARGUMENTS = {
    "materializer_sha256": "materializer_path",
    "prompt_sha256": "prompt_path",
    "schema_sha256": "schema_path",
    "workflow_sha256": "workflow_path",
}
IMMUTABLE_METADATA_KEYS = (
    "schema_version",
    "repository",
    "pull_request",
    "base_ref",
    "base_sha",
    "head_sha",
    "merge_base_sha",
    "integration_tree_sha",
    "diff_sha256",
    "review_bytes",
    "trusted_workflow_sha",
    "trigger",
    "materializer_sha256",
    "prompt_sha256",
    "schema_sha256",
    "workflow_sha256",
    "input_sha256",
)


class MaterializationError(RuntimeError):
    """Raised when the exact review input cannot be proven."""


def fail(message: str) -> NoReturn:
    raise MaterializationError(message)


def executable(name: str) -> str:
    resolved = shutil.which(name, path=os.defpath)
    if resolved is None:
        fail(f"Required executable is unavailable in the system path: {name}")
    return resolved


def command_environment(*, home: Path, include_token: bool) -> dict[str, str]:
    environment = {
        "GIT_CONFIG_GLOBAL": os.devnull,
        "GIT_CONFIG_NOSYSTEM": "1",
        "GIT_TERMINAL_PROMPT": "0",
        "HOME": str(home),
        "LANG": "C.UTF-8",
        "LC_ALL": "C.UTF-8",
        "PATH": os.defpath,
        "XDG_CONFIG_HOME": str(home / ".config"),
    }
    if include_token:
        token = os.environ.get("GH_TOKEN", "")
        if not token:
            fail("GH_TOKEN is required for live GitHub verification.")
        environment["GH_TOKEN"] = token
    return environment


def run(
    arguments: Sequence[str],
    *,
    environment: dict[str, str],
    cwd: Path | None = None,
    binary: bool = False,
) -> subprocess.CompletedProcess[Any]:
    result = subprocess.run(  # noqa: S603
        list(arguments),
        cwd=cwd,
        env=environment,
        check=False,
        capture_output=True,
        text=not binary,
    )
    if result.returncode != 0:
        stderr = (
            result.stderr
            if isinstance(result.stderr, str)
            else result.stderr.decode(errors="replace")
        )
        command = " ".join(arguments) or "<empty-command>"
        fail(f"Command failed closed: {command}: {stderr.strip()}")
    return result


def require_sha(value: str, name: str) -> str:
    if not SHA1_PATTERN.fullmatch(value):
        fail(f"{name} must be a full lowercase SHA-1 object ID.")
    return value


def require_single_sha_output(value: str, name: str) -> str:
    lines = value.splitlines()
    if len(lines) != 1:
        fail(f"{name} must contain exactly one Git object ID.")
    return require_sha(lines[0], name)


def protected_asset_bytes(path: Path, name: str) -> bytes:
    """Read one bounded regular protected asset without following a symlink."""
    no_follow = getattr(os, "O_NOFOLLOW", None)
    if not isinstance(no_follow, int) or no_follow == 0:
        fail("Protected asset reading requires O_NOFOLLOW support.")
    flags = os.O_RDONLY
    flags |= getattr(os, "O_CLOEXEC", 0)
    flags |= no_follow
    try:
        descriptor = os.open(path, flags)
    except OSError as error:
        fail(f"Protected {name} is unavailable: {error}")
    try:
        details = os.fstat(descriptor)
        if not stat.S_ISREG(details.st_mode):
            fail(f"Protected {name} must be a regular non-symlink file.")
        if details.st_size <= 0 or details.st_size > MAX_PROTECTED_ASSET_BYTES:
            fail(f"Protected {name} must contain 1..{MAX_PROTECTED_ASSET_BYTES} bytes.")
        with os.fdopen(descriptor, "rb", closefd=False) as protected_asset:
            payload = protected_asset.read(MAX_PROTECTED_ASSET_BYTES + 1)
        if len(payload) != details.st_size:
            fail(f"Protected {name} changed while reading.")
        return payload
    finally:
        os.close(descriptor)


def bind_protected_assets(
    metadata: dict[str, Any], asset_paths: dict[str, Path]
) -> dict[str, Any]:
    """Bind every base-controlled review asset into one canonical input hash."""
    if set(asset_paths) != set(ASSET_ARGUMENTS):
        fail("The complete protected review-asset set is required.")
    bound = dict(metadata)
    for metadata_key, path in asset_paths.items():
        asset_name = metadata_key.removesuffix("_sha256").replace("_", " ")
        bound[metadata_key] = hashlib.sha256(
            protected_asset_bytes(path, asset_name)
        ).hexdigest()
    canonical = json.dumps(bound, sort_keys=True, separators=(",", ":")).encode("utf-8")
    bound["input_sha256"] = hashlib.sha256(canonical).hexdigest()
    return bound


def asset_paths_from_arguments(arguments: argparse.Namespace) -> dict[str, Path]:
    paths: dict[str, Path] = {}
    for metadata_key, argument_name in ASSET_ARGUMENTS.items():
        path = getattr(arguments, argument_name, None)
        if not isinstance(path, Path):
            fail(f"Protected asset argument is required: {argument_name}")
        paths[metadata_key] = path
    return paths


def validate_inputs(arguments: argparse.Namespace) -> None:
    if not REPOSITORY_PATTERN.fullmatch(arguments.repository):
        fail("Repository must use the owner/name form.")
    if arguments.pull_request <= 0:
        fail("Pull-request number must be positive.")
    if arguments.base_ref not in {"develop", "main"}:
        fail("Base ref must be develop or main.")
    require_sha(arguments.expected_base, "Expected base")
    require_sha(arguments.expected_head, "Expected head")
    require_sha(arguments.trusted_workflow_sha, "Trusted workflow")
    if arguments.expected_base != arguments.trusted_workflow_sha:
        fail("The protected workflow SHA must equal the live pull-request base SHA.")
    if arguments.trigger not in {"ready_for_review", "app_dispatch"}:
        fail("Unsupported exact-review trigger.")
    if (
        arguments.trigger == "app_dispatch"
        and arguments.dispatch_ref != f"refs/heads/{arguments.base_ref}"
    ):
        fail("App dispatch must execute from the protected pull-request base ref.")


def read_live_pull_request(
    arguments: argparse.Namespace, *, home: Path
) -> dict[str, Any]:
    gh = executable("gh")
    result = run(
        [
            gh,
            "api",
            f"repos/{arguments.repository}/pulls/{arguments.pull_request}",
        ],
        environment=command_environment(home=home, include_token=True),
    )
    try:
        pull_request = json.loads(result.stdout)
    except json.JSONDecodeError as error:
        fail(f"GitHub returned malformed pull-request JSON: {error}")
    expected = {
        "state": "open",
        "draft": False,
        "author": RELEASE_BOT,
        "author_type": "Bot",
        "base_ref": arguments.base_ref,
        "base_sha": arguments.expected_base,
        "base_repository": arguments.repository,
        "head_sha": arguments.expected_head,
        "head_repository": arguments.repository,
    }
    user = pull_request.get("user") or {}
    base = pull_request.get("base") or {}
    head = pull_request.get("head") or {}
    base_repository = base.get("repo") or {}
    head_repository = head.get("repo") or {}
    observed = {
        "state": pull_request.get("state"),
        "draft": pull_request.get("draft"),
        "author": user.get("login"),
        "author_type": user.get("type"),
        "base_ref": base.get("ref"),
        "base_sha": base.get("sha"),
        "base_repository": base_repository.get("full_name"),
        "head_sha": head.get("sha"),
        "head_repository": head_repository.get("full_name"),
    }
    if observed != expected:
        fail(
            f"Live pull-request binding changed or is unauthorized: {json.dumps(observed, sort_keys=True)}"
        )
    return pull_request


def git_output(
    git: str,
    git_dir: Path,
    arguments: Sequence[str],
    *,
    environment: dict[str, str],
    binary: bool = False,
) -> bytes | str:
    result = run(
        [git, f"--git-dir={git_dir}", *arguments],
        environment=environment,
        binary=binary,
    )
    return result.stdout


def materialize(
    arguments: argparse.Namespace, output_directory: Path
) -> dict[str, Any]:
    validate_inputs(arguments)
    if output_directory.exists():
        fail(f"Review workspace already exists: {output_directory}")
    try:
        output_directory.mkdir(mode=0o700, parents=False)
    except OSError as error:
        fail(f"Unable to create the exact-revision review workspace: {error}")

    runner_temp = Path(os.environ.get("RUNNER_TEMP", tempfile.gettempdir())).resolve()
    if not runner_temp.is_dir():
        fail("RUNNER_TEMP must identify an existing directory.")
    with tempfile.TemporaryDirectory(
        prefix="exact-revision-materializer.", dir=runner_temp
    ) as temporary:
        temporary_root = Path(temporary)
        home = temporary_root / "home"
        home.mkdir(mode=0o700)
        read_live_pull_request(arguments, home=home)

        git = executable("git")
        git_dir = temporary_root / "objects.git"
        git_environment = command_environment(home=home, include_token=True)
        run([git, "init", "--bare", str(git_dir)], environment=git_environment)
        git_output(
            git,
            git_dir,
            ["config", "credential.helper", "!gh auth git-credential"],
            environment=git_environment,
        )
        git_output(
            git,
            git_dir,
            [
                "remote",
                "add",
                "origin",
                f"https://github.com/{arguments.repository}.git",
            ],
            environment=git_environment,
        )
        git_output(
            git,
            git_dir,
            [
                "fetch",
                "--quiet",
                "--no-tags",
                "--no-recurse-submodules",
                "origin",
                f"+{arguments.expected_base}:refs/review/base",
                f"+{arguments.expected_head}:refs/review/head",
            ],
            environment=git_environment,
        )
        for name, expected in (
            ("base", arguments.expected_base),
            ("head", arguments.expected_head),
        ):
            resolved = str(
                git_output(
                    git,
                    git_dir,
                    ["rev-parse", f"refs/review/{name}^{{commit}}"],
                    environment=git_environment,
                )
            ).strip()
            if resolved != expected:
                fail(f"Fetched {name} object does not equal the expected object ID.")

        merge_base = require_single_sha_output(
            str(
                git_output(
                    git,
                    git_dir,
                    [
                        "merge-base",
                        "--all",
                        arguments.expected_base,
                        arguments.expected_head,
                    ],
                    environment=git_environment,
                )
            ),
            "Merge base",
        )

        integration_tree = require_single_sha_output(
            str(
                git_output(
                    git,
                    git_dir,
                    [
                        "merge-tree",
                        "--write-tree",
                        arguments.expected_base,
                        arguments.expected_head,
                    ],
                    environment=git_environment,
                )
            ),
            "Integration tree",
        )
        object_type = str(
            git_output(
                git,
                git_dir,
                ["cat-file", "-t", integration_tree],
                environment=git_environment,
            )
        ).strip()
        if object_type != "tree":
            fail("The integration object is not a Git tree.")

        diff = git_output(
            git,
            git_dir,
            [
                "diff",
                "--binary",
                "--full-index",
                "--no-color",
                "--no-ext-diff",
                "--no-textconv",
                f"{arguments.expected_base}^{{tree}}",
                integration_tree,
            ],
            environment=git_environment,
            binary=True,
        )
        if not isinstance(diff, bytes):
            fail("Git returned an invalid diff representation.")
        review_bytes = len(diff)
        if review_bytes <= 0 or review_bytes >= MAX_REVIEW_BYTES:
            fail(
                "Exact-revision review input must contain "
                f"1..{MAX_REVIEW_BYTES - 1} bytes; observed {review_bytes}."
            )
        diff_sha256 = hashlib.sha256(diff).hexdigest()

        read_live_pull_request(arguments, home=home)
        metadata = {
            "schema_version": 3,
            "repository": arguments.repository,
            "pull_request": arguments.pull_request,
            "base_ref": arguments.base_ref,
            "base_sha": arguments.expected_base,
            "head_sha": arguments.expected_head,
            "merge_base_sha": merge_base,
            "integration_tree_sha": integration_tree,
            "diff_sha256": diff_sha256,
            "review_bytes": review_bytes,
            "trusted_workflow_sha": arguments.trusted_workflow_sha,
            "trigger": arguments.trigger,
        }
        patch = output_directory / "change.patch"
        metadata_path = output_directory / "review-metadata.json"
        patch.write_bytes(diff)
        metadata_path.write_text(
            json.dumps(metadata, indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )
        patch.chmod(0o600)
        metadata_path.chmod(0o600)
        return metadata


def bind_assets(review_directory: Path, asset_paths: dict[str, Path]) -> dict[str, Any]:
    metadata_path = review_directory / "review-metadata.json"
    if not metadata_path.is_file() or metadata_path.is_symlink():
        fail("Review metadata must be a regular, non-symlink file.")
    try:
        metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, UnicodeDecodeError) as error:
        fail(f"Review metadata is malformed: {error}")
    if any(key in metadata for key in (*ASSET_ARGUMENTS, "input_sha256")):
        fail("Review metadata already contains protected asset bindings.")
    bound = bind_protected_assets(metadata, asset_paths)
    metadata_path.write_text(
        json.dumps(bound, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    return bound


def verify(
    arguments: argparse.Namespace,
    review_directory: Path,
    asset_paths: dict[str, Path],
) -> dict[str, Any]:
    validate_inputs(arguments)
    patch = review_directory / "change.patch"
    metadata_path = review_directory / "review-metadata.json"
    if (
        not patch.is_file()
        or patch.is_symlink()
        or not metadata_path.is_file()
        or metadata_path.is_symlink()
    ):
        fail("The review diff and metadata must be regular, non-symlink files.")
    patch_size = patch.stat().st_size
    if patch_size <= 0 or patch_size >= MAX_REVIEW_BYTES:
        fail(f"The review diff must be between 1 and {MAX_REVIEW_BYTES - 1} bytes.")
    try:
        expected_metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, UnicodeDecodeError) as error:
        fail(f"Review metadata is malformed: {error}")
    if not isinstance(expected_metadata, dict):
        fail("Review metadata must be a JSON object.")
    expected_keys = set(IMMUTABLE_METADATA_KEYS)
    observed_keys = set(expected_metadata)
    if observed_keys != expected_keys:
        missing = sorted(expected_keys - observed_keys)
        unexpected = sorted(observed_keys - expected_keys)
        fail(
            "Review metadata keys differ from the protected materializer output: "
            f"missing={missing}, unexpected={unexpected}"
        )

    runner_temp = Path(os.environ.get("RUNNER_TEMP", tempfile.gettempdir())).resolve()
    if not runner_temp.is_dir():
        fail("RUNNER_TEMP must identify an existing directory.")
    with tempfile.TemporaryDirectory(
        prefix="exact-revision-recheck.", dir=runner_temp
    ) as temporary:
        regenerated = Path(temporary) / "review"
        actual_metadata = bind_protected_assets(
            materialize(arguments, regenerated), asset_paths
        )
        if patch.read_bytes() != (regenerated / "change.patch").read_bytes():
            fail("The full binary diff changed during exact-revision verification.")
    for key in IMMUTABLE_METADATA_KEYS:
        if expected_metadata.get(key) != actual_metadata.get(key):
            fail(f"Exact-revision metadata changed during verification: {key}")
    return actual_metadata


def parse_arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("mode", choices=("materialize", "bind-assets", "verify"))
    parser.add_argument("--repository", required=True)
    parser.add_argument("--pull-request", required=True, type=int)
    parser.add_argument("--base-ref", required=True)
    parser.add_argument("--expected-base", required=True)
    parser.add_argument("--expected-head", required=True)
    parser.add_argument("--trusted-workflow-sha", required=True)
    parser.add_argument(
        "--trigger", required=True, choices=("ready_for_review", "app_dispatch")
    )
    parser.add_argument("--dispatch-ref", default="")
    parser.add_argument("--review-directory", required=True, type=Path)
    parser.add_argument("--materializer-path", type=Path)
    parser.add_argument("--prompt-path", type=Path)
    parser.add_argument("--schema-path", type=Path)
    parser.add_argument("--workflow-path", type=Path)
    return parser.parse_args()


def main() -> int:
    arguments = parse_arguments()
    try:
        if arguments.mode == "materialize":
            metadata = materialize(arguments, arguments.review_directory)
        elif arguments.mode == "bind-assets":
            metadata = bind_assets(
                arguments.review_directory, asset_paths_from_arguments(arguments)
            )
        else:
            metadata = verify(
                arguments,
                arguments.review_directory,
                asset_paths_from_arguments(arguments),
            )
    except MaterializationError as error:
        print(f"error: {error}", file=sys.stderr)
        return 1
    print(json.dumps(metadata, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
