# ee-wunder-devtools-ubi9

<!-- BEGIN LIT_SHARED_RELEASE_MODEL -->

## Release and Quality Model

This repository follows the Lightning IT shared release and quality model.

See [RELEASE.md](./RELEASE.md) for:

- branch and release flow
- required quality checks
- test matrix
- release evidence
- artifact publishing
- supported repository-specific release behavior

Repository classification: **Container Image**.
Required test profiles: `pre-commit, lint, container-build, container-smoke, trivy, fuzzing, release-validation`.
Publishing targets: `github-release, quay.io`.

## Supported and Tested Platforms

| Platform / Product |                  Status | Validation           |
| ------------------ | ----------------------: | -------------------- |
| ubuntu-latest      |               Supported | Container CI / Trivy |
| ubi9               | Tested where applicable | Container CI / Trivy |
| podman             | Tested where applicable | Container CI / Trivy |
| docker-buildx      | Tested where applicable | Container CI / Trivy |

<!-- END LIT_SHARED_RELEASE_MODEL -->

<!-- BEGIN LIT_QUALITY_BADGES -->

[![CI](https://github.com/lightning-it/container-ee-wunder-devtools-ubi9/actions/workflows/container-ci.yml/badge.svg?branch=develop)](https://github.com/lightning-it/container-ee-wunder-devtools-ubi9/actions/workflows/container-ci.yml)
[![Latest Release](https://img.shields.io/github/v/release/lightning-it/container-ee-wunder-devtools-ubi9?sort=semver)](https://github.com/lightning-it/container-ee-wunder-devtools-ubi9/releases/latest)
[![OpenSSF Scorecard](https://api.scorecard.dev/projects/github.com/lightning-it/container-ee-wunder-devtools-ubi9/badge)](https://scorecard.dev/viewer/?uri=github.com/lightning-it/container-ee-wunder-devtools-ubi9)
[![OpenSSF Best Practices](https://www.bestpractices.dev/projects/13514/badge)](https://www.bestpractices.dev/projects/13514)
[![Quay.io](https://img.shields.io/badge/Quay.io-image-blue?logo=quay&logoColor=white)](https://quay.io/repository/l-it/ee-wunder-devtools-ubi9)
[![Trivy](https://github.com/lightning-it/container-ee-wunder-devtools-ubi9/actions/workflows/container-trivy.yml/badge.svg?branch=develop)](https://github.com/lightning-it/container-ee-wunder-devtools-ubi9/actions/workflows/container-trivy.yml)
[![Container Build](https://github.com/lightning-it/container-ee-wunder-devtools-ubi9/actions/workflows/container-build.yml/badge.svg?branch=develop)](https://github.com/lightning-it/container-ee-wunder-devtools-ubi9/actions/workflows/container-build.yml)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](./LICENSE)

<!-- END LIT_QUALITY_BADGES -->

Shared development tools container for local and CI workflows.

This image bundles a unified toolchain for infrastructure automation and Ansible
development. It is based on **Red Hat UBI 9** and includes:

- Ansible Core
- ansible-lint
- antsibull-changelog
- yamllint
- ShellCheck
- actionlint
- uv for reproducible, hash-locked Python dependency refreshes
- Node.js, npm, and pnpm for repository-owned, lockfile-pinned validators
- automatic image-native Node.js `24.18.0` / npm `11.16.0` selection for
  repositories that declare `24.18.0` in `.node-version`
- Terraform CLI
- TFLint
- terraform-docs
- Helm CLI
- COPR CLI (`copr-cli`)
- RPM build tooling (`rpmspec`, `rpmbuild`)
- VM image tooling (`qemu-img`, `virt-customize`, `virt-sysprep`, `guestfish`)

Use it as a stable execution environment for:

- Local development
- `pre-commit` hooks
- CI pipelines
- Integration tests (e.g. against local Keycloak containers)

The host supplies only Git, the container engine, and the wrapper. Repository validation
commands run in this digest-pinned Devtools image and do not depend on host language runtimes.

The repository also provides a digest-pinned
[Dev Container and host acceptance matrix](docs/host-parity.md) for RHEL,
Ubuntu, and macOS pipeline-parity work.

> Current image: `quay.io/l-it/ee-wunder-devtools-ubi9:v1.12.0`

---

## Features

- Based on **UBI 9** (`registry.access.redhat.com/ubi9/ubi`)
- Preinstalled tooling:
  - `ansible-core`
  - `ansible-lint`
  - `antsibull-changelog`
  - `yamllint`
  - `shellcheck`
  - `actionlint`
  - `uv`
  - `node` / `npm` / `pnpm`
  - `terraform`
  - `tflint`
  - `terraform-docs`
  - `helm`
  - `copr-cli`
  - `rpmspec` / `rpmbuild`
  - `qemu-img`
  - `virt-customize` / `virt-sysprep`
  - `guestfish`
- Non-root default user (`wunder`)
- Default working directory `/workspace`

---

## Usage

### Start an interactive shell

```bash
docker run --rm -it -v "$PWD":/workspace -w /workspace quay.io/l-it/ee-wunder-devtools-ubi9:v1.12.0
```

### Run Ansible commands

```bash
docker run --rm -v "$PWD":/workspace -w /workspace quay.io/l-it/ee-wunder-devtools-ubi9:v1.12.0 ansible-lint
```

```bash
docker run --rm -v "$PWD":/workspace -w /workspace quay.io/l-it/ee-wunder-devtools-ubi9:v1.12.0 ansible-playbook -i <inventory.yml> <playbook.yml>
```

### Run Terraform tooling

```bash
docker run --rm -v "$PWD":/workspace -w /workspace quay.io/l-it/ee-wunder-devtools-ubi9:v1.12.0 terraform fmt -recursive
```

```bash
docker run --rm -v "$PWD":/workspace -w /workspace quay.io/l-it/ee-wunder-devtools-ubi9:v1.12.0 tflint --recursive
```

```bash
docker run --rm -v "$PWD":/workspace -w /workspace quay.io/l-it/ee-wunder-devtools-ubi9:v1.12.0 terraform-docs markdown table --output-file README.md --output-mode replace .
```

### Run Helm commands

Check Helm CLI:

```bash
docker run --rm -v "$PWD":/workspace -w /workspace quay.io/l-it/ee-wunder-devtools-ubi9:v1.12.0 helm version --short
```

Run against your local kubeconfig:

```bash
docker run --rm \
  -v "$PWD":/workspace -w /workspace \
  -v "$HOME/.kube:/home/wunder/.kube:Z" \
  -e KUBECONFIG=/home/wunder/.kube/config \
  quay.io/l-it/ee-wunder-devtools-ubi9:v1.12.0 helm list -A
```

---

## Example wrapper script

In your repositories you can add a small helper script, e.g. `scripts/wunder-devtools-ee.sh`:

```bash
#!/usr/bin/env bash
set -euo pipefail

IMAGE="quay.io/l-it/ee-wunder-devtools-ubi9:v1.12.0"

docker run --rm \
  --entrypoint "" \
  -v "$PWD":/workspace \
  -w /workspace \
  "$IMAGE" "$@"
```

Make it executable:

```bash
chmod +x scripts/wunder-devtools-ee.sh
```

Then use it in `pre-commit`, Makefiles or CI jobs to run `ansible-lint`, `yamllint`,
`shellcheck`, `actionlint`, `terraform`, `tflint`, `terraform-docs`, `helm`,
`copr-cli`, RPM tooling, and VM image tooling in a consistent environment.

### Configure COPR from the container

If your host does not have `copr-cli`, run COPR commands inside this devtools image:

```bash
podman run --rm -it \
  --userns keep-id \
  -v "$(git rev-parse --show-toplevel):/workspace:Z" -w /workspace \
  -v "$HOME/.config/copr:/home/wunder/.config/copr:ro,Z" \
  -e COPR_OWNER=litroc \
  -e COPR_PROJECT=modulix \
  -e COPR_PACKAGE=modulix-automation-runtime \
  quay.io/l-it/ee-wunder-devtools-ubi9:v1.12.0 \
  bash /workspace/packaging/rpm/configure-copr-scm.sh
```

---

## CI publishing

A typical GitHub Actions workflow builds and publishes the image to GHCR on every
push to `main` and for tags starting with `v`. The resulting image is available as:

```text
quay.io/l-it/ee-wunder-devtools-ubi9:<tag>
```

## Security

See [SECURITY.md](./SECURITY.md) for supported versions and vulnerability reporting.

## Contributing

See [CONTRIBUTING.md](./CONTRIBUTING.md) for contribution and review expectations.

## License

See [LICENSE](./LICENSE).

<!-- BEGIN LIT_RELEASE_QUALITY_MODEL -->

## Release and Quality Model

This repository follows the Lightning IT shared release and quality model.
The README shows the current supported and tested matrix.
Exact per-version validation proof is stored with each GitHub Release as `release-evidence.md` and `release-evidence.json`.
Releases are created from the protected `main` branch after a reviewed `develop -> main` release promotion.
Container releases validate build, smoke behavior, Trivy scanning, and Quay.io publishing where enabled.

See:

- [RELEASE.md](./RELEASE.md)
- [TESTING.md](./TESTING.md)
- [GitHub Releases](../../releases)

Repository classification: **Container Image**.
Required test profiles: `pre-commit, lint, container-build, container-smoke, trivy, release-validation`.
Publishing targets: `github-release, quay.io`.

<!-- END LIT_RELEASE_QUALITY_MODEL -->

<!-- BEGIN LIT_COMPATIBILITY_MATRIX -->

## Compatibility Matrix

| Image Version  | Base Image    | Runtime                 | Validation           |
| -------------- | ------------- | ----------------------- | -------------------- |
| Latest release | ubi9          | Podman / GitHub Actions | See release evidence |
| Latest release | podman        | Podman / GitHub Actions | See release evidence |
| Latest release | docker-buildx | Podman / GitHub Actions | See release evidence |

Validation proof for each released version is stored in the corresponding GitHub Release evidence.

<!-- END LIT_COMPATIBILITY_MATRIX -->

## Release Evidence

Every released version includes immutable release evidence attached to the corresponding GitHub Release.
The evidence records:

- tested matrix combinations
- GitHub Actions run links
- artifact references
- publish status
- security scan status

See [GitHub Releases](../../releases), [RELEASE.md](./RELEASE.md), and [TESTING.md](./TESTING.md) for the release process and validation model.
