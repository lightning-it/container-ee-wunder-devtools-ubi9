from __future__ import annotations

import importlib.util
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

SCRIPT = Path(__file__).resolve().parents[1] / "scripts/download_go_modules.py"
SPEC = importlib.util.spec_from_file_location("go_download", SCRIPT)
assert SPEC and SPEC.loader
helper = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(helper)
PATH = "github.com/hashicorp/terraform-plugin-sdk/v2"
VERSION = "v2.36.1"
URL = f"https://proxy.golang.org/{PATH}/@v/{VERSION}.zip"


def failure(error: str = f'{PATH}@{VERSION}: read "{URL}": unexpected EOF') -> str:
    return json.dumps({"Path": PATH, "Version": VERSION, "Error": error})


def process(code: int, output: str, error: str = "") -> subprocess.CompletedProcess:
    return subprocess.CompletedProcess([], code, output, error)


class GoDownloadTests(unittest.TestCase):
    def test_retries_failed_pin_only_and_preserves_successful_cache(self) -> None:
        output = json.dumps({"Path": "example.org/ok", "Version": "v1.0.0"})
        with (
            mock.patch.object(
                helper.subprocess,
                "run",
                side_effect=[process(1, output + failure()), process(0, "{}")],
            ) as run,
            mock.patch.object(helper.time, "sleep") as sleep,
        ):
            self.assertEqual(0, helper.download())
        self.assertEqual(
            ["go", "mod", "download", "-json", "all"], run.call_args_list[0].args[0]
        )
        self.assertEqual(
            ["go", "mod", "download", "-json", f"{PATH}@{VERSION}"],
            run.call_args_list[1].args[0],
        )
        sleep.assert_called_once_with(1)

    def test_sumdb_http2_failure_retries_only_the_failed_pin(self) -> None:
        coordinate = "go.uber.org/multierr@v1.9.0"
        error = (
            f"{coordinate}: verifying go.mod: {coordinate}/go.mod: reading "
            "https://sum.golang.org/tile/8/0/x056/058: stream error: "
            "stream ID 669; INTERNAL_ERROR; received from peer"
        )
        output = json.dumps({"Path": "go.uber.org/multierr", "Version": "v1.9.0", "Error": error})
        with (
            mock.patch.object(helper.subprocess, "run", side_effect=[process(1, output), process(0, "{}")]) as run,
            mock.patch.object(helper.time, "sleep") as sleep,
            mock.patch.object(helper.sys, "stdout"),
        ):
            self.assertEqual(0, helper.download())
        self.assertEqual(["go", "mod", "download", "-json", coordinate], run.call_args_list[1].args[0])
        sleep.assert_called_once_with(1)
        for old, new in [
            ("sum.golang.org", "evil.example"),
            ("tile/8/0/x056/058", "tile/8/0/x056/058?x=1"),
            ("tile/8/0/x056/058", "tile/8/0/../058"),
            ("INTERNAL_ERROR", "PROTOCOL_ERROR"),
            ("stream ID 669", "stream ID 0"),
            ("verifying go.mod", "verifying zip"),
            ("received from peer", "checksum mismatch"),
        ]:
            with self.subTest(replacement=new):
                malformed = json.dumps({"Path": "go.uber.org/multierr", "Version": "v1.9.0", "Error": error.replace(old, new)})
                self.assertEqual([], helper.interrupted_downloads(malformed, ""))
        self.assertEqual([], helper.interrupted_downloads(output + failure("SECURITY ERROR"), ""))
        self.assertEqual([], helper.interrupted_downloads(output, "SECURITY ERROR"))
        with (
            mock.patch.object(helper.subprocess, "run", return_value=process(1, output)) as run,
            mock.patch.object(helper.time, "sleep") as sleep,
            mock.patch.object(helper.sys, "stdout"),
        ):
            self.assertEqual(1, helper.download())
        self.assertEqual(3, run.call_count)
        self.assertEqual([mock.call(1), mock.call(2)], sleep.call_args_list)

    def test_three_attempt_ceiling_and_one_two_second_delays(self) -> None:
        with (
            mock.patch.object(
                helper.subprocess, "run", return_value=process(1, failure())
            ) as run,
            mock.patch.object(helper.time, "sleep") as sleep,
            mock.patch.object(helper.sys, "stdout"),
        ):
            self.assertEqual(1, helper.download())
        self.assertEqual(3, run.call_count)
        self.assertEqual([mock.call(1), mock.call(2)], sleep.call_args_list)

    def test_retries_exact_public_proxy_zip_transport_failures(self) -> None:
        coordinate = f"{PATH}@{VERSION}"
        errors = [
            f'{coordinate}: read "{URL}": unexpected EOF',
            f'{coordinate}: Get "{URL}": unexpected EOF',
            f'{coordinate}: Get "{URL}": dial tcp 142.250.154.141:443: i/o timeout',
            f'{coordinate}: Get "{URL}": dial tcp [2607:f8b0:4001:c08::8d]:443: i/o timeout',
            f'{coordinate}: Get "{URL}": net/http: TLS handshake timeout',
        ]
        output = "".join(failure(error) for error in errors)
        self.assertEqual(
            [coordinate],
            helper.interrupted_downloads(output, ""),
        )

    def test_deterministic_and_unknown_errors_are_terminal(self) -> None:
        for error in [
            f'read "{URL}": 404 Not Found',
            f'read "{URL}": x509: certificate signed by unknown authority',
            "checksum mismatch",
            "SECURITY ERROR",
            "permission denied",
            "unexpected EOF",
            'read "https://evil.example/x.zip": unexpected EOF',
            f'read "{URL.replace(".zip", ".mod")}": unexpected EOF',
            f'{PATH}@{VERSION}: Get "{URL}": dial tcp proxy.example:443: i/o timeout',
            f'{PATH}@{VERSION}: Get "{URL}": dial tcp 999.999.999.999:443: i/o timeout',
            f'{PATH}@{VERSION}: Get "{URL}": dial tcp [:::]:443: i/o timeout',
            f'{PATH}@{VERSION}: Get "{URL}": dial tcp 127.0.0.1:443: i/o timeout',
            f'{PATH}@{VERSION}: Get "{URL}": dial tcp 10.0.0.1:443: i/o timeout',
            f'{PATH}@{VERSION}: Get "{URL}": dial tcp 169.254.169.254:443: i/o timeout',
            f'{PATH}@{VERSION}: Get "{URL}": dial tcp 0.0.0.0:443: i/o timeout',
            f'{PATH}@{VERSION}: Get "{URL}": dial tcp 224.0.0.1:443: i/o timeout',
            f'{PATH}@{VERSION}: Get "{URL}": dial tcp [::1]:443: i/o timeout',
            f'{PATH}@{VERSION}: Get "{URL}": dial tcp [fc00::1]:443: i/o timeout',
            f'{PATH}@{VERSION}: Get "{URL}": dial tcp [fe80::1]:443: i/o timeout',
            f'{PATH}@{VERSION}: Get "{URL}": dial tcp [::]:443: i/o timeout',
            f'{PATH}@{VERSION}: Get "{URL}": dial tcp [ff02::1]:443: i/o timeout',
            f'{PATH}@{VERSION}: Get "{URL}": dial tcp 142.250.154.141:80: i/o timeout',
            f'{PATH}@{VERSION}: Get "{URL}": context deadline exceeded',
        ]:
            with (
                self.subTest(error=error),
                mock.patch.object(
                    helper.subprocess, "run", return_value=process(1, failure(error))
                ) as run,
                mock.patch.object(helper.time, "sleep") as sleep,
                mock.patch.object(helper.sys, "stdout"),
            ):
                self.assertEqual(1, helper.download())
                run.assert_called_once()
                sleep.assert_not_called()

    def test_mixed_failure_malformed_output_and_stderr_are_terminal(self) -> None:
        for output, stderr in [
            (failure() + failure("checksum mismatch"), ""),
            (failure(), "SECURITY ERROR"),
            (failure() + "garbage", ""),
            ("[]", ""),
            ("{}", ""),
            (failure().replace(VERSION, "latest"), ""),
        ]:
            self.assertEqual([], helper.interrupted_downloads(output, stderr))

    def test_uppercase_module_proxy_escape(self) -> None:
        item = {
            "Path": "github.com/Example/One",
            "Version": "v1.0.0",
            "Error": 'github.com/Example/One@v1.0.0: read "https://proxy.golang.org/github.com/!example/!one/@v/v1.0.0.zip": unexpected EOF',
        }
        self.assertEqual(
            ["github.com/Example/One@v1.0.0"],
            helper.interrupted_downloads(json.dumps(item), ""),
        )

    def test_uppercase_version_proxy_escape_preserves_retry_coordinate(self) -> None:
        path = "github.com/Example/One"
        version = "v1.0.0-RC1"
        url = "https://proxy.golang.org/github.com/!example/!one/@v/v1.0.0-!r!c1.zip"
        item = {
            "Path": path,
            "Version": version,
            "Error": f'{path}@{version}: read "{url}": unexpected EOF',
        }
        with (
            mock.patch.object(
                helper.subprocess, "run",
                side_effect=[process(1, json.dumps(item)), process(0, "{}")],
            ) as run,
            mock.patch.object(helper.time, "sleep") as sleep,
        ):
            self.assertEqual(0, helper.download())
        self.assertEqual(
            ["go", "mod", "download", "-json", f"{path}@{version}"],
            run.call_args_list[1].args[0],
        )
        sleep.assert_called_once_with(1)
        # A raw or incorrectly escaped URL is still an unknown terminal error.
        for invalid_url in [url.replace("!r!c1", "RC1"), url.replace("!r!c1", "rc1")]:
            item["Error"] = f'{path}@{version}: read "{invalid_url}": unexpected EOF'
            self.assertEqual([], helper.interrupted_downloads(json.dumps(item), ""))

    def test_go_failure_signal_is_not_retried(self) -> None:
        for signal in (-9, -15):
            for output in ("", failure()):
                with (
                    self.subTest(signal=signal, output=output),
                    mock.patch.object(
                        helper.subprocess,
                        "run",
                        side_effect=[process(signal, output), process(0, "{}")],
                    ) as run,
                    mock.patch.object(helper.time, "sleep") as sleep,
                    mock.patch.object(helper.sys, "stdout"),
                    mock.patch.object(helper.sys, "stderr"),
                ):
                    self.assertEqual(1, helper.download())
                    run.assert_called_once_with(
                        ["go", "mod", "download", "-json", "all"],
                        capture_output=True,
                        text=True,
                        check=False,
                    )
                    sleep.assert_not_called()

    def test_terraform_build_is_offline_after_verified_prefetch(self) -> None:
        dockerfile = SCRIPT.parents[1].joinpath("Dockerfile").read_text()
        self.assertIn("python3 /usr/local/lib/download_go_modules.py &&", dockerfile)
        self.assertIn("GOPROXY=off go mod verify &&", dockerfile)
        self.assertIn("CGO_ENABLED=0 GOPROXY=off go build", dockerfile)
        self.assertIn("GOSUMDB=sum.golang.org", dockerfile)

    def test_actual_terraform_stage_recovers_first_zip_before_offline_go_get(self) -> None:
        dockerfile = SCRIPT.parents[1].joinpath("Dockerfile").read_text()
        stage = dockerfile.split("RUN curl -fsSLo /tmp/terraform.tar.gz", 1)[1]
        stage = stage.split("    cd /tmp/terraform-source && \\\n", 1)[1]
        commands = stage.split("    CGO_ENABLED=0 GOPROXY=off go build", 1)[0]
        commands = commands.replace(
            "python3 /usr/local/lib/download_go_modules.py",
            f"{sys.executable} {SCRIPT}",
        ).rstrip().removesuffix("\\").rstrip().removesuffix("&&")
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            tools = root / "bin"
            tools.mkdir()
            stub = tools / "go"
            stub.write_text(
                f"#!{sys.executable}\n"
                "import json, os, sys\n"
                "from pathlib import Path\n"
                "root = Path(os.environ['GO_PROBE_ROOT'])\n"
                "args = sys.argv[1:]\n"
                "with (root/'calls').open('a') as log:\n"
                "    log.write(json.dumps([args, os.environ.get('GOPROXY')])+'\\n')\n"
                "if args[:2] == ['mod', 'edit']:\n"
                "    sys.exit(0)\n"
                "if args[:3] == ['mod', 'download', '-json']:\n"
                "    if not (root/'first-download').exists():\n"
                "        (root/'first-download').touch()\n"
                "        print(json.dumps({'Path':'google.golang.org/grpc', 'Version':'v1.83.2',\n"
                "          'Error':'google.golang.org/grpc@v1.83.2: read \"https://proxy.golang.org/google.golang.org/grpc/@v/v1.83.2.zip\": unexpected EOF'}))\n"
                "        sys.exit(1)\n"
                "    (root/'prefetched').touch()\n"
                "    print('{}')\n"
                "    sys.exit(0)\n"
                "if not (root/'prefetched').exists():\n"
                "    print('first ZIP unexpectedly fetched before classified prefetch', file=sys.stderr)\n"
                "    sys.exit(71)\n"
                "if os.environ.get('GOPROXY') != 'off':\n"
                "    sys.exit(72)\n"
                "if args[0] == 'list':\n"
                "    print('v1.83.2')\n"
                "elif args[:2] == ['mod', 'verify']:\n"
                "    (root/'verified').touch()\n"
            )
            stub.chmod(0o755)
            result = subprocess.run(
                ["bash", "-e", "-o", "pipefail", "-c", commands],
                cwd=root,
                env={
                    **os.environ,
                    "PATH": f"{tools}:{os.environ['PATH']}",
                    "GO_GRPC_VERSION": "1.83.2",
                    "GO_X_CRYPTO_VERSION": "0.57.0",
                    "GO_X_NET_VERSION": "0.60.0",
                    "GO_X_TEXT_VERSION": "0.42.0",
                    "GO_PROBE_ROOT": str(root),
                },
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertEqual(0, result.returncode, result.stderr)
            calls = [json.loads(line) for line in (root/'calls').read_text().splitlines()]
            self.assertEqual(['mod', 'edit', '-require=google.golang.org/grpc@v1.83.2'], calls[0][0])
            self.assertEqual(
                [
                    'mod',
                    'edit',
                    '-replace=golang.org/x/crypto=golang.org/x/crypto@v0.57.0',
                    '-replace=golang.org/x/net=golang.org/x/net@v0.60.0',
                    '-replace=golang.org/x/text=golang.org/x/text@v0.42.0',
                ],
                calls[1][0],
            )
            self.assertEqual(['mod', 'download', '-json', 'all'], calls[2][0])
            self.assertEqual(['mod', 'download', '-json', 'google.golang.org/grpc@v1.83.2'], calls[3][0])
            self.assertEqual(['get', 'google.golang.org/grpc@v1.83.2'], calls[4][0])
            self.assertEqual('off', calls[4][1])
            self.assertTrue((root/'verified').exists())
