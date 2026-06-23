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
  - `.github/workflows/renovate-guarded-automerge.yml`
  - `.github/workflows/semantic-release.yml`

## Branch and release model

- `develop` is the default development and integration branch.
- Feature, Renovate, and shared-assets sync PRs target `develop`.
- `main` is the stable production release branch.
- Promotion from `develop` to `main` happens only through a pull request.
- Merging `develop` into `main` is the container release trigger.
- Use merge commits for `develop` to `main` promotion PRs so branch ancestry remains clear.
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

## Dependency pinning

- Keep Dockerfile tool/runtime versions pinned (`ARG ..._VERSION=` or pinned image refs).
- For every change to pinned versions in managed files (workflows, scripts, container files), maintain Renovate in the same change (`renovate.json` package rules/custom managers, or the shared-assets-lit Renovate source).
- Validate Renovate config changes before commit (for example: `pre-commit run renovate-config-validate --files renovate.json`).
- Do not relax version pinning in managed container templates without an explicit decision in `shared-assets-lit`.

## Repo-specific overrides

- Some container repositories use repo-specific overrides from:
  - `shared-assets-lit/container/overrides/<repo>/...`
- If a file exists in an override path, it supersedes the baseline file from `shared-assets-lit/container/base`.
- For `.github/workflows/container-build-publish.yml`, always check for an override before changing downstream repo copies.
