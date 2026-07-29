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


def tree_fingerprint() -> str:
    untracked = git_output("ls-files", "--others", "--exclude-standard").splitlines()
    payload = {
        "head": git_output("rev-parse", "HEAD").strip(),
        "status": git_output("status", "--porcelain=v1", "--untracked-files=all"),
        "diff": git_output("diff", "--no-ext-diff", "--binary", "HEAD"),
        "untracked": {
            path: hashlib.sha256((ROOT / path).read_bytes()).hexdigest()
            for path in untracked
        },
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
        name = check.get("name")
        command = check.get("command")
        if not name or not isinstance(command, list) or not command:
            raise RuntimeError("each check requires a name and non-empty command array")
        started = time.monotonic()
        print(f"==> {name}: {shlex.join(command)}", flush=True)
        result = run(command)
        elapsed = round(time.monotonic() - started, 3)
        results.append(
            {
                "name": name,
                "command": command,
                "exit_code": result.returncode,
                "duration_seconds": elapsed,
            }
        )
        if result.returncode:
            raise RuntimeError(f"check failed: {name}")
    return results


def changed_paths() -> list[str]:
    values = git_output("status", "--porcelain=v1", "--untracked-files=all").splitlines()
    return [line[3:] for line in values if len(line) > 3]


def ensure_review_safe(diff: str) -> None:
    unsafe = []
    for path in changed_paths():
        lowered = path.lower()
        if any(part in lowered for part in SECRET_PATH_PARTS):
            unsafe.append(path)
    if unsafe:
        raise RuntimeError(
            "Copilot review refused for secret-like paths: " + ", ".join(sorted(unsafe))
        )
    if any(pattern.search(diff) for pattern in SECRET_CONTENT_PATTERNS):
        raise RuntimeError("Copilot review refused because the planned diff contains secret-like content")


def planned_diff() -> str:
    worktree = git_output("diff", "--no-ext-diff", "--unified=40", "HEAD")
    if worktree:
        return worktree
    upstream = run(
        ["git", "rev-parse", "--abbrev-ref", "--symbolic-full-name", "@{upstream}"],
        capture=True,
    )
    if upstream.returncode == 0:
        candidate = git_output(
            "diff", "--no-ext-diff", "--unified=40", f"{upstream.stdout.strip()}...HEAD"
        )
        if candidate:
            return candidate
    return git_output(
        "diff", "--no-ext-diff", "--unified=40", EMPTY_TREE, "HEAD"
    )


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
    with tempfile.NamedTemporaryFile(mode="w+", encoding="utf-8") as output:
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
        )
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
