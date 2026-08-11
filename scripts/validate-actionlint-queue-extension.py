#!/usr/bin/env python3
"""Validate GitHub's concurrency queue extension missing from actionlint 1.7.12.

GitHub introduced ``concurrency.queue: max`` on 2026-05-07.  The pinned
actionlint release predates that schema addition, so its one stale diagnostic is
ignored only after this validator has fail-closed on the exact supported shape
and the exact MLX-90 workflow locations.

Official contract:
https://docs.github.com/en/actions/how-tos/write-workflows/choose-when-workflows-run/control-workflow-concurrency
Release announcement:
https://github.blog/changelog/2026-05-07-github-actions-concurrency-groups-now-allow-larger-queues/
"""

from __future__ import annotations

import argparse
import re
from pathlib import Path


SHARED_GROUP = "mlx90-container-release-${{ github.repository }}"
EXPECTED = {
    ("semantic-release.yml", ("jobs", "release", "concurrency")): SHARED_GROUP,
    ("container-build-publish.yml", ("concurrency",)): SHARED_GROUP,
    (
        "security-release-update.yml",
        ("concurrency",),
    ): "mlx90-security-release-update",
    (
        "security-release-finalize.yml",
        ("concurrency",),
    ): "mlx90-finalize-${{ inputs.container_release_tag }}",
    (
        "security-release-promote-tags.yml",
        ("concurrency",),
    ): "mlx90-promote-tags-${{ inputs.container_release_tag }}",
}


def parse_mapping_paths(workflow: Path) -> dict[tuple[str, ...], str | None]:
    """Parse mapping paths while deliberately ignoring YAML block scalar bodies."""

    values: dict[tuple[str, ...], str | None] = {}
    stack: list[tuple[int, str]] = []
    block_indent: int | None = None
    mapping = re.compile(r"^(?P<indent> *)(?P<key>[A-Za-z0-9_-]+):(?:[ ]*(?P<value>.*))?$")
    for line_number, raw_line in enumerate(
        workflow.read_text(encoding="utf-8").splitlines(), start=1
    ):
        if not raw_line.strip() or raw_line.lstrip().startswith("#"):
            continue
        indent = len(raw_line) - len(raw_line.lstrip(" "))
        if "\t" in raw_line[:indent]:
            raise ValueError(f"tabs are not allowed: {workflow}:{line_number}")
        if block_indent is not None:
            if indent > block_indent:
                continue
            block_indent = None
        while stack and indent <= stack[-1][0]:
            stack.pop()
        match = mapping.match(raw_line)
        if match is None:
            if raw_line.lstrip().startswith("-"):
                continue
            continue
        key = match.group("key")
        value = (match.group("value") or "").strip()
        if " #" in value:
            value = value.split(" #", maxsplit=1)[0].rstrip()
        path = (*[item[1] for item in stack], key)
        values[path] = value or None
        if value.startswith(("|", ">")):
            block_indent = indent
        elif not value:
            stack.append((indent, key))
    return values


def validate(workflows_dir: Path, *, allow_mlx90_queue: bool = False) -> None:
    documents: dict[str, dict[tuple[str, ...], str | None]] = {}
    queue_locations: set[tuple[str, tuple[str, ...]]] = set()
    for workflow in sorted((*workflows_dir.glob("*.yml"), *workflows_dir.glob("*.yaml"))):
        document = parse_mapping_paths(workflow)
        documents[workflow.name] = document
        for path in document:
            if path[-1] == "queue":
                queue_locations.add((workflow.name, path[:-1]))

    mlx90 = allow_mlx90_queue and "security-release-finalize.yml" in documents
    expected = EXPECTED if mlx90 else {}
    if queue_locations != set(expected):
        raise ValueError(
            f"unexpected GitHub queue locations: actual={sorted(queue_locations)!r} "
            f"expected={sorted(expected)!r}"
        )
    for (filename, path), group in expected.items():
        document = documents[filename]
        exact = {
            "group": group,
            "queue": "max",
            "cancel-in-progress": "false",
        }
        concurrency = {
            key: value
            for child_path, value in document.items()
            if child_path[:-1] == path
            for key in (child_path[-1],)
        }
        if concurrency != exact or document.get(path) is not None:
            raise ValueError(
                f"{filename}:{'.'.join(path)} must equal {exact!r}; "
                f"got {concurrency!r}"
            )
    if mlx90:
        semantic = documents["semantic-release.yml"]
        if ("concurrency",) in semantic:
            raise ValueError("semantic-release concurrency must not be workflow-level")
        if ("jobs", "release_dry_run") not in semantic:
            raise ValueError("semantic release PR dry-run job is missing")
        if ("jobs", "release_dry_run", "concurrency") in semantic:
            raise ValueError("semantic release PR dry-run must not share release concurrency")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--workflows-dir",
        type=Path,
        action="append",
        required=True,
    )
    parser.add_argument(
        "--mlx90-workflows-dir",
        type=Path,
    )
    args = parser.parse_args()
    mlx90_dir = (
        args.mlx90_workflows_dir.resolve(strict=True)
        if args.mlx90_workflows_dir is not None
        else None
    )
    directories = tuple(
        dict.fromkeys(directory.resolve(strict=True) for directory in args.workflows_dir)
    )
    if mlx90_dir is not None and mlx90_dir not in directories:
        raise ValueError("MLX-90 workflow directory is outside the validated set")
    for directory in directories:
        if not directory.is_dir():
            raise ValueError(f"workflow path is not a directory: {directory}")
        validate(directory, allow_mlx90_queue=directory == mlx90_dir)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
