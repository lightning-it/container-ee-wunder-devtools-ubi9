from __future__ import annotations

import hashlib
import importlib
import socket
import ssl
import sys
import tempfile
import unittest
from pathlib import Path
from typing import Self
from unittest import mock

SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
sys.path.insert(0, str(SCRIPTS))
inventory = importlib.import_module("devtools_collection_inventory")
installer = importlib.import_module("install_devtools_collections")


class FakeResponse:
    def __init__(self, payload: bytes, declared_length: int | None = None) -> None:
        self.payload = payload
        self.offset = 0
        length = len(payload) if declared_length is None else declared_length
        self.headers = {"Content-Length": str(length)}

    def __enter__(self) -> Self:
        return self

    def __exit__(self, *_args: object) -> None:
        return None

    def read(self, size: int) -> bytes:
        chunk = self.payload[self.offset : self.offset + size]
        self.offset += len(chunk)
        return chunk


class DevtoolsDownloadRetryTests(unittest.TestCase):
    def _valid_lock(self) -> str:
        return (
            "collections:\n"
            "  - name: example.one\n"
            "    version: 1.2.3\n"
            f"    url: {inventory.expected_artifact_url('example.one', '1.2.3')}\n"
            f"    sha256: '{'0' * 64}'\n"
            "    size: 8\n"
        )

    def test_lock_accepts_unambiguous_exact_inventory(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            lock = Path(temporary) / "collections.yml"
            lock.write_text(self._valid_lock())
            result = inventory.load_lock(lock)
        self.assertEqual("0" * 64, result["example.one"].sha256)
        self.assertEqual(8, result["example.one"].size)

    def test_lock_rejects_duplicate_top_level_and_nested_trust_fields(self) -> None:
        valid = self._valid_lock()
        for text in (
            valid + valid,
            valid.replace("    sha256:", f"    sha256: '{'1' * 64}'\n    sha256:"),
            valid.replace("    url:", "    url: https://untrusted.invalid/artifact\n    url:"),
        ):
            with self.subTest(text=text), tempfile.TemporaryDirectory() as temporary:
                lock = Path(temporary) / "collections.yml"
                lock.write_text(text)
                with self.assertRaisesRegex(RuntimeError, "Duplicate mapping key"):
                    inventory.load_lock(lock)

    def test_lock_rejects_root_and_nested_yaml_merge_keys(self) -> None:
        valid = self._valid_lock()
        entries = valid.split("collections:\n  - ", 1)[1]
        for text in (
            "<<: &payload\n" + "\n".join("  " + line for line in valid.splitlines()),
            "collections:\n  - <<:\n" + "\n".join(
                "      " + line.lstrip() for line in entries.splitlines()
            ),
        ):
            with self.subTest(text=text), tempfile.TemporaryDirectory() as temporary:
                lock = Path(temporary) / "collections.yml"
                lock.write_text(text)
                with self.assertRaisesRegex(RuntimeError, "YAML merge keys are forbidden"):
                    inventory.load_lock(lock)

    def test_verified_download_accepts_exact_bytes(self) -> None:
        payload = b"bound collection artifact"
        artifact = inventory.CollectionArtifact(
            "example.one",
            "1.2.3",
            inventory.expected_artifact_url("example.one", "1.2.3"),
            hashlib.sha256(payload).hexdigest(),
            len(payload),
        )
        with tempfile.TemporaryDirectory() as temporary:
            destination = Path(temporary) / "artifact.tar.gz"
            with mock.patch.object(
                installer.urllib.request,
                "urlopen",
                side_effect=lambda *_args, **_kwargs: FakeResponse(payload),
            ):
                installer.download_artifact(artifact, destination)
            self.assertEqual(payload, destination.read_bytes())

    def test_verified_download_rejects_hash_and_removes_partial_file(self) -> None:
        payload = b"wrong bytes"
        artifact = inventory.CollectionArtifact(
            "example.one",
            "1.2.3",
            inventory.expected_artifact_url("example.one", "1.2.3"),
            "0" * 64,
            len(payload),
        )
        with tempfile.TemporaryDirectory() as temporary:
            destination = Path(temporary) / "artifact.tar.gz"
            with (
                mock.patch.object(
                    installer.urllib.request,
                    "urlopen",
                    side_effect=lambda *_args, **_kwargs: FakeResponse(payload),
                ) as urlopen,
                self.assertRaisesRegex(
                    RuntimeError,
                    rf"computed={hashlib.sha256(payload).hexdigest()}, expected={'0' * 64}",
                ),
            ):
                installer.download_artifact(artifact, destination)
            self.assertEqual(1, urlopen.call_count)
            self.assertFalse(destination.exists())

    def test_verified_download_reports_declared_and_expected_size(self) -> None:
        payload = b"bound collection artifact"
        artifact = inventory.CollectionArtifact(
            "example.one",
            "1.2.3",
            inventory.expected_artifact_url("example.one", "1.2.3"),
            hashlib.sha256(payload).hexdigest(),
            len(payload),
        )
        declared_length = len(payload) + 1
        with tempfile.TemporaryDirectory() as temporary:
            destination = Path(temporary) / "artifact.tar.gz"
            with (
                mock.patch.object(
                    installer.urllib.request,
                    "urlopen",
                    side_effect=lambda *_args, **_kwargs: FakeResponse(
                        payload, declared_length=declared_length
                    ),
                ) as urlopen,
                self.assertRaisesRegex(
                    RuntimeError,
                    rf"received={declared_length}, expected={len(payload)}",
                ),
            ):
                installer.download_artifact(artifact, destination)
            self.assertEqual(1, urlopen.call_count)
            self.assertFalse(destination.exists())

    def test_transient_download_recovers_after_one_or_two_errors(self) -> None:
        payload = b"bound collection artifact"
        artifact = inventory.CollectionArtifact(
            "example.one",
            "1.2.3",
            inventory.expected_artifact_url("example.one", "1.2.3"),
            hashlib.sha256(payload).hexdigest(),
            len(payload),
        )
        for failures in (1, 2):
            with (
                self.subTest(failures=failures),
                tempfile.TemporaryDirectory() as temporary,
            ):
                destination = Path(temporary) / "artifact.tar.gz"
                responses = [
                    installer.urllib.error.HTTPError(
                        artifact.url, 503, "fixture", {}, None
                    )
                    for _ in range(failures)
                ]
                responses.append(FakeResponse(payload))
                with (
                    mock.patch.object(
                        installer.urllib.request, "urlopen", side_effect=responses
                    ) as urlopen,
                    mock.patch.object(installer.time, "sleep") as sleep,
                ):
                    installer.download_artifact(artifact, destination)
                self.assertEqual(failures + 1, urlopen.call_count)
                self.assertEqual(
                    [mock.call(delay) for delay in (1, 2)[:failures]],
                    sleep.call_args_list,
                )
                self.assertEqual(payload, destination.read_bytes())

    def test_third_transient_error_is_terminal_without_fourth_request(self) -> None:
        artifact = inventory.CollectionArtifact(
            "example.one",
            "1.2.3",
            inventory.expected_artifact_url("example.one", "1.2.3"),
            "0" * 64,
            1,
        )
        with tempfile.TemporaryDirectory() as temporary:
            destination = Path(temporary) / "artifact.tar.gz"
            errors = [
                installer.urllib.error.HTTPError(artifact.url, 503, "fixture", {}, None)
                for _ in range(3)
            ]
            errors.append(FakeResponse(b"x"))
            with (
                mock.patch.object(
                    installer.urllib.request, "urlopen", side_effect=errors
                ) as urlopen,
                mock.patch.object(installer.time, "sleep") as sleep,
                self.assertRaisesRegex(RuntimeError, "Unable to download"),
            ):
                installer.download_artifact(artifact, destination)
            self.assertEqual(3, urlopen.call_count)
            self.assertEqual([mock.call(1), mock.call(2)], sleep.call_args_list)
            self.assertFalse(destination.exists())

    def test_deterministic_transport_errors_do_not_retry(self) -> None:
        artifact = inventory.CollectionArtifact(
            "example.one",
            "1.2.3",
            inventory.expected_artifact_url("example.one", "1.2.3"),
            "0" * 64,
            1,
        )
        errors = [
            installer.urllib.error.HTTPError(artifact.url, code, "fixture", {}, None)
            for code in (400, 401, 403, 404, 409, 422)
        ]
        errors.extend(
            (
                installer.urllib.error.URLError(
                    ssl.SSLCertVerificationError("fixture")
                ),
                installer.urllib.error.URLError(
                    socket.gaierror(socket.EAI_NONAME, "fixture")
                ),
            )
        )
        for error in errors:
            with (
                self.subTest(error=type(error).__name__),
                tempfile.TemporaryDirectory() as temporary,
            ):
                destination = Path(temporary) / "artifact.tar.gz"
                with (
                    mock.patch.object(
                        installer.urllib.request, "urlopen", side_effect=error
                    ) as urlopen,
                    mock.patch.object(installer.time, "sleep") as sleep,
                    self.assertRaisesRegex(RuntimeError, "Unable to download"),
                ):
                    installer.download_artifact(artifact, destination)
                self.assertEqual(1, urlopen.call_count)
                sleep.assert_not_called()
                self.assertFalse(destination.exists())

    def test_incomplete_response_does_not_retry(self) -> None:
        artifact = inventory.CollectionArtifact(
            "example.one",
            "1.2.3",
            inventory.expected_artifact_url("example.one", "1.2.3"),
            "0" * 64,
            1,
        )
        response = FakeResponse(b"x")
        response.read = mock.Mock(
            side_effect=installer.http.client.IncompleteRead(b"", 1)
        )
        with tempfile.TemporaryDirectory() as temporary:
            destination = Path(temporary) / "artifact.tar.gz"
            with (
                mock.patch.object(
                    installer.urllib.request, "urlopen", return_value=response
                ) as urlopen,
                mock.patch.object(installer.time, "sleep") as sleep,
                self.assertRaisesRegex(RuntimeError, "Unable to download"),
            ):
                installer.download_artifact(artifact, destination)
            self.assertEqual(1, urlopen.call_count)
            sleep.assert_not_called()
            self.assertFalse(destination.exists())

    def test_local_filesystem_timeout_does_not_retry_network(self) -> None:
        artifact = inventory.CollectionArtifact(
            "example.one",
            "1.2.3",
            inventory.expected_artifact_url("example.one", "1.2.3"),
            hashlib.sha256(b"x").hexdigest(),
            1,
        )
        with tempfile.TemporaryDirectory() as temporary:
            destination = Path(temporary) / "artifact.tar.gz"
            with (
                mock.patch.object(
                    installer.urllib.request, "urlopen", return_value=FakeResponse(b"x")
                ) as urlopen,
                mock.patch.object(
                    installer.os, "fsync", side_effect=TimeoutError("local filesystem")
                ),
                mock.patch.object(installer.time, "sleep") as sleep,
                self.assertRaisesRegex(RuntimeError, "local filesystem"),
            ):
                installer.download_artifact(artifact, destination)
            self.assertEqual(1, urlopen.call_count)
            sleep.assert_not_called()
            self.assertFalse(destination.exists())


if __name__ == "__main__":
    unittest.main()
