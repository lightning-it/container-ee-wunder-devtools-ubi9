# Container Documentation

This document provides the basic user and operator documentation for `container-ee-wunder-devtools-ubi9`.

## Install

Install a local container runtime such as Podman or Docker, then pull the published image:

```bash
podman pull quay.io/l-it/ee-wunder-devtools-ubi9:latest
```

Pinned release tags are preferred for repeatable automation:

```bash
podman pull quay.io/l-it/ee-wunder-devtools-ubi9:vX.Y.Z
```

## Start

Run the image with an explicit command and a read-only project mount when possible:

```bash
podman run --rm -it \
  --pull=always \
  --volume "$PWD:/workspace:Z" \
  --workdir /workspace \
  quay.io/l-it/ee-wunder-devtools-ubi9:latest --help
```

## Use

This image is intended for CI and operator workflows documented in `README.md`, `RELEASE.md`, and `TESTING.md`.
Use repository-specific scripts or GitHub Actions as the reference interface for builds, smoke tests, release evidence,
and vulnerability scanning.

## Interface

The supported external interface is the container image entrypoint, its command-line arguments, environment variables
documented by the image scripts, mounted workspace files, published image tags, and GitHub release artifacts. Container
labels and release evidence identify the source repository, commit, version, and build workflow.

## Secure Use

- Prefer immutable version tags for production or release automation.
- Pull images over HTTPS from the configured registry.
- Run with the minimum required filesystem mounts and environment variables.
- Do not pass long-lived credentials through command-line arguments.
- Keep secrets in GitHub Actions secrets, local secret stores, or short-lived environment variables.
- Review Trivy results and release evidence before promoting a new image into trusted automation.
