#!/usr/bin/env python3
"""Create commit-bound local pipeline and Copilot review evidence."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shlex
import shutil
import stat
import subprocess
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(os.environ.get("LIT_REPOSITORY_ROOT", Path(__file__).resolve().parents[1])).resolve()
CONFIG = ROOT / ".lit" / "push-ready.json"
COPILOT = ROOT / ".github" / "copilot-instructions.md"
AGENTS = ROOT / "AGENTS.md"
PASS_MARKER = "PUSH_READY: PASS"
EMPTY_TREE = "4b825dc642cb6eb9a060e54bf8d69288fbee4904"
CONTRACT_LINE = "<!-- Managed contract: Codex and Copilot must apply AGENTS.md. -->"
SECRET_PATH_PARTS = {".env", "id_rsa", "id_ed25519", "secrets", "vault-password"}
SECRET_CONTENT_PATTERNS = (
    re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----"),
    re.compile(r"(?i)(?:api[_-]?key|client[_-]?secret|access[_-]?token|password)\s*[:=]\s*[\"']?[A-Za-z0-9_./+=-]{16,}"),
    re.compile(r"\bgh[opusr]_[A-Za-z0-9]{20,}\b"),
)


def run(command: list[str], *, capture: bool = False) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        command,
        cwd=ROOT,
        check=False,
        text=True,
        stdout=subprocess.PIPE if capture else None,
        stderr=subprocess.STDOUT if capture else None,
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


def open_untracked_regular(name: str, *, purpose: str) -> int:
    """Open an untracked file without following any path-component symlink."""
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
        raise RuntimeError(f"{purpose} refused for unsafe untracked path: {name}")

    directory_flags = (
        os.O_RDONLY
        | os.O_CLOEXEC
        | os.O_DIRECTORY
        | os.O_NOFOLLOW
    )
    file_flags = (
        os.O_RDONLY
        | os.O_CLOEXEC
        | os.O_NOFOLLOW
        | os.O_NONBLOCK
    )
    directory_descriptors: list[int] = []
    descriptor = -1
    keep_descriptor = False
    try:
        current = os.open(ROOT, directory_flags)
        directory_descriptors.append(current)
        for component in parts[:-1]:
            current = os.open(component, directory_flags, dir_fd=current)
            directory_descriptors.append(current)
        descriptor = os.open(parts[-1], file_flags, dir_fd=current)
        if not stat.S_ISREG(os.fstat(descriptor).st_mode):
            raise RuntimeError(
                f"{purpose} refused for non-regular untracked path: {name}"
            )
        keep_descriptor = True
        return descriptor
    except OSError as exc:
        raise RuntimeError(
            f"{purpose} could not safely inspect untracked path: {name}"
        ) from exc
    finally:
        if descriptor >= 0 and not keep_descriptor:
            os.close(descriptor)
        for directory_descriptor in reversed(directory_descriptors):
            os.close(directory_descriptor)


def untracked_file_hashes(max_bytes: int = 100_000_000) -> dict[str, str]:
    names = git_output("ls-files", "--others", "--exclude-standard", "-z")
    hashes: dict[str, str] = {}
    total = 0
    root = ROOT.resolve()
    for name in (entry for entry in names.split("\0") if entry):
        path = ROOT / name
        if path.is_symlink():
            raise RuntimeError(f"Cannot fingerprint untracked symbolic link: {name}")
        try:
            resolved = path.resolve()
            resolved.relative_to(root)
        except (OSError, ValueError) as exc:
            raise RuntimeError(
                f"Cannot fingerprint escaping or unresolvable untracked path: {name}"
            ) from exc
        if not resolved.is_file():
            raise RuntimeError(
                f"Cannot fingerprint non-regular untracked path: {name}"
            )
        digest = hashlib.sha256()
        descriptor = open_untracked_regular(name, purpose="Fingerprint")
        try:
            with os.fdopen(descriptor, "rb") as stream:
                descriptor = -1
                while chunk := stream.read(1024 * 1024):
                    total += len(chunk)
                    if total > max_bytes:
                        raise RuntimeError(
                            "Untracked fingerprint input exceeds "
                            f"{max_bytes} bytes"
                        )
                    digest.update(chunk)
        except OSError as exc:
            raise RuntimeError(
                f"Cannot read untracked path for fingerprint: {name}"
            ) from exc
        finally:
            if descriptor >= 0:
                os.close(descriptor)
        hashes[name] = digest.hexdigest()
    return hashes


def tree_fingerprint() -> str:
    payload = {
        "head": git_output("rev-parse", "HEAD").strip(),
        "status": git_output("status", "--porcelain=v1", "--untracked-files=all"),
        "diff": git_output("diff", "--no-ext-diff", "--binary", "HEAD"),
        "untracked": untracked_file_hashes(),
    }
    return hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


def load_config() -> dict:
    if not CONFIG.is_file():
        raise RuntimeError(f"missing required configuration: {CONFIG.relative_to(ROOT)}")
    data = json.loads(CONFIG.read_text(encoding="utf-8"))
    if not isinstance(data, dict) or data.get("version") != 1 or not isinstance(data.get("checks"), list):
        raise RuntimeError("push-ready configuration must use version 1 and define checks")
    return data


def instructions_digest() -> str:
    if not AGENTS.is_file() or not COPILOT.is_file():
        raise RuntimeError("AGENTS.md and .github/copilot-instructions.md are required")
    return hashlib.sha256(AGENTS.read_bytes()).hexdigest()


def check_instruction_contract() -> None:
    expected = instructions_digest()
    marker = f"<!-- AGENTS_SHA256: {expected} -->"
    lines = COPILOT.read_text(encoding="utf-8").splitlines()
    if lines[-2:] != [CONTRACT_LINE, marker]:
        raise RuntimeError(
            "Copilot instructions are stale; run "
            "`python3 scripts/lit-push-ready.py sync-instructions`"
        )


def sync_instructions() -> None:
    if not AGENTS.is_file() or not COPILOT.is_file():
        raise RuntimeError("AGENTS.md and .github/copilot-instructions.md are required")
    lines = COPILOT.read_text(encoding="utf-8").splitlines()
    lines = [
        line
        for line in lines
        if not line.startswith("<!-- AGENTS_SHA256:")
        and line
        != CONTRACT_LINE
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


def execute_checks(config: dict) -> list[dict]:
    results: list[dict] = []
    for check in config["checks"]:
        if not isinstance(check, dict):
            raise RuntimeError("each check must be an object")
        name = check.get("name")
        command = check.get("command")
        if (
            not isinstance(name, str)
            or not name
            or not isinstance(command, list)
            or not command
            or any(not isinstance(argument, str) for argument in command)
        ):
            raise RuntimeError(
                "each check requires a non-empty string name and "
                "non-empty command array of strings"
            )
        runtime_command = (
            [sys.executable, *command[1:]]
            if command[0] in {"python", "python3"}
            else command
        )
        started = time.monotonic()
        print(f"==> {name}: {shlex.join(runtime_command)}", flush=True)
        result = run(runtime_command)
        elapsed = round(time.monotonic() - started, 3)
        results.append(
            {
                "name": name,
                "command": runtime_command,
                "exit_code": result.returncode,
                "duration_seconds": elapsed,
            }
        )
        if result.returncode:
            raise RuntimeError(f"check failed: {name}")
    return results


def changed_paths() -> list[str]:
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
        status = entry[:2]
        paths.append(entry[3:])
        if "R" in status or "C" in status:
            if index >= len(values) or not values[index]:
                raise RuntimeError("rename/copy status is missing its paired path")
            paths.append(values[index])
            index += 1
    return paths


def ensure_review_safe(diff: str) -> None:
    unsafe = []
    for path in sorted(set(changed_paths() + planned_paths())):
        lowered = path.lower()
        if any(part in lowered for part in SECRET_PATH_PARTS):
            unsafe.append(path)
    if unsafe:
        raise RuntimeError(
            "Copilot review refused for secret-like paths: " + ", ".join(sorted(unsafe))
        )
    review_text = diff + "\n" + untracked_review_text()
    if any(pattern.search(review_text) for pattern in SECRET_CONTENT_PATTERNS):
        raise RuntimeError(
            "Copilot review refused because the planned review input "
            "contains secret-like content"
        )


def untracked_review_text(max_bytes: int = 1_000_000) -> str:
    names = git_output("ls-files", "--others", "--exclude-standard", "-z")
    chunks: list[str] = []
    total = 0
    for name in (entry for entry in names.split("\0") if entry):
        path = ROOT / name
        if path.is_symlink():
            raise RuntimeError(
                f"Copilot review refused for untracked symbolic link: {name}"
            )
        try:
            path.resolve().relative_to(ROOT.resolve())
        except (OSError, ValueError) as exc:
            raise RuntimeError(
                f"Copilot review refused for unsafe untracked path: {name}"
            ) from exc
        remaining = max_bytes - total
        descriptor = -1
        try:
            descriptor = open_untracked_regular(name, purpose="Copilot review")
            with os.fdopen(descriptor, "rb") as stream:
                descriptor = -1
                payload = stream.read(remaining + 1)
        except OSError as exc:
            raise RuntimeError(
                f"Copilot review could not inspect untracked path: {name}"
            ) from exc
        finally:
            if descriptor >= 0:
                os.close(descriptor)
        if len(payload) > remaining:
            raise RuntimeError(
                "Copilot review refused because untracked content exceeds "
                f"{max_bytes} bytes"
            )
        total += len(payload)
        chunks.append(payload.decode("latin-1"))
    return "\n".join(chunks)


def planned_diff() -> str:
    worktree = git_output("diff", "--no-ext-diff", "--unified=40", "HEAD")
    if worktree:
        return worktree
    upstream = run(
        ["git", "rev-parse", "--abbrev-ref", "--symbolic-full-name", "@{upstream}"],
        capture=True,
    )
    if upstream.returncode == 0:
        return git_output(
            "diff", "--no-ext-diff", "--unified=40", f"{upstream.stdout.strip()}...HEAD"
        )
    return git_output(
        "diff", "--no-ext-diff", "--unified=40", EMPTY_TREE, "HEAD"
    )


def planned_paths() -> list[str]:
    worktree = git_output("diff", "--name-only", "-z", "HEAD")
    if worktree:
        return [path for path in worktree.split("\0") if path]
    upstream = run(
        ["git", "rev-parse", "--abbrev-ref", "--symbolic-full-name", "@{upstream}"],
        capture=True,
    )
    if upstream.returncode == 0:
        names = git_output(
            "diff",
            "--name-only",
            "-z",
            f"{upstream.stdout.strip()}...HEAD",
        )
        return [path for path in names.split("\0") if path]
    names = git_output("diff", "--name-only", "-z", EMPTY_TREE, "HEAD")
    return [path for path in names.split("\0") if path]


def copilot_review(config: dict) -> dict:
    diff = planned_diff()
    ensure_review_safe(diff)
    executable = shutil.which("copilot")
    if executable is None:
        raise RuntimeError("required Copilot CLI executable is unavailable")
    max_bytes = int(config.get("copilot", {}).get("max_diff_bytes", 200_000))
    encoded = diff.encode()
    if len(encoded) > max_bytes:
        raise RuntimeError(f"planned diff exceeds Copilot review limit of {max_bytes} bytes")
    prompt = (
        "Review the following planned Lightning IT change. Apply AGENTS.md and "
        ".github/copilot-instructions.md. Report correctness, security, test, "
        "scope and expected GitHub Actions problems. Do not modify files or run "
        "commands. End with exactly 'PUSH_READY: PASS' only when there is no "
        "blocking finding; otherwise end with 'PUSH_READY: BLOCKED'.\n\n"
        + diff
    )
    started = time.monotonic()
    raw_timeout = config.get("copilot", {}).get("timeout_seconds", 300)
    if isinstance(raw_timeout, bool) or not isinstance(raw_timeout, int):
        raise RuntimeError(
            "Copilot review timeout must be an integer between 1 and 1800 seconds"
        )
    timeout_seconds = raw_timeout
    if timeout_seconds <= 0 or timeout_seconds > 1800:
        raise RuntimeError("Copilot review timeout must be between 1 and 1800 seconds")
    with tempfile.NamedTemporaryFile(mode="w+", encoding="utf-8") as output:
        try:
            result = subprocess.run(
                [
                    executable,
                    "-p",
                    prompt,
                    "--silent",
                    "--available-tools",
                    "view,grep,glob",
                    "--allow-tool",
                    "read",
                ],
                cwd=ROOT,
                check=False,
                text=True,
                stdout=output,
                stderr=subprocess.STDOUT,
                timeout=timeout_seconds,
            )
        except subprocess.TimeoutExpired as exc:
            raise RuntimeError(
                f"Copilot review timed out after {timeout_seconds} seconds"
            ) from exc
        output.seek(0)
        review = output.read()
    final_line = next((line.strip() for line in reversed(review.splitlines()) if line.strip()), "")
    if result.returncode or final_line != PASS_MARKER:
        print(review)
        raise RuntimeError("Copilot review did not produce a passing result")
    digest = hashlib.sha256(review.encode()).hexdigest()
    print(review)
    return {
        "command": "copilot -p <review-prompt> --silent --available-tools view,grep,glob --allow-tool read",
        "duration_seconds": round(time.monotonic() - started, 3),
        "output_sha256": digest,
        "result": "pass",
    }


def write_evidence(config: dict, checks: list[dict], review: dict) -> None:
    evidence = evidence_path()
    evidence.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "version": 1,
        "tree_fingerprint": tree_fingerprint(),
        "head": git_output("rev-parse", "HEAD").strip(),
        "agents_sha256": instructions_digest(),
        "checks": checks,
        "copilot_review": review,
        "remote_only_checks": config.get("remote_only_checks", []),
        "created_at_epoch": int(time.time()),
    }
    evidence.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def verify_evidence() -> None:
    evidence = evidence_path()
    if not evidence.is_file():
        raise RuntimeError("push-ready evidence does not exist")
    payload = json.loads(evidence.read_text(encoding="utf-8"))
    if payload.get("tree_fingerprint") != tree_fingerprint():
        raise RuntimeError("push-ready evidence is stale for the current Git tree")
    if payload.get("agents_sha256") != instructions_digest():
        raise RuntimeError("push-ready evidence used different AGENTS.md instructions")


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
            "sync-instructions",
        ),
    )
    args = parser.parse_args()
    try:
        if args.command == "sync-instructions":
            sync_instructions()
            return 0
        check_instruction_contract()
        if args.command == "instructions":
            return 0
        config = load_config()
        if args.command == "verify":
            verify_evidence()
            return 0
        if args.command == "validate":
            execute_checks(config)
            return 0
        if args.command == "review":
            copilot_review(config)
            return 0
        checks = execute_checks(config)
        review = copilot_review(config)
        write_evidence(config, checks, review)
        verify_evidence()
        print(f"Push-ready evidence: {evidence_path()}")
        return 0
    except (OSError, RuntimeError, json.JSONDecodeError) as exc:
        print(f"push-ready: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
