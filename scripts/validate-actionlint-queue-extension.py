#!/usr/bin/env python3
"""Validate GitHub's concurrency queue extension missing from actionlint 1.7.12.

GitHub introduced ``concurrency.queue: max`` on 2026-05-07.  The pinned
actionlint release predates that schema addition, so its one stale diagnostic is
ignored only after this validator has fail-closed on the exact supported shape
and the exact allowlisted workflow locations.

Official contract:
https://docs.github.com/en/actions/how-tos/write-workflows/choose-when-workflows-run/control-workflow-concurrency
Release announcement:
https://github.blog/changelog/2026-05-07-github-actions-concurrency-groups-now-allow-larger-queues/
"""

from __future__ import annotations

import argparse
from pathlib import Path

try:
    import yaml
    from yaml.nodes import MappingNode, Node, ScalarNode, SequenceNode
except ImportError:
    raise SystemExit(
        "ERROR: PyYAML is required to validate workflow queue extensions; "
        "install the repository's pinned requirements before running this script."
    )


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
COLLECTION_SYNC_EXPECTED = {
    (
        "sync-ansible-collections.yml",
        ("concurrency",),
    ): "sync-ansible-collections-${{ github.ref }}",
}


def parse_mapping_paths(workflow: Path) -> dict[tuple[str, ...], str | None]:
    """Parse every YAML mapping path without losing alternate key syntax."""

    try:
        root = yaml.compose(
            workflow.read_text(encoding="utf-8"),
            Loader=yaml.SafeLoader,
        )
    except yaml.YAMLError as error:
        raise ValueError(f"invalid YAML: {workflow}: {error}") from error
    if root is None:
        return {}
    if not isinstance(root, MappingNode):
        raise ValueError(f"workflow root must be a mapping: {workflow}")

    values: dict[tuple[str, ...], str | None] = {}

    def walk(node: Node, path: tuple[str, ...], ancestors: frozenset[int]) -> None:
        if id(node) in ancestors:
            raise ValueError(f"recursive YAML aliases are not allowed: {workflow}")
        descendants = ancestors | {id(node)}
        if isinstance(node, MappingNode):
            seen: set[str] = set()
            for key_node, value_node in node.value:
                if not isinstance(key_node, ScalarNode):
                    raise ValueError(f"mapping keys must be scalar: {workflow}")
                key = key_node.value
                if key == "<<":
                    raise ValueError(f"YAML merge keys are not allowed: {workflow}")
                if key in seen:
                    raise ValueError(f"duplicate mapping key {key!r}: {workflow}")
                seen.add(key)
                child = (*path, key)
                if isinstance(value_node, ScalarNode):
                    values[child] = value_node.value or None
                elif isinstance(value_node, (MappingNode, SequenceNode)):
                    values[child] = None
                    walk(value_node, child, descendants)
                else:  # pragma: no cover - SafeLoader currently has three node types.
                    raise ValueError(f"unsupported YAML node: {workflow}")
            return
        if isinstance(node, SequenceNode):
            for index, item in enumerate(node.value):
                child = (*path, f"[{index}]")
                if isinstance(item, ScalarNode):
                    values[child] = item.value or None
                elif isinstance(item, (MappingNode, SequenceNode)):
                    values[child] = None
                    walk(item, child, descendants)
                else:  # pragma: no cover - SafeLoader currently has three node types.
                    raise ValueError(f"unsupported YAML node: {workflow}")
            return
        raise ValueError(f"unsupported YAML document: {workflow}")

    walk(root, (), frozenset())
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
    expected = dict(EXPECTED) if mlx90 else {}
    if "sync-ansible-collections.yml" in documents:
        expected.update(COLLECTION_SYNC_EXPECTED)
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
