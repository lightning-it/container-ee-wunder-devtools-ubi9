# Testing

This repository uses the Lightning IT shared test model.

## Test Profiles

- `pre-commit`
- `lint`
- `container-build`
- `container-smoke`
- `trivy`
- `fuzzing`
- `release-validation`

## Supported Matrix

Operating systems and runners:

- `ubuntu-latest`

Products and runtimes:

- `ubi9`
- `podman`
- `docker-buildx`

## When Tests Run

- Normal pull requests run the declared test profiles relevant to changed files.
- Renovate and verified shared-assets or repository-quality synchronization pull requests target `develop` and may auto-merge only after required checks pass.
- `develop` to `main` promotion pull requests run the strongest validation profile for this repository.
- Trusted `main` release workflows build and publish artifacts only after validation succeeds.

## Local Commands

Run the managed repository-policy checks:

```bash
python3 -m venv .venv
.venv/bin/python -m pip install PyYAML==6.0.3
.venv/bin/python scripts/lit-repository-quality.py
.venv/bin/python scripts/lit-push-ready.py push-ready
```

Run the declared pre-commit profile:

```bash
pre-commit run --all-files
```

Run the repository-specific commands declared in
`.lit/push-ready.json` and the required CI workflow named in
`.lit/repository.yml`. Do not substitute unrelated toolchains.

Heavy Incus execution is not required for this repository. Do not report an Incus run as part of its acceptance evidence.

## Interpreting GitHub Actions

The GitHub Actions matrix is the primary dashboard. Job names should expose the repository class, OS/runtime where applicable, and profile, for example `container / ubuntu / build-smoke`.

Release evidence is generated during trusted release workflows and attached to or linked from GitHub Releases where the repository publishes release artifacts.
