# ee-wunder-devtools-ubi9

Shared development tools container for local and CI workflows.

This image bundles a unified toolchain for infrastructure automation and Ansible
development. It is based on **Red Hat UBI 9** and includes:

- Ansible Core
- ansible-lint
- yamllint
- ShellCheck
- Terraform CLI
- TFLint
- terraform-docs
- Helm CLI
- COPR CLI (`copr-cli`)

Use it as a stable execution environment for:

- Local development
- `pre-commit` hooks
- CI pipelines
- Integration tests (e.g. against local Keycloak containers)

> Image: `quay.io/l-it/ee-wunder-devtools-ubi9:<tag>`

---

## Features

- Based on **UBI 9** (`registry.access.redhat.com/ubi9/ubi`)
- Preinstalled tooling:
  - `ansible-core`
  - `ansible-lint`
  - `yamllint`
  - `shellcheck`
  - `terraform`
  - `tflint`
  - `terraform-docs`
  - `helm`
  - `copr-cli`
- Non-root default user (`wunder`)
- Default working directory `/workspace`

---

## Usage

### Start an interactive shell

```bash
docker run --rm -it -v "$PWD":/workspace -w /workspace quay.io/l-it/ee-wunder-devtools-ubi9:main
```

### Run Ansible commands

```bash
docker run --rm -v "$PWD":/workspace -w /workspace quay.io/l-it/ee-wunder-devtools-ubi9:main ansible-lint
```

```bash
docker run --rm -v "$PWD":/workspace -w /workspace quay.io/l-it/ee-wunder-devtools-ubi9:main ansible-playbook -i inventories/dev/hosts.yml playbooks/site.yml
```

### Run Terraform tooling

```bash
docker run --rm -v "$PWD":/workspace -w /workspace quay.io/l-it/ee-wunder-devtools-ubi9:main terraform fmt -recursive
```

```bash
docker run --rm -v "$PWD":/workspace -w /workspace quay.io/l-it/ee-wunder-devtools-ubi9:main tflint --recursive
```

```bash
docker run --rm -v "$PWD":/workspace -w /workspace quay.io/l-it/ee-wunder-devtools-ubi9:main terraform-docs markdown table --output-file README.md --output-mode replace .
```

### Run Helm commands

Check Helm CLI:

```bash
docker run --rm -v "$PWD":/workspace -w /workspace quay.io/l-it/ee-wunder-devtools-ubi9:main helm version --short
```

Run against your local kubeconfig:

```bash
docker run --rm \
  -v "$PWD":/workspace -w /workspace \
  -v "$HOME/.kube:/home/wunder/.kube:Z" \
  -e KUBECONFIG=/home/wunder/.kube/config \
  quay.io/l-it/ee-wunder-devtools-ubi9:main helm list -A
```

---

## Example wrapper script

In your repositories you can add a small helper script, e.g. `scripts/wunder-devtools-ee.sh`:

```bash
#!/usr/bin/env bash
set -euo pipefail

IMAGE="quay.io/l-it/ee-wunder-devtools-ubi9:main"

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
`shellcheck`, `terraform`, `tflint`, `terraform-docs`, `helm`, and `copr-cli` in a consistent
environment.

### Configure COPR from the container

If your host does not have `copr-cli`, run COPR commands inside this devtools image:

```bash
podman run --rm -it \
  --userns keep-id \
  -v "$(git rev-parse --show-toplevel):/workspace:Z" -w /workspace \
  -v "$HOME/.config/copr:/home/wunder/.config/copr:ro,Z" \
  -e COPR_OWNER=litroc \
  -e COPR_PROJECT=modulix \
  -e COPR_PACKAGE=modulix-scripts \
  quay.io/l-it/ee-wunder-devtools-ubi9:latest \
  bash /workspace/packaging/rpm/configure-copr-scm.sh
```

---

## CI publishing

A typical GitHub Actions workflow builds and publishes the image to GHCR on every
push to `main` and for tags starting with `v`. The resulting image is available as:

```text
quay.io/l-it/ee-wunder-devtools-ubi9:<tag>
```
