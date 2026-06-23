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

### Branch and release flow

- Open normal PRs against `develop`.
- Renovate and shared-assets sync PRs also target `develop`.
- `main` is the production release branch and should only receive changes through the automated `develop` to `main`
  promotion PR.
- Merging the promotion PR into `main` runs semantic-release.
- After `main` changes, automation opens a `main` back to `develop` PR so future promotion PRs start from a clean branch
  ancestry.
- semantic-release calculates the next version, creates the Git tag, and publishes GitHub Release notes.
- Container images are built from the exact release tag and published with immutable version/SHA tags plus the moving
  production tag.
- Release images are published with Buildx SBOM/provenance attestations and are signed by immutable digest with
  keyless Sigstore/Cosign.
- The release workflow verifies expected tags, digests, vulnerability policy, and signing identity before it finishes.
- Container repositories do not maintain a committed `CHANGELOG.md`; use GitHub Releases as the changelog.

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

### Renovate scope for certified RH collections

For Red Hat Automation Hub certified collections, do not rely on Mend-hosted
Renovate lookups when authentication is based on offline tokens.

Reason:

- Red Hat offline tokens require a refresh-token -> access-token exchange flow.
- Renovate `galaxy-collection` lookups use direct HTTP auth and do not execute
  this exchange flow in Mend-hosted mode.

Policy:

- Exclude `collections/requirements-certified-extra.yml` (or equivalent
  certified-only requirement files) from Renovate checks/updates.
- Manage certified collection versions with a controlled manual or CI workflow.

### Install pre-commit hooks

```bash
python -m pip install --user pre-commit
pre-commit install
```

### Run checks locally

```bash
pre-commit run --all-files
```

The managed pre-commit hook runs the same container CI parity script that GitHub PR checks run, inside the devtools
container. A local green run should therefore catch the normal PR build, lint, runtime contract, Renovate config, and
container vulnerability checks before you push.

## Container Build & Test

### Build locally

Docker (recommended with buildx):

```bash
docker buildx build -t ee-wunder-toolbox-ubi9:local .
```

Podman:

```bash
podman build --format docker -t ee-wunder-toolbox-ubi9:local .
```

### Smoke test

Example (basic CLI check):

```bash
podman run --rm ee-wunder-toolbox-ubi9:local ansible-navigator --version
podman run --rm ee-wunder-toolbox-ubi9:local helm version --short
podman run --rm ee-wunder-toolbox-ubi9:local kustomize version
podman run --rm ee-wunder-toolbox-ubi9:local sh -lc 'command -v ansible-nav && command -v test-ansible.sh'
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
