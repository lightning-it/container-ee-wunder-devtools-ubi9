# AGENTS.md

## Shared-assets ownership

- This repository receives centrally managed baseline files from `lightning-it/shared-assets-lit`.
- Do not hand-edit shared-managed files in downstream container repositories unless the same change is made in `shared-assets-lit`.
- For container CI changes, treat `shared-assets-lit` as source of truth first.

## Managed files

- Managed default files from `shared-assets-lit/default`:
  - `LICENSE`
  - `CODE_OF_CONDUCT.md`
  - `scripts/wunder-devtools-ee.sh`
- Managed container baseline files from `shared-assets-lit/container/base`:
  - `AGENTS.md`
  - `.gitignore`
  - `.pre-commit-config.yaml`
  - `.releaserc`
  - `.yamllint`
  - `CONTRIBUTING.md`
  - `.github/workflows/container-ci.yml`
  - `.github/workflows/container-build-publish.yml`
  - `.github/workflows/promote-develop-to-main.yml`
  - `.github/workflows/sync-main-to-develop.yml`
  - `.github/workflows/renovate-guarded-automerge.yml`
  - `.github/workflows/semantic-release.yml`
  - `scripts/devtools-container-ci.sh`
  - `scripts/devtools-container-release-verify.sh`
  - `scripts/container-download-verified.sh`
  - `scripts/ee-entrypoint.sh`
  - `scripts/install-galaxy-content.sh`

## Branch and release model

- `develop` is the default development and integration branch.
- Feature, Renovate, and shared-assets sync PRs target `develop`.
- `main` is the stable production release branch.
- Promotion from `develop` to `main` happens only through a pull request.
- Merging `develop` into `main` is the container release trigger.
- Use merge commits for `develop` to `main` promotion PRs so branch ancestry remains clear.
- After `main` changes, the shared `sync-main-to-develop` workflow must open a back-sync PR from `main` to `develop` so
  the next promotion PR can be opened without branch drift.
- Repository settings, default branches, branch protection, and workflow permissions belong in `github-management-lit`.

## Semantic release and container publishing

- Container repositories use `semantic-release` on `main` for version calculation, Git tag creation, GitHub Release
  creation, and release notes.
- Do not use `@semantic-release/changelog`, `@semantic-release/git`, or committed `CHANGELOG.md` for container
  repositories unless a repository has an explicit, documented exception.
- The container publish workflow must build from the exact semantic-release tag.
- Released images must publish immutable release-version and commit-SHA tags plus the repository's moving production
  tag, usually `latest`.
- Released images must include OCI labels for source repository, revision, version, creation time, title/name, and any
  repo-specific description/license metadata already in use.
- Release builds must publish SBOM and maximum provenance attestations through Buildx.
- Release images must be signed by digest with keyless Sigstore/Cosign using GitHub OIDC.
- Release verification must inspect all expected tags, compare them to the pushed digest, verify the Cosign identity for
  the repository workflow/tag ref, and record the digest in the workflow summary.
- PR CI and local pre-commit must run the shared container CI parity script through the devtools container. Add new PR
  checks there first so local validation and GitHub validation stay aligned.
- Container vulnerability scans fail on `CRITICAL` findings and report `HIGH` findings without failing unless a stricter
  policy is deliberately added in `shared-assets-lit`.
- Dockerfiles must not download executable tools without checksum or signature verification. Use the shared
  `scripts/container-download-verified.sh` helper when possible.
- Larger entrypoints and repeated build helpers should be tracked scripts, not embedded heredocs, so shell linting and
  shared review rules can cover them.
- Non-secret ARG names must avoid secret-looking words such as `AUTH`, `TOKEN`, or `PASSWORD` unless the ARG really is a
  secret. Real secrets must use BuildKit secrets or GitHub secrets and must not persist in image layers.

## Dependency pinning

- Keep Dockerfile tool/runtime versions pinned (`ARG ..._VERSION=` or pinned image refs).
- For every change to pinned versions in managed files (workflows, scripts, container files), maintain Renovate in the same change (`renovate.json` package rules/custom managers, or the shared-assets-lit Renovate source).
- Validate Renovate config changes before commit (for example: `pre-commit run renovate-config-validate --files renovate.json`).
- Do not relax version pinning in managed container templates without an explicit decision in `shared-assets-lit`.
- Pin third-party GitHub Actions to full-length commit SHAs in shared workflow templates. Keep the human-readable version
  in a YAML comment and ensure Renovate can maintain the pin.
- Pin helper container images used by validation scripts; do not use `latest` for CI linters, scanners, or release
  tooling.

## Repo-specific overrides

- Some container repositories use repo-specific overrides from:
  - `shared-assets-lit/container/overrides/<repo>/...`
- If a file exists in an override path, it supersedes the baseline file from `shared-assets-lit/container/base`.
- For `.github/workflows/container-build-publish.yml`, always check for an override before changing downstream repo copies.
