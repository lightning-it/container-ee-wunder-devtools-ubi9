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
scripts/lit-ci-profile.sh repository-quality
```

This command is a managed dispatcher into the digest-pinned Devtools image;
it does not use host language runtimes as acceptance evidence. If the image
lacks a required tool, update and normally release the Devtools image and then
repin its managed digest instead of creating a host virtual environment.
Where present, `.github/requirements/repository-quality.lock` is consumed by
this profile and must match the PyYAML version in the pinned Devtools image.

Heavy Incus execution is not required for this repository. Do not report an Incus run as part of its acceptance evidence.

## Interpreting GitHub Actions

The GitHub Actions matrix is the primary dashboard. Job names should expose the repository class, OS/runtime where applicable, and profile, for example `container / ubuntu / build-smoke`.

Release evidence is generated during trusted release workflows and attached to or linked from GitHub Releases where the repository publishes release artifacts.
