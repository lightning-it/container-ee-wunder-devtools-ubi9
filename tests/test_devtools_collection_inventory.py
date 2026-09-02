from __future__ import annotations

import hashlib
import importlib
import json
import sys
import tempfile
import unittest
from pathlib import Path
from typing import Self
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

inventory = importlib.import_module("devtools_collection_inventory")
installer = importlib.import_module("install_devtools_collections")

LOCK = ROOT / "collections/offline-requirements.lock.yml"
EXPECTED = {
    "amazon.aws": (
        "10.3.2",
        "9c6ded292d7e79560f50a0b0ae9b03f184a7942d2be2ecfb3720e1108b7f2311",
        1300275,
    ),
    "ansible.posix": (
        "2.2.2",
        "00a58c5d804c9adc99c3c3dc1b9f2246f4bb5f7337941440e0956f0e31c3b82b",
        166545,
    ),
    "community.aws": (
        "10.1.1",
        "64cc4c5f4041f9c2f2b741bcde9864231c2366b2dfa38a057d54e37dcbab1b5b",
        807257,
    ),
    "community.crypto": (
        "3.3.0",
        "b17e3fe14fb934a38213204d8fe70c52fd63aabf6ea8ffd56e8fbaef70b69f18",
        596994,
    ),
    "community.docker": (
        "5.2.2",
        "96f30eea08f719918bb223a3777271bf82ef72076eef204a4986dfcea94ce3f7",
        595920,
    ),
    "community.general": (
        "11.4.9",
        "18db0bed0d0d12165fc18b6a6430035fdda4b6ceaadada4d60a4d71e5bbe92eb",
        2713911,
    ),
    "community.hashi_vault": (
        "7.1.0",
        "090e1b52f2889887baa3792abc4284f700200ae0359f534a14d0a34951db8e57",
        267852,
    ),
    "community.hrobot": (
        "2.7.2",
        "6cc374ebede982027b9f6533100a2f624d3f3b7c961781cb54a5c3803f30063d",
        134752,
    ),
    "community.library_inventory_filtering_v1": (
        "1.1.5",
        "cbb9e86c5b1720df21e940cedcd2f3e1226c38262623e090a883712610733851",
        36002,
    ),
    "community.vmware": (
        "5.10.0",
        "80910a58c552973d23ec3ecbdeaad181bcce140ffe244db658079bf695a22c0f",
        658480,
    ),
    "hetzner.hcloud": (
        "6.10.0",
        "f91f6f4761cce1cdea052a5e64e22beabb04dcc8f213729d0bc1c2835ab12ebd",
        268821,
    ),
    "lit.foundational": (
        "1.32.0",
        "755e7aac974e833c0f60a0f30e06e75e4dcc24c2b029063cdd7215ff3841dcba",
        236720,
    ),
    "lit.rhel": (
        "1.17.1",
        "160b87d8345f652f1ece44f7ac08e3af65a7c0b933d7517d5c9e1f44a9d09eac",
        159738,
    ),
    "vmware.vmware": (
        "2.9.0",
        "6761d3e69bcf828745edebe442566095bb45deb4e5b8a130c3197421a6e45a98",
        375678,
    ),
}


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


class DevtoolsCollectionInventoryTests(unittest.TestCase):
    @staticmethod
    def write_manifest(root: Path, name: str, version: str) -> None:
        namespace, collection = name.split(".", maxsplit=1)
        collection_path = root / namespace / collection
        collection_path.mkdir(parents=True)
        (collection_path / "MANIFEST.json").write_text(
            json.dumps(
                {
                    "collection_info": {
                        "namespace": namespace,
                        "name": collection,
                        "version": version,
                    }
                }
            ),
            encoding="utf-8",
        )

    def test_repository_lock_is_exact_complete_and_unmanaged(self) -> None:
        actual = inventory.load_lock(LOCK)
        self.assertEqual(
            EXPECTED,
            {
                name: (artifact.version, artifact.sha256, artifact.size)
                for name, artifact in actual.items()
            },
        )

        dockerfile = (ROOT / "Dockerfile").read_text(encoding="utf-8")
        self.assertIn(
            "COPY collections/offline-requirements.lock.yml "
            "/usr/local/share/wunder-devtools/collections.lock.yml",
            dockerfile,
        )
        self.assertIn(
            "python /usr/local/bin/install_devtools_collections.py", dockerfile
        )
        self.assertIn(
            "python /usr/local/bin/devtools_collection_inventory.py", dockerfile
        )
        self.assertNotIn("ansible-galaxy collection install", dockerfile)

        renovate = (ROOT / "renovate.json").read_text(encoding="utf-8")
        self.assertNotIn("offline-requirements.lock.yml", renovate)

    def test_patched_go_crypto_is_forced_into_vulnerable_binaries(self) -> None:
        dockerfile = (ROOT / "Dockerfile").read_text(encoding="utf-8")
        self.assertIn("ARG GO_X_CRYPTO_VERSION=0.55.0", dockerfile)
        self.assertIn(
            'github.com/terraform-docs/terraform-docs "v${TF_DOCS_VERSION}" '
            ". terraform-docs \\\n"
            '      "golang.org/x/crypto@v${GO_X_CRYPTO_VERSION}"',
            dockerfile,
        )
        self.assertIn(
            'helm.sh/helm/v4 "v${HELM_VERSION}" ./cmd/helm helm \\\n'
            '      "golang.org/x/crypto@v${GO_X_CRYPTO_VERSION}"',
            dockerfile,
        )

    def test_patched_grpc_is_forced_into_every_affected_binary(self) -> None:
        dockerfile = (ROOT / "Dockerfile").read_text(encoding="utf-8")
        compose_builder = (ROOT / "scripts/container-build-compose.sh").read_text(
            encoding="utf-8"
        )

        self.assertIn("ARG GO_GRPC_VERSION=1.83.1", dockerfile)
        self.assertEqual(
            2,
            dockerfile.count(
                'go get "google.golang.org/grpc@v${GO_GRPC_VERSION}"'
            ),
        )
        self.assertIn(
            'github.com/cli/cli/v2 "v${GH_VERSION}" ./cmd/gh gh \\\n'
            '      "golang.org/x/mod@v${GO_X_MOD_VERSION}" \\\n'
            '      "google.golang.org/grpc@v${GO_GRPC_VERSION}"',
            dockerfile,
        )
        self.assertIn(
            'cp vendor.sum go.sum && \\\n'
            '    GOFLAGS=-mod=mod go get '
            '"google.golang.org/grpc@v${GO_GRPC_VERSION}"',
            dockerfile,
        )
        self.assertIn("CGO_ENABLED=0 GOFLAGS=-mod=mod go build", dockerfile)
        self.assertIn(
            "for binary in terraform tflint terraform-docs gh docker "
            "docker-compose",
            dockerfile,
        )
        self.assertNotIn("-mod=vendor", dockerfile)
        self.assertIn("<grpc-version>", compose_builder)
        self.assertIn("invalid container build coordinate", compose_builder)
        self.assertNotIn("invalid Compose build coordinate", compose_builder)
        self.assertIn(
            '"-replace=google.golang.org/grpc='
            'google.golang.org/grpc@v${grpc_version}"',
            compose_builder,
        )
        self.assertIn(
            'effective_grpc_version="$(\n'
            "  go version -m /out/docker-compose",
            compose_builder,
        )

    def test_exact_inventory_passes(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            collections_root = root / "collections"
            collections_root.mkdir()
            self.write_manifest(collections_root, "example.one", "1.2.3")
            self.write_manifest(collections_root, "example.two", "2.3.4")
            self.assertEqual(
                {"example.one": "1.2.3", "example.two": "2.3.4"},
                inventory.load_installed(collections_root),
            )

    def test_symlinked_namespace_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            collections_root = root / "collections"
            collections_root.mkdir()
            outside = root / "outside"
            outside.mkdir()
            (collections_root / "example").symlink_to(outside, target_is_directory=True)
            with self.assertRaisesRegex(RuntimeError, "must be a real directory"):
                inventory.load_installed(collections_root)

    def test_invalid_installed_version_identifies_manifest_and_value(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            collections_root = Path(temporary) / "collections"
            collections_root.mkdir()
            self.write_manifest(collections_root, "example.one", "not-a-version")
            manifest = collections_root / "example" / "one" / "MANIFEST.json"
            with self.assertRaisesRegex(
                RuntimeError,
                rf"invalid version at {manifest}: 'not-a-version'",
            ):
                inventory.load_installed(collections_root)

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
            self.assertEqual(installer.DOWNLOAD_ATTEMPTS, urlopen.call_count)
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
            self.assertEqual(installer.DOWNLOAD_ATTEMPTS, urlopen.call_count)
            self.assertFalse(destination.exists())


if __name__ == "__main__":
    unittest.main()
