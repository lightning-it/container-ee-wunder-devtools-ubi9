#!/usr/bin/env python3
"""Create exact-diff local pipeline and dual-agent review evidence."""

from __future__ import annotations

import argparse
import base64
import contextlib
import hashlib
import json
import os
import platform
import re
import secrets
import shlex
import shutil
import stat
import subprocess
import sys
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, NamedTuple, Optional, Tuple

ENGINE_PATH = Path(__file__)
if ENGINE_PATH.is_symlink():
    raise RuntimeError("push-ready engine must not be a symbolic link")
try:
    ENGINE_PATH = ENGINE_PATH.resolve(strict=True)
except OSError as exc:
    raise RuntimeError("push-ready engine path cannot be resolved safely") from exc

AUTHORIZED_ROOT = globals().get("_LIT_AUTHORIZED_REPOSITORY_ROOT")
if AUTHORIZED_ROOT is None:
    ROOT = ENGINE_PATH.parents[1]
else:
    if not isinstance(AUTHORIZED_ROOT, str) or not AUTHORIZED_ROOT:
        raise RuntimeError("authorized repository root must be an absolute path")
    authorized_candidate = Path(AUTHORIZED_ROOT)
    if not authorized_candidate.is_absolute():
        raise RuntimeError("authorized repository root must be an absolute path")
    try:
        ROOT = authorized_candidate.resolve(strict=True)
        authorized_engine = (
            ROOT / "default" / "scripts" / "lit-push-ready.py"
        ).resolve(strict=True)
    except OSError as exc:
        raise RuntimeError(
            "authorized repository root cannot be resolved safely"
        ) from exc
    if ROOT != ENGINE_PATH.parents[2] or authorized_engine != ENGINE_PATH:
        raise RuntimeError(
            "authorized repository root is not bound to the running engine"
        )
CONFIG = ROOT / ".lit" / "push-ready.json"
COPILOT = ROOT / ".github" / "copilot-instructions.md"
AGENTS = ROOT / "AGENTS.md"
PASS_MARKER = "PUSH_READY: PASS"
BLOCKED_MARKER = "PUSH_READY: BLOCKED"
CONTRACT_LINE = "<!-- Managed contract: Codex and Copilot must apply AGENTS.md. -->"
SECRET_PATH_PARTS = {
    ".env",
    ".netrc",
    ".pypirc",
    "auth.json",
    "credentials",
    "credentials.json",
    "id_ed25519",
    "id_rsa",
    "kubeconfig",
    "secrets",
    "vault-password",
}
SECRET_CONTENT_PATTERNS = (
    re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----"),
    re.compile(
        r"(?i)(?:api[_-]?key|client[_-]?secret|access[_-]?token|password)"
        r"\s*[:=]\s*[\"']?[A-Za-z0-9_./+=-]{16,}"
    ),
    re.compile(r"\bgh[opusr]_[A-Za-z0-9]{20,}\b"),
    re.compile(r"\bgithub_pat_[A-Za-z0-9_]{20,}\b"),
    re.compile(r"\bglpat-[A-Za-z0-9_-]{20,}\b"),
    re.compile(r"\bpypi-[A-Za-z0-9_-]{20,}\b"),
    re.compile(r"\bnpm_[A-Za-z0-9]{20,}\b"),
    re.compile(r"\bsk_(?:live|test)_[A-Za-z0-9]{16,}\b"),
    re.compile(r"\bAKIA[A-Z0-9]{16}\b"),
    re.compile(r"\bAIza[0-9A-Za-z_-]{35}\b"),
    re.compile(r"\b(?:xox[baprs]-|sk-(?:proj-)?)[A-Za-z0-9_-]{20,}\b"),
    re.compile(r"\bBearer\s+[A-Za-z0-9._~+/=-]{20,}\b", re.IGNORECASE),
    re.compile(r"\beyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\b"),
    re.compile(r"(?i)_authToken\s*=\s*[^\s]{12,}"),
)
NPMRC_AUTH_PATTERN = re.compile(
    r"(?im)(?:^|[+:])\s*(?:_authToken|_auth|_password|username)\s*="
)
# The authoritative base contains this exact public synthetic test fixture.
# Permit only its removal during this one-time bootstrap; added occurrences,
# surrounding content, and every other secret-like value remain blocked.
KNOWN_NON_SECRET_REMOVED_REVIEW_LINE = (
    "-            \"password = '"
    + "this-is-a-"
    + "secret-value"
    + "'\\n\","
)
INSTRUCTION_PATH_PATTERN = re.compile(
    r"(?:^|/)AGENTS\.md$|^\.github/copilot-instructions\.md$|"
    r"^\.github/instructions/.+\.instructions\.md$"
)
MAX_CONFIG_BYTES = 1_000_000
MAX_REVIEW_BYTES = 5_000_000
MAX_TIMEOUT_SECONDS = 3_600
CHECK_TIMEOUT_SECONDS = 1_800
AUTHORITATIVE_BASE_REFS = {
    "refs/remotes/origin/develop": "develop",
    "refs/remotes/origin/main": "main",
}
INTEGRATION_DIRECTORY_PREFIX = ".lit-integration-"
COPILOT_DEVTOOL_IMAGE = "quay.io/l-it/ee-wunder-devtools-ubi9:v1.12.0@sha256:b1189c8d51cb8f9f7b8aa396b8aaf30da7635ebd5d0fc9fe8b0f9f9d3c36d6de"
CHECK_PROFILE = {
    "name": "repository-quality-profile",
    "command": ["scripts/lit-ci-profile.sh", "repository-quality"],
}
TRUSTED_CHECK_POLICY_PATHS = (
    ".lit/push-ready.json",
    "scripts/lit-ci-profile.sh",
    "default/scripts/lit-push-ready.py",
    "default/scripts/wunder-devtools-ee.sh",
    "default/scripts/wunder-container-run.sh",
    "scripts/lit-push-ready.py",
    "scripts/lit-safe-temp-run.py",
    "scripts/wunder-devtools-ee.sh",
    "scripts/wunder-container-run.sh",
    "scripts/test-devtools-molecule-ownership.sh",
)
PARITY_GAPS = (
    {
        "id": "copilot-review-surface",
        "local": "GitHub Copilot CLI read-only exact-diff review",
        "remote": "GitHub Copilot pull-request code review on the current head SHA",
        "status": "not-identical-by-product-design",
        "remote_gate_required": True,
    },
    {
        "id": "github-actions-runtime",
        "local": "repository-declared deterministic checks",
        "remote": "GitHub-hosted or self-hosted workflow runners and services",
        "status": "remote-only-environment",
        "remote_gate_required": True,
    },
    {
        "id": "github-authorization",
        "local": "no GitHub write-token or branch-policy exercise",
        "remote": "GitHub App, token, environment, and branch-policy behavior",
        "status": "remote-only-authorization",
        "remote_gate_required": True,
    },
)
LOCAL_EVIDENCE_TRUST = {
    "level": "developer-controlled-advisory",
    "purpose": "local staleness and workflow enforcement",
    "security_attestation": False,
    "remote_gate_required": True,
}
COPILOT_PROMPT_MODE_BOUNDARY = {
    "COPILOT_MCP_TOOL_CACHE": "false",
    "GITHUB_COPILOT_PROMPT_MODE_EXTENSIONS": "false",
    "GITHUB_COPILOT_PROMPT_MODE_REPO_HOOKS": "false",
    "GITHUB_COPILOT_PROMPT_MODE_WORKSPACE_MCP": "false",
}
COPILOT_REQUIRED_SAFETY_ARGUMENTS = (
    "-s",
    "--no-ask-user",
    "--no-bash-env",
    "--no-remote",
    "--no-remote-export",
    "--disable-builtin-mcps",
    "--disallow-temp-dir",
    "--no-custom-instructions",
    "--available-tools=view,grep,glob",
    "--allow-tool=read",
    "--deny-tool=write,memory,url,shell",
)


class PlannedChange(NamedTuple):
    """Immutable description of the repository state intended for the push."""

    base_ref: str
    base_tip: str
    base_commit: str
    head_commit: str
    diff: str
    paths: tuple[str, ...]
    untracked_sha256: dict[str, str]
    tree_fingerprint: str

    @property
    def diff_sha256(self) -> str:
        return sha256_text(self.diff)


def now_utc() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace(
        "+00:00", "Z"
    )


def sha256_bytes(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def sha256_text(payload: str) -> str:
    try:
        encoded = payload.encode("utf-8")
    except UnicodeError as exc:
        raise RuntimeError("text input cannot be represented safely as UTF-8") from exc
    return sha256_bytes(encoded)


def utf8_size(payload: str) -> int:
    try:
        return len(payload.encode("utf-8"))
    except UnicodeError as exc:
        raise RuntimeError(
            "planned review input cannot be represented safely as UTF-8"
        ) from exc


GIT_IDENTITY_ENVIRONMENT = frozenset(
    {
        "GIT_AUTHOR_NAME",
        "GIT_AUTHOR_EMAIL",
        "GIT_AUTHOR_DATE",
        "GIT_COMMITTER_NAME",
        "GIT_COMMITTER_EMAIL",
        "GIT_COMMITTER_DATE",
    }
)


def trusted_container_git_binding(source: dict[str, str]) -> dict[str, str]:
    """Retain only the wrapper's fixed, read-only linked-worktree binding."""
    required = ("GIT_DIR", "GIT_COMMON_DIR", "GIT_WORK_TREE")
    if any(name not in source for name in required):
        return {}
    try:
        work_tree = Path(source["GIT_WORK_TREE"]).resolve(strict=True)
        common = Path(source["GIT_COMMON_DIR"])
        git_dir = Path(source["GIT_DIR"])
    except (OSError, ValueError):
        return {}
    mount_root = Path("/run/wunder-git/common")
    if (
        work_tree != ROOT
        or not common.is_absolute()
        or common != mount_root
        or not git_dir.is_absolute()
    ):
        return {}
    try:
        relative_git_dir = git_dir.relative_to(common)
    except ValueError:
        return {}
    if (
        len(relative_git_dir.parts) < 2
        or relative_git_dir.parts[0] != "worktrees"
        or any(part in {"", ".", ".."} for part in relative_git_dir.parts)
    ):
        return {}
    return {name: source[name] for name in required}


def isolated_git_environment(
    environment: Optional[Dict[str, str]] = None,
) -> dict[str, str]:
    """Return an environment that cannot redirect or configure Git externally.

    The tool's root is a Python path binding, not an inherited Git working-tree
    binding.  In particular, retain only the explicit deterministic commit
    identity from callers and discard every other ``GIT_*`` variable.
    """
    source = environment if environment is not None else os.environ
    result = {
        name: value
        for name, value in source.items()
        if not name.startswith("GIT_")
    }
    for name in GIT_IDENTITY_ENVIRONMENT:
        if name in source:
            result[name] = source[name]
    result.update(trusted_container_git_binding(source))
    result.update(
        {
            "GIT_CONFIG_NOSYSTEM": "1",
            "GIT_CONFIG_GLOBAL": os.devnull,
            "GIT_TERMINAL_PROMPT": "0",
        }
    )
    return result


def assert_safe_git_configuration(cwd: Path) -> None:
    """Refuse local config that can execute code or change tree materialization."""
    configured = run(
        ["git", "config", "--local", "--null", "--name-only", "--list"],
        capture=True,
        cwd=cwd,
    )
    if configured.returncode:
        raise RuntimeError("could not inspect local Git configuration safely")
    unsafe: list[str] = []
    for name in (entry for entry in configured.stdout.split("\0") if entry):
        lowered = name.lower()
        if (
            lowered in {
                "core.attributesfile",
                "core.fsmonitor",
                "core.hookspath",
            }
            or lowered.startswith("filter.")
            or (lowered.startswith("merge.") and lowered.endswith(".driver"))
        ):
            unsafe.append(name)
    if unsafe:
        raise RuntimeError(
            "local Git configuration can alter or execute the reviewed tree: "
            + ", ".join(sorted(unsafe))
        )


def run(
    command: list[str],
    *,
    capture: bool = False,
    input_text: Optional[str] = None,
    timeout: Optional[int] = None,
    cwd: Optional[Path] = None,
    env: Optional[Dict[str, str]] = None,
) -> subprocess.CompletedProcess[str]:
    resolved_environment = env
    if command and command[0] == "git":
        resolved_environment = isolated_git_environment(env)
    return subprocess.run(
        command,
        cwd=cwd or ROOT,
        check=False,
        text=True,
        encoding="utf-8",
        errors="surrogateescape",
        input=input_text,
        stdout=subprocess.PIPE if capture else None,
        stderr=subprocess.STDOUT if capture else None,
        timeout=timeout,
        env=resolved_environment,
    )


def git_output(*args: str) -> str:
    result = run(["git", *args], capture=True)
    if result.returncode:
        raise RuntimeError(result.stdout.strip())
    return result.stdout


def evidence_path() -> Path:
    git_dir = Path(git_output("rev-parse", "--git-dir").strip())
    if not git_dir.is_absolute():
        git_dir = ROOT / git_dir
    return git_dir.resolve() / "lit-push-ready-evidence.json"


def open_regular_below(root: Path, name: str, *, purpose: str) -> int:
    """Open a file below root without following any path-component symlink."""
    required_flags = ("O_CLOEXEC", "O_DIRECTORY", "O_NOFOLLOW", "O_NONBLOCK")
    missing_flags = [
        flag for flag in required_flags if not isinstance(getattr(os, flag, None), int)
    ]
    if missing_flags or os.open not in os.supports_dir_fd:
        unsupported = ", ".join(missing_flags) or "open(dir_fd=...)"
        raise RuntimeError(
            f"{purpose} requires unavailable safe-open capability: {unsupported}"
        )

    candidate = Path(name)
    parts = candidate.parts
    if (
        candidate.is_absolute()
        or not parts
        or any(part in {"", ".", ".."} for part in parts)
    ):
        raise RuntimeError(f"{purpose} refused for unsafe repository path: {name}")

    directory_flags = (
        os.O_RDONLY | os.O_CLOEXEC | os.O_DIRECTORY | os.O_NOFOLLOW
    )
    file_flags = os.O_RDONLY | os.O_CLOEXEC | os.O_NOFOLLOW | os.O_NONBLOCK
    directory_descriptors: list[int] = []
    descriptor = -1
    keep_descriptor = False
    try:
        current = os.open(root, directory_flags)
        directory_descriptors.append(current)
        for component in parts[:-1]:
            current = os.open(component, directory_flags, dir_fd=current)
            directory_descriptors.append(current)
        descriptor = os.open(parts[-1], file_flags, dir_fd=current)
        if not stat.S_ISREG(os.fstat(descriptor).st_mode):
            raise RuntimeError(
                f"{purpose} refused for non-regular repository path: {name}"
            )
        keep_descriptor = True
        return descriptor
    except OSError as exc:
        raise RuntimeError(
            f"{purpose} could not safely inspect repository path: {name}"
        ) from exc
    finally:
        if descriptor >= 0 and not keep_descriptor:
            os.close(descriptor)
        for directory_descriptor in reversed(directory_descriptors):
            os.close(directory_descriptor)


def open_repository_regular(name: str, *, purpose: str) -> int:
    """Open a repository file without following any path-component symlink."""
    return open_regular_below(ROOT, name, purpose=purpose)


# Retain the public helper name used by existing downstream regression tests.
def open_untracked_regular(name: str, *, purpose: str) -> int:
    return open_repository_regular(name, purpose=purpose)


def read_repository_file(
    name: str, *, purpose: str, max_bytes: int
) -> tuple[bytes, int]:
    if max_bytes < 0:
        raise RuntimeError(f"{purpose} input exceeds its aggregate byte limit")
    descriptor = open_repository_regular(name, purpose=purpose)
    try:
        mode = os.fstat(descriptor).st_mode
        with os.fdopen(descriptor, "rb") as stream:
            descriptor = -1
            payload = stream.read(max_bytes + 1)
    except OSError as exc:
        raise RuntimeError(f"{purpose} could not read repository path: {name}") from exc
    finally:
        if descriptor >= 0:
            os.close(descriptor)
    if len(payload) > max_bytes:
        raise RuntimeError(f"{purpose} input exceeds {max_bytes} bytes")
    return payload, mode


def untracked_names() -> list[str]:
    names = git_output("ls-files", "--others", "--exclude-standard", "-z")
    return [entry for entry in names.split("\0") if entry]


def untracked_file_hashes(max_bytes: int = 100_000_000) -> dict[str, str]:
    hashes: dict[str, str] = {}
    total = 0
    for name in untracked_names():
        remaining = max_bytes - total
        if remaining < 0:
            raise RuntimeError("Fingerprint input exceeds its aggregate byte limit")
        payload, _ = read_repository_file(
            name,
            purpose="Fingerprint",
            max_bytes=remaining,
        )
        total += len(payload)
        hashes[name] = sha256_bytes(payload)
    return hashes


def tree_fingerprint() -> str:
    reject_hidden_index_entries()
    payload = {
        "head": git_output("rev-parse", "HEAD").strip(),
        "status": git_output(
            "status", "--porcelain=v1", "--untracked-files=all", "-z"
        ),
        "diff": git_output(
            "diff",
            "--no-ext-diff",
            "--no-textconv",
            "--binary",
            "HEAD",
            "--",
        ),
        "untracked": untracked_file_hashes(),
    }
    return sha256_text(
        json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    )


def reject_hidden_index_entries() -> None:
    """Reject index flags that can hide policy or source modifications."""
    entries = git_output("ls-files", "-v", "-z").split("\0")
    hidden: list[str] = []
    for entry in entries:
        if not entry:
            continue
        if len(entry) < 3 or entry[1] != " ":
            raise RuntimeError("Git returned a malformed index visibility entry")
        marker = entry[0]
        if marker == "S" or marker.islower():
            hidden.append(entry[2:])
    if hidden:
        preview = ", ".join(sorted(hidden)[:20])
        raise RuntimeError(
            "push-ready does not support assume-unchanged, skip-worktree, "
            f"or sparse index entries; clear hidden flags for: {preview}"
        )


def require_policy_files_committed() -> None:
    reject_hidden_index_entries()
    try:
        running_engine = (
            Path(__file__).resolve().relative_to(ROOT).as_posix()
        )
    except ValueError as exc:
        raise RuntimeError(
            "push-ready engine is outside the repository root"
        ) from exc
    for path in (
        ".lit/push-ready.json",
        "AGENTS.md",
        ".github/copilot-instructions.md",
        "scripts/lit-ci-profile.sh",
        running_engine,
    ):
        candidate = ROOT / path
        if not candidate.exists():
            raise RuntimeError(f"required push-ready policy file is missing: {path}")
        if not candidate.is_file() or candidate.is_symlink():
            raise RuntimeError(
                f"required push-ready policy file is unsafe: {path}"
            )
        unstaged = run(
            ["git", "diff", "--quiet", "--", path],
            capture=True,
        )
        staged = run(
            ["git", "diff", "--cached", "--quiet", "HEAD", "--", path],
            capture=True,
        )
        if unstaged.returncode or staged.returncode:
            raise RuntimeError(
                f"push-ready policy file must match committed HEAD: {path}"
            )


def require_clean_head() -> None:
    """Require that a push can transfer exactly the state being evaluated."""
    require_policy_files_committed()
    status_value = git_output(
        "status", "--porcelain=v1", "--untracked-files=all", "-z"
    )
    if status_value:
        raise RuntimeError(
            "push-ready requires a clean committed HEAD; commit or remove "
            "staged, unstaged, and untracked changes, then rerun"
        )


def current_branch_ref() -> str:
    branch = git_output("symbolic-ref", "--quiet", "HEAD").strip()
    if not branch.startswith("refs/heads/"):
        raise RuntimeError("push-ready requires an attached local branch")
    if branch in {"refs/heads/develop", "refs/heads/main"}:
        raise RuntimeError(
            "push-ready requires a feature branch; direct pushes to develop "
            "and main are not authorized"
        )
    return branch


def github_https_authorization() -> str:
    """Return a masked-process-safe GitHub Authorization header value."""
    token = os.environ.get("GH_TOKEN") or os.environ.get("GITHUB_TOKEN")
    if token is None:
        result = run(
            ["gh", "auth", "token", "--hostname", "github.com"],
            capture=True,
            timeout=30,
        )
        if result.returncode:
            raise RuntimeError(
                "GitHub HTTPS origin requires GH_TOKEN, GITHUB_TOKEN, or "
                "an authenticated gh session"
            )
        token = result.stdout.strip()
    if (
        not token
        or len(token) > 4096
        or any(ord(character) < 32 or ord(character) == 127 for character in token)
    ):
        raise RuntimeError("GitHub HTTPS authentication token is invalid")
    credentials = base64.b64encode(
        f"x-access-token:{token}".encode("utf-8")
    ).decode("ascii")
    return f"AUTHORIZATION: basic {credentials}"


def fetch_authoritative_base(branch: str, base_ref: str) -> subprocess.CompletedProcess[str]:
    """Fetch one governed base branch without exposing credentials on argv."""
    origin_url = git_output("remote", "get-url", "origin").strip()
    push_url = git_output("remote", "get-url", "--push", "origin").strip()
    fetch_remote = governed_push_remote_from_url("origin", origin_url)
    push_remote = governed_push_remote_from_url("origin", push_url)
    if fetch_remote["repository"] != push_remote["repository"]:
        raise RuntimeError(
            "origin fetch and push URLs must target the same governed repository"
        )
    command = [
        "git",
        "fetch",
        "--quiet",
        "--no-tags",
        "origin",
        f"+refs/heads/{branch}:{base_ref}",
    ]
    if not origin_url.startswith("https://github.com/"):
        return run(command, capture=True, timeout=120)
    environment = isolated_git_environment()
    environment.update(
        {
            "GIT_CONFIG_COUNT": "1",
            "GIT_CONFIG_KEY_0": "http.https://github.com/.extraheader",
            "GIT_CONFIG_VALUE_0": github_https_authorization(),
        }
    )
    return subprocess.run(
        command,
        cwd=ROOT,
        check=False,
        text=True,
        encoding="utf-8",
        errors="surrogateescape",
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        timeout=120,
        env=environment,
    )


def refresh_authoritative_base(config: dict[str, Any]) -> str:
    """Fetch the governed base ref so integration checks never use stale state."""
    base_ref = config["base_ref"]
    branch = AUTHORITATIVE_BASE_REFS.get(base_ref)
    if branch is None:
        raise RuntimeError("cannot refresh an ungoverned base ref")
    result = fetch_authoritative_base(branch, base_ref)
    if result.returncode:
        raise RuntimeError(
            f"could not refresh the authoritative origin/{branch} base"
        )
    return git_output(
        "rev-parse",
        "--verify",
        "--end-of-options",
        f"{base_ref}^{{commit}}",
    ).strip()


def require_nonempty_string(value: Any, description: str) -> str:
    if not isinstance(value, str) or not value or "\0" in value:
        raise RuntimeError(f"{description} must be a non-empty string")
    return value


def require_positive_integer(
    value: Any, description: str, *, maximum: int
) -> int:
    if (
        isinstance(value, bool)
        or not isinstance(value, int)
        or value <= 0
        or value > maximum
    ):
        raise RuntimeError(
            f"{description} must be an integer between 1 and {maximum}"
        )
    return value


def validate_command(value: Any, description: str) -> list[str]:
    if (
        not isinstance(value, list)
        or not value
        or any(not isinstance(argument, str) or not argument for argument in value)
    ):
        raise RuntimeError(
            f"{description} must be a non-empty command array of non-empty strings"
        )
    return value


def validate_agent_config(name: str, value: Any) -> None:
    if not isinstance(value, dict):
        raise RuntimeError(f"agents.{name} must be an object")
    enabled = value.get("enabled")
    required = value.get("required")
    if not isinstance(enabled, bool) or not isinstance(required, bool):
        raise RuntimeError(
            f"agents.{name}.enabled and agents.{name}.required must be booleans"
        )
    if enabled is not True or required is not True:
        raise RuntimeError(
            f"agents.{name} must be enabled and required by the v2 policy"
        )
    command = validate_command(value.get("command"), f"agents.{name}.command")
    if command != [name]:
        raise RuntimeError(
            f"agents.{name}.command is centrally fixed to [{name!r}]"
        )
    require_positive_integer(
        value.get("timeout_seconds"),
        f"agents.{name}.timeout_seconds",
        maximum=MAX_TIMEOUT_SECONDS,
    )
    model = value.get("model")
    if model is not None:
        require_nonempty_string(model, f"agents.{name}.model")
        if len(model) > 100 or model.startswith("-"):
            raise RuntimeError(f"agents.{name}.model is unsafe")


def validate_remote_only_checks(value: Any) -> None:
    if not isinstance(value, list) or not value:
        raise RuntimeError(
            "remote_only_checks must be a non-empty array of gap objects"
        )
    identifiers: list[str] = []
    required_keys = {"id", "workflow", "job", "reason", "owner"}
    for item in value:
        if not isinstance(item, dict) or set(item) != required_keys:
            raise RuntimeError(
                "each remote_only_checks item must define exactly id, "
                "workflow, job, reason, and owner"
            )
        identifier = require_nonempty_string(
            item.get("id"), "remote_only_checks id"
        )
        workflow = require_nonempty_string(
            item.get("workflow"), "remote_only_checks workflow"
        )
        job = require_nonempty_string(
            item.get("job"), "remote_only_checks job"
        )
        reason = require_nonempty_string(
            item.get("reason"), "remote_only_checks reason"
        )
        owner = require_nonempty_string(
            item.get("owner"), "remote_only_checks owner"
        )
        if not re.fullmatch(r"[a-z0-9]+(?:-[a-z0-9]+)*", identifier):
            raise RuntimeError("remote_only_checks id is unsafe")
        if not re.fullmatch(
            r"\.github/workflows/[A-Za-z0-9_.-]+\.(?:yml|yaml)",
            workflow,
        ):
            raise RuntimeError(
                "remote_only_checks workflow must name a repository workflow"
            )
        if not re.fullmatch(r"[A-Za-z0-9_.-]+", job):
            raise RuntimeError("remote_only_checks job is unsafe")
        if len(reason) > 1_000 or len(owner) > 200:
            raise RuntimeError("remote_only_checks text is unreasonably large")
        identifiers.append(identifier)
    if len(identifiers) != len(set(identifiers)):
        raise RuntimeError("remote_only_checks ids must be unique")


def load_config() -> dict[str, Any]:
    reject_hidden_index_entries()
    if not CONFIG.is_file() or CONFIG.is_symlink():
        raise RuntimeError(
            "missing required regular configuration: "
            f"{CONFIG.relative_to(ROOT)}"
        )
    if CONFIG.stat().st_size > MAX_CONFIG_BYTES:
        raise RuntimeError("push-ready configuration is unreasonably large")
    data = json.loads(CONFIG.read_text(encoding="utf-8"))
    if (
        not isinstance(data, dict)
        or data.get("version") != 2
        or not isinstance(data.get("checks"), list)
        or not data.get("checks")
    ):
        raise RuntimeError(
            "push-ready configuration must use version 2 and define checks"
        )
    base_ref = require_nonempty_string(data.get("base_ref"), "base_ref")
    if base_ref not in AUTHORITATIVE_BASE_REFS:
        raise RuntimeError(
            "base_ref must be a centrally governed remote-tracking ref: "
            + ", ".join(sorted(AUTHORITATIVE_BASE_REFS))
        )
    if data["checks"] != [CHECK_PROFILE]:
        raise RuntimeError(
            "checks must contain exactly the centrally allowlisted "
            "repository-quality profile"
        )
    agents = data.get("agents")
    if not isinstance(agents, dict) or set(agents) != {"copilot", "codex"}:
        raise RuntimeError("agents must define exactly copilot and codex")
    for name in ("copilot", "codex"):
        validate_agent_config(name, agents[name])
    review = data.get("review")
    if not isinstance(review, dict):
        raise RuntimeError("review must be an object")
    require_positive_integer(
        review.get("max_diff_bytes"),
        "review.max_diff_bytes",
        maximum=MAX_REVIEW_BYTES,
    )
    evidence = data.get("evidence")
    if not isinstance(evidence, dict):
        raise RuntimeError("evidence must be an object")
    require_positive_integer(
        evidence.get("max_age_seconds"),
        "evidence.max_age_seconds",
        maximum=7 * 24 * 60 * 60,
    )
    validate_remote_only_checks(data.get("remote_only_checks"))
    return data


def instructions_digest() -> str:
    if not AGENTS.is_file() or AGENTS.is_symlink():
        raise RuntimeError("AGENTS.md must be a regular file")
    return sha256_bytes(AGENTS.read_bytes())


def instruction_file_hashes() -> dict[str, str]:
    if not COPILOT.is_file() or COPILOT.is_symlink():
        raise RuntimeError(".github/copilot-instructions.md must be a regular file")
    names = git_output("ls-files", "--cached", "-z")
    candidates = {
        name
        for name in names.split("\0")
        if name and INSTRUCTION_PATH_PATTERN.search(name)
    }
    candidates.update({"AGENTS.md", ".github/copilot-instructions.md"})
    hashes: dict[str, str] = {}
    for name in sorted(candidates):
        payload, _ = read_repository_file(
            name,
            purpose="Instruction hashing",
            max_bytes=MAX_CONFIG_BYTES,
        )
        hashes[name] = sha256_bytes(payload)
    return hashes


def check_instruction_contract() -> None:
    reject_hidden_index_entries()
    expected = instructions_digest()
    marker = f"<!-- AGENTS_SHA256: {expected} -->"
    if not COPILOT.is_file() or COPILOT.is_symlink():
        raise RuntimeError(
            "AGENTS.md and .github/copilot-instructions.md are required regular files"
        )
    lines = COPILOT.read_text(encoding="utf-8").splitlines()
    if lines[-2:] != [CONTRACT_LINE, marker]:
        raise RuntimeError(
            "Copilot instructions are stale; run "
            "`python3 scripts/lit-push-ready.py sync-instructions`"
        )


def sync_instructions() -> None:
    if (
        not AGENTS.is_file()
        or AGENTS.is_symlink()
        or not COPILOT.is_file()
        or COPILOT.is_symlink()
    ):
        raise RuntimeError(
            "AGENTS.md and .github/copilot-instructions.md are required regular files"
        )
    lines = COPILOT.read_text(encoding="utf-8").splitlines()
    lines = [
        line
        for line in lines
        if not line.startswith("<!-- AGENTS_SHA256:") and line != CONTRACT_LINE
    ]
    while lines and not lines[-1]:
        lines.pop()
    lines.extend(
        [
            "",
            CONTRACT_LINE,
            f"<!-- AGENTS_SHA256: {instructions_digest()} -->",
        ]
    )
    COPILOT.write_text("\n".join(lines) + "\n", encoding="utf-8")


def existing_unix_socket(value: str) -> Optional[str]:
    candidate_value = value.removeprefix("unix://")
    try:
        candidate = Path(candidate_value).expanduser().resolve(strict=True)
        mode = candidate.stat().st_mode
    except OSError:
        return None
    if not stat.S_ISSOCK(mode):
        return None
    return str(candidate)


def minimal_check_environment(state_root: Path) -> dict[str, str]:
    """Return a credential-free host environment for the fixed CI profile."""
    path_value = os.environ.get("PATH")
    if not path_value:
        raise RuntimeError("deterministic checks require PATH")
    home = state_root / "home"
    temporary = state_root / "tmp"
    home.mkdir(mode=0o700)
    temporary.mkdir(mode=0o700)
    environment = {
        "CI": "1",
        "HOME": str(home),
        "LANG": "C",
        "LC_ALL": "C",
        "PATH": path_value,
        "TMPDIR": str(temporary),
    }
    selected_engine = os.environ.get("WUNDER_CONTAINER_ENGINE")
    if selected_engine:
        if selected_engine not in {"docker", "podman"}:
            raise RuntimeError(
                "WUNDER_CONTAINER_ENGINE must be docker or podman when set"
            )
        environment["WUNDER_CONTAINER_ENGINE"] = selected_engine
    configured_host = os.environ.get("DOCKER_HOST")
    if configured_host and not configured_host.startswith("unix://"):
        raise RuntimeError(
            "deterministic checks refuse a non-local DOCKER_HOST"
        )
    socket_candidates = []
    if configured_host:
        socket_candidates.append(configured_host)
    socket_candidates.extend(
        [
            str(Path.home() / ".docker" / "run" / "docker.sock"),
            f"/run/user/{os.getuid()}/podman/podman.sock",
            "/var/run/docker.sock",
        ]
    )
    for value in socket_candidates:
        socket_path = existing_unix_socket(value)
        if socket_path:
            environment["DOCKER_HOST"] = f"unix://{socket_path}"
            break
    runtime_directory = os.environ.get("XDG_RUNTIME_DIR")
    if runtime_directory:
        runtime_path = Path(runtime_directory)
        if runtime_path.is_absolute() and runtime_path.is_dir():
            environment["XDG_RUNTIME_DIR"] = str(runtime_path.resolve())
    return environment


def execute_checks(
    config: dict[str, Any], *, cwd: Optional[Path] = None
) -> list[dict[str, Any]]:
    results: list[dict[str, Any]] = []
    check_cwd = (cwd or ROOT).resolve()
    with tempfile.TemporaryDirectory(prefix="lit-check-environment-") as temporary:
        environment = minimal_check_environment(Path(temporary))
        for check in config["checks"]:
            # load_config validates these values; retain validation for direct callers.
            if not isinstance(check, dict):
                raise RuntimeError("each check must be an object")
            name = require_nonempty_string(check.get("name"), "each check name")
            command = validate_command(check.get("command"), "each check command")
            runtime_command = (
                [sys.executable, *command[1:]]
                if command[0] in {"python", "python3"}
                else command
            )
            started_at = now_utc()
            started = time.monotonic()
            print(f"==> {name}: {shlex.join(runtime_command)}", flush=True)
            try:
                result = run(
                    runtime_command,
                    cwd=check_cwd,
                    env=environment,
                    timeout=CHECK_TIMEOUT_SECONDS,
                )
            except subprocess.TimeoutExpired as exc:
                raise RuntimeError(
                    f"check timed out after {CHECK_TIMEOUT_SECONDS} seconds: {name}"
                ) from exc
            completed_at = now_utc()
            elapsed = round(time.monotonic() - started, 3)
            results.append(
                {
                    "name": name,
                    "command": runtime_command,
                    "exit_code": result.returncode,
                    "started_at": started_at,
                    "completed_at": completed_at,
                    "duration_seconds": elapsed,
                }
            )
            if result.returncode:
                raise RuntimeError(f"check failed: {name}")
    return results


def resolve_base(
    config: dict[str, Any], override: Optional[str] = None
) -> Tuple[str, str, str]:
    base_ref = override or config["base_ref"]
    require_nonempty_string(base_ref, "base_ref")
    if len(base_ref) > 200 or base_ref.startswith("-") or any(
        character.isspace() for character in base_ref
    ):
        raise RuntimeError("base_ref is unsafe")
    base_tip = git_output(
        "rev-parse", "--verify", "--end-of-options", f"{base_ref}^{{commit}}"
    ).strip()
    head_commit = git_output("rev-parse", "--verify", "HEAD^{commit}").strip()
    base_commit = git_output("merge-base", base_tip, head_commit).strip()
    if not re.fullmatch(r"[0-9a-fA-F]{40,64}", base_commit):
        raise RuntimeError("Git returned an invalid merge-base commit")
    return base_ref, base_tip, base_commit


def git_output_at(cwd: Path, *args: str) -> str:
    result = run(["git", *args], capture=True, cwd=cwd)
    if result.returncode:
        raise RuntimeError(result.stdout.strip())
    return result.stdout


def expected_integration_tree(change: PlannedChange) -> str:
    """Produce the pull-request merge tree with Git 2.34-compatible commands."""
    assert_safe_git_configuration(ROOT)
    with isolated_integration_directory() as temporary:
        worktree = temporary / "merge-tree-worktree"
        disabled_hooks = temporary / "disabled-hooks"
        disabled_hooks.mkdir(mode=0o700)
        added = run(
            [
                "git",
                "-c",
                f"core.hooksPath={disabled_hooks}",
                "worktree",
                "add",
                "--detach",
                str(worktree),
                change.base_tip,
            ],
            capture=True,
        )
        if added.returncode:
            raise RuntimeError(
                "could not create the compatibility merge worktree: "
                + added.stdout.strip()
            )
        worktree_identity = directory_identity(
            worktree,
            purpose="compatibility merge worktree",
        )
        try:
            merged = run(
                [
                    "git",
                    "-c",
                    f"core.hooksPath={disabled_hooks}",
                    "-c",
                    "merge.autoStash=false",
                    "-c",
                    "user.name=Lightning IT push-ready",
                    "-c",
                    "user.email=push-ready@invalid",
                    "merge",
                    "--no-commit",
                    "--no-ff",
                    "--strategy=ort",
                    change.head_commit,
                ],
                capture=True,
                cwd=worktree,
            )
            if merged.returncode:
                raise RuntimeError(
                    "the reviewed HEAD does not merge cleanly with the "
                    f"authoritative base {change.base_tip}: "
                    f"{merged.stdout.strip()}"
                )
            tree = git_output_at(worktree, "write-tree").strip()
            if not re.fullmatch(r"[0-9a-fA-F]{40,64}", tree):
                raise RuntimeError("Git returned an invalid integration tree")
            return tree
        finally:
            active_error = sys.exc_info()[1]
            cleanup_error: Optional[RuntimeError] = None
            try:
                if directory_identity(
                    worktree,
                    purpose="compatibility merge worktree",
                ) != worktree_identity:
                    raise RuntimeError(
                        "compatibility merge worktree identity changed; "
                        "cleanup was refused"
                    )
                merge_head = run(
                    ["git", "rev-parse", "--verify", "--quiet", "MERGE_HEAD"],
                    capture=True,
                    cwd=worktree,
                )
                if merge_head.returncode == 0:
                    aborted = run(
                        [
                            "git",
                            "-c",
                            f"core.hooksPath={disabled_hooks}",
                            "merge",
                            "--abort",
                        ],
                        capture=True,
                        cwd=worktree,
                    )
                    if aborted.returncode:
                        raise RuntimeError(
                            "could not abort the compatibility merge safely: "
                            + aborted.stdout.strip()
                        )
                elif merge_head.returncode != 1:
                    raise RuntimeError(
                        "could not inspect compatibility merge state"
                    )
                status_value = git_output_at(
                    worktree,
                    "status",
                    "--porcelain=v1",
                    "--untracked-files=all",
                    "-z",
                )
                if status_value:
                    raise RuntimeError(
                        "compatibility merge cleanup left a modified worktree"
                    )
                removed = run(
                    ["git", "worktree", "remove", str(worktree)],
                    capture=True,
                )
                if removed.returncode:
                    raise RuntimeError(
                        "could not remove compatibility merge worktree: "
                        + removed.stdout.strip()
                    )
                disabled_hooks.rmdir()
            except (OSError, RuntimeError) as exc:
                cleanup_error = (
                    exc
                    if isinstance(exc, RuntimeError)
                    else RuntimeError(
                        "compatibility merge cleanup could not finish safely"
                    )
                )
            if cleanup_error is not None:
                if active_error is not None:
                    raise RuntimeError(
                        f"{active_error}; compatibility merge cleanup also "
                        f"failed: {cleanup_error}"
                    ) from active_error
                raise cleanup_error


def git_tree_entry(commit: str, path: str) -> str:
    result = run(
        ["git", "ls-tree", "-z", commit, "--", path],
        capture=True,
    )
    if result.returncode:
        raise RuntimeError(f"cannot inspect governed check-policy path: {path}")
    return result.stdout


def require_trusted_check_policy(change: PlannedChange) -> None:
    """Refuse local host execution when executable policy differs from base."""
    try:
        running_engine = (
            Path(__file__).resolve().relative_to(ROOT).as_posix()
        )
    except ValueError as exc:
        raise RuntimeError(
            "push-ready engine is outside the repository root"
        ) from exc
    policy_paths = tuple(
        dict.fromkeys((*TRUSTED_CHECK_POLICY_PATHS, running_engine))
    )
    required_paths = {
        ".lit/push-ready.json",
        "scripts/lit-ci-profile.sh",
        running_engine,
    }
    for path in policy_paths:
        base_entry = git_tree_entry(change.base_tip, path)
        head_entry = git_tree_entry(change.head_commit, path)
        if path in required_paths and (not base_entry or not head_entry):
            raise RuntimeError(
                f"required check-policy path is missing: {path}"
            )
        if base_entry != head_entry:
            raise RuntimeError(
                "local execution refused because executable check policy "
                f"differs from authoritative base: {path}. Policy bootstrap "
                "changes require protected CI review before later feature "
                "branches can produce push-ready evidence."
            )


def integration_worktree_fingerprint(
    cwd: Path, *, include_ignored: bool = False
) -> str:
    untracked_command = ["ls-files", "--others"]
    if not include_ignored:
        untracked_command.append("--exclude-standard")
    untracked_command.append("-z")
    untracked = git_output_at(cwd, *untracked_command).split("\0")
    untracked_hashes: dict[str, str] = {}
    untracked_bytes = 0
    for name in (entry for entry in untracked if entry):
        descriptor = open_regular_below(
            cwd,
            name,
            purpose="Worktree fingerprint",
        )
        try:
            with os.fdopen(descriptor, "rb") as stream:
                descriptor = -1
                payload = stream.read(100_000_001)
        finally:
            if descriptor >= 0:
                os.close(descriptor)
        if len(payload) > 100_000_000:
            raise RuntimeError(
                "worktree fingerprint input exceeds 100000000 bytes"
            )
        untracked_bytes += len(payload)
        if untracked_bytes > 500_000_000:
            raise RuntimeError(
                "worktree fingerprint input exceeds 500000000 total bytes"
            )
        untracked_hashes[name] = sha256_bytes(payload)
    payload = {
        "head": git_output_at(cwd, "rev-parse", "HEAD").strip(),
        "index_tree": git_output_at(cwd, "write-tree").strip(),
        "status": git_output_at(
            cwd, "status", "--porcelain=v1", "--untracked-files=all", "-z"
        ),
        "diff": git_output_at(
            cwd,
            "diff",
            "--no-ext-diff",
            "--no-textconv",
            "--binary",
            "HEAD",
            "--",
        ),
        "untracked": untracked_hashes,
    }
    return sha256_text(
        json.dumps(payload, sort_keys=True, separators=(",", ":"))
    )


def synthetic_integration_commit(
    change: PlannedChange, integration_tree: str
) -> str:
    """Create the deterministic two-parent commit Actions checks out for a PR."""
    environment = dict(os.environ)
    environment.update(
        {
            "GIT_AUTHOR_NAME": "Lightning IT push-ready",
            "GIT_AUTHOR_EMAIL": "push-ready@invalid",
            "GIT_AUTHOR_DATE": "2000-01-01T00:00:00Z",
            "GIT_COMMITTER_NAME": "Lightning IT push-ready",
            "GIT_COMMITTER_EMAIL": "push-ready@invalid",
            "GIT_COMMITTER_DATE": "2000-01-01T00:00:00Z",
        }
    )
    result = run(
        [
            "git",
            "-c",
            "commit.gpgSign=false",
            "commit-tree",
            integration_tree,
            "-p",
            change.base_tip,
            "-p",
            change.head_commit,
            "-m",
            "Synthetic pull-request integration",
        ],
        capture=True,
        env=environment,
    )
    commit = result.stdout.strip()
    if result.returncode or not re.fullmatch(r"[0-9a-fA-F]{40,64}", commit):
        raise RuntimeError(
            "could not create the synthetic pull-request integration commit"
        )
    return commit


def create_integration_directory() -> tuple[Path, tuple[int, int, int, int]]:
    """Create a private executable worktree parent strictly below ROOT."""
    required_flags = ("O_CLOEXEC", "O_DIRECTORY", "O_NOFOLLOW")
    missing_flags = [
        flag
        for flag in required_flags
        if not isinstance(getattr(os, flag, None), int)
    ]
    required_dir_fd_calls = (os.mkdir, os.rmdir, os.stat)
    if missing_flags or any(
        call not in os.supports_dir_fd for call in required_dir_fd_calls
    ):
        unsupported = (
            ", ".join(missing_flags)
            or "directory-relative filesystem calls"
        )
        raise RuntimeError(
            "isolated integration checks require unavailable safe-directory "
            f"capability: {unsupported}"
        )

    directory_flags = (
        os.O_RDONLY | os.O_CLOEXEC | os.O_DIRECTORY | os.O_NOFOLLOW
    )
    try:
        root_descriptor = os.open(ROOT, directory_flags)
    except OSError as exc:
        raise RuntimeError(
            "could not safely open the repository for integration checks"
        ) from exc
    created_name: Optional[str] = None
    created_identity: Optional[Tuple[int, int]] = None
    completed = False
    try:
        root_stat = os.fstat(root_descriptor)
        path_stat = os.stat(ROOT, follow_symlinks=False)
        if (
            not stat.S_ISDIR(root_stat.st_mode)
            or (root_stat.st_dev, root_stat.st_ino)
            != (path_stat.st_dev, path_stat.st_ino)
        ):
            raise RuntimeError(
                "repository identity changed before integration checks"
            )
        for _attempt in range(128):
            candidate = (
                f"{INTEGRATION_DIRECTORY_PREFIX}{secrets.token_hex(16)}"
            )
            try:
                os.mkdir(candidate, mode=0o700, dir_fd=root_descriptor)
            except FileExistsError:
                continue
            except OSError as exc:
                raise RuntimeError(
                    "could not create a private integration directory below "
                    "the repository; the checkout must be writable and executable"
                ) from exc
            created_name = candidate
            break
        if created_name is None:
            raise RuntimeError(
                "could not allocate a collision-free integration directory"
            )

        created_stat = os.stat(
            created_name,
            dir_fd=root_descriptor,
            follow_symlinks=False,
        )
        created_identity = created_stat.st_dev, created_stat.st_ino
        if (
            not stat.S_ISDIR(created_stat.st_mode)
            or created_stat.st_uid != os.geteuid()
            or stat.S_IMODE(created_stat.st_mode) & 0o077
        ):
            raise RuntimeError(
                "private integration directory has unsafe ownership or permissions"
            )
        directory = ROOT / created_name
        try:
            resolved = directory.resolve(strict=True)
        except OSError as exc:
            raise RuntimeError(
                "private integration directory could not be resolved safely"
            ) from exc
        if resolved != directory or resolved.parent != ROOT:
            raise RuntimeError(
                "private integration directory escaped the repository"
            )
        identity = (
            root_stat.st_dev,
            root_stat.st_ino,
            created_stat.st_dev,
            created_stat.st_ino,
        )
        completed = True
        return directory, identity
    finally:
        if created_name is not None and not completed:
            try:
                current_stat = os.stat(
                    created_name,
                    dir_fd=root_descriptor,
                    follow_symlinks=False,
                )
                if (
                    stat.S_ISDIR(current_stat.st_mode)
                    and current_stat.st_uid == os.geteuid()
                    and (current_stat.st_dev, current_stat.st_ino)
                    == created_identity
                ):
                    os.rmdir(created_name, dir_fd=root_descriptor)
            except OSError:
                # Never recurse or follow a changed path during failure cleanup.
                pass
        os.close(root_descriptor)


def remove_integration_directory(
    directory: Path, identity: tuple[int, int, int, int]
) -> None:
    """Remove only the same empty private directory that this process created."""
    if (
        directory.parent != ROOT
        or not directory.name.startswith(INTEGRATION_DIRECTORY_PREFIX)
    ):
        raise RuntimeError(
            "refused cleanup for an unbound integration directory"
        )
    directory_flags = (
        os.O_RDONLY | os.O_CLOEXEC | os.O_DIRECTORY | os.O_NOFOLLOW
    )
    try:
        root_descriptor = os.open(ROOT, directory_flags)
    except OSError as exc:
        raise RuntimeError(
            "could not safely reopen the repository for integration cleanup"
        ) from exc
    try:
        root_stat = os.fstat(root_descriptor)
        try:
            current_stat = os.stat(
                directory.name,
                dir_fd=root_descriptor,
                follow_symlinks=False,
            )
        except OSError as exc:
            raise RuntimeError(
                "integration directory identity changed before cleanup"
            ) from exc
        expected = identity
        current = (
            root_stat.st_dev,
            root_stat.st_ino,
            current_stat.st_dev,
            current_stat.st_ino,
        )
        if (
            current != expected
            or not stat.S_ISDIR(current_stat.st_mode)
            or current_stat.st_uid != os.geteuid()
        ):
            raise RuntimeError(
                "integration directory identity changed before cleanup"
            )
        try:
            os.rmdir(directory.name, dir_fd=root_descriptor)
        except OSError as exc:
            raise RuntimeError(
                "integration directory is not empty; recursive cleanup was "
                "refused to protect unrelated data"
            ) from exc
    finally:
        os.close(root_descriptor)


@contextlib.contextmanager
def isolated_integration_directory():
    """Yield a fresh private directory and clean up only its verified inode."""
    directory, identity = create_integration_directory()
    try:
        yield directory
    finally:
        active_error = sys.exc_info()[1]
        try:
            remove_integration_directory(directory, identity)
        except RuntimeError as cleanup_error:
            if active_error is not None:
                raise RuntimeError(
                    f"{active_error}; integration cleanup also failed: "
                    f"{cleanup_error}"
                ) from active_error
            raise


def directory_identity(path: Path, *, purpose: str) -> tuple[int, int]:
    try:
        path_stat = path.lstat()
    except OSError as exc:
        raise RuntimeError(f"{purpose} is unavailable") from exc
    if not stat.S_ISDIR(path_stat.st_mode) or path.is_symlink():
        raise RuntimeError(f"{purpose} is not a real directory")
    return path_stat.st_dev, path_stat.st_ino


def execute_integration_checks(
    config: dict[str, Any], change: PlannedChange
) -> tuple[list[dict[str, Any]], str, str, str]:
    """Run deterministic checks on the same fresh-base merge tree as PR CI."""
    integration_tree = expected_integration_tree(change)
    integration_commit = synthetic_integration_commit(
        change,
        integration_tree,
    )
    with isolated_integration_directory() as temporary:
        worktree = temporary / "worktree"
        added = run(
            [
                "git",
                "worktree",
                "add",
                "--detach",
                str(worktree),
                integration_commit,
            ],
            capture=True,
        )
        if added.returncode:
            raise RuntimeError(
                "could not create isolated integration worktree: "
                + added.stdout.strip()
            )
        worktree_identity = directory_identity(
            worktree,
            purpose="isolated integration worktree",
        )
        try:
            checked_tree = git_output_at(worktree, "write-tree").strip()
            if checked_tree != integration_tree:
                raise RuntimeError(
                    "isolated integration checkout does not match git merge-tree"
                )
            status_value = git_output_at(
                worktree,
                "status",
                "--porcelain=v1",
                "--untracked-files=all",
                "-z",
            )
            if status_value:
                raise RuntimeError(
                    "synthetic pull-request integration checkout is not clean"
                )
            parents = git_output_at(
                worktree,
                "show",
                "-s",
                "--format=%P",
                "HEAD",
            ).strip().split()
            if parents != [change.base_tip, change.head_commit]:
                raise RuntimeError(
                    "synthetic pull-request integration parents are invalid"
                )
            before = integration_worktree_fingerprint(worktree)
            checks = execute_checks(config, cwd=worktree)
            after = integration_worktree_fingerprint(worktree)
            if after != before:
                raise RuntimeError(
                    "a deterministic check changed the isolated integration "
                    "checkout; commit the intended output and rerun"
                )
            return checks, integration_tree, integration_commit, before
        finally:
            if directory_identity(
                worktree,
                purpose="isolated integration worktree",
            ) != worktree_identity:
                raise RuntimeError(
                    "isolated integration worktree identity changed; cleanup "
                    "was refused"
                )
            removed = run(
                ["git", "worktree", "remove", str(worktree)],
                capture=True,
            )
            if removed.returncode:
                raise RuntimeError(
                    "could not remove isolated integration worktree: "
                    + removed.stdout.strip()
                )


def quote_diff_path(prefix: str, name: str) -> str:
    value = f"{prefix}/{name}"
    if re.search(r"[\s\"\\\x00-\x1f\x7f-\xff]", value):
        encoded = value.encode("utf-8", errors="surrogateescape")
        escaped: list[str] = []
        for byte in encoded:
            if byte == ord('\\'):
                escaped.append("\\\\")
            elif byte == ord('"'):
                escaped.append('\\"')
            elif byte == ord("\t"):
                escaped.append("\\t")
            elif byte == ord("\n"):
                escaped.append("\\n")
            elif byte == ord("\r"):
                escaped.append("\\r")
            elif 0x20 <= byte <= 0x7E:
                escaped.append(chr(byte))
            else:
                escaped.append(f"\\{byte:03o}")
        return '"' + "".join(escaped) + '"'
    return value


def render_untracked_patch(
    name: str, payload: bytes, mode: int
) -> str:
    if b"\0" in payload:
        raise RuntimeError(
            f"local review refused for binary untracked path: {name}"
        )
    try:
        text = payload.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise RuntimeError(
            f"local review refused for non-UTF-8 untracked path: {name}"
        ) from exc
    old_path = quote_diff_path("a", name)
    new_path = quote_diff_path("b", name)
    file_mode = "100755" if mode & 0o111 else "100644"
    parts = [
        f"diff --git {old_path} {new_path}\n",
        f"new file mode {file_mode}\n",
    ]
    if not text:
        parts.append("index 0000000..e69de29\n")
        return "".join(parts)
    parts.extend(
        [
        "--- /dev/null\n",
        f"+++ {new_path}\n",
        ]
    )
    lines = text.splitlines(keepends=True)
    if lines:
        parts.append(f"@@ -0,0 +1,{len(lines)} @@\n")
        for line in lines:
            if line.endswith("\n"):
                parts.append("+" + line)
            else:
                parts.append("+" + line + "\n")
                parts.append("\\ No newline at end of file\n")
    return "".join(parts)


def planned_change(
    config: dict[str, Any], *, base_override: Optional[str] = None
) -> PlannedChange:
    initial_tree_fingerprint = tree_fingerprint()
    base_ref, base_tip, base_commit = resolve_base(config, base_override)
    head_commit = git_output("rev-parse", "--verify", "HEAD^{commit}").strip()
    tracked_diff = git_output(
        "diff",
        "--no-ext-diff",
        "--no-textconv",
        "--binary",
        "--unified=40",
        base_commit,
        "--",
    )
    if "GIT binary patch\n" in tracked_diff or "\nBinary files " in tracked_diff:
        raise RuntimeError(
            "local review refused because the planned tracked diff contains "
            "binary content"
        )
    tracked_names = git_output(
        "diff", "--name-only", "--no-renames", "-z", base_commit, "--"
    ).split("\0")
    max_bytes = require_positive_integer(
        config["review"]["max_diff_bytes"],
        "review.max_diff_bytes",
        maximum=MAX_REVIEW_BYTES,
    )
    untracked_hashes: dict[str, str] = {}
    patches: list[str] = []
    consumed = utf8_size(tracked_diff)
    for name in untracked_names():
        remaining = max_bytes - consumed
        if remaining <= 0:
            raise RuntimeError(
                f"planned diff exceeds local review limit of {max_bytes} bytes"
            )
        payload, mode = read_repository_file(
            name,
            purpose="Local review",
            max_bytes=remaining,
        )
        patch = render_untracked_patch(name, payload, mode)
        patch_bytes = utf8_size(patch)
        consumed += patch_bytes
        if consumed > max_bytes:
            raise RuntimeError(
                f"planned diff exceeds local review limit of {max_bytes} bytes"
            )
        patches.append(patch)
        untracked_hashes[name] = sha256_bytes(payload)
    diff = tracked_diff + "".join(patches)
    if utf8_size(diff) > max_bytes:
        raise RuntimeError(
            f"planned diff exceeds local review limit of {max_bytes} bytes"
        )
    paths = tuple(
        sorted(
            {
                path
                for path in tracked_names
                if path
            }
            | set(untracked_hashes)
        )
    )
    final_tree_fingerprint = tree_fingerprint()
    if final_tree_fingerprint != initial_tree_fingerprint:
        raise RuntimeError(
            "Git tree changed while constructing the exact planned push patch"
        )
    change = PlannedChange(
        base_ref=base_ref,
        base_tip=base_tip,
        base_commit=base_commit,
        head_commit=head_commit,
        diff=diff,
        paths=paths,
        untracked_sha256=untracked_hashes,
        tree_fingerprint=final_tree_fingerprint,
    )
    ensure_review_safe(change)
    return change


def changed_paths() -> list[str]:
    """Return all index, worktree, and untracked paths, including rename pairs."""
    values = git_output(
        "status",
        "--porcelain=v1",
        "-z",
        "--untracked-files=all",
    ).split("\0")
    paths: list[str] = []
    index = 0
    while index < len(values):
        entry = values[index]
        index += 1
        if not entry:
            continue
        if len(entry) < 4:
            raise RuntimeError("malformed porcelain status entry")
        status_value = entry[:2]
        paths.append(entry[3:])
        if "R" in status_value or "C" in status_value:
            if index >= len(values) or not values[index]:
                raise RuntimeError("rename/copy status is missing its paired path")
            paths.append(values[index])
            index += 1
    return paths


def planned_paths(
    config: Optional[dict[str, Any]] = None,
    *,
    base_override: Optional[str] = None,
) -> list[str]:
    if config is None:
        config = load_config()
    return list(planned_change(config, base_override=base_override).paths)


def planned_diff(
    config: Optional[dict[str, Any]] = None,
    *,
    base_override: Optional[str] = None,
) -> str:
    if config is None:
        config = load_config()
    return planned_change(config, base_override=base_override).diff


def untracked_review_text(max_bytes: int = 1_000_000) -> str:
    """Return bounded UTF-8 untracked content for compatibility tests."""
    chunks: list[str] = []
    total = 0
    for name in untracked_names():
        payload, _ = read_repository_file(
            name,
            purpose="Local review",
            max_bytes=max_bytes - total,
        )
        total += len(payload)
        try:
            chunks.append(payload.decode("utf-8"))
        except UnicodeDecodeError as exc:
            raise RuntimeError(
                f"local review refused for non-UTF-8 untracked path: {name}"
            ) from exc
    return "\n".join(chunks)


def ensure_review_safe(change: PlannedChange) -> None:
    unsafe = []
    for path in change.paths:
        lowered = path.lower()
        if any(part in lowered for part in SECRET_PATH_PARTS):
            unsafe.append(path)
    if unsafe:
        raise RuntimeError(
            "local review refused for secret-like paths: "
            + ", ".join(sorted(unsafe))
        )
    scan_text = "".join(
        line
        for line in change.diff.splitlines(keepends=True)
        if line.rstrip("\r\n") != KNOWN_NON_SECRET_REMOVED_REVIEW_LINE
    )
    if any(pattern.search(scan_text) for pattern in SECRET_CONTENT_PATTERNS):
        raise RuntimeError(
            "local review refused because the planned review input contains "
            "secret-like content"
        )
    if any(Path(path).name.lower() == ".npmrc" for path in change.paths) \
        and NPMRC_AUTH_PATTERN.search(scan_text):
        raise RuntimeError(
            "local review refused because planned .npmrc content contains "
            "authentication configuration"
        )


def checkout_sanitized_base(commit: str, destination: Path, hooks: Path) -> None:
    """Materialize an exact Git tree without archive export transformations.

    ``git archive`` observes export-ignore/export-subst and ZIP cannot preserve
    Git symlinks.  A clean, local temporary repository checks out the commit
    directly from its object tree instead.  It deliberately has no templates,
    global/system config, or hooks.
    """
    initialized = run(
        [
            "git",
            "-c",
            "init.templateDir=",
            "-c",
            f"core.hooksPath={hooks}",
            "init",
            "-q",
            "-b",
            "review-base",
        ],
        capture=True,
        cwd=destination,
    )
    if initialized.returncode:
        raise RuntimeError(
            "could not initialize sanitized review repository: "
            + initialized.stdout.strip()
        )
    fetched = run(
        [
            "git",
            "-c",
            "protocol.file.allow=always",
            "fetch",
            "-q",
            "--no-tags",
            "--no-recurse-submodules",
            str(ROOT),
            commit,
        ],
        capture=True,
        cwd=destination,
    )
    if fetched.returncode:
        raise RuntimeError(
            "could not fetch sanitized review base: " + fetched.stdout.strip()
        )
    checked_out = run(
        ["git", "checkout", "-q", "--detach", "FETCH_HEAD"],
        capture=True,
        cwd=destination,
    )
    if checked_out.returncode:
        raise RuntimeError(
            "could not materialize sanitized review base: "
            + checked_out.stdout.strip()
        )


@contextlib.contextmanager
def sanitized_review_workspace(change: PlannedChange):
    """Yield a tracked-only repository snapshot with the exact patch applied."""
    assert_safe_git_configuration(ROOT)
    with tempfile.TemporaryDirectory(prefix="lit-agent-review-") as temporary:
        root = Path(temporary)
        workspace = root / "workspace"
        workspace.mkdir()
        disabled_hooks = root / "disabled-hooks"
        disabled_hooks.mkdir(mode=0o700)
        checkout_sanitized_base(change.base_tip, workspace, disabled_hooks)
        if change.diff:
            applied = run(
                [
                    "git",
                    "-c",
                    f"core.hooksPath={disabled_hooks}",
                    "apply",
                    "--3way",
                    "--index",
                    "--binary",
                    "--whitespace=nowarn",
                    "-",
                ],
                capture=True,
                input_text=change.diff,
                cwd=workspace,
            )
            if applied.returncode:
                raise RuntimeError(
                    "could not apply exact patch in sanitized review repository: "
                    + applied.stdout.strip()
                )
            committed = run(
                [
                    "git",
                    "-c",
                    f"core.hooksPath={disabled_hooks}",
                    "-c",
                    "user.name=Lightning IT push-ready",
                    "-c",
                    "user.email=push-ready@invalid",
                    "commit",
                    "-qm",
                    "sanitized exact planned push",
                ],
                capture=True,
                cwd=workspace,
            )
            if committed.returncode:
                raise RuntimeError(
                    "could not commit exact patch in sanitized review repository: "
                    + committed.stdout.strip()
                )
        source_status = git_output(
            "status",
            "--porcelain=v1",
            "--untracked-files=all",
            "-z",
        )
        if not source_status:
            expected_tree = expected_integration_tree(change)
            actual_tree = git_output_at(workspace, "write-tree").strip()
            if actual_tree != expected_tree:
                raise RuntimeError(
                    "sanitized review tree does not match the synthetic "
                    "pull-request integration tree"
                )
        ensure_workspace_review_safe(workspace)
        yield workspace, root


def ensure_workspace_review_safe(workspace: Path) -> None:
    """Scan the complete tracked review snapshot before external model use."""
    names = git_output_at(workspace, "ls-files", "-z").split("\0")
    total = 0
    unsafe_paths: list[str] = []
    sensitive_basenames = {
        ".env",
        ".netrc",
        ".pypirc",
        "auth.json",
        "credentials",
        "credentials.json",
        "id_ed25519",
        "id_rsa",
        "kubeconfig",
        "vault-password",
    }
    sensitive_directories = {".aws", ".ssh", "secrets"}
    for name in (entry for entry in names if entry):
        parts = tuple(part.lower() for part in Path(name).parts)
        if (
            parts[-1] in sensitive_basenames
            or any(part in sensitive_directories for part in parts[:-1])
        ):
            unsafe_paths.append(name)
        candidate = workspace / name
        if not candidate.is_file() or candidate.is_symlink():
            raise RuntimeError(
                f"sanitized review path is not a regular file: {name}"
            )
        payload = candidate.read_bytes()
        total += len(payload)
        if total > 500_000_000:
            raise RuntimeError("sanitized review secret scan exceeds 500 MB")
        # Preserve every ASCII secret marker even when an unchanged tracked
        # binary contains invalid UTF-8. New or changed binary content is
        # rejected from the planned diff before workspace creation.
        text_value = payload.decode("utf-8", errors="replace")
        if parts[-1] == ".npmrc" and NPMRC_AUTH_PATTERN.search(text_value):
            raise RuntimeError(
                "local review refused because tracked .npmrc contains "
                "authentication configuration"
            )
        if any(pattern.search(text_value) for pattern in SECRET_CONTENT_PATTERNS):
            raise RuntimeError(
                "local review refused because the tracked review snapshot "
                f"contains secret-like content in {name}"
            )
    if unsafe_paths:
        raise RuntimeError(
            "local review refused for secret-like tracked paths: "
            + ", ".join(sorted(unsafe_paths))
        )


def tracked_instruction_bundle(workspace: Path) -> str:
    names = git_output_at(workspace, "ls-files", "-z").split("\0")
    chunks: list[str] = []
    total = 0
    for name in sorted(
        entry
        for entry in names
        if entry and INSTRUCTION_PATH_PATTERN.search(entry)
    ):
        candidate = workspace / name
        if not candidate.is_file() or candidate.is_symlink():
            raise RuntimeError(
                f"sanitized instruction is not a regular file: {name}"
            )
        payload = candidate.read_bytes()
        total += len(payload)
        if total > 2_000_000:
            raise RuntimeError("tracked instruction bundle exceeds 2 MB")
        try:
            text_value = payload.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise RuntimeError(
                f"tracked instruction is not UTF-8: {name}"
            ) from exc
        chunks.append(f"----- BEGIN {name} -----\n{text_value}\n----- END {name} -----")
    if not any(chunk.startswith("----- BEGIN AGENTS.md -----") for chunk in chunks):
        raise RuntimeError("sanitized review repository lacks tracked AGENTS.md")
    return "\n\n".join(chunks)


def minimal_agent_environment(
    *, state_root: Path, agent: str, workspace: Optional[Path] = None
) -> dict[str, str]:
    allowed = {
        "HOME",
        "LANG",
        "LC_ALL",
        "LOGNAME",
        "PATH",
        "SSL_CERT_DIR",
        "SSL_CERT_FILE",
        "TMPDIR",
        "USER",
    }
    if agent == "copilot":
        allowed.update(
            {
                "COPILOT_GH_HOST",
                "COPILOT_GITHUB_TOKEN",
                "GH_HOST",
                "GH_TOKEN",
                "GITHUB_TOKEN",
                "HTTPS_PROXY",
                "HTTP_PROXY",
                "NO_PROXY",
            }
        )
    else:
        allowed.update({"CODEX_API_KEY", "OPENAI_API_KEY"})
    environment = {
        key: value
        for key, value in os.environ.items()
        if key in allowed and value
    }
    environment["CI"] = "1"
    environment["TMPDIR"] = str(state_root / "tmp")
    Path(environment["TMPDIR"]).mkdir(mode=0o700, exist_ok=True)
    if agent == "copilot":
        environment["COPILOT_HOME"] = str(state_root / "copilot-home")
        Path(environment["COPILOT_HOME"]).mkdir(mode=0o700, exist_ok=True)
        environment.update(COPILOT_PROMPT_MODE_BOUNDARY)
        if not any(
            environment.get(name)
            for name in ("COPILOT_GITHUB_TOKEN", "GH_TOKEN", "GITHUB_TOKEN")
        ):
            gh = shutil.which("gh")
            if gh is not None:
                token = run(
                    [gh, "auth", "token"],
                    capture=True,
                    timeout=30,
                    env=environment,
                )
                if token.returncode == 0 and token.stdout.strip():
                    environment["COPILOT_GITHUB_TOKEN"] = token.stdout.strip()
    else:
        if workspace is None:
            raise RuntimeError("Codex isolation requires an explicit workspace")
        isolated_home = state_root / "codex-home"
        isolated_home.mkdir(mode=0o700, exist_ok=True)
        source_home = Path(
            os.environ.get("CODEX_HOME", str(Path.home() / ".codex"))
        )
        source_auth = source_home / "auth.json"
        if (
            not environment.get("CODEX_API_KEY")
            and not environment.get("OPENAI_API_KEY")
            and source_auth.is_file()
            and not source_auth.is_symlink()
        ):
            target_auth = isolated_home / "auth.json"
            shutil.copy2(source_auth, target_auth)
            target_auth.chmod(0o600)
        workspace_key = json.dumps(str(workspace.resolve()))
        permission_profile = codex_permission_profile_name(state_root)
        (isolated_home / "config.toml").write_text(
            "\n".join(
                [
                    f'default_permissions = "{permission_profile}"',
                    'approval_policy = "never"',
                    "allow_login_shell = false",
                    'web_search = "disabled"',
                    "",
                    "[features]",
                    "apps = false",
                    "hooks = false",
                    "memories = false",
                    "multi_agent = false",
                    "remote_plugin = false",
                    "",
                    f"[permissions.{permission_profile}.filesystem]",
                    '":minimal" = "read"',
                    "",
                    (
                        f'[permissions.{permission_profile}.filesystem.'
                        '":workspace_roots"]'
                    ),
                    '"." = "read"',
                    "",
                    f"[permissions.{permission_profile}.network]",
                    "enabled = false",
                    "",
                    f"[projects.{workspace_key}]",
                    'trust_level = "untrusted"',
                    "",
                    "[shell_environment_policy]",
                    'inherit = "none"',
                    "ignore_default_excludes = false",
                    "",
                ]
            ),
            encoding="utf-8",
        )
        environment["CODEX_HOME"] = str(isolated_home)
    process_home = state_root / f"{agent}-process-home"
    process_home.mkdir(mode=0o700, exist_ok=True)
    environment["HOME"] = str(process_home)
    return environment


def require_copilot_prompt_mode_boundary(
    environment: dict[str, str], arguments: list[str]
) -> None:
    """Fail unless official prompt-mode and CLI isolation controls are active."""
    invalid_environment = [
        name
        for name, expected in COPILOT_PROMPT_MODE_BOUNDARY.items()
        if environment.get(name) != expected
    ]
    missing_arguments = [
        argument
        for argument in COPILOT_REQUIRED_SAFETY_ARGUMENTS
        if argument not in arguments
    ]
    if invalid_environment or missing_arguments:
        details = []
        if invalid_environment:
            details.append(
                "environment: " + ", ".join(sorted(invalid_environment))
            )
        if missing_arguments:
            details.append("arguments: " + ", ".join(missing_arguments))
        raise RuntimeError(
            "Copilot prompt-mode safety boundary is incomplete: "
            + "; ".join(details)
        )


def codex_permission_profile_name(state_root: Path) -> str:
    suffix = sha256_text(str(state_root.resolve()))[:16]
    return f"lit-local-review-{suffix}"


def require_codex_permission_profile_version(version: str) -> None:
    match = re.search(r"\b(\d+)\.(\d+)\.(\d+)(?:[-+.\w]*)?\b", version)
    if match is None:
        raise RuntimeError(
            "Codex version is unparseable; permission-profile enforcement "
            "cannot be established"
        )
    current = tuple(int(value) for value in match.groups())
    if current < (0, 138, 0):
        raise RuntimeError(
            "Codex 0.138.0 or newer is required for local permission profiles"
        )


def verify_codex_permission_profile(
    command: list[str],
    *,
    environment: dict[str, str],
    workspace: Path,
    state_root: Path,
) -> None:
    """Exercise the selected profile before exposing repository content."""
    true_command = shutil.which("true")
    cat_command = shutil.which("cat")
    if true_command is None or cat_command is None:
        raise RuntimeError(
            "Codex permission-profile self-test requires true and cat"
        )
    profile = codex_permission_profile_name(state_root)
    common = [
        *command,
        "sandbox",
        "--include-managed-config",
        "--permission-profile",
        profile,
        "--cd",
        str(workspace),
        "--",
    ]
    allowed = run(
        [*common, true_command],
        capture=True,
        timeout=30,
        cwd=workspace,
        env=environment,
    )
    if allowed.returncode:
        raise RuntimeError(
            "Codex permission-profile self-test could not execute a minimal "
            "runtime command"
        )
    workspace_read = run(
        [*common, cat_command, str(workspace / "AGENTS.md")],
        capture=True,
        timeout=30,
        cwd=workspace,
        env=environment,
    )
    if workspace_read.returncode:
        raise RuntimeError(
            "Codex permission-profile self-test could not read the sanitized "
            "review workspace"
        )
    canary = state_root / "codex-denied-read-canary"
    canary.write_text(
        "LIT_CODEX_PERMISSION_PROFILE_CANARY\n",
        encoding="utf-8",
    )
    canary.chmod(0o600)
    try:
        denied = run(
            [*common, cat_command, str(canary)],
            capture=True,
            timeout=30,
            cwd=workspace,
            env=environment,
        )
    finally:
        canary.unlink(missing_ok=True)
    if denied.returncode == 0:
        raise RuntimeError(
            "Codex permission profile allowed a read outside the sanitized "
            "review workspace"
        )


def resolve_command(command: list[str], name: str) -> list[str]:
    executable = command[0]
    if "/" not in executable and "\\" not in executable:
        resolved = shutil.which(executable)
        if resolved is None:
            raise RuntimeError(f"required {name} executable is unavailable")
        return [resolved, *command[1:]]
    candidate = Path(executable)
    if not candidate.is_absolute():
        candidate = ROOT / candidate
        current = ROOT
        try:
            relative_parts = candidate.relative_to(ROOT).parts
        except ValueError as exc:
            raise RuntimeError(
                f"required {name} command escapes the repository"
            ) from exc
        if any(part in {"", ".", ".."} for part in relative_parts):
            raise RuntimeError(
                f"required {name} command uses an unsafe repository path"
            )
        for part in relative_parts:
            current /= part
            if current.is_symlink():
                raise RuntimeError(
                    f"required {name} command contains a symbolic link"
                )
        try:
            candidate.resolve(strict=True).relative_to(ROOT)
        except (OSError, ValueError) as exc:
            raise RuntimeError(
                f"required {name} command is unavailable or unsafe"
            ) from exc
    if not candidate.is_file() or candidate.is_symlink():
        raise RuntimeError(f"required {name} command is unavailable or unsafe")
    return [str(candidate.resolve()), *command[1:]]


def copilot_container_command(
    environment: dict[str, str], workspace: Path
) -> list[str]:
    """Run the pinned Copilot CLI without requiring a host installation."""
    requested_engine = os.environ.get("WUNDER_CONTAINER_ENGINE")
    if requested_engine and requested_engine not in {"docker", "podman"}:
        raise RuntimeError(
            "WUNDER_CONTAINER_ENGINE must be docker or podman when set"
        )
    engine_names = (
        [requested_engine]
        if requested_engine
        else ["docker", "podman"]
    )
    engine = next(
        (
            resolved
            for name in engine_names
            if name is not None
            for resolved in [shutil.which(name)]
            if resolved is not None
        ),
        None,
    )
    if engine is None:
        raise RuntimeError(
            "Copilot CLI requires either the host executable or a usable "
            "Docker/Podman client for the pinned Devtool fallback"
        )
    if Path(engine).name == "docker":
        configured_host = os.environ.get("DOCKER_HOST")
        if configured_host and not configured_host.startswith("unix://"):
            raise RuntimeError(
                "containerized Copilot review refuses a non-local DOCKER_HOST"
            )
        socket_candidates = []
        if configured_host:
            socket_candidates.append(configured_host)
        socket_candidates.extend(
            [
                str(Path.home() / ".docker" / "run" / "docker.sock"),
                "/var/run/docker.sock",
            ]
        )
        for value in socket_candidates:
            socket_path = existing_unix_socket(value)
            if socket_path:
                environment["DOCKER_HOST"] = f"unix://{socket_path}"
                break
    elif os.environ.get("XDG_RUNTIME_DIR"):
        runtime_path = Path(os.environ["XDG_RUNTIME_DIR"])
        if runtime_path.is_absolute() and runtime_path.is_dir():
            environment["XDG_RUNTIME_DIR"] = str(runtime_path.resolve())
    canonical_workspace = workspace.resolve(strict=True)
    if (
        not canonical_workspace.is_dir()
        or workspace.is_symlink()
        or any(character in str(canonical_workspace) for character in (":", ","))
    ):
        raise RuntimeError("Copilot review workspace is unsafe to mount")
    workspace_mount = f"{canonical_workspace}:/workspace:ro"
    if Path(engine).name == "podman" and platform.system() == "Linux":
        workspace_mount += ",z"
    command = [
        engine,
        "run",
        "--rm",
        "-i",
        "--network",
        "bridge",
        "--read-only",
        "--cap-drop",
        "ALL",
        "--security-opt",
        "no-new-privileges=true",
        "--pids-limit",
        "256",
        "--tmpfs",
        "/tmp:rw,exec,nosuid,nodev,size=256m",
        "--tmpfs",
        "/copilot-cache:rw,exec,nosuid,nodev,size=256m",
        "--tmpfs",
        "/copilot-home:rw,exec,nosuid,nodev,size=256m",
        "--tmpfs",
        "/home/wunder:rw,exec,nosuid,nodev,size=256m,mode=1777",
        "-e",
        "CI=1",
        "-e",
        "HOME=/home/wunder",
        "-e",
        "XDG_CACHE_HOME=/copilot-cache",
        "-e",
        "COPILOT_HOME=/copilot-home",
        "-v",
        workspace_mount,
        "-w",
        "/workspace",
    ]
    if Path(engine).name == "podman":
        command.append("--read-only-tmpfs=false")
    for name, value in COPILOT_PROMPT_MODE_BOUNDARY.items():
        if environment.get(name) != value:
            raise RuntimeError(
                "Copilot container prompt-mode boundary is incomplete: "
                + name
            )
        command.extend(["-e", f"{name}={value}"])
    for name in ("COPILOT_GITHUB_TOKEN", "GH_TOKEN", "GITHUB_TOKEN"):
        if environment.get(name):
            command.extend(["-e", name])
    command.extend([COPILOT_DEVTOOL_IMAGE, "copilot"])
    return command


def tool_version(
    command: list[str],
    name: str,
    *,
    cwd: Optional[Path] = None,
    env: Optional[Dict[str, str]] = None,
) -> str:
    try:
        result = run(
            [*command, "--version"],
            capture=True,
            timeout=30,
            cwd=cwd,
            env=env,
        )
    except subprocess.TimeoutExpired as exc:
        raise RuntimeError(f"{name} version check timed out") from exc
    version = result.stdout.strip()
    if result.returncode or not version:
        raise RuntimeError(f"{name} did not report a version")
    return version[:500]


def review_prompt(
    change: PlannedChange, *, agent: str, instructions: str
) -> str:
    local_boundary = (
        "This is a local pre-push approximation. It is not, and must not be "
        "reported as, the authoritative GitHub Copilot pull-request review. "
        "The server-side current-head review and required GitHub Actions "
        "checks remain mandatory."
    )
    task = (
        "Review the exact planned push patch below against AGENTS.md, nested "
        "AGENTS.md files, and .github/copilot-instructions.md. Check "
        "correctness, security, failure behavior, tests, scope, and likely "
        "GitHub Actions failures. The patch combines committed, staged, "
        "unstaged, and safe untracked content relative to the recorded "
        "merge-base. The mounted workspace is the authoritative merge-base "
        "snapshot with this patch applied: a dependency need not have a diff "
        "hunk, so verify its presence in that workspace before reporting it "
        "as missing. Do not modify files, use network tools, or expose "
        "credentials. The embedded patch is authoritative for review scope."
    )
    if agent == "copilot":
        verdict = (
            f"End with exactly {PASS_MARKER!r} only when there is no actionable "
            f"or unresolved finding of any severity. Otherwise end with exactly "
            f"{BLOCKED_MARKER!r}."
        )
        prefix = ""
    else:
        verdict = (
            "Use the caller-supplied structured verdict schema. A passing "
            "verdict requires an empty findings array."
        )
        prefix = ""
    return (
        prefix
        + local_boundary
        + "\n\n"
        + task
        + "\n\n"
        + verdict
        + "\n\n"
        + f"Base ref: {change.base_ref}\n"
        + f"Base tip: {change.base_tip}\n"
        + f"Merge-base: {change.base_commit}\n"
        + f"HEAD: {change.head_commit}\n"
        + f"Patch SHA-256: {change.diff_sha256}\n"
        + "\n----- BEGIN TRACKED REVIEW INSTRUCTIONS -----\n"
        + instructions
        + "\n----- END TRACKED REVIEW INSTRUCTIONS -----\n"
        + "\n----- BEGIN EXACT PLANNED PUSH PATCH -----\n"
        + change.diff
        + "\n----- END EXACT PLANNED PUSH PATCH -----\n"
    )


def copilot_review(
    config: dict[str, Any],
    change: PlannedChange,
    expected_tree_fingerprint: str,
    *,
    workspace: Path,
    state_root: Path,
    instructions: str,
) -> dict[str, Any]:
    agent = config["agents"]["copilot"]
    environment = minimal_agent_environment(
        state_root=state_root,
        agent="copilot",
    )
    command = copilot_container_command(environment, workspace)
    container_runtime = Path(command[0]).name
    container_runtime_version = tool_version(
        [command[0]],
        "Copilot container runtime",
        cwd=workspace,
        env=environment,
    )
    version = tool_version(
        command,
        "Copilot CLI",
        cwd=workspace,
        env=environment,
    )
    args = [
        *command,
        *COPILOT_REQUIRED_SAFETY_ARGUMENTS,
        "--no-auto-update",
        "--secret-env-vars=COPILOT_GITHUB_TOKEN,GH_TOKEN,GITHUB_TOKEN,"
        "CODEX_API_KEY,OPENAI_API_KEY,AWS_ACCESS_KEY_ID,"
        "AWS_SECRET_ACCESS_KEY,AWS_SESSION_TOKEN",
    ]
    if agent.get("model"):
        args.extend(["--model", agent["model"]])
    require_copilot_prompt_mode_boundary(environment, args)
    # GitHub's programmatic CLI contract explicitly supports piping a prompt
    # to `copilot`; `-s` is also documented for captured output in that mode.
    # Keep the exact private diff on stdin instead of adding `-p`, which would
    # expose the complete prompt through the process argument list.
    started_at = now_utc()
    started = time.monotonic()
    try:
        result = run(
            args,
            capture=True,
            input_text=review_prompt(
                change,
                agent="copilot",
                instructions=instructions,
            ),
            timeout=agent["timeout_seconds"],
            cwd=workspace,
            env=environment,
        )
    except subprocess.TimeoutExpired as exc:
        raise RuntimeError(
            "Copilot CLI exact-diff review timed out after "
            f"{agent['timeout_seconds']} seconds"
        ) from exc
    completed_at = now_utc()
    review = result.stdout
    final_line = next(
        (line.strip() for line in reversed(review.splitlines()) if line.strip()),
        "",
    )
    if tree_fingerprint() != expected_tree_fingerprint:
        raise RuntimeError(
            "Copilot CLI exact-diff review modified the reviewed Git tree"
        )
    if (
        result.returncode
        or final_line != PASS_MARKER
        or any(line.strip() == BLOCKED_MARKER for line in review.splitlines())
    ):
        print(review)
        raise RuntimeError(
            "Copilot CLI exact-diff review did not produce a passing result"
        )
    if COPILOT_DEVTOOL_IMAGE not in command:
        raise RuntimeError("Copilot CLI is not bound to the pinned Devtool image")
    print(review)
    return {
        "agent": "copilot",
        "surface": "GitHub Copilot CLI read-only exact-diff review",
        "authoritative_pr_review": False,
        "required": agent["required"],
        "command": (
            "copilot <pinned-devtool-container> -s --no-ask-user "
            "--available-tools=view,grep,glob --allow-tool=read "
            "--deny-tool=write,memory,url,shell"
        ),
        "model": agent.get("model", "cli-default"),
        "execution_mode": "pinned-devtool-container",
        "container_image": COPILOT_DEVTOOL_IMAGE,
        "container_runtime": container_runtime,
        "container_runtime_version": container_runtime_version,
        "tool_version": version,
        "started_at": started_at,
        "completed_at": completed_at,
        "duration_seconds": round(time.monotonic() - started, 3),
        "output_sha256": sha256_text(review),
        "result": "pass",
    }


def codex_output_schema() -> dict[str, Any]:
    return {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "type": "object",
        "properties": {
            "verdict": {"type": "string", "enum": ["pass", "blocked"]},
            "summary": {"type": "string"},
            "findings": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "title": {"type": "string"},
                        "description": {"type": "string"},
                    },
                    "required": ["title", "description"],
                    "additionalProperties": False,
                },
            },
        },
        "required": ["verdict", "summary", "findings"],
        "additionalProperties": False,
    }


def codex_review(
    config: dict[str, Any],
    change: PlannedChange,
    expected_tree_fingerprint: str,
    *,
    workspace: Path,
    state_root: Path,
    instructions: str,
) -> dict[str, Any]:
    agent = config["agents"]["codex"]
    command = resolve_command(agent["command"], "Codex CLI")
    environment = minimal_agent_environment(
        state_root=state_root,
        agent="codex",
        workspace=workspace,
    )
    version = tool_version(
        command,
        "Codex CLI",
        cwd=workspace,
        env=environment,
    )
    require_codex_permission_profile_version(version)
    verify_codex_permission_profile(
        command,
        environment=environment,
        workspace=workspace,
        state_root=state_root,
    )
    started_at = now_utc()
    started = time.monotonic()
    with tempfile.TemporaryDirectory(
        prefix="lit-codex-review-",
        dir=state_root,
    ) as temporary:
        temp = Path(temporary)
        schema = temp / "review-schema.json"
        output = temp / "last-message.json"
        schema.write_text(
            json.dumps(codex_output_schema(), sort_keys=True),
            encoding="utf-8",
        )
        args = [
            *command,
            "--strict-config",
            "exec",
            "--ephemeral",
            "--ignore-rules",
            "--color",
            "never",
            "--output-schema",
            str(schema),
            "--output-last-message",
            str(output),
        ]
        if agent.get("model"):
            args.extend(["--model", agent["model"]])
        args.append("-")
        codex_prompt = (
            review_prompt(
                change,
                agent="codex",
                instructions=instructions,
            )
            + "\nReturn only a JSON object matching the supplied schema. Use "
            "'pass' with an empty findings array only when the exact patch has "
            "no blocking finding; otherwise use 'blocked' and list findings.\n"
        )
        try:
            result = run(
                args,
                capture=True,
                input_text=codex_prompt,
                timeout=agent["timeout_seconds"],
                cwd=workspace,
                env=environment,
            )
        except subprocess.TimeoutExpired as exc:
            raise RuntimeError(
                f"Codex review timed out after {agent['timeout_seconds']} seconds"
            ) from exc
        if not output.is_file():
            if result.stdout:
                print(result.stdout)
            raise RuntimeError("Codex review did not produce structured output")
        raw_review = output.read_text(encoding="utf-8")
    completed_at = now_utc()
    if tree_fingerprint() != expected_tree_fingerprint:
        raise RuntimeError("Codex review modified the reviewed Git tree")
    try:
        review = json.loads(raw_review)
    except json.JSONDecodeError as exc:
        raise RuntimeError("Codex review output is not valid JSON") from exc
    valid_shape = (
        isinstance(review, dict)
        and set(review) == {"verdict", "summary", "findings"}
        and isinstance(review.get("summary"), str)
        and isinstance(review.get("findings"), list)
        and all(
            isinstance(finding, dict)
            and set(finding) == {"title", "description"}
            and isinstance(finding.get("title"), str)
            and isinstance(finding.get("description"), str)
            for finding in review.get("findings", [])
        )
    )
    if not valid_shape:
        raise RuntimeError("Codex review output does not match the required schema")
    if (
        result.returncode
        or review.get("verdict") != "pass"
        or review.get("findings") != []
    ):
        print(raw_review)
        raise RuntimeError("Codex review did not produce a passing result")
    print(raw_review)
    return {
        "agent": "codex",
        "surface": "Codex CLI exec read-only exact-diff review",
        "authoritative_pr_review": False,
        "required": agent["required"],
        "command": (
            "codex <configured-prefix> exec --ephemeral "
            "--permission-profile local-review --output-schema <schema> "
            "--output-last-message <output> -"
        ),
        "model": agent.get("model", "cli-default"),
        "execution_mode": "host",
        "container_image": None,
        "container_runtime": None,
        "container_runtime_version": None,
        "tool_version": version,
        "started_at": started_at,
        "completed_at": completed_at,
        "duration_seconds": round(time.monotonic() - started, 3),
        "output_sha256": sha256_text(raw_review),
        "result": "pass",
    }


def run_agent_reviews(
    config: dict[str, Any], change: PlannedChange
) -> list[dict[str, Any]]:
    expected = change.tree_fingerprint
    if tree_fingerprint() != expected:
        raise RuntimeError("exact planned push patch is stale before local review")
    reviews: list[dict[str, Any]] = []
    with sanitized_review_workspace(change) as (workspace, state_root):
        instructions = tracked_instruction_bundle(workspace)
        workspace_fingerprint = integration_worktree_fingerprint(
            workspace,
            include_ignored=True,
        )
        reviews.append(
            copilot_review(
                config,
                change,
                expected,
                workspace=workspace,
                state_root=state_root,
                instructions=instructions,
            )
        )
        if (
            integration_worktree_fingerprint(
                workspace,
                include_ignored=True,
            )
            != workspace_fingerprint
        ):
            raise RuntimeError(
                "Copilot review changed the sanitized exact-patch workspace"
            )
        reviews.append(
            codex_review(
                config,
                change,
                expected,
                workspace=workspace,
                state_root=state_root,
                instructions=instructions,
            )
        )
        if (
            integration_worktree_fingerprint(
                workspace,
                include_ignored=True,
            )
            != workspace_fingerprint
        ):
            raise RuntimeError(
                "Codex review changed the sanitized exact-patch workspace"
            )
    if tree_fingerprint() != expected:
        raise RuntimeError("local agent review changed the reviewed Git tree")
    return reviews


def command_version(command: list[str]) -> str:
    try:
        result = run(command, capture=True, timeout=30)
    except subprocess.TimeoutExpired as exc:
        raise RuntimeError(f"tool version check timed out: {command[0]}") from exc
    if result.returncode or not result.stdout.strip():
        raise RuntimeError(f"tool did not report a version: {command[0]}")
    return result.stdout.strip()[:500]


def platform_evidence() -> dict[str, str]:
    return {
        "system": platform.system(),
        "release": platform.release(),
        "machine": platform.machine(),
        "python_implementation": platform.python_implementation(),
        "python_version": platform.python_version(),
    }


def runtime_versions() -> dict[str, str]:
    return {
        "git": command_version(["git", "--version"]),
        "python": sys.version.replace("\n", " "),
    }


def governed_push_remote_from_url(
    name: str, url: str
) -> dict[str, str]:
    if name != "origin" or not url or any(
        ord(character) < 32 or ord(character) == 127 for character in url
    ):
        raise RuntimeError("push-ready requires the governed origin remote")
    value = url[:-4] if url.endswith(".git") else url
    prefixes = (
        "https://github.com/lightning-it/",
        "ssh://git@github.com/lightning-it/",
        "git@github.com:lightning-it/",
    )
    repository_name = ""
    for prefix in prefixes:
        if value.startswith(prefix):
            repository_name = value[len(prefix) :]
            break
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,99}", repository_name):
        raise RuntimeError(
            "origin push URL must target a Lightning IT repository on github.com"
        )
    return {
        "name": "origin",
        "host": "github.com",
        "repository": f"lightning-it/{repository_name}",
        "url_sha256": sha256_text(url),
    }


def governed_push_remote() -> dict[str, str]:
    url = git_output("remote", "get-url", "--push", "origin").strip()
    return governed_push_remote_from_url("origin", url)


def config_sha256() -> str:
    return sha256_bytes(CONFIG.read_bytes())


def write_evidence(
    config: dict[str, Any],
    checks: list[dict[str, Any]],
    reviews: list[dict[str, Any]],
    change: PlannedChange,
    *,
    started_at: str,
    started_monotonic: float,
    integration_tree: str,
    integration_commit: str,
    integration_fingerprint: str,
) -> None:
    evidence = evidence_path()
    evidence.parent.mkdir(parents=True, exist_ok=True)
    if tree_fingerprint() != change.tree_fingerprint:
        raise RuntimeError("exact planned push patch is stale before evidence write")
    completed_at = now_utc()
    payload = {
        "version": 2,
        "started_at": started_at,
        "completed_at": completed_at,
        "duration_seconds": round(time.monotonic() - started_monotonic, 3),
        "base_ref": change.base_ref,
        "base_tip": change.base_tip,
        "base_commit": change.base_commit,
        "head_commit": change.head_commit,
        "local_branch_ref": current_branch_ref(),
        "tree_fingerprint": change.tree_fingerprint,
        "integration_tree": integration_tree,
        "integration_commit": integration_commit,
        "integration_fingerprint": integration_fingerprint,
        "planned_diff_sha256": change.diff_sha256,
        "planned_paths": list(change.paths),
        "untracked_sha256": change.untracked_sha256,
        "config_sha256": config_sha256(),
        "instruction_files": instruction_file_hashes(),
        "platform": platform_evidence(),
        "runtime_versions": runtime_versions(),
        "push_remote": governed_push_remote(),
        "checks": checks,
        "agent_reviews": reviews,
        "remote_only_checks": config["remote_only_checks"],
        "parity_gaps": list(PARITY_GAPS),
        "remote_pr_review_authoritative": True,
        "push_scope": "clean-head",
        "evidence_trust": LOCAL_EVIDENCE_TRUST,
    }
    evidence.write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def parse_timestamp(value: Any, description: str) -> datetime:
    if not isinstance(value, str):
        raise RuntimeError(f"evidence {description} is invalid")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise RuntimeError(f"evidence {description} is invalid") from exc
    if parsed.tzinfo is None:
        raise RuntimeError(f"evidence {description} has no timezone")
    return parsed


def verify_evidence(config: dict[str, Any]) -> dict[str, Any]:
    evidence = evidence_path()
    if not evidence.is_file() or evidence.is_symlink():
        raise RuntimeError("push-ready evidence does not exist as a regular file")
    payload = json.loads(evidence.read_text(encoding="utf-8"))
    if not isinstance(payload, dict) or payload.get("version") != 2:
        raise RuntimeError("push-ready evidence must use version 2")
    completed = parse_timestamp(payload.get("completed_at"), "completed_at")
    started = parse_timestamp(payload.get("started_at"), "started_at")
    if started > completed:
        raise RuntimeError("push-ready evidence timestamps are reversed")
    duration = payload.get("duration_seconds")
    if (
        isinstance(duration, bool)
        or not isinstance(duration, (int, float))
        or duration < 0
    ):
        raise RuntimeError("push-ready evidence duration is invalid")
    age = (datetime.now(timezone.utc) - completed).total_seconds()
    max_age = config["evidence"]["max_age_seconds"]
    if age < -300 or age > max_age:
        raise RuntimeError(
            f"push-ready evidence is outside the allowed age of {max_age} seconds"
        )
    change = planned_change(config)
    expected_integration = expected_integration_tree(change)
    expected = {
        "config_sha256": config_sha256(),
        "instruction_files": instruction_file_hashes(),
        "base_ref": change.base_ref,
        "base_tip": change.base_tip,
        "base_commit": change.base_commit,
        "head_commit": change.head_commit,
        "local_branch_ref": current_branch_ref(),
        "tree_fingerprint": change.tree_fingerprint,
        "integration_tree": expected_integration,
        "integration_commit": synthetic_integration_commit(
            change,
            expected_integration,
        ),
        "planned_diff_sha256": change.diff_sha256,
        "planned_paths": list(change.paths),
        "untracked_sha256": change.untracked_sha256,
        "platform": platform_evidence(),
        "runtime_versions": runtime_versions(),
        "push_remote": governed_push_remote(),
        "remote_only_checks": config["remote_only_checks"],
        "parity_gaps": list(PARITY_GAPS),
        "remote_pr_review_authoritative": True,
        "push_scope": "clean-head",
        "evidence_trust": LOCAL_EVIDENCE_TRUST,
    }
    for key, value in expected.items():
        if payload.get(key) != value:
            raise RuntimeError(
                f"push-ready evidence is stale or malformed for {key}"
            )
    integration_fingerprint = payload.get("integration_fingerprint")
    if not isinstance(integration_fingerprint, str) or not re.fullmatch(
        r"[0-9a-f]{64}", integration_fingerprint
    ):
        raise RuntimeError(
            "push-ready evidence has an invalid integration fingerprint"
        )
    checks = payload.get("checks")
    if not isinstance(checks, list) or len(checks) != len(config["checks"]):
        raise RuntimeError("push-ready evidence skipped a required check")
    for configured, recorded in zip(config["checks"], checks):
        expected_command = (
            [sys.executable, *configured["command"][1:]]
            if configured["command"][0] in {"python", "python3"}
            else configured["command"]
        )
        if (
            not isinstance(recorded, dict)
            or recorded.get("name") != configured["name"]
            or recorded.get("command") != expected_command
            or recorded.get("exit_code") != 0
        ):
            raise RuntimeError(
                f"push-ready evidence lacks passing check {configured['name']}"
            )
        check_duration = recorded.get("duration_seconds")
        if (
            isinstance(check_duration, bool)
            or not isinstance(check_duration, (int, float))
            or check_duration < 0
        ):
            raise RuntimeError(
                f"push-ready evidence has invalid timing for {configured['name']}"
            )
        parse_timestamp(
            recorded.get("started_at"),
            f"check {configured['name']} started_at",
        )
        parse_timestamp(
            recorded.get("completed_at"),
            f"check {configured['name']} completed_at",
        )
    reviews = payload.get("agent_reviews")
    if not isinstance(reviews, list):
        raise RuntimeError("push-ready evidence has invalid agent reviews")
    by_name = {
        review.get("agent"): review
        for review in reviews
        if isinstance(review, dict)
    }
    enabled_agents = {
        name for name, agent in config["agents"].items() if agent["enabled"]
    }
    if len(by_name) != len(reviews) or set(by_name) != enabled_agents:
        raise RuntimeError("push-ready evidence has incomplete agent reviews")
    for name, agent in config["agents"].items():
        if not agent["enabled"]:
            continue
        review = by_name.get(name)
        if (
            not isinstance(review, dict)
            or review.get("result") != "pass"
            or review.get("required") is not agent["required"]
            or not isinstance(review.get("tool_version"), str)
            or not review.get("tool_version")
            or review.get("authoritative_pr_review") is not False
            or not isinstance(review.get("output_sha256"), str)
            or not re.fullmatch(r"[0-9a-f]{64}", review["output_sha256"])
        ):
            raise RuntimeError(
                f"push-ready evidence lacks a passing local {name} review"
            )
        execution_mode = review.get("execution_mode")
        if name == "copilot":
            if execution_mode != "pinned-devtool-container":
                raise RuntimeError(
                    "push-ready evidence has invalid Copilot execution mode"
                )
            if (
                review.get("container_image") != COPILOT_DEVTOOL_IMAGE
                or review.get("container_runtime") not in {"docker", "podman"}
                or not isinstance(
                    review.get("container_runtime_version"), str
                )
                or not review.get("container_runtime_version")
            ):
                raise RuntimeError(
                    "push-ready evidence has invalid Copilot container binding"
                )
        elif (
            execution_mode != "host"
            or review.get("container_image") is not None
            or review.get("container_runtime") is not None
            or review.get("container_runtime_version") is not None
        ):
            raise RuntimeError("push-ready evidence has invalid Codex execution mode")
        review_duration = review.get("duration_seconds")
        if (
            isinstance(review_duration, bool)
            or not isinstance(review_duration, (int, float))
            or review_duration < 0
        ):
            raise RuntimeError(
                f"push-ready evidence has invalid timing for {name} review"
            )
        parse_timestamp(
            review.get("started_at"),
            f"{name} review started_at",
        )
        parse_timestamp(
            review.get("completed_at"),
            f"{name} review completed_at",
        )
    return payload


def verify_pre_push_updates(
    payload: dict[str, Any],
    hook_input: str,
    *,
    remote_name: str,
    remote_url: str,
) -> None:
    """Bind every ref update supplied by Git's pre-push hook to reviewed HEAD."""
    supplied_remote = governed_push_remote_from_url(remote_name, remote_url)
    if payload.get("push_remote") != supplied_remote:
        raise RuntimeError(
            "pre-push remote does not match the reviewed GitHub origin"
        )
    updates = [line for line in hook_input.splitlines() if line.strip()]
    if not updates:
        raise RuntimeError(
            "pre-push requires Git hook update input; use `verify` for a "
            "manual evidence check"
        )
    if len(updates) != 1:
        raise RuntimeError(
            "push-ready evidence authorizes exactly one branch update; push "
            "tags, notes, releases, and additional branches separately"
        )
    expected_head = payload.get("head_commit")
    expected_branch = payload.get("local_branch_ref")
    for line in updates:
        fields = line.split()
        if len(fields) != 4:
            raise RuntimeError("pre-push received malformed Git hook input")
        local_ref, local_oid, remote_ref, remote_oid = fields
        if (
            local_ref != expected_branch
            or remote_ref != expected_branch
            or not local_ref.startswith("refs/heads/")
            or not re.fullmatch(r"[0-9a-fA-F]{40}|[0-9a-fA-F]{64}", local_oid)
            or not re.fullmatch(r"[0-9a-fA-F]{40}|[0-9a-fA-F]{64}", remote_oid)
        ):
            raise RuntimeError("pre-push received an unsafe ref update")
        if set(local_oid) == {"0"}:
            raise RuntimeError("push-ready evidence does not authorize ref deletion")
        creates_remote_branch = set(remote_oid) == {"0"}
        pushed_commit = git_output(
            "rev-parse",
            "--verify",
            "--end-of-options",
            f"{local_oid}^{{commit}}",
        ).strip()
        if pushed_commit != expected_head:
            raise RuntimeError(
                "pre-push ref update is not bound to the reviewed evidence HEAD"
            )
        if not creates_remote_branch:
            ancestry = run(
                ["git", "merge-base", "--is-ancestor", remote_oid, local_oid],
                capture=True,
            )
            if ancestry.returncode:
                raise RuntimeError(
                    "push-ready evidence does not authorize a non-fast-forward "
                    "branch update"
                )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "command",
        choices=(
            "instructions",
            "validate",
            "review",
            "push-ready",
            "verify",
            "pre-push",
            "sync-instructions",
        ),
    )
    parser.add_argument(
        "--base",
        help="override the configured target ref used to calculate the merge-base",
    )
    parser.add_argument(
        "--remote-name",
        help="remote name supplied as pre-push hook argv[1]",
    )
    parser.add_argument(
        "--remote-url",
        help="remote URL supplied as pre-push hook argv[2]",
    )
    args = parser.parse_args()
    try:
        if args.base and args.command != "review":
            raise RuntimeError(
                "--base is diagnostic-only and may be used only with `review`"
            )
        if args.command == "sync-instructions":
            sync_instructions()
            return 0
        check_instruction_contract()
        if args.command == "instructions":
            return 0
        config = load_config()
        if args.command == "verify":
            verify_evidence(config)
            print(f"Verified push-ready evidence: {evidence_path()}")
            return 0
        if args.command == "pre-push":
            if not args.remote_name or not args.remote_url:
                raise RuntimeError(
                    "pre-push requires --remote-name and --remote-url from "
                    "the Git hook arguments"
                )
            require_clean_head()
            refresh_authoritative_base(config)
            payload = verify_evidence(config)
            verify_pre_push_updates(
                payload,
                sys.stdin.read(),
                remote_name=args.remote_name,
                remote_url=args.remote_url,
            )
            print(f"Verified push-ready evidence: {evidence_path()}")
            return 0
        if args.command == "validate":
            require_clean_head()
            refresh_authoritative_base(config)
            change = planned_change(config)
            require_trusted_check_policy(change)
            execute_integration_checks(config, change)
            return 0
        if args.command == "review":
            change = planned_change(config, base_override=args.base)
            run_agent_reviews(config, change)
            return 0
        require_clean_head()
        original_head = git_output("rev-parse", "HEAD").strip()
        original_branch = current_branch_ref()
        original_tree_fingerprint = tree_fingerprint()
        refresh_authoritative_base(config)
        change = planned_change(config)
        require_trusted_check_policy(change)
        started_at = now_utc()
        started = time.monotonic()
        (
            checks,
            integration_tree,
            integration_commit,
            integration_fingerprint,
        ) = (
            execute_integration_checks(config, change)
        )
        require_clean_head()
        if (
            git_output("rev-parse", "HEAD").strip() != original_head
            or current_branch_ref() != original_branch
            or tree_fingerprint() != original_tree_fingerprint
        ):
            raise RuntimeError(
                "deterministic checks changed the reviewed branch or Git tree"
            )
        change = planned_change(config)
        reviews = run_agent_reviews(config, change)
        write_evidence(
            config,
            checks,
            reviews,
            change,
            started_at=started_at,
            started_monotonic=started,
            integration_tree=integration_tree,
            integration_commit=integration_commit,
            integration_fingerprint=integration_fingerprint,
        )
        verify_evidence(config)
        print(f"Push-ready evidence: {evidence_path()}")
        return 0
    except (
        OSError,
        RuntimeError,
        json.JSONDecodeError,
        subprocess.SubprocessError,
    ) as exc:
        print(f"push-ready: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
