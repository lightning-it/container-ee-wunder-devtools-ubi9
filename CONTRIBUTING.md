# Contributing to Lightning IT Containers

Thanks for your interest in contributing to Lightning IT container images and related build tooling! This document explains how to propose changes, what we expect from contributions, and how to keep the project consistent and maintainable.

## Scope

This repository contains:

- Container build definitions (Dockerfile/Containerfile)
- Supporting scripts and configuration (CI, linters, build helpers)
- Documentation and shared templates for Lightning IT container images

If you are unsure whether something belongs here, open an issue first.

## Code of Conduct

This project follows our community standards described in `CODE_OF_CONDUCT.md`. By participating, you agree to abide by it.

## How to Contribute

### 1) Open an Issue (recommended for non-trivial changes)

Please open an issue for:

- New features or significant refactoring
- Dependency or base image changes
- Security-related changes
- Breaking changes (anything that affects users or pipelines)

Include:

- What you want to change and why
- Expected behavior
- Any relevant logs or reproduction steps

### 2) Submit a Pull Request

We welcome pull requests for:

- Bug fixes
- Documentation improvements
- Small refactors
- Build and CI improvements

A good PR:

- Has a clear title (e.g., `fix: ...`, `chore: ...`, `docs: ...`)
- Contains a short explanation of *why* the change is needed
- Keeps changes focused (avoid unrelated modifications)
- Updates documentation where relevant

## Development Setup

### Prerequisites

- Git
- Docker or Podman (Buildx recommended if using Docker)
- Python 3.11+ (for pre-commit and local checks)
- `pre-commit`

### Install pre-commit hooks

```bash
python -m pip install --user pre-commit
pre-commit install
```

### Run checks locally

```bash
pre-commit run --all-files
```

## Container Build & Test

### Build locally

Docker (recommended with buildx):

```bash
docker buildx build -t ee-wunder-ansible-ubi9:local .
```

Podman:

```bash
podman build --format docker -t ee-wunder-ansible-ubi9:local .
```

### Smoke test

Example (basic CLI check):

```bash
docker run --rm ee-wunder-ansible-ubi9:local ansible --version
docker run --rm ee-wunder-ansible-ubi9:local ansible-galaxy --version
docker run --rm ee-wunder-ansible-ubi9:local ansible-runner --version
```

## Dependency Policy

### Base images

- Avoid `:latest` for production images.
- Prefer pinning to a release tag or digest.
- Document base image changes in the PR description.

### Python packages (pip)

- Pin versions wherever possible.
- Prefer using a `requirements.txt` when multiple packages are installed.
- Avoid unpinned upgrades unless needed for security reasons.

### OS packages (RPMs / bindep)

- Use `bindep.txt` to document RPM dependencies.
- Keep the list minimal and justified by actual requirements.
- If a dependency is optional, document the use case in a comment.

## Security

If you discover a vulnerability or suspect a security issue, please do **not** open a public issue.

Instead, report it privately:

- Email: **security@l-it.io**

We aim to acknowledge reports promptly and coordinate a responsible disclosure.

## Licensing

Unless stated otherwise, contributions are accepted under the repository’s license. By submitting a pull request, you agree that your contribution may be redistributed under the same license terms.

## Review Process

- Maintainers review PRs for correctness, security, and maintainability.
- We may request changes (style, tests, documentation).
- Once approved, a maintainer will merge the PR.

## Contact

For general questions and contribution help:

- **community@l-it.io**
