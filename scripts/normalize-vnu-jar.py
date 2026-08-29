from __future__ import annotations

import argparse
import os
import tempfile
import zipfile
from pathlib import Path


ARCHIVE_TIMESTAMP = (2026, 8, 29, 0, 0, 0)
GENERATED_PROPERTIES = "nu/validator/localentities/files/misc.properties"
GENERATED_HEADER = b"#Sat, 29 Aug 2026 00:00:00 +0000\n"


def normalized_payload(name: str, payload: bytes) -> bytes:
    if name != GENERATED_PROPERTIES:
        return payload
    lines = payload.splitlines(keepends=True)
    if not lines or not lines[0].startswith(b"#"):
        raise ValueError(f"unexpected generated properties format: {name}")
    return GENERATED_HEADER + b"".join(lines[1:])


def archive_order(name: str) -> tuple[int, str]:
    if name == "META-INF/":
        return (0, name)
    if name == "META-INF/MANIFEST.MF":
        return (1, name)
    return (2, name)


def normalize_jar(path: Path) -> None:
    if not path.is_file() or path.is_symlink():
        raise ValueError(f"JAR must be a regular file: {path}")

    with zipfile.ZipFile(path, "r") as source:
        names = source.namelist()
        if len(names) != len(set(names)):
            raise ValueError("JAR contains duplicate entries")
        entries = [(name, normalized_payload(name, source.read(name))) for name in names]

    descriptor, temporary_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    os.close(descriptor)
    temporary = Path(temporary_name)
    try:
        with zipfile.ZipFile(
            temporary,
            "w",
            compression=zipfile.ZIP_DEFLATED,
            compresslevel=9,
            strict_timestamps=True,
        ) as target:
            for name, payload in sorted(entries, key=lambda item: archive_order(item[0])):
                directory = name.endswith("/")
                info = zipfile.ZipInfo(name, ARCHIVE_TIMESTAMP)
                info.create_system = 3
                info.external_attr = ((0o40755 if directory else 0o100644) << 16)
                target.writestr(
                    info,
                    payload,
                    compress_type=zipfile.ZIP_STORED if directory else zipfile.ZIP_DEFLATED,
                    compresslevel=9,
                )
        os.chmod(temporary, 0o444)
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def main() -> None:
    parser = argparse.ArgumentParser(description="Normalize the generated Nu checker JAR")
    parser.add_argument("jar", type=Path)
    arguments = parser.parse_args()
    normalize_jar(arguments.jar)


if __name__ == "__main__":
    main()
