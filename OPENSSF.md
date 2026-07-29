# OpenSSF Readiness

This repository follows the Lightning IT shared OpenSSF readiness model generated from `lightning-it/shared-assets-lit`.

## Governing Decisions And Standards

The controlled internal architecture register contains the following governing
decisions. Internal knowledge-base locations are deliberately not published in
this public repository:

- Repository Topology and Shared Engineering Assets
- Branching, Review and Release Governance
- Transitional Self-Approval for Protected Deployments
- Mandatory CI Quality and Artifact Assurance
- Distributed Test Ownership and Central Heavy Execution
- ModuLix Lifecycle, Versioning and Release Evidence
- Repository and Secure SDLC Standard
- Technology Engineering Standards
- Quality Gates and Definition of Done
- OpenSSF and Software Supply Chain Assurance
- Compliance Gaps and Migration Roadmap

The public implementation is independently reviewable through this repository's
policy files, protected workflows, required checks, and release evidence.

## Repository

- Repository: `container-ee-wunder-devtools-ubi9`
- Visibility: `public`
- Type: `container_image`
- Release type: `semantic_release`
- Artifact type: `container_image`

## Scorecard

Enabled through `.github/workflows/openssf-scorecard.yml` with scheduled, manual, and `branch_protection_rule` triggers. The workflow executes a digest-pinned Scorecard container, retains SARIF as an artifact of the GitHub Actions workflow run, and uploads SARIF to GitHub code scanning where the repository supports it. Repository-run results are not published to the OpenSSF API because its workflow verifier does not currently accept the immutable container invocation.

The Scorecard badge is included in `README.md` only for public repositories where the workflow is synced. It can reflect OpenSSF's independent scan rather than a repository-published result.

## Best Practices Badge

Enrolled in OpenSSF Best Practices. The badge is emitted from the central release-model inventory using project `13514` with target level `passing`.

Do not add a passing OpenSSF Best Practices badge until the repository is actually enrolled and passing. Badges must be generated from the central `release-model/repositories.yml` inventory in `lightning-it/shared-assets-lit`; hand-written badges are rejected by the release-model audit.

## Security Policy

`SECURITY.md` describes supported versions, vulnerability reporting, coordinated disclosure, supported artifact scope, and the distinction between public repository content and private customer or infrastructure data.

## Branch Protection And Release Integrity

- `main` is the protected release branch.
- `develop` is the integration branch for normal work, Renovate, and shared-assets-lit PRs.
- Every non-trusted-automation pull request must have a completed GitHub Copilot review
  for its current head revision. Trusted automation classes are exempt only when
  their dedicated gate verifies the exact actor, branch, title, current head
  revision, and class-specific bounded change contract.
- `develop` to `main` promotion PRs are manual release gates and must never auto-merge.
- Integration and backmerge PRs may auto-merge only after required checks pass, all review conversations are resolved, and there are no conflicts.
- Releases and publishing happen only from trusted `main` workflows after validation.
- Release evidence is generated for repositories with release artifacts.

## Dependency Automation

Dependency automation must target `develop` and must not bypass required checks. Coverage should include GitHub Actions, language dependencies, Ansible content, container base images, pre-commit hooks, and documentation tooling where applicable.

## Security Scanning

container build validation, Trivy image/filesystem scanning where configured, linting, and release evidence scan summaries.

## Exceptions

Repository-specific exceptions must be documented in this file or in `.lit/repository.yml`. Exceptions must not expose secrets, private infrastructure details, customer data, or credential-bearing examples.
