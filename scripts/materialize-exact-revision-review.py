"""Materialize the bounded REP-60 / MLX-90 section 7.2 review input."""

# Canonical formatting contract: Ruff-compatible Python with line length 120.

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import secrets
import selectors
import shutil
import stat
import subprocess
import sys
import tempfile
import time
from collections.abc import Sequence
from pathlib import Path
from typing import Any, NoReturn

SHA1_PATTERN = re.compile(r"^[0-9a-f]{40}$")
REPOSITORY_PATTERN = re.compile(r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$")
RELEASE_BOT = "lightning-it-release-automation[bot]"
MAX_REVIEW_BYTES = 200_000
MAX_PROTECTED_ASSET_BYTES = 1_000_000
COMMAND_TIMEOUT_SECONDS = 120
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
    try:
        result = subprocess.run(  # noqa: S603
            list(arguments),
            cwd=cwd,
            env=environment,
            check=False,
            capture_output=True,
            text=not binary,
            timeout=COMMAND_TIMEOUT_SECONDS,
        )
    except subprocess.TimeoutExpired:
        command = " ".join(arguments) or "<empty-command>"
        fail(f"Command timed out after {COMMAND_TIMEOUT_SECONDS} seconds: {command}")
    if result.returncode != 0:
        stderr = result.stderr if isinstance(result.stderr, str) else result.stderr.decode(errors="replace")
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


def close_descriptor_after_error(
    descriptor: int,
    label: str,
    *,
    first_error: OSError | None = None,
) -> list[str]:
    """Attempt one close and never reuse a descriptor after an ambiguous error."""
    if first_error is not None:
        return [f"{label} close failed: {first_error}"]
    try:
        os.close(descriptor)
    except OSError as error:
        # POSIX does not make a failed close safe to retry. The numeric
        # descriptor may already have been released and reused by another
        # thread, so neither fstat() nor another close() may touch it.
        return [f"{label} close failed: {error}"]
    return []


def add_error_notes(error: BaseException, notes: Sequence[str]) -> None:
    """Attach cleanup details without requiring Python 3.11 exception notes."""
    add_note = getattr(error, "add_note", None)
    if callable(add_note):
        for note in notes:
            add_note(note)


def fail_after_descriptor_cleanup(message: str, descriptor: int, label: str) -> NoReturn:
    """Raise one proof error after deterministically cleaning up its descriptor."""
    cleanup_errors = close_descriptor_after_error(descriptor, label)
    failure = MaterializationError(message)
    add_error_notes(failure, cleanup_errors)
    raise failure


def open_owned_parent_directory(path: Path, name: str, requirement: str) -> tuple[int, int, int]:
    """Return the final parent fd plus O_NOFOLLOW and O_CLOEXEC flag values."""
    no_follow = getattr(os, "O_NOFOLLOW", None)
    if not isinstance(no_follow, int) or no_follow == 0:
        fail(f"{requirement} requires O_NOFOLLOW support.")
    if path.name in {"", ".", ".."}:
        fail(f"Protected {name} path is invalid.")
    close_on_exec = getattr(os, "O_CLOEXEC", 0)
    directory_flags = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0) | no_follow
    directory_flags |= close_on_exec
    directory = -1
    try:
        parent = path.parent
        if parent.is_absolute():
            directory = os.open(parent.anchor, directory_flags)
            components = parent.parts[1:]
        else:
            directory = os.open(".", directory_flags)
            components = parent.parts
        for component in components:
            if component in {"", "."}:
                continue
            if component == "..":
                fail(f"Protected {name} parent traversal is forbidden.")
            next_directory = os.open(component, directory_flags, dir_fd=directory)
            previous_directory = directory
            try:
                os.close(previous_directory)
            except OSError as close_error:
                cleanup_errors = close_descriptor_after_error(
                    previous_directory,
                    "Previous parent directory",
                    first_error=close_error,
                )
                cleanup_errors.extend(
                    close_descriptor_after_error(
                        next_directory,
                        "New parent directory",
                    )
                )
                directory = -1
                failure = MaterializationError(f"Protected {name} parent cannot be opened safely: {close_error}")
                add_error_notes(failure, cleanup_errors)
                raise failure from close_error
            directory = next_directory
    except OSError as error:
        cleanup_errors = []
        if directory >= 0:
            cleanup_errors = close_descriptor_after_error(
                directory,
                "Current parent directory",
            )
            directory = -1
        failure = MaterializationError(f"Protected {name} parent cannot be opened safely: {error}")
        add_error_notes(failure, cleanup_errors)
        raise failure from error
    except BaseException as error:
        if directory >= 0:
            cleanup_errors = close_descriptor_after_error(
                directory,
                "Current parent directory",
            )
            add_error_notes(error, cleanup_errors)
        raise
    try:
        parent_details = os.fstat(directory)
    except OSError as error:
        cleanup_errors = close_descriptor_after_error(
            directory,
            "Validated parent directory",
        )
        failure = MaterializationError(f"Protected {name} parent cannot be inspected safely: {error}")
        add_error_notes(failure, cleanup_errors)
        raise failure from error
    if not stat.S_ISDIR(parent_details.st_mode):
        fail_after_descriptor_cleanup(
            f"Protected {name} parent must be a directory.",
            directory,
            "Validated parent directory",
        )
    if parent_details.st_uid != os.geteuid():
        fail_after_descriptor_cleanup(
            f"Protected {name} parent must be owned by the current user.",
            directory,
            "Validated parent directory",
        )
    return directory, no_follow, close_on_exec


def protected_asset_bytes(path: Path, name: str) -> bytes:
    """Read one bounded regular protected asset through an anchored parent chain."""
    directory, no_follow, close_on_exec = open_owned_parent_directory(
        path,
        name,
        "Protected asset reading",
    )
    descriptor = -1
    try:
        try:
            descriptor = os.open(
                path.name,
                os.O_RDONLY | no_follow | close_on_exec,
                dir_fd=directory,
            )
        except OSError as error:
            fail(f"Protected {name} is unavailable: {error}")
        details = os.fstat(descriptor)
        if not stat.S_ISREG(details.st_mode) or details.st_nlink != 1:
            fail(f"Protected {name} must be one regular non-symlink file.")
        if details.st_uid != os.geteuid():
            fail(f"Protected {name} must be owned by the current user.")
        if details.st_size <= 0 or details.st_size > MAX_PROTECTED_ASSET_BYTES:
            fail(f"Protected {name} must contain 1..{MAX_PROTECTED_ASSET_BYTES} bytes.")
        with os.fdopen(descriptor, "rb", closefd=False) as protected_asset:
            payload = protected_asset.read(MAX_PROTECTED_ASSET_BYTES + 1)
        if len(payload) != details.st_size:
            fail(f"Protected {name} changed while reading.")
        return payload
    finally:
        active_error = sys.exc_info()[1]
        cleanup_errors = []
        if descriptor >= 0:
            cleanup_errors.extend(
                close_descriptor_after_error(
                    descriptor,
                    f"Protected {name} file descriptor",
                )
            )
        cleanup_errors.extend(
            close_descriptor_after_error(
                directory,
                f"Protected {name} parent directory",
            )
        )
        if cleanup_errors:
            if active_error is None:
                failure = MaterializationError(f"Protected {name} descriptors could not be closed safely.")
                add_error_notes(failure, cleanup_errors)
                raise failure
            add_error_notes(active_error, cleanup_errors)


def write_owned_regular_file(path: Path, payload: bytes, name: str) -> None:
    """Replace a bounded owned file without following its parent chain or target."""
    if len(payload) <= 0 or len(payload) > MAX_PROTECTED_ASSET_BYTES:
        fail(f"Protected {name} must contain 1..{MAX_PROTECTED_ASSET_BYTES} bytes.")
    directory, no_follow, close_on_exec = open_owned_parent_directory(
        path,
        name,
        "Protected file writing",
    )
    temporary_name = f".mlx90-protected-{secrets.token_hex(16)}.tmp"
    temporary_descriptor = -1
    replaced = False
    try:
        existing_descriptor = -1
        try:
            existing_descriptor = os.open(
                path.name,
                os.O_RDONLY | no_follow | close_on_exec,
                dir_fd=directory,
            )
        except FileNotFoundError:
            pass
        except OSError as error:
            fail(f"Protected {name} cannot be opened safely: {error}")
        try:
            if existing_descriptor >= 0:
                existing = os.fstat(existing_descriptor)
                if not stat.S_ISREG(existing.st_mode) or existing.st_nlink != 1:
                    fail(f"Protected {name} must be one regular non-symlink file.")
                if existing.st_uid != os.geteuid():
                    fail(f"Protected {name} must be owned by the current user.")
        finally:
            if existing_descriptor >= 0:
                descriptor_to_close = existing_descriptor
                existing_descriptor = -1
                active_error = sys.exc_info()[1]
                cleanup_errors = close_descriptor_after_error(
                    descriptor_to_close,
                    f"Protected {name} existing descriptor",
                )
                if active_error is None and cleanup_errors:
                    failure = MaterializationError(f"Protected {name} existing descriptor could not be closed safely.")
                    add_error_notes(failure, cleanup_errors)
                    raise failure
                if active_error is not None:
                    add_error_notes(active_error, cleanup_errors)

        temporary_descriptor = os.open(
            temporary_name,
            os.O_RDWR | os.O_CREAT | os.O_EXCL | no_follow | close_on_exec,
            0o600,
            dir_fd=directory,
        )
        temporary = os.fstat(temporary_descriptor)
        if not stat.S_ISREG(temporary.st_mode) or temporary.st_nlink != 1:
            fail(f"Protected {name} temporary file is not a single regular file.")
        if temporary.st_uid != os.geteuid():
            fail(f"Protected {name} temporary file has an unexpected owner.")
        os.fchmod(temporary_descriptor, 0o600)
        remaining = memoryview(payload)
        while remaining:
            written = os.write(temporary_descriptor, remaining)
            if written <= 0:
                fail(f"Protected {name} was not written completely.")
            remaining = remaining[written:]
        os.fsync(temporary_descriptor)
        temporary = os.fstat(temporary_descriptor)
        if (
            not stat.S_ISREG(temporary.st_mode)
            or temporary.st_nlink != 1
            or temporary.st_uid != os.geteuid()
            or temporary.st_size != len(payload)
        ):
            fail(f"Protected {name} temporary file changed while writing.")
        os.lseek(temporary_descriptor, 0, os.SEEK_SET)
        with os.fdopen(temporary_descriptor, "rb", closefd=False) as protected_file:
            if protected_file.read(len(payload) + 1) != payload:
                fail(f"Protected {name} temporary content changed while writing.")
        descriptor_to_close = temporary_descriptor
        temporary_descriptor = -1
        cleanup_errors = close_descriptor_after_error(
            descriptor_to_close,
            f"Protected {name} temporary descriptor",
        )
        if cleanup_errors:
            failure = MaterializationError(f"Protected {name} temporary descriptor could not be closed safely.")
            add_error_notes(failure, cleanup_errors)
            raise failure

        os.replace(
            temporary_name,
            path.name,
            src_dir_fd=directory,
            dst_dir_fd=directory,
        )
        replaced = True
        # The atomic replace is the commit point. Some filesystems do not
        # support directory fsync; no post-commit durability probe may turn a
        # complete replacement into a reported partial-write failure.
        try:
            os.fsync(directory)
        except OSError:
            pass
    except OSError as error:
        failure = MaterializationError(f"Protected {name} cannot be written atomically: {error}")
        add_error_notes(failure, getattr(error, "__notes__", ()))
        raise failure from error
    finally:
        active_error = sys.exc_info()[1]
        final_cleanup_errors: list[str] = []
        if temporary_descriptor >= 0:
            descriptor_to_close = temporary_descriptor
            temporary_descriptor = -1
            final_cleanup_errors.extend(
                close_descriptor_after_error(
                    descriptor_to_close,
                    f"Protected {name} temporary descriptor",
                )
            )
        if not replaced:
            try:
                os.unlink(temporary_name, dir_fd=directory)
            except FileNotFoundError:
                pass
            except OSError as cleanup_error:
                final_cleanup_errors.append(f"Protected {name} temporary cleanup also failed: {cleanup_error}")
        final_cleanup_errors.extend(
            close_descriptor_after_error(
                directory,
                f"Protected {name} parent directory",
            )
        )
        if final_cleanup_errors:
            if active_error is None:
                failure = MaterializationError(f"Protected {name} cleanup failed closed.")
                add_error_notes(failure, final_cleanup_errors)
                raise failure
            add_error_notes(active_error, final_cleanup_errors)


def bind_protected_assets(metadata: dict[str, Any], asset_paths: dict[str, Path]) -> dict[str, Any]:
    """Bind every base-controlled review asset into one canonical input hash."""
    if set(asset_paths) != set(ASSET_ARGUMENTS):
        fail("The complete protected review-asset set is required.")
    bound = dict(metadata)
    for metadata_key, path in asset_paths.items():
        asset_name = metadata_key.removesuffix("_sha256").replace("_", " ")
        bound[metadata_key] = hashlib.sha256(protected_asset_bytes(path, asset_name)).hexdigest()
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
    if arguments.trigger == "app_dispatch" and arguments.dispatch_ref != f"refs/heads/{arguments.base_ref}":
        fail("App dispatch must execute from the protected pull-request base ref.")


def read_live_pull_request(arguments: argparse.Namespace, *, home: Path) -> dict[str, Any]:
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
        fail(f"Live pull-request binding changed or is unauthorized: {json.dumps(observed, sort_keys=True)}")
    return pull_request


def git_output(
    git: str,
    git_dir: Path,
    arguments: Sequence[str],
    *,
    environment: dict[str, str],
    binary: bool = False,
    max_bytes: int | None = None,
) -> bytes | str:
    command = [git, f"--git-dir={git_dir}", *arguments]
    if max_bytes is not None:
        if not binary or max_bytes <= 0:
            fail("Bounded Git output requires a positive binary byte limit.")
        try:
            process = subprocess.Popen(  # noqa: S603
                command,
                env=environment,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )
        except OSError as error:
            fail(f"Command failed to start: {' '.join(command)}: {error}")
        if process.stdout is None or process.stderr is None:
            process.kill()
            process.wait()
            fail("Bounded Git output pipes could not be created.")
        selector = selectors.DefaultSelector()
        stdout = bytearray()
        stderr = bytearray()
        limit_exceeded = False
        deadline = time.monotonic() + COMMAND_TIMEOUT_SECONDS
        try:
            for stream, label in (
                (process.stdout, "stdout"),
                (process.stderr, "stderr"),
            ):
                os.set_blocking(stream.fileno(), False)
                selector.register(stream, selectors.EVENT_READ, label)
            while selector.get_map():
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    process.kill()
                    process.wait()
                    fail(f"Command timed out after {COMMAND_TIMEOUT_SECONDS} seconds: {' '.join(command)}")
                for key, _events in selector.select(remaining):
                    if key.data == "stdout":
                        remaining_bytes = max_bytes - len(stdout)
                        read_size = min(65_536, remaining_bytes + 1)
                    else:
                        read_size = 65_536
                    try:
                        chunk = os.read(key.fd, read_size)
                    except BlockingIOError:
                        continue
                    if not chunk:
                        selector.unregister(key.fileobj)
                        continue
                    if key.data == "stdout":
                        remaining_bytes = max_bytes - len(stdout)
                        if remaining_bytes > 0:
                            stdout.extend(chunk[:remaining_bytes])
                        if len(chunk) >= remaining_bytes:
                            limit_exceeded = True
                            if process.poll() is None:
                                process.kill()
                    elif len(stderr) < 65_536:
                        stderr.extend(chunk[: 65_536 - len(stderr)])
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                process.kill()
                process.wait()
                fail(f"Command timed out after {COMMAND_TIMEOUT_SECONDS} seconds: {' '.join(command)}")
            try:
                return_code = process.wait(timeout=remaining)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait()
                fail(f"Command timed out after {COMMAND_TIMEOUT_SECONDS} seconds: {' '.join(command)}")
        finally:
            selector.close()
            process.stdout.close()
            process.stderr.close()
            if process.poll() is None:
                process.kill()
                process.wait()
        if limit_exceeded:
            fail(f"Exact-revision review input exceeds the protected byte limit of {max_bytes - 1} bytes.")
        if return_code != 0:
            fail(f"Command failed closed: {' '.join(command)}: {stderr.decode(errors='replace').strip()}")
        return bytes(stdout)
    result = run(
        command,
        environment=environment,
        binary=binary,
    )
    return result.stdout


def materialize(arguments: argparse.Namespace, output_directory: Path) -> dict[str, Any]:
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
    with tempfile.TemporaryDirectory(prefix="exact-revision-materializer.", dir=runner_temp) as temporary:
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
            max_bytes=MAX_REVIEW_BYTES,
        )
        if not isinstance(diff, bytes):
            fail("Git returned an invalid diff representation.")
        review_bytes = len(diff)
        if review_bytes <= 0 or review_bytes >= MAX_REVIEW_BYTES:
            fail(f"Exact-revision review input must contain 1..{MAX_REVIEW_BYTES - 1} bytes; observed {review_bytes}.")
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
        write_owned_regular_file(patch, diff, "review diff")
        write_owned_regular_file(
            metadata_path,
            (json.dumps(metadata, indent=2, sort_keys=True) + "\n").encode("utf-8"),
            "review metadata",
        )
        return metadata


def bind_assets(review_directory: Path, asset_paths: dict[str, Path]) -> dict[str, Any]:
    metadata_path = review_directory / "review-metadata.json"
    try:
        metadata = json.loads(protected_asset_bytes(metadata_path, "review metadata").decode("utf-8"))
    except (json.JSONDecodeError, UnicodeDecodeError) as error:
        fail(f"Review metadata is malformed: {error}")
    if not isinstance(metadata, dict):
        fail("Review metadata must be a JSON object.")
    if any(key in metadata for key in (*ASSET_ARGUMENTS, "input_sha256")):
        fail("Review metadata already contains protected asset bindings.")
    bound = bind_protected_assets(metadata, asset_paths)
    write_owned_regular_file(
        metadata_path,
        (json.dumps(bound, indent=2, sort_keys=True) + "\n").encode("utf-8"),
        "review metadata",
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
    if not patch.is_file() or patch.is_symlink() or not metadata_path.is_file() or metadata_path.is_symlink():
        fail("The review diff and metadata must be regular, non-symlink files.")
    patch_size = patch.stat().st_size
    if patch_size <= 0 or patch_size >= MAX_REVIEW_BYTES:
        fail(f"The review diff must be between 1 and {MAX_REVIEW_BYTES - 1} bytes.")
    try:
        expected_metadata = json.loads(protected_asset_bytes(metadata_path, "review metadata").decode("utf-8"))
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
    with tempfile.TemporaryDirectory(prefix="exact-revision-recheck.", dir=runner_temp) as temporary:
        regenerated = Path(temporary) / "review"
        actual_metadata = bind_protected_assets(materialize(arguments, regenerated), asset_paths)
        if protected_asset_bytes(patch, "review diff") != protected_asset_bytes(
            regenerated / "change.patch", "regenerated diff"
        ):
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
    parser.add_argument("--trigger", required=True, choices=("ready_for_review", "app_dispatch"))
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
            metadata = bind_assets(arguments.review_directory, asset_paths_from_arguments(arguments))
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
