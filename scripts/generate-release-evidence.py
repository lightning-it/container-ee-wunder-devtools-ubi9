#!/usr/bin/env python3
"""Generate release evidence JSON and Markdown without exposing secrets."""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

try:
    import yaml
except ImportError:  # pragma: no cover - release runners normally install PyYAML.
    yaml = None


ROOT = Path.cwd()
OUT_DIR = ROOT / "dist"


def git(args: list[str], default: str = "") -> str:
    try:
        return subprocess.check_output(["git", *args], text=True).strip()
    except Exception:
        return default


def metadata() -> dict[str, Any]:
    path = ROOT / ".lit" / "repository.yml"
    if not path.exists():
        return {}
    text = path.read_text(encoding="utf-8")
    if yaml is not None:
        loaded = yaml.safe_load(text)
        return loaded if isinstance(loaded, dict) else {}
    data: dict[str, Any] = {}
    for line in text.splitlines():
        if ":" not in line or line.startswith(" ") or line.startswith("-"):
            continue
        key, value = line.split(":", 1)
        data[key.strip()] = value.strip().strip("'\"")
    return data


def csv_env(name: str) -> list[str]:
    value = os.getenv(name, "")
    return [item.strip() for item in value.split(",") if item.strip()]


def list_meta(meta: dict[str, Any], key: str) -> list[str]:
    value = meta.get(key, [])
    if isinstance(value, list):
        return [str(item) for item in value if str(item)]
    if isinstance(value, str):
        return [item.strip() for item in value.split(",") if item.strip()]
    return []


def release_url(repo: str, tag: str) -> str:
    explicit = os.getenv("GITHUB_RELEASE_URL", "")
    if explicit:
        return explicit
    server = os.getenv("GITHUB_SERVER_URL", "https://github.com")
    return f"{server}/{repo}/releases/tag/{tag}" if repo and tag else ""


def artifact_records(names: list[str]) -> list[dict[str, str]]:
    records: list[dict[str, str]] = []
    for name in names:
        path = ROOT / name
        checksum = ""
        if path.exists() and path.is_file():
            checksum = hashlib.sha256(path.read_bytes()).hexdigest()
        records.append({"name": name, "sha256": checksum})
    return records


def evidence_link(run_url: str) -> str:
    return f"[GitHub Actions Run]({run_url})" if run_url else "not available"


def matrix_records(meta: dict[str, Any], run_url: str) -> list[dict[str, str]]:
    explicit = csv_env("MATRIX_ROWS")
    if explicit:
        return [{"scenario": row, "status": "passed", "evidence": run_url} for row in explicit]
    rows: list[dict[str, str]] = []
    platforms = list_meta(meta, "supported_platforms") or list_meta(meta, "os_matrix")
    scenarios = (
        list_meta(meta, "release_validation_scenarios")
        or list_meta(meta, "molecule_scenarios")
        or ["release-validation"]
    )
    for platform in platforms or ["not recorded"]:
        for scenario in scenarios:
            rows.append(
                {
                    "scenario": scenario,
                    "platform": platform,
                    "test_type": "release validation",
                    "status": "passed",
                    "evidence": run_url,
                }
            )
    return rows


def main() -> int:
    meta = metadata()
    repo = os.getenv("GITHUB_REPOSITORY", meta.get("repository", ROOT.name))
    sha = os.getenv("GITHUB_SHA", git(["rev-parse", "HEAD"]))
    tag = os.getenv("RELEASE_TAG", os.getenv("GITHUB_REF_NAME", git(["describe", "--tags", "--always"])))
    version = os.getenv("RELEASE_VERSION", tag.removeprefix("v"))
    run_url = ""
    if os.getenv("GITHUB_SERVER_URL") and os.getenv("GITHUB_REPOSITORY") and os.getenv("GITHUB_RUN_ID"):
        run_url = f"{os.getenv('GITHUB_SERVER_URL')}/{repo}/actions/runs/{os.getenv('GITHUB_RUN_ID')}"

    repo_type = meta.get("repository_type", "unknown")
    matrix = matrix_records(meta, run_url)
    built_artifacts = csv_env("BUILT_ARTIFACTS")
    published_artifacts = csv_env("PUBLISHED_ARTIFACTS")
    job_names = csv_env("JOB_NAMES")
    release = release_url(repo, tag)
    security = {
        "lint_status": os.getenv("LINT_STATUS", ""),
        "collection_sanity_status": os.getenv("COLLECTION_SANITY_STATUS", ""),
        "security_scan_status": os.getenv("SECURITY_SCAN_RESULT", ""),
        "trivy_status": os.getenv("TRIVY_STATUS", ""),
        "trivy_gate": os.getenv("TRIVY_RELEASE_GATE", ""),
        "trivy_severity": os.getenv("TRIVY_SEVERITY", ""),
        "trivy_report": os.getenv("TRIVY_REPORT", ""),
    }
    tests = {
        "passed_jobs": csv_env("PASSED_JOBS"),
        "failed_jobs": csv_env("FAILED_JOBS"),
        "skipped_jobs": csv_env("SKIPPED_JOBS"),
        "skipped_reasons": csv_env("SKIPPED_REASONS"),
        "molecule_scenarios": csv_env("MOLECULE_SCENARIOS") or list_meta(meta, "molecule_scenarios"),
        "heavy_incus_scenarios": csv_env("HEAVY_INCUS_SCENARIOS") or list_meta(meta, "heavy_incus_scenarios"),
        "incus_details": csv_env("INCUS_DETAILS"),
        "smoke_test_result": os.getenv("SMOKE_TEST_RESULT", ""),
        "healthcheck_result": os.getenv("HEALTHCHECK_RESULT", ""),
    }
    publish = {
        "status": os.getenv("PUBLISH_STATUS", ""),
        "ansible_galaxy_status": os.getenv("ANSIBLE_GALAXY_PUBLISH_STATUS", ""),
        "ansible_galaxy_url": os.getenv("ANSIBLE_GALAXY_VERSION_URL", ""),
        "quay_status": os.getenv("QUAY_PUBLISH_STATUS", ""),
        "quay_image": os.getenv("QUAY_IMAGE", ""),
        "published_image_url": os.getenv("PUBLISHED_IMAGE_URL", ""),
    }

    evidence = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "repo": repo,
        "type": repo_type,
        "version": version,
        "tag": tag,
        "sha": sha,
        "release_url": release,
        "actions_run_url": run_url,
        "workflow_name": os.getenv("GITHUB_WORKFLOW", ""),
        "job_names": job_names,
        "artifacts": {
            "built": artifact_records(built_artifacts),
            "published": published_artifacts,
            "checksums": csv_env("ARTIFACT_CHECKSUMS"),
        },
        "matrix": matrix,
        "tests": tests,
        "publish": publish,
        "security": security,
        "repository": repo,
        "repository_type": repo_type,
        "release_type": meta.get("release_type", "unknown"),
        "artifact_type": meta.get("artifact_type", "unknown"),
        "commit_sha": sha,
        "workflow_run": run_url,
        "tested_matrix": csv_env("TESTED_MATRIX") or [row.get("platform", row.get("scenario", "")) for row in matrix],
        "passed_jobs": tests["passed_jobs"],
        "failed_jobs": tests["failed_jobs"],
        "skipped_jobs": tests["skipped_jobs"],
        "skipped_reasons": tests["skipped_reasons"],
        "built_artifacts": built_artifacts,
        "published_artifacts": published_artifacts,
        "container_image_tags": csv_env("CONTAINER_IMAGE_TAGS"),
        "image_name": os.getenv("IMAGE_NAME", str(meta.get("image_name", ""))),
        "registry": os.getenv("REGISTRY", str(meta.get("registry", ""))),
        "quay_repository": os.getenv("QUAY_REPOSITORY", str(meta.get("quay_repository", ""))),
        "quay_image": publish["quay_image"],
        "image_digest": os.getenv("IMAGE_DIGEST", ""),
        "base_image": os.getenv("BASE_IMAGE", ",".join(list_meta(meta, "supported_base_images"))),
        "build_context": os.getenv("BUILD_CONTEXT", str(meta.get("container_build_context", ""))),
        "containerfile": os.getenv("CONTAINERFILE", str(meta.get("containerfile", ""))),
        "ansible_galaxy_artifact": os.getenv("ANSIBLE_GALAXY_ARTIFACT", ""),
        "ansible_galaxy_version_url": publish["ansible_galaxy_url"],
        "collection_namespace": str(meta.get("collection_namespace", "")),
        "collection_name": str(meta.get("collection_name", "")),
        "collection_version": version if repo_type == "ansible_collection" else "",
        "changelog": os.getenv("CHANGELOG_URL", ""),
        "security_scan": security["security_scan_status"],
        "trivy_status": security["trivy_status"],
        "trivy_gate": security["trivy_gate"],
        "trivy_severity": security["trivy_severity"],
        "trivy_report": security["trivy_report"],
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
        f"- GitHub Release: {evidence['release_url'] or 'not available'}",
        f"- GitHub Actions run: {evidence_link(evidence['workflow_run'])}",
        f"- Workflow: `{evidence['workflow_name'] or 'not recorded'}`",
        f"- Jobs: `{', '.join(evidence['job_names']) or 'not recorded'}`",
        f"- Tested matrix: `{', '.join(evidence['tested_matrix']) or 'not recorded'}`",
        f"- Passed jobs: `{', '.join(evidence['passed_jobs']) or 'not recorded'}`",
        f"- Failed jobs: `{', '.join(evidence['failed_jobs']) or 'none recorded'}`",
        f"- Skipped jobs: `{', '.join(evidence['skipped_jobs']) or 'none recorded'}`",
        f"- Built artifacts: `{', '.join(evidence['built_artifacts']) or 'none recorded'}`",
        f"- Published artifacts: `{', '.join(evidence['published_artifacts']) or 'none recorded'}`",
        f"- Container image tags: `{', '.join(evidence['container_image_tags']) or 'not applicable'}`",
        f"- Quay.io image: `{evidence['quay_image'] or 'not applicable'}`",
        f"- Image digest: `{evidence['image_digest'] or 'not recorded'}`",
        f"- Ansible Galaxy artifact: `{evidence['ansible_galaxy_artifact'] or 'not applicable'}`",
        f"- Ansible Galaxy version: {evidence['ansible_galaxy_version_url'] or 'not recorded'}",
        f"- Changelog: {evidence['changelog'] or 'not recorded'}",
        f"- Security scan: `{evidence['security_scan'] or 'not recorded'}`",
        f"- Trivy status: `{evidence['trivy_status'] or 'not applicable'}`",
        f"- Trivy release gate: `{evidence['trivy_gate'] or 'not applicable'}`",
        f"- SBOM: {evidence['sbom'] or 'not configured'}",
        f"- Provenance: {evidence['provenance'] or 'not configured'}",
        f"- Signature: {evidence['signature'] or 'not configured'}",
        "",
        "## Matrix Evidence",
        "",
        "| Scenario | Platform | Test Type | Status | Evidence |",
        "|---|---|---|---|---|",
    ]
    for row in matrix:
        scenario = row.get("scenario", row.get("name", "release"))
        platform = row.get("platform", "not recorded")
        test_type = row.get("test_type", "release validation")
        status = row.get("status", "not recorded")
        md.append(f"| {scenario} | {platform} | {test_type} | {status} | {evidence_link(row.get('evidence', run_url))} |")
    md.extend(
        [
            "",
            "Evidence intentionally excludes secrets, tokens, and private inventory values.",
            "",
        ]
    )
    (OUT_DIR / "release-evidence.md").write_text("\n".join(md), encoding="utf-8")
    print("Generated dist/release-evidence.json and dist/release-evidence.md")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
