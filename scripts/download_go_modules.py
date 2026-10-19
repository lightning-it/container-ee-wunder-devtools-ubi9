#!/usr/bin/env python3
"""Prefetch Go modules; retry only bounded public-proxy ZIP transport errors.

Go owns cache cleanup, go.sum and sumdb verification. No build/get/tidy command
is retried. Successful modules stay cached; retries address only failed pins.
"""

from __future__ import annotations

import ipaddress
import json
import re
import subprocess
import sys
import time

MODULE = re.compile(r"[A-Za-z0-9._/~+!-]+")
VERSION = re.compile(r"v[0-9A-Za-z._+!-]+")
def proxy_escape(value: str) -> str:
    """Use Go's ASCII case encoding for both module paths and versions."""
    return re.sub(r"[A-Z]", lambda match: "!" + match.group().lower(), value)


def valid_tcp_timeout(detail: str) -> bool:
    """Accept only a valid IP literal on the HTTPS port."""
    prefix, suffix = "dial tcp ", ": i/o timeout"
    if not detail.startswith(prefix) or not detail.endswith(suffix):
        return False
    endpoint = detail[len(prefix) : -len(suffix)]
    host, separator, port = endpoint.rpartition(":")
    if separator != ":" or port != "443" or not host:
        return False
    bracketed = host.startswith("[") and host.endswith("]")
    literal = host[1:-1] if bracketed else host
    if (":" in literal) != bracketed:
        return False
    try:
        address = ipaddress.ip_address(literal)
    except ValueError:
        return False
    return address.is_global and not address.is_multicast


def retryable_transport_error(error: str, coordinate: str, url: str) -> bool:
    """Recognize only transport failures for the exact public-proxy ZIP."""
    for operation in ("read", "Get"):
        prefix = f'{coordinate}: {operation} "{url}": '
        if not error.startswith(prefix):
            continue
        detail = error[len(prefix) :]
        return detail in {
            "unexpected EOF",
            "net/http: TLS handshake timeout",
        } or valid_tcp_timeout(detail)
    return False


def interrupted_downloads(output: str, stderr: str) -> list[str]:
    """Fail closed on mixed, integrity, local, malformed or unknown errors."""
    if stderr.strip():
        return []
    decoder = json.JSONDecoder()
    remaining = output.strip()
    failed = []
    try:
        while remaining:
            item, end = decoder.raw_decode(remaining)
            remaining = remaining[end:].lstrip()
            if not isinstance(item, dict):
                return []
            error = item.get("Error")
            if not error:
                continue
            path, version = item.get("Path", ""), item.get("Version", "")
            if not isinstance(path, str) or not isinstance(version, str):
                return []
            if not MODULE.fullmatch(path) or not VERSION.fullmatch(version):
                return []
            url = (
                f"https://proxy.golang.org/{proxy_escape(path)}/@v/"
                f"{proxy_escape(version)}.zip"
            )
            coordinate = f"{path}@{version}"
            if not retryable_transport_error(error, coordinate, url):
                return []
            failed.append(coordinate)
    except (ValueError, TypeError):
        return []
    return list(dict.fromkeys(failed))


def download() -> int:
    # Include the upgraded requirement's entire selected module graph before
    # the offline go get reconciles indirect requirements in go.mod.
    coordinates: list[str] = ["all"]
    for attempt in range(3):
        result = subprocess.run(
            ["go", "mod", "download", "-json", *coordinates],
            capture_output=True,
            text=True,
            check=False,
        )
        if result.returncode == 0:
            return 0
        coordinates = interrupted_downloads(result.stdout, result.stderr)
        if not coordinates or attempt == 2:
            sys.stdout.write(result.stdout)
            sys.stderr.write(result.stderr)
            return result.returncode if result.returncode > 0 else 1
        print(
            f"Go module ZIP transport interrupted; retry {attempt + 1}/2 "
            f"for {len(coordinates)} pinned module(s)",
            file=sys.stderr,
        )
        time.sleep(attempt + 1)
    return 1


if __name__ == "__main__":
    raise SystemExit(download())
