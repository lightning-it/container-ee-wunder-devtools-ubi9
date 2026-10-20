#!/usr/bin/env python3
# Managed by lightning-it/shared-assets-lit; edit the central container override.
"""Install SHA-256-bound Galaxy artifacts into the Devtools image."""

from __future__ import annotations

import argparse
import hashlib
import http.client
import json
import os
import socket
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
from pathlib import Path

from devtools_collection_inventory import CollectionArtifact, load_lock

CHUNK_BYTES = 1024 * 1024
DOWNLOAD_ATTEMPTS = 3
RETRY_DELAYS_SECONDS = (1, 2)
TRANSIENT_HTTP_STATUSES = frozenset({408, 429, 500, 502, 503, 504})


def transient_network_error(error: BaseException) -> bool:
    """Retry only recognized temporary read-transport failures."""
    if isinstance(error, urllib.error.HTTPError):
        return error.code in TRANSIENT_HTTP_STATUSES
    reason = error.reason if isinstance(error, urllib.error.URLError) else error
    if isinstance(reason, socket.gaierror):
        return reason.errno == socket.EAI_AGAIN
    return isinstance(
        reason,
        (
            TimeoutError,
            ConnectionResetError,
            ConnectionRefusedError,
            ConnectionAbortedError,
        ),
    )


def download_artifact(artifact: CollectionArtifact, destination: Path) -> None:
    last_error: BaseException | None = None
    for attempt in range(1, DOWNLOAD_ATTEMPTS + 1):
        print(
            json.dumps(
                {
                    "event": "verified-download-attempt",
                    "attempt": attempt,
                    "max_attempts": DOWNLOAD_ATTEMPTS,
                }
            ),
            file=sys.stderr,
            flush=True,
        )
        destination.unlink(missing_ok=True)
        digest = hashlib.sha256()
        received = 0
        request = urllib.request.Request(
            artifact.url,
            headers={"User-Agent": "Lightning-IT-Devtools-Builder/1"},
        )
        network_operation = False
        try:
            network_operation = True
            response = urllib.request.urlopen(request, timeout=60)
            network_operation = False
            with response:
                declared_length = response.headers.get("Content-Length")
                if (
                    declared_length is not None
                    and int(declared_length) != artifact.size
                ):
                    raise RuntimeError(
                        f"Unexpected Content-Length for {artifact.name}: "
                        f"received={declared_length}, expected={artifact.size}"
                    )
                with destination.open("xb") as output:
                    os.chmod(destination, 0o600)
                    while True:
                        network_operation = True
                        chunk = response.read(CHUNK_BYTES)
                        network_operation = False
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
            computed_sha256 = digest.hexdigest()
            if computed_sha256 != artifact.sha256:
                raise RuntimeError(
                    f"Artifact SHA-256 mismatch for {artifact.name}: "
                    f"computed={computed_sha256}, expected={artifact.sha256}"
                )
            return
        except (
            OSError,
            RuntimeError,
            urllib.error.URLError,
            ValueError,
            http.client.HTTPException,
        ) as error:
            last_error = error
            destination.unlink(missing_ok=True)
            if (
                not network_operation
                or not transient_network_error(error)
                or attempt == DOWNLOAD_ATTEMPTS
            ):
                break
            delay = RETRY_DELAYS_SECONDS[attempt - 1]
            print(
                json.dumps(
                    {
                        "event": "verified-download-transient-retry",
                        "next_attempt": attempt + 1,
                        "delay_seconds": delay,
                    }
                ),
                file=sys.stderr,
                flush=True,
            )
            time.sleep(delay)
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
