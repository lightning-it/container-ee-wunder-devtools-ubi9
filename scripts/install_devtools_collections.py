#!/usr/bin/env python3
"""Install SHA-256-bound Galaxy artifacts into the Devtools image."""

from __future__ import annotations

import argparse
import hashlib
import os
import subprocess
import tempfile
import urllib.error
import urllib.request
from pathlib import Path

from devtools_collection_inventory import CollectionArtifact, load_lock

CHUNK_BYTES = 1024 * 1024
DOWNLOAD_ATTEMPTS = 3


def download_artifact(artifact: CollectionArtifact, destination: Path) -> None:
    last_error: BaseException | None = None
    for attempt in range(1, DOWNLOAD_ATTEMPTS + 1):
        destination.unlink(missing_ok=True)
        digest = hashlib.sha256()
        received = 0
        request = urllib.request.Request(
            artifact.url,
            headers={"User-Agent": "Lightning-IT-Devtools-Builder/1"},
        )
        try:
            with urllib.request.urlopen(request, timeout=60) as response:
                declared_length = response.headers.get("Content-Length")
                if (
                    declared_length is not None
                    and int(declared_length) != artifact.size
                ):
                    raise RuntimeError(
                        f"Unexpected Content-Length for {artifact.name}: {declared_length}"
                    )
                with destination.open("xb") as output:
                    os.chmod(destination, 0o600)
                    while True:
                        chunk = response.read(CHUNK_BYTES)
                        if not chunk:
                            break
                        received += len(chunk)
                        if received > artifact.size:
                            raise RuntimeError(
                                f"Oversized artifact for {artifact.name}"
                            )
                        digest.update(chunk)
                        output.write(chunk)
                    output.flush()
                    os.fsync(output.fileno())
            if received != artifact.size:
                raise RuntimeError(
                    f"Artifact size mismatch for {artifact.name}: {received} != {artifact.size}"
                )
            if digest.hexdigest() != artifact.sha256:
                raise RuntimeError(f"Artifact SHA-256 mismatch for {artifact.name}")
            return
        except (OSError, RuntimeError, urllib.error.URLError, ValueError) as error:
            last_error = error
            destination.unlink(missing_ok=True)
            if attempt == DOWNLOAD_ATTEMPTS:
                break
    raise RuntimeError(
        f"Unable to download verified artifact for {artifact.name}: {last_error}"
    ) from last_error


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--lock", type=Path, required=True)
    parser.add_argument("--collections-path", type=Path, required=True)
    args = parser.parse_args()

    artifacts = load_lock(args.lock)
    args.collections_path.mkdir(parents=True, exist_ok=False)
    with tempfile.TemporaryDirectory(prefix="devtools-collections-") as temporary:
        staging = Path(temporary)
        archives: list[Path] = []
        for artifact in artifacts.values():
            filename = artifact.url.rsplit("/", maxsplit=1)[-1]
            archive = staging / filename
            download_artifact(artifact, archive)
            archives.append(archive)
        subprocess.run(
            [
                "ansible-galaxy",
                "collection",
                "install",
                "--no-deps",
                "--collections-path",
                str(args.collections_path),
                *(str(archive) for archive in archives),
            ],
            check=True,
            timeout=900,
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
