# ee-wunder-devtools-ubi9

<!-- BEGIN LIT_QUALITY_BADGES -->

[![CI](https://github.com/lightning-it/container-ee-wunder-devtools-ubi9/actions/workflows/container-ci.yml/badge.svg?branch=develop)](https://github.com/lightning-it/container-ee-wunder-devtools-ubi9/actions/workflows/container-ci.yml)
[![Latest Release](https://img.shields.io/github/v/release/lightning-it/container-ee-wunder-devtools-ubi9?sort=semver)](https://github.com/lightning-it/container-ee-wunder-devtools-ubi9/releases/latest)
[![OpenSSF Scorecard](https://api.scorecard.dev/projects/github.com/lightning-it/container-ee-wunder-devtools-ubi9/badge)](https://scorecard.dev/viewer/?uri=github.com/lightning-it/container-ee-wunder-devtools-ubi9)
[![Trivy](https://github.com/lightning-it/container-ee-wunder-devtools-ubi9/actions/workflows/container-trivy.yml/badge.svg?branch=develop)](https://github.com/lightning-it/container-ee-wunder-devtools-ubi9/actions/workflows/container-trivy.yml)
[![Container Build](https://github.com/lightning-it/container-ee-wunder-devtools-ubi9/actions/workflows/container-build.yml/badge.svg?branch=develop)](https://github.com/lightning-it/container-ee-wunder-devtools-ubi9/actions/workflows/container-build.yml)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](./LICENSE)

<!-- END LIT_QUALITY_BADGES -->

<!-- BEGIN LIT_COMPATIBILITY_MATRIX -->

## Compatibility Matrix

| Image Version | Image | Base Platform | Runtime | Test Type | Validation |
|---|---|---|---|---|---|
| Current release | quay.io/l-it/ee-wunder-devtools-ubi9 | ubi9 | ubi9, podman, docker-buildx | Build / Smoke / Trivy | See GitHub Release evidence |
| Current release | quay.io/l-it/ee-wunder-devtools-ubi9 | podman | ubi9, podman, docker-buildx | Build / Smoke / Trivy | See GitHub Release evidence |
| Current release | quay.io/l-it/ee-wunder-devtools-ubi9 | docker-buildx | ubi9, podman, docker-buildx | Build / Smoke / Trivy | See GitHub Release evidence |

Validation proof for each released version is stored in the corresponding GitHub Release evidence.

<!-- END LIT_COMPATIBILITY_MATRIX -->

<!-- BEGIN LIT_RELEASE_QUALITY_MODEL -->

## Release and Quality Model

This repository follows the Lightning IT shared release and quality model.
The README shows the current supported and tested matrix.
Exact per-version proof is stored with every GitHub Release as `release-evidence.md` and `release-evidence.json`.

See:

- [RELEASE.md](./RELEASE.md)
- [TESTING.md](./TESTING.md)
- [GitHub Releases](../../releases)

Repository classification: **Container Image**.
Required test profiles: `pre-commit, lint, container-build, container-smoke, trivy, release-validation`.
Publishing targets: `github-release, quay.io`.

Release evidence records the exact GitHub Actions run, validated matrix rows, built artifacts, publish result, and security status for each release.

<!-- END LIT_RELEASE_QUALITY_MODEL -->


Shared development tools container for local and CI workflows.

This image bundles a unified toolchain for infrastructure automation and Ansible
development. It is based on **Red Hat UBI 9** and includes:

- Ansible Core
- ansible-lint
- antsibull-changelog
- yamllint
- ShellCheck
- actionlint
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

> Current image: `quay.io/l-it/ee-wunder-devtools-ubi9:v1.9.2`

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
docker run --rm -it -v "$PWD":/workspace -w /workspace quay.io/l-it/ee-wunder-devtools-ubi9:v1.9.2
```

### Run Ansible commands

```bash
docker run --rm -v "$PWD":/workspace -w /workspace quay.io/l-it/ee-wunder-devtools-ubi9:v1.9.2 ansible-lint
```

```bash
docker run --rm -v "$PWD":/workspace -w /workspace quay.io/l-it/ee-wunder-devtools-ubi9:v1.9.2 ansible-playbook -i <inventory.yml> <playbook.yml>
```

### Run Terraform tooling

```bash
docker run --rm -v "$PWD":/workspace -w /workspace quay.io/l-it/ee-wunder-devtools-ubi9:v1.9.2 terraform fmt -recursive
```

```bash
docker run --rm -v "$PWD":/workspace -w /workspace quay.io/l-it/ee-wunder-devtools-ubi9:v1.9.2 tflint --recursive
```

```bash
docker run --rm -v "$PWD":/workspace -w /workspace quay.io/l-it/ee-wunder-devtools-ubi9:v1.9.2 terraform-docs markdown table --output-file README.md --output-mode replace .
```

### Run Helm commands

Check Helm CLI:

```bash
docker run --rm -v "$PWD":/workspace -w /workspace quay.io/l-it/ee-wunder-devtools-ubi9:v1.9.2 helm version --short
```

Run against your local kubeconfig:

```bash
docker run --rm \
  -v "$PWD":/workspace -w /workspace \
  -v "$HOME/.kube:/home/wunder/.kube:Z" \
  -e KUBECONFIG=/home/wunder/.kube/config \
  quay.io/l-it/ee-wunder-devtools-ubi9:v1.9.2 helm list -A
```

---

## Example wrapper script

In your repositories you can add a small helper script, e.g. `scripts/wunder-devtools-ee.sh`:

```bash
#!/usr/bin/env bash
set -euo pipefail

IMAGE="quay.io/l-it/ee-wunder-devtools-ubi9:v1.9.2"

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
  quay.io/l-it/ee-wunder-devtools-ubi9:v1.9.2 \
  bash /workspace/packaging/rpm/configure-copr-scm.sh
```

---

## CI publishing

A typical GitHub Actions workflow builds and publishes the image to GHCR on every
push to `main` and for tags starting with `v`. The resulting image is available as:

```text
quay.io/l-it/ee-wunder-devtools-ubi9:<tag>
```
