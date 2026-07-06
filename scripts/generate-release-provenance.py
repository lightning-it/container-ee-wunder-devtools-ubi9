#!/usr/bin/env python3
"""Generate a release provenance statement for GitHub release assets."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


ROOT = Path.cwd()


def git(args: list[str], default: str = "") -> str:
    try:
        return subprocess.check_output(["git", *args], text=True).strip()
    except Exception:
        return default


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def csv(value: str | list[str]) -> list[str]:
    if isinstance(value, list):
        entries = value
    else:
        entries = [value]
    items: list[str] = []
    for entry in entries:
        items.extend(item.strip() for item in entry.split(",") if item.strip())
    return items


def subject_from_file(path: Path) -> dict[str, Any]:
    return {
        "name": path.name,
        "digest": {
            "sha256": sha256(path),
        },
    }


def build_statement(args: argparse.Namespace) -> dict[str, Any]:
    repo = args.repository or os.getenv("GITHUB_REPOSITORY", ROOT.name)
    tag = args.release_tag or os.getenv("RELEASE_TAG") or os.getenv("GITHUB_REF_NAME") or git(["describe", "--tags", "--always"])
    commit = args.commit or os.getenv("GITHUB_SHA") or git(["rev-parse", "HEAD"])
    run_url = ""
    if os.getenv("GITHUB_SERVER_URL") and os.getenv("GITHUB_REPOSITORY") and os.getenv("GITHUB_RUN_ID"):
        run_url = f"{os.getenv('GITHUB_SERVER_URL')}/{repo}/actions/runs/{os.getenv('GITHUB_RUN_ID')}"

    subjects = [subject_from_file(path) for path in sorted(args.subject)]
    for artifact in csv(args.artifact):
        subjects.append({"name": artifact})

    return {
        "_type": "https://in-toto.io/Statement/v1",
        "subject": subjects,
        "predicateType": "https://slsa.dev/provenance/v1",
        "predicate": {
            "buildDefinition": {
                "buildType": f"https://lightning-it.io/provenance/{args.mode}",
                "externalParameters": {
                    "repository": repo,
                    "release": tag,
                    "commit": commit,
                },
                "internalParameters": {},
                "resolvedDependencies": [
                    {
                        "uri": f"git+https://github.com/{repo}@{commit}",
                        "digest": {"gitCommit": commit},
                    }
                ],
            },
            "runDetails": {
                "builder": {
                    "id": args.builder_id or f"https://github.com/{repo}/actions",
                },
                "metadata": {
                    "invocationId": os.getenv("GITHUB_RUN_ID", ""),
                    "startedOn": args.generated_at,
                    "finishedOn": args.generated_at,
                },
                "byproducts": [
                    {
                        "name": "workflow_run",
                        "uri": run_url,
                    }
                ]
                if run_url
                else [],
            },
        },
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", default="dist/release-provenance.intoto.jsonl")
    parser.add_argument("--mode", default="workflow-release")
    parser.add_argument("--repository", default="")
    parser.add_argument("--release-tag", default="")
    parser.add_argument("--commit", default="")
    parser.add_argument("--artifact", action="append", default=[])
    parser.add_argument("--subject", type=Path, action="append", default=[])
    parser.add_argument("--builder-id", default="")
    parser.add_argument("--generated-at", default=datetime.now(timezone.utc).isoformat())
    args = parser.parse_args()

    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(build_statement(args), sort_keys=True) + "\n", encoding="utf-8")
    print(f"Generated {output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
