from __future__ import annotations

import importlib.util
import tempfile
import unittest
from pathlib import Path

from packaging.requirements import Requirement

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts/verify_devtools_collection_python.py"
SPEC = importlib.util.spec_from_file_location("collection_python", SCRIPT)
assert SPEC is not None and SPEC.loader is not None
checker = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(checker)


class CollectionPythonTests(unittest.TestCase):
    def test_hcloud_missing_dateutil_is_rejected(self):
        requirements = checker.declarations(
            {"requirements.txt": "python-dateutil\nrequests\n"}.get
        )
        with self.assertRaisesRegex(ValueError, "python-dateutil"):
            checker.validate(requirements, {"requests": "2.34.2"}.get)

    def test_hcloud_complete_runtime_is_accepted(self):
        requirements = checker.declarations(
            {"requirements.txt": "python-dateutil\nrequests\n"}.get
        )
        self.assertEqual(
            len(
                checker.validate(
                    requirements,
                    {
                        "python-dateutil": "2.9.0.post0",
                        "requests": "2.34.2",
                    }.get,
                )
            ),
            2,
        )

    def test_incompatible_aws_version_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "botocore"):
            checker.validate(
                [Requirement("botocore>=1.34.0")], {"botocore": "1.33.0"}.get
            )

    def test_ee_runtime_file_and_include_are_followed(self):
        files = {
            "meta/execution-environment.yml": "dependencies:\n  python: meta/ee-requirements.txt\n",
            "meta/ee-requirements.txt": "-r common.txt\nhvac>=1.2.1\n",
            "meta/common.txt": "requests\n",
            "requirements.txt": "not-a-runtime-dev-package\n",
        }
        self.assertEqual(
            [r.name for r in checker.declarations(files.get)], ["requests", "hvac"]
        )

    def test_missing_and_escaping_include_fail_closed(self):
        for value in ["missing.txt", "../outside.txt"]:
            with self.subTest(value=value), self.assertRaises(ValueError):
                checker.declarations({"requirements.txt": f"-r {value}\n"}.get)

    def test_platform_marker_is_respected(self):
        self.assertEqual(
            checker.validate([Requirement('missing; python_version < "2"')], {}.get), []
        )

    def test_real_hash_lock_contains_complete_runtime_requirements(self):
        versions = checker.locked_versions(SCRIPT.parents[1] / "requirements.lock")
        required = [
            "boto3>=1.34.0",
            "botocore>=1.34.0",
            "paramiko",
            "azure-identity",
            "python-dateutil",
            "vmware-vcenter",
            "vmware-vapi-common-client",
        ]
        self.assertEqual(
            len(checker.validate([Requirement(r) for r in required], versions.get)), 7
        )

    def test_unpinned_lock_is_rejected(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "requirements.lock"
            path.write_text("python-dateutil>=2\n")
            with self.assertRaises(ValueError):
                checker.locked_versions(path)


if __name__ == "__main__":
    unittest.main()
