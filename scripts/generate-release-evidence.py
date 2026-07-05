#!/usr/bin/env python3
"""Generate release evidence JSON and Markdown without exposing secrets."""

from __future__ import annotations

import json
import os
import subprocess
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path.cwd()
OUT_DIR = ROOT / "dist"


def git(args: list[str], default: str = "") -> str:
    try:
        return subprocess.check_output(["git", *args], text=True).strip()
    except Exception:
        return default


def metadata() -> dict[str, str]:
    path = ROOT / ".lit" / "repository.yml"
    data: dict[str, str] = {}
    if not path.exists():
        return data
    for line in path.read_text(encoding="utf-8").splitlines():
        if ":" not in line or line.startswith(" ") or line.startswith("-"):
            continue
        key, value = line.split(":", 1)
        data[key.strip()] = value.strip().strip("'\"")
    return data


def csv_env(name: str) -> list[str]:
    value = os.getenv(name, "")
    return [item.strip() for item in value.split(",") if item.strip()]


def main() -> int:
    meta = metadata()
    repo = os.getenv("GITHUB_REPOSITORY", meta.get("repository", ROOT.name))
    sha = os.getenv("GITHUB_SHA", git(["rev-parse", "HEAD"]))
    tag = os.getenv("RELEASE_TAG", os.getenv("GITHUB_REF_NAME", git(["describe", "--tags", "--always"])))
    version = os.getenv("RELEASE_VERSION", tag.removeprefix("v"))
    run_url = ""
    if os.getenv("GITHUB_SERVER_URL") and os.getenv("GITHUB_REPOSITORY") and os.getenv("GITHUB_RUN_ID"):
        run_url = f"{os.getenv('GITHUB_SERVER_URL')}/{repo}/actions/runs/{os.getenv('GITHUB_RUN_ID')}"

    evidence = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "repository": repo,
        "repository_type": meta.get("repository_type", "unknown"),
        "release_type": meta.get("release_type", "unknown"),
        "artifact_type": meta.get("artifact_type", "unknown"),
        "version": version,
        "tag": tag,
        "commit_sha": sha,
        "workflow_run": run_url,
        "tested_matrix": csv_env("TESTED_MATRIX"),
        "passed_jobs": csv_env("PASSED_JOBS"),
        "failed_jobs": csv_env("FAILED_JOBS"),
        "skipped_jobs": csv_env("SKIPPED_JOBS"),
        "skipped_reasons": csv_env("SKIPPED_REASONS"),
        "built_artifacts": csv_env("BUILT_ARTIFACTS"),
        "published_artifacts": csv_env("PUBLISHED_ARTIFACTS"),
        "container_image_tags": csv_env("CONTAINER_IMAGE_TAGS"),
        "quay_image": os.getenv("QUAY_IMAGE", ""),
        "ansible_galaxy_artifact": os.getenv("ANSIBLE_GALAXY_ARTIFACT", ""),
        "changelog": os.getenv("CHANGELOG_URL", ""),
        "security_scan": os.getenv("SECURITY_SCAN_RESULT", ""),
        "sbom": os.getenv("SBOM_URL", ""),
        "provenance": os.getenv("PROVENANCE_URL", ""),
        "signature": os.getenv("SIGNATURE_URL", ""),
    }

    OUT_DIR.mkdir(exist_ok=True)
    (OUT_DIR / "release-evidence.json").write_text(
        json.dumps(evidence, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )

    md = [
        "# Release Evidence",
        "",
        f"- Repository: `{evidence['repository']}`",
        f"- Repository type: `{evidence['repository_type']}`",
        f"- Version: `{evidence['version']}`",
        f"- Tag: `{evidence['tag']}`",
        f"- Commit SHA: `{evidence['commit_sha']}`",
        f"- Workflow run: {evidence['workflow_run'] or 'not available'}",
        f"- Tested matrix: `{', '.join(evidence['tested_matrix']) or 'not recorded'}`",
        f"- Passed jobs: `{', '.join(evidence['passed_jobs']) or 'not recorded'}`",
        f"- Failed jobs: `{', '.join(evidence['failed_jobs']) or 'none recorded'}`",
        f"- Skipped jobs: `{', '.join(evidence['skipped_jobs']) or 'none recorded'}`",
        f"- Built artifacts: `{', '.join(evidence['built_artifacts']) or 'none recorded'}`",
        f"- Published artifacts: `{', '.join(evidence['published_artifacts']) or 'none recorded'}`",
        f"- Container image tags: `{', '.join(evidence['container_image_tags']) or 'not applicable'}`",
        f"- Quay.io image: `{evidence['quay_image'] or 'not applicable'}`",
        f"- Ansible Galaxy artifact: `{evidence['ansible_galaxy_artifact'] or 'not applicable'}`",
        f"- Changelog: {evidence['changelog'] or 'not recorded'}",
        f"- Security scan: `{evidence['security_scan'] or 'not recorded'}`",
        f"- SBOM: {evidence['sbom'] or 'not configured'}",
        f"- Provenance: {evidence['provenance'] or 'not configured'}",
        f"- Signature: {evidence['signature'] or 'not configured'}",
        "",
        "Evidence intentionally excludes secrets, tokens, and private inventory values.",
        "",
    ]
    (OUT_DIR / "release-evidence.md").write_text("\n".join(md), encoding="utf-8")
    print("Generated dist/release-evidence.json and dist/release-evidence.md")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
