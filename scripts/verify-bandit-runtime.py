#!/usr/bin/env python3
"""Qualify the image's scanner with real clean and intentionally unsafe inputs."""

from __future__ import annotations

import importlib.metadata
import json
import subprocess
import sys
import tempfile
from pathlib import Path


EXPECTED_VERSION = "1.9.4"


def check_result(completed, *, rule=None, severity=None):
    report = json.loads(completed.stdout)
    if not isinstance(report, dict) or report.get("errors") != []:
        raise AssertionError("Bandit smoke report has parse errors or an invalid schema")
    results = report.get("results")
    if not isinstance(results, list):
        raise AssertionError("Bandit smoke report has no results inventory")
    if rule is None:
        if completed.returncode != 0 or results:
            raise AssertionError("Bandit rejected the clean smoke fixture")
    elif completed.returncode != 1 or not any(
        item.get("test_id") == rule and item.get("issue_severity") == severity
        for item in results
    ):
        raise AssertionError(f"Bandit did not reject the {rule} smoke fixture")


def main():
    actual = importlib.metadata.version("bandit")
    if actual != EXPECTED_VERSION:
        raise AssertionError(f"Expected Bandit {EXPECTED_VERSION}, found {actual}")
    fixtures = (
        ("clean", "def add(left, right):\n    return left + right\n", None, None),
        ("known-violation", "eval('1 + 1')  # nosec B307\n", "B307", "MEDIUM"),
        ("low-severity", "assert True  # nosec B101\n", "B101", "LOW"),
    )
    with tempfile.TemporaryDirectory() as directory:
        for name, content, rule, severity in fixtures:
            path = Path(directory) / f"{name}.py"
            path.write_text(content, encoding="utf-8")
            completed = subprocess.run(
                [sys.executable, "-m", "bandit", "--format", "json",
                 "--severity-level", "low", "--confidence-level", "low",
                 "--ignore-nosec", str(path)],
                capture_output=True, text=True, check=False, timeout=60,
            )
            check_result(completed, rule=rule, severity=severity)
            print(f"Bandit {actual} smoke {name}: expected exit {completed.returncode}")


if __name__ == "__main__":
    main()
