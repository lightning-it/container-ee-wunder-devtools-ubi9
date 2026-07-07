# OpenSSF Readiness

This repository follows the Lightning IT shared OpenSSF readiness model generated from `lightning-it/shared-assets-lit`.

## Repository

- Repository: `container-ee-wunder-devtools-ubi9`
- Visibility: `public`
- Type: `container_image`
- Release type: `semantic_release`
- Artifact type: `container_image`

## Scorecard

Enabled through `.github/workflows/openssf-scorecard.yml` with scheduled, manual, `branch_protection_rule`, and `main` push triggers. Results are published to the OpenSSF API and uploaded as SARIF to GitHub code scanning.

The Scorecard badge is included in `README.md` only for public repositories where the workflow is synced.

## Best Practices Badge

Enrolled in OpenSSF Best Practices. The badge is emitted from the central release-model inventory using project `13514` with target level `passing`.

Do not add a passing OpenSSF Best Practices badge until the repository is actually enrolled and passing. Badges must be generated from `release-model/repositories.yml`; hand-written badges are rejected by the release-model audit.

## Security Policy

`SECURITY.md` describes supported versions, vulnerability reporting, coordinated disclosure, supported artifact scope, and the distinction between public repository content and private customer or infrastructure data.

## Branch Protection And Release Integrity

- `main` is the protected release branch.
- `develop` is the integration branch for normal work, Renovate, and shared-assets-lit PRs.
- `develop` to `main` promotion PRs require manual review.
- Renovate and shared-assets-lit PRs may auto-merge only into `develop` after required checks pass.
- Releases and publishing happen only from trusted `main` workflows after validation.
- Release evidence is generated for repositories with release artifacts.

## Dependency Automation

Dependency automation must target `develop` and must not bypass required checks. Coverage should include GitHub Actions, language dependencies, Ansible content, container base images, pre-commit hooks, and documentation tooling where applicable.

## Security Scanning

container build validation, Trivy image/filesystem scanning where configured, linting, and release evidence scan summaries.

## Exceptions

Repository-specific exceptions must be documented in this file or in `.lit/repository.yml`. Exceptions must not expose secrets, private infrastructure details, customer data, or credential-bearing examples.
