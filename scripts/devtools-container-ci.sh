#!/usr/bin/env bash
set -euo pipefail

mode="${1:-all}"

github_repository_env="${GITHUB_REPOSITORY:-}"
repo_name="${github_repository_env##*/}"
if [ -z "$repo_name" ] || [ "$repo_name" = "$github_repository_env" ]; then
  repo_name="$(basename "${WUNDER_DEVTOOLS_HOST_WORKSPACE:-$PWD}")"
fi

github_repository="${github_repository_env:-lightning-it/${repo_name}}"
github_sha="${GITHUB_SHA:-$(git rev-parse HEAD 2>/dev/null || echo local)}"
short_sha="${github_sha:0:12}"
created="$(date -u +'%Y-%m-%dT%H:%M:%SZ')"
image="local/${repo_name}:ci"
actionlint_image="${ACTIONLINT_IMAGE:-docker.io/rhysd/actionlint:1.7.7}"
renovate_image="${RENOVATE_IMAGE:-docker.io/renovate/renovate:41.0.0}"
trivy_image="${TRIVY_IMAGE:-docker.io/aquasec/trivy:0.68.1}"
nested_workspace_args=()
nested_socket_args=()
trivy_ignore_args=()

set_nested_workspace_args() {
  if [ -f /.dockerenv ] && docker container inspect "$(hostname)" >/dev/null 2>&1; then
    nested_workspace_args=(--volumes-from "$(hostname)" -w "$PWD")
  else
    nested_workspace_args=(-v "${WUNDER_DEVTOOLS_HOST_WORKSPACE:-$PWD}:/repo:z" -w /repo)
  fi

  nested_socket_args=()
  if [ -n "${WUNDER_DEVTOOLS_DOCKER_SOCKET_HOST:-}" ]; then
    nested_socket_args=(-v "${WUNDER_DEVTOOLS_DOCKER_SOCKET_HOST}:/var/run/docker.sock")
  fi
}

detect_targetarch() {
  case "$(uname -m)" in
    x86_64) echo "amd64" ;;
    aarch64|arm64) echo "arm64" ;;
    *)
      echo "ERROR: unsupported build architecture: $(uname -m)" >&2
      exit 1
      ;;
  esac
}

require_docker() {
  if docker info >/dev/null 2>&1; then
    return 0
  fi

  if [ "${CI:-false}" = "true" ] || [ "${GITHUB_ACTIONS:-false}" = "true" ] \
    || [ "${WUNDER_DEVTOOLS_STRICT:-0}" = "1" ]; then
    echo "ERROR: Docker API is required for container CI parity checks." >&2
    exit 1
  fi

  echo "Skipping container CI parity checks because Docker API is unavailable locally." >&2
  echo "Set WUNDER_DEVTOOLS_STRICT=1 to fail instead of skipping." >&2
  exit 0
}

run_yaml_checks() {
  yamllint .
}

run_shellcheck() {
  if compgen -G "scripts/*.sh" >/dev/null; then
    shellcheck scripts/*.sh
  fi
}

run_actionlint() {
  require_docker
  set_nested_workspace_args
  docker run --rm \
    "${nested_workspace_args[@]}" \
    "$actionlint_image"
}

run_hadolint() {
  require_docker
  docker run --rm -i docker.io/hadolint/hadolint:v2.14.0 \
    hadolint --failure-threshold error --ignore DL3041 - < Dockerfile
}

run_container_build() {
  require_docker
  set_nested_workspace_args
  docker run --rm \
    "${nested_workspace_args[@]}" \
    "${nested_socket_args[@]}" \
    -e DOCKER_HOST=unix:///var/run/docker.sock \
    docker.io/library/docker:29-cli \
    docker buildx build --load \
    --build-arg COLLECTION_PROFILE=public \
    --build-arg "TARGETARCH=$(detect_targetarch)" \
    --label "org.opencontainers.image.source=https://github.com/${github_repository}" \
    --label "org.opencontainers.image.revision=${github_sha}" \
    --label "org.opencontainers.image.version=ci-${short_sha}" \
    --label "org.opencontainers.image.created=${created}" \
    --label "org.opencontainers.image.title=${repo_name}" \
    -t "$image" \
    -f Dockerfile \
    .
}

assert_label() {
  local label="$1"
  local expected="$2"
  local actual

  actual="$(docker image inspect "$image" --format "{{ index .Config.Labels \"${label}\" }}")"
  if [ "$actual" != "$expected" ]; then
    echo "ERROR: ${label} is '${actual}', expected '${expected}'." >&2
    exit 1
  fi
}

run_label_checks() {
  require_docker
  if ! docker image inspect "$image" >/dev/null 2>&1; then
    run_container_build
  fi

  assert_label "org.opencontainers.image.source" "https://github.com/${github_repository}"
  assert_label "org.opencontainers.image.revision" "${github_sha}"
  assert_label "org.opencontainers.image.version" "ci-${short_sha}"

  docker image inspect "$image" --format 'Built image {{ .Id }} with tags {{ .RepoTags }}'
}

run_contract_tests() {
  require_docker
  if ! docker image inspect "$image" >/dev/null 2>&1; then
    run_container_build
  fi

  case "$repo_name" in
    container-ee-wunder-devtools-ubi9)
      docker run --rm "$image" bash -lc '
        set -euo pipefail
        terraform -version
        tflint --version
        terraform-docs --version
        helm version --short
        ansible-lint --version
        pre-commit --version
        gh --version
        docker --version
        antsibull-changelog --version
      '
      ;;
    container-ee-wunder-ansible-ubi9)
      docker run --rm "$image" bash -lc '
        set -euo pipefail
        ansible --version
        ansible-galaxy --version
        ansible-runner --version
        terraform -version
        terragrunt --version
        helm version --short
        ansible-galaxy collection list -p /usr/share/ansible/collections
      '
      ;;
    container-ee-wunder-toolbox-ubi9)
      docker run --rm "$image" bash -lc '
        set -euo pipefail
        ansible-navigator --version
        ansible-doc --version
        helm version --short
        kustomize version
        vault --version
        podman --version
        command -v ansible-nav
        command -v ansible-nav-local
        rpm -q modulix-automation-runtime
      '
      ;;
    *)
      echo "No image-specific contract tests configured for ${repo_name}; skipping."
      ;;
  esac
}

run_vulnerability_scan() {
  require_docker
  if ! docker image inspect "$image" >/dev/null 2>&1; then
    run_container_build
  fi

  set_nested_workspace_args
  trivy_ignore_args=()
  if [ -f .trivyignore ]; then
    trivy_ignore_args=(--ignorefile .trivyignore)
  fi

  docker run --rm \
    "${nested_workspace_args[@]}" \
    "${nested_socket_args[@]}" \
    -e DOCKER_HOST=unix:///var/run/docker.sock \
    "$trivy_image" image \
      --scanners vuln \
      --ignore-unfixed \
      "${trivy_ignore_args[@]}" \
      --severity HIGH \
      --exit-code 0 \
      "$image"

  docker run --rm \
    "${nested_workspace_args[@]}" \
    "${nested_socket_args[@]}" \
    -e DOCKER_HOST=unix:///var/run/docker.sock \
    "$trivy_image" image \
      --scanners vuln \
      --ignore-unfixed \
      "${trivy_ignore_args[@]}" \
      --severity CRITICAL \
      --exit-code 1 \
      "$image"
}

run_renovate_config() {
  if [ ! -f renovate.json ] && [ ! -f renovate-container.json ]; then
    return 0
  fi

  require_docker
  set_nested_workspace_args
  docker run --rm -u 0:0 \
    "${nested_workspace_args[@]}" \
    "$renovate_image" renovate-config-validator
}

run_semantic_release_dry_run() {
  if [ ! -f .releaserc ]; then
    return 0
  fi

  require_docker
  set_nested_workspace_args

  if [ -z "${GITHUB_TOKEN:-${GH_TOKEN:-}}" ]; then
    if [ "${CI:-false}" = "true" ] || [ "${GITHUB_ACTIONS:-false}" = "true" ] \
      || [ "${WUNDER_DEVTOOLS_STRICT:-0}" = "1" ]; then
      echo "ERROR: GITHUB_TOKEN or GH_TOKEN is required for semantic-release dry run." >&2
      exit 1
    fi
    echo "Skipping semantic-release dry run because GITHUB_TOKEN/GH_TOKEN is unavailable locally." >&2
    echo "Set WUNDER_DEVTOOLS_STRICT=1 and export a token to enforce it." >&2
    return 0
  fi

  docker run --rm \
    "${nested_workspace_args[@]}" \
    -e GITHUB_TOKEN="${GITHUB_TOKEN:-${GH_TOKEN:-}}" \
    -e GH_TOKEN="${GH_TOKEN:-${GITHUB_TOKEN:-}}" \
    docker.io/library/node:24-bookworm \
    sh -lc 'npx --yes \
      --package semantic-release@25 \
      --package @semantic-release/commit-analyzer@13 \
      --package @semantic-release/github@12 \
      --package @semantic-release/release-notes-generator@14 \
      --package conventional-changelog-conventionalcommits@9 \
      semantic-release --dry-run --no-ci --branches main'
}

run_ci() {
  run_yaml_checks
  run_shellcheck
  run_actionlint
  run_hadolint
  run_container_build
  run_label_checks
  run_contract_tests
  run_vulnerability_scan
  run_renovate_config
}

case "$mode" in
  all)
    run_ci
    run_semantic_release_dry_run
    ;;
  ci)
    run_ci
    ;;
  semantic-release-dry-run)
    run_semantic_release_dry_run
    ;;
  *)
    echo "Usage: $0 [all|ci|semantic-release-dry-run]" >&2
    exit 2
    ;;
esac
