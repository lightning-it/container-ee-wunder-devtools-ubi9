# AGENT.md

## Shared-assets ownership

- This repository receives centrally managed baseline files from `lightning-it/shared-assets`.
- Do not hand-edit shared-managed files in downstream container repositories unless the same change is made in `shared-assets`.
- For container CI changes, treat `shared-assets` as source of truth first.

## Managed files

- Managed default files from `shared-assets/default`:
  - `LICENSE`
  - `CODE_OF_CONDUCT.md`
  - `scripts/wunder-devtools-ee.sh`
- Managed container baseline files from `shared-assets/container/base`:
  - `AGENT.md`
  - `.gitignore`
  - `.pre-commit-config.yaml`
  - `.releaserc`
  - `.yamllint`
  - `CONTRIBUTING.md`
  - `.github/workflows/container-build-publish.yml`
  - `.github/workflows/semantic-release.yml`

## Dependency pinning

- Keep Dockerfile tool/runtime versions pinned (`ARG ..._VERSION=` or pinned image refs).
- If you add or rename pinned versions, update `renovate.json` (or custom managers) in the same change.
- Do not relax version pinning in managed container templates without an explicit decision in `shared-assets`.

## Repo-specific overrides

- Some container repositories use repo-specific overrides from:
  - `shared-assets/container/overrides/<repo>/...`
- If a file exists in an override path, it supersedes the baseline file from `shared-assets/container/base`.
- For `.github/workflows/container-build-publish.yml`, always check for an override before changing downstream repo copies.
