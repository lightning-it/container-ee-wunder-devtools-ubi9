# Testing

This repository uses the Lightning IT shared test model.

## Test Profiles

- `pre-commit`
- `lint`
- `container-build`
- `container-smoke`
- `trivy`
- `release-validation`

## Supported Matrix

Operating systems and runners:

- `ubuntu-latest`

Products and runtimes:

- `ubi9`
- `podman`
- `docker-buildx`

## When Tests Run

- Normal pull requests run pre-commit, linting, syntax checks, and light tests relevant to changed files.
- Renovate and shared-assets synchronization pull requests target `develop` and may auto-merge only after required checks pass.
- `develop` to `main` promotion pull requests run the strongest validation profile for this repository.
- Trusted `main` release workflows build and publish artifacts only after validation succeeds.

## Local Commands

Run pre-commit locally:

```bash
pre-commit run --all-files
```

Run repository-specific light checks from the checked-out repository:

```bash
bash scripts/wunder-devtools-ee.sh true
```

Heavy Incus tests require an Ubuntu host or runner with Incus available, suitable images, and repository-specific scenario configuration. Heavy tests must use sanitized inputs and must not rely on private inventory values.

## Interpreting GitHub Actions

The GitHub Actions matrix is the primary dashboard. Job names should expose the repository class, OS/runtime, and profile, for example `ansible / rhel9 / molecule-heavy-incus` or `container / ubuntu / build-smoke`.

Release evidence is generated during trusted release workflows and attached to or linked from GitHub Releases where the repository publishes release artifacts.
