#!/usr/bin/env python3
"""Check declared Galaxy Python dependencies before building and after installing."""

from __future__ import annotations

import argparse
import importlib.metadata
import json
import re
import tarfile
import tempfile
from pathlib import Path, PurePosixPath

import yaml
from packaging.requirements import Requirement
from packaging.utils import canonicalize_name

MAX_DECLARATION_BYTES = 256 * 1024


def relative_name(value: str) -> str:
    path = PurePosixPath(value)
    if not value or path.is_absolute() or ".." in path.parts or "\\" in value:
        raise ValueError("unsafe collection dependency path")
    return str(path)


def locked_versions(path: Path) -> dict[str, str]:
    versions = {}
    for line in path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith(("#", "--hash=")):
            continue
        requirement = Requirement(line.removesuffix("\\").strip())
        pins = list(requirement.specifier)
        if len(pins) != 1 or pins[0].operator != "==" or requirement.url:
            raise ValueError("Python lock must contain exact versions")
        name = canonicalize_name(requirement.name)
        if name in versions:
            raise ValueError("duplicate Python lock package")
        versions[name] = pins[0].version
    return versions


def declarations(read):
    """Use the standard EE Python file, falling back to root requirements.txt."""
    ee = read("meta/execution-environment.yml")
    if ee is None:
        ee = read("meta/execution-environment.yaml")
    dependency = None
    if ee is not None:
        config = yaml.safe_load(ee) or {}
        dependency = (config.get("dependencies") or {}).get("python")
    if dependency:
        paths = [relative_name(dependency)]
    else:
        paths = ["requirements.txt"] if read("requirements.txt") is not None else []
    seen = set()
    requirements = []

    def visit(name):
        name = relative_name(name)
        if name in seen:
            raise ValueError("repeated or cyclic requirement include")
        seen.add(name)
        content = read(name)
        if content is None:
            raise ValueError(f"missing declared Python requirements: {name}")
        for raw in content.splitlines():
            line = re.split(r"\s+#", raw, maxsplit=1)[0].strip()
            if not line or line.startswith("#"):
                continue
            if line.startswith(("-r ", "--requirement ")):
                visit(str(PurePosixPath(name).parent / line.split(maxsplit=1)[1]))
                continue
            requirement = Requirement(line)
            if requirement.url:
                raise ValueError("unlocked direct dependency URL")
            requirements.append(requirement)

    for name in paths:
        visit(name)
    return requirements


def validate(requirements, version_for):
    records = []
    for requirement in requirements:
        if requirement.marker and not requirement.marker.evaluate({"extra": ""}):
            continue
        version = version_for(canonicalize_name(requirement.name))
        if version is None or not requirement.specifier.contains(
            version, prereleases=True
        ):
            raise ValueError(
                f"unsatisfied collection Python dependency: {requirement}; found {version}"
            )
        records.append({"requirement": str(requirement), "version": version})
    return records


def tar_reader(archive):
    members = {
        member.name.removeprefix("./"): member for member in archive.getmembers()
    }

    def read(name):
        member = members.get(relative_name(name))
        if member is None:
            return None
        if not member.isfile() or member.size > MAX_DECLARATION_BYTES:
            raise ValueError("unsafe collection dependency declaration")
        stream = archive.extractfile(member)
        if stream is None:
            raise ValueError("unreadable collection dependency declaration")
        return stream.read(MAX_DECLARATION_BYTES + 1).decode("utf-8")

    return read


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--collection-lock", type=Path, required=True)
    parser.add_argument("--python-lock", type=Path)
    parser.add_argument("--installed-root", type=Path)
    args = parser.parse_args()
    from devtools_collection_inventory import load_lock

    inventory = load_lock(args.collection_lock)
    if bool(args.python_lock) == bool(args.installed_root):
        parser.error("choose Python lock preflight or installed runtime check")
    versions = locked_versions(args.python_lock) if args.python_lock else None

    def version_for(name):
        if versions is not None:
            return versions.get(name)
        try:
            return importlib.metadata.version(name)
        except importlib.metadata.PackageNotFoundError:
            return None

    results = []
    with tempfile.TemporaryDirectory(prefix="collection-python-") as temporary:
        for name, artifact in inventory.items():
            if args.installed_root:
                collection = args.installed_root.joinpath(*name.split("."))

                def read(path):
                    target = collection / relative_name(path)
                    if not target.exists():
                        return None
                    if (
                        target.is_symlink()
                        or not target.is_file()
                        or target.stat().st_size > MAX_DECLARATION_BYTES
                    ):
                        raise ValueError("unsafe installed dependency declaration")
                    return target.read_text()

                manifest = json.loads(read("MANIFEST.json"))["collection_info"]
                requirements = declarations(read)
            else:
                from install_devtools_collections import download_artifact

                target = Path(temporary) / f"{name}.tar.gz"
                download_artifact(artifact, target)
                with tarfile.open(target, "r:gz") as archive:
                    read = tar_reader(archive)
                    manifest = json.loads(read("MANIFEST.json"))["collection_info"]
                    requirements = declarations(read)
            if (
                manifest["namespace"] + "." + manifest["name"],
                manifest["version"],
            ) != (name, artifact.version):
                raise ValueError("collection manifest differs from immutable inventory")
            results.append(
                {
                    "collection": name,
                    "version": artifact.version,
                    "python_requirements": validate(requirements, version_for),
                }
            )
    print(
        json.dumps(
            {
                "collections": results,
                "scope": "standard EE/root Python runtime declarations",
            },
            sort_keys=True,
        )
    )


if __name__ == "__main__":
    main()
