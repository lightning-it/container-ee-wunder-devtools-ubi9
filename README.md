# container-wunder-devtools-ee

Shared development tools container for local and CI workflows.

This image bundles a unified toolchain for infrastructure automation and Ansible
development. It is based on **Red Hat UBI 9** and includes:

- Ansible Core
- ansible-lint
- yamllint
- Terraform CLI
- TFLint
- terraform-docs

Use it as a stable execution environment for:

- Local development
- `pre-commit` hooks
- CI pipelines
- Integration tests (e.g. against local Keycloak containers)

> Image: `quay.io/l-it/container-wunder-devtools-ee:<tag>`

---

## Features

- Based on **UBI 9** (`registry.access.redhat.com/ubi9/ubi`)
- Preinstalled tooling:
  - `ansible-core`
  - `ansible-lint`
  - `yamllint`
  - `terraform`
  - `tflint`
  - `terraform-docs`
- Non-root default user (`wunder`)
- Default working directory `/workspace`

---

## Usage

### Start an interactive shell

```bash
docker run --rm -it -v "$PWD":/workspace -w /workspace quay.io/l-it/container-wunder-devtools-ee:main
```

### Run Ansible commands

```bash
docker run --rm -v "$PWD":/workspace -w /workspace quay.io/l-it/container-wunder-devtools-ee:main ansible-lint
```

```bash
docker run --rm -v "$PWD":/workspace -w /workspace quay.io/l-it/container-wunder-devtools-ee:main ansible-playbook -i inventories/dev/hosts.yml playbooks/site.yml
```

### Run Terraform tooling

```bash
docker run --rm -v "$PWD":/workspace -w /workspace quay.io/l-it/container-wunder-devtools-ee:main terraform fmt -recursive
```

```bash
docker run --rm -v "$PWD":/workspace -w /workspace quay.io/l-it/container-wunder-devtools-ee:main tflint --recursive
```

```bash
docker run --rm -v "$PWD":/workspace -w /workspace quay.io/l-it/container-wunder-devtools-ee:main terraform-docs markdown table --output-file README.md --output-mode replace .
```

---

## Example wrapper script

In your repositories you can add a small helper script, e.g. `scripts/wunder-devtools-ee.sh`:

```bash
#!/usr/bin/env bash
set -euo pipefail

IMAGE="quay.io/l-it/container-wunder-devtools-ee:main"

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
`terraform`, `tflint` and `terraform-docs` in a consistent environment.

---

## CI publishing

A typical GitHub Actions workflow builds and publishes the image to GHCR on every
push to `main` and for tags starting with `v`. The resulting image is available as:

```text
quay.io/l-it/container-wunder-devtools-ee:<tag>
```
