#!/usr/bin/env python3
"""Load and verify the immutable Galaxy collection inventory in Devtools."""

from __future__ import annotations

import argparse
import json
import re
import stat
from dataclasses import dataclass
from pathlib import Path
from typing import NoReturn
from urllib.parse import urlsplit

import yaml

FQCN_PATTERN = re.compile(r"^[a-z0-9_]+\.[a-z0-9_]+$")
VERSION_PATTERN = re.compile(r"^[0-9]+\.[0-9]+\.[0-9]+$")
SHA256_PATTERN = re.compile(r"^[0-9a-f]{64}$")
MAX_ARTIFACT_BYTES = 100 * 1024 * 1024


@dataclass(frozen=True)
class CollectionArtifact:
    name: str
    version: str
    url: str
    sha256: str
    size: int


def fail(message: str) -> NoReturn:
    raise RuntimeError(message)


def require_regular_file(path: Path, label: str) -> None:
    try:
        metadata = path.lstat()
    except OSError as error:
        fail(f"Unable to inspect {label} {path}: {error}")
    if not stat.S_ISREG(metadata.st_mode):
        fail(f"{label} must be a regular non-symlink file: {path}")


def require_real_directory(path: Path, label: str) -> None:
    try:
        metadata = path.lstat()
    except OSError as error:
        fail(f"Unable to inspect {label} {path}: {error}")
    if not stat.S_ISDIR(metadata.st_mode):
        fail(f"{label} must be a real directory: {path}")


def expected_artifact_url(name: str, version: str) -> str:
    namespace, collection = name.split(".", maxsplit=1)
    filename = f"{namespace}-{collection}-{version}.tar.gz"
    return (
        "https://galaxy.ansible.com/api/v3/plugin/ansible/content/published/"
        f"collections/artifacts/{filename}"
    )


def load_lock(lock_path: Path) -> dict[str, CollectionArtifact]:
    require_regular_file(lock_path, "collection lock")
    try:
        payload = yaml.safe_load(lock_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, yaml.YAMLError) as error:
        fail(f"Unable to parse collection lock: {error}")
    if not isinstance(payload, dict) or set(payload) != {"collections"}:
        fail("Collection lock must contain only the collections key")
    collections = payload["collections"]
    if not isinstance(collections, list) or not collections:
        fail("Collection lock collections must be a non-empty list")

    expected: dict[str, CollectionArtifact] = {}
    fields = {"name", "version", "url", "sha256", "size"}
    for entry in collections:
        if not isinstance(entry, dict) or set(entry) != fields:
            fail(
                "Every collection lock entry must contain only name, version, url, sha256, and size"
            )
        name = entry["name"]
        version = entry["version"]
        url = entry["url"]
        sha256 = entry["sha256"]
        size = entry["size"]
        if not isinstance(name, str) or FQCN_PATTERN.fullmatch(name) is None:
            fail(f"Invalid collection name: {name!r}")
        if not isinstance(version, str) or VERSION_PATTERN.fullmatch(version) is None:
            fail(f"Invalid exact collection version for {name}: {version!r}")
        if not isinstance(url, str) or url != expected_artifact_url(name, version):
            fail(f"Invalid official artifact URL for {name}: {url!r}")
        parsed = urlsplit(url)
        if parsed.query or parsed.fragment or parsed.username or parsed.password:
            fail(f"Unsafe artifact URL for {name}")
        if not isinstance(sha256, str) or SHA256_PATTERN.fullmatch(sha256) is None:
            fail(f"Invalid SHA-256 for {name}")
        if (
            isinstance(size, bool)
            or not isinstance(size, int)
            or not 0 < size <= MAX_ARTIFACT_BYTES
        ):
            fail(f"Invalid bounded artifact size for {name}: {size!r}")
        if name in expected:
            fail(f"Duplicate collection lock entry: {name}")
        expected[name] = CollectionArtifact(name, version, url, sha256, size)
    if list(expected) != sorted(expected):
        fail("Collection lock entries must be sorted by name")
    return expected


def load_expected(lock_path: Path) -> dict[str, str]:
    return {name: artifact.version for name, artifact in load_lock(lock_path).items()}


def load_installed(collections_root: Path) -> dict[str, str]:
    require_real_directory(collections_root, "collection root")
    installed: dict[str, str] = {}
    for namespace_path in sorted(collections_root.iterdir()):
        require_real_directory(namespace_path, "collection namespace")
        for collection_path in sorted(namespace_path.iterdir()):
            require_real_directory(collection_path, "installed collection")
            manifest_path = collection_path / "MANIFEST.json"
            require_regular_file(manifest_path, "installed collection manifest")
            try:
                payload = json.loads(manifest_path.read_text(encoding="utf-8"))
            except (OSError, UnicodeError, json.JSONDecodeError) as error:
                fail(
                    f"Unable to parse installed collection manifest {manifest_path}: {error}"
                )
            info = payload.get("collection_info") if isinstance(payload, dict) else None
            if not isinstance(info, dict):
                fail(
                    f"Installed collection manifest lacks collection_info: {manifest_path}"
                )
            name = f"{info.get('namespace')}.{info.get('name')}"
            version = info.get("version")
            expected_name = f"{namespace_path.name}.{collection_path.name}"
            if name != expected_name or FQCN_PATTERN.fullmatch(name) is None:
                fail(f"Installed collection identity mismatch at {manifest_path}")
            if (
                not isinstance(version, str)
                or VERSION_PATTERN.fullmatch(version) is None
            ):
                fail(
                    f"Installed collection has an invalid version at {manifest_path}: "
                    f"{version!r}"
                )
            if name in installed:
                fail(f"Duplicate installed collection: {name}")
            installed[name] = version
    return installed


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--lock", type=Path, required=True)
    parser.add_argument("--collections-root", type=Path, required=True)
    args = parser.parse_args()

    expected = load_expected(args.lock)
    installed = load_installed(args.collections_root)
    if installed != expected:
        missing = sorted(set(expected) - set(installed))
        extra = sorted(set(installed) - set(expected))
        mismatched = sorted(
            name
            for name in set(expected) & set(installed)
            if expected[name] != installed[name]
        )
        fail(
            "Pinned collection inventory mismatch: "
            f"missing={missing}, extra={extra}, version_mismatch={mismatched}"
        )
    print(f"Verified {len(installed)} pinned Galaxy collections.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
