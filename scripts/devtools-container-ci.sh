#!/usr/bin/env bash
set -euo pipefail

script_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)"
mode="${1:-all}"

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

require_digest_pinned_image() {
  local name="$1"
  local reference="$2"

  if [[ ! "$reference" =~ ^[^[:space:]@]+@sha256:[a-f0-9]{64}$ ]]; then
    echo "ERROR: ${name} must be an immutable image reference with a sha256 digest." >&2
    exit 1
  fi
}

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
target_arch="$(detect_targetarch)"
case "$target_arch" in
  amd64)
    actionlint_default="docker.io/rhysd/actionlint:1.7.12@sha256:9d36088643581e728c969f35141f88139fec77280b2be23c1f66f8e40e1025e7"
    renovate_default="docker.io/renovate/renovate:43.288.0@sha256:bcde7a061ab42d1ae6d4500769d80727e5694bb889dbcbf1005e9f4e741ab76d"
    trivy_default="docker.io/aquasec/trivy:0.74.0@sha256:ee940acbf1f58ebadb42d01434ce4609530bf1b52536afbd1eee66cd7123c5c9"
    hadolint_image="docker.io/hadolint/hadolint:v2.15.1@sha256:fdf19d026b54834f88c62774fdf2a61ff3b586a42632e5070674d41a796bfdf3"
    docker_cli_image="docker.io/library/docker:29-cli@sha256:e650b7a58d7f56be91d4f7be799196380a3bbc1bcbc41f1f4dff1b36ac309e1e"
    node_image="docker.io/library/node:24-bookworm@sha256:f6d02cf1353049cf3658e6ce9ec03c6877a6479495f122062d195e2279d01055"
    ;;
  arm64)
    actionlint_default="docker.io/rhysd/actionlint:1.7.12@sha256:33ffa3f1ad576165ea9c26f726884defdc411fb1fcb9ccc6a117b2f554ba1723"
    renovate_default="docker.io/renovate/renovate:43.288.0@sha256:63067f15fdb44df7a55a1e65e34df93c8c8dab930677d0a46de8086c6d5b0703"
    trivy_default="docker.io/aquasec/trivy:0.74.0@sha256:55ad20f8a239a3e95427e60b8aaea38788550c18a3f1772976bebf732e6ae166"
    hadolint_image="docker.io/hadolint/hadolint:v2.15.1@sha256:84179f01a1034d34ea470f1808f055f0a02195ba0e0038d097f8384ae878383f"
    docker_cli_image="docker.io/library/docker:29-cli@sha256:d7ee65bd10b7f794c6bba9ce66cf0ec83f4cb9a606f68b2a804b11ceb00d60cb"
    node_image="docker.io/library/node:24-bookworm@sha256:7e4b2953088599075c288871d109e23bc7a33384b96ca443a7cfb7b5c318b099"
    ;;
esac
actionlint_image="${ACTIONLINT_IMAGE:-$actionlint_default}"
renovate_image="${RENOVATE_IMAGE:-$renovate_default}"
trivy_image="${TRIVY_IMAGE:-$trivy_default}"
for image_name in actionlint renovate trivy hadolint docker-cli node; do
  case "$image_name" in
    actionlint) image_ref="$actionlint_image" ;;
    renovate) image_ref="$renovate_image" ;;
    trivy) image_ref="$trivy_image" ;;
    hadolint) image_ref="$hadolint_image" ;;
    docker-cli) image_ref="$docker_cli_image" ;;
    node) image_ref="$node_image" ;;
  esac
  require_digest_pinned_image "$image_name" "$image_ref"
done

workspace_host="${WUNDER_DEVTOOLS_HOST_WORKSPACE:-$(pwd -P)}"
readonly_workspace_args=(-v "${workspace_host}:/repo:ro" -w /repo)
nested_socket_args=()
nested_git_args=()
trivy_ignore_args=()
containerfile=""
container_build_context=""
container_inputs_loaded=false
validation_container_args=(
  --read-only
  --network none
  --cap-drop ALL
  --security-opt no-new-privileges=true
  --security-opt label=disable
  --pids-limit 128
  --tmpfs "/tmp:rw,noexec,nosuid,nodev,size=64m"
)
engine_container_args=(
  --read-only
  --cap-drop ALL
  --security-opt no-new-privileges=true
  --security-opt label=disable
  --pids-limit 256
  --tmpfs "/tmp:rw,noexec,nosuid,nodev,size=1g"
)

repository_metadata_value() {
  local key="$1"

  if ! command -v python3 >/dev/null 2>&1; then
    echo "ERROR: python3 is required to read .lit/repository.yml." >&2
    return 1
  fi
  if ! python3 -c 'import yaml' >/dev/null 2>&1; then
    echo "ERROR: the Python PyYAML module is required to read .lit/repository.yml." >&2
    return 1
  fi
  python3 - "$key" <<'PY'
import sys
from pathlib import Path

import yaml

key = sys.argv[1]
path = Path(".lit/repository.yml")
try:
    metadata = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
except (OSError, yaml.YAMLError) as exc:
    raise SystemExit(f"ERROR: unable to read {path}: {exc}") from exc
if not isinstance(metadata, dict):
    raise SystemExit(f"ERROR: {path} must contain a YAML mapping.")
value = metadata.get(key, "")
if value is None:
    value = ""
if not isinstance(value, str):
    raise SystemExit(f"ERROR: {key} in {path} must be a string.")
if any(ord(character) < 32 or ord(character) == 127 for character in value):
    raise SystemExit(f"ERROR: {key} in {path} contains control characters.")
print(value, end="")
PY
}

validate_container_input() {
  local kind="$1"
  local label="$2"
  local path="$3"
  local resolved workspace_root

  if [ -z "$path" ] || [[ "$path" =~ [[:cntrl:]] ]]; then
    echo "ERROR: configured ${label} must be a non-empty path without control characters." >&2
    exit 1
  fi
  case "$path" in
    /*)
      echo "ERROR: configured ${label} must be relative to the repository: ${path}" >&2
      exit 1
      ;;
    -*)
      echo "ERROR: configured ${label} must not begin with a hyphen: ${path}" >&2
      exit 1
      ;;
  esac
  case "/${path}/" in
    */../*)
      echo "ERROR: configured ${label} must stay within the repository: ${path}" >&2
      exit 1
      ;;
  esac

  command -v python3 >/dev/null 2>&1 || {
    echo "ERROR: python3 is required to validate ${label}." >&2
    exit 1
  }
  workspace_root="$(pwd -P)"
  if ! resolved="$(
    python3 - "$path" <<'PY'
import pathlib
import sys

try:
    print(pathlib.Path(sys.argv[1]).resolve(strict=True))
except (OSError, RuntimeError):
    raise SystemExit(1)
PY
  )"; then
    echo "ERROR: configured ${label} does not exist: ${path}" >&2
    exit 1
  fi
  case "$resolved" in
    "$workspace_root"|"$workspace_root"/*) ;;
    *)
      echo "ERROR: configured ${label} resolves outside the repository: ${path}" >&2
      exit 1
      ;;
  esac

  case "$kind" in
    file) [ -f "$resolved" ] || { echo "ERROR: configured ${label} is not a file: ${path}" >&2; exit 1; } ;;
    directory) [ -d "$resolved" ] || { echo "ERROR: configured ${label} is not a directory: ${path}" >&2; exit 1; } ;;
    *) echo "ERROR: unsupported container input kind: ${kind}" >&2; exit 1 ;;
  esac
}

load_container_inputs() {
  local metadata_containerfile=""
  local metadata_context=""

  if [ "$container_inputs_loaded" = true ]; then
    return 0
  fi
  if [ -f .lit/repository.yml ]; then
    if ! metadata_containerfile="$(repository_metadata_value containerfile)"; then
      echo "ERROR: unable to resolve configured containerfile." >&2
      exit 1
    fi
    if ! metadata_context="$(repository_metadata_value container_build_context)"; then
      echo "ERROR: unable to resolve configured container build context." >&2
      exit 1
    fi
  fi

  containerfile="${CONTAINERFILE:-$metadata_containerfile}"
  container_build_context="${CONTAINER_BUILD_CONTEXT:-$metadata_context}"
  containerfile="${containerfile:-Dockerfile}"
  container_build_context="${container_build_context:-.}"

  validate_container_input file containerfile "$containerfile"
  validate_container_input directory "container build context" "$container_build_context"
  container_inputs_loaded=true
}

set_nested_socket_args() {
  local socket_host="${WUNDER_DEVTOOLS_DOCKER_SOCKET_HOST:-}"
  nested_socket_args=()
  if [ -z "$socket_host" ] && [[ "${DOCKER_HOST:-}" == unix://* ]]; then
    socket_host="${DOCKER_HOST#unix://}"
  fi
  if [ -z "$socket_host" ] && [ -S "$HOME/.docker/run/docker.sock" ]; then
    socket_host="$HOME/.docker/run/docker.sock"
  fi
  if [ -z "$socket_host" ] && [ -S /var/run/docker.sock ]; then
    socket_host="/var/run/docker.sock"
  fi
  if [ -z "$socket_host" ]; then
    echo "ERROR: an explicit Docker-compatible socket is required for this operation." >&2
    exit 1
  fi
  nested_socket_args=(
    -v "${socket_host}:/var/run/docker.sock"
    -e DOCKER_HOST=unix:///var/run/docker.sock
  )
}

set_nested_git_args() {
  local host_gitdir="${WUNDER_DEVTOOLS_HOST_GIT_DIR:-}"
  local host_common="${WUNDER_DEVTOOLS_HOST_GIT_COMMON_DIR:-}"
  local gitdir_relative

  nested_git_args=()
  if [ -z "$host_gitdir" ] && [ -z "$host_common" ]; then
    if [ ! -f "${workspace_host}/.git" ]; then
      return 0
    fi
    host_gitdir="$(git -C "$workspace_host" rev-parse --absolute-git-dir)"
    host_common="$(
      git -C "$workspace_host" rev-parse --path-format=absolute --git-common-dir
    )"
  elif [ -z "$host_gitdir" ] || [ -z "$host_common" ]; then
    echo "ERROR: both linked-worktree host Git paths must be provided." >&2
    exit 1
  fi

  case "$host_gitdir" in
    /*) ;;
    *) echo "ERROR: linked-worktree host gitdir must be absolute." >&2; exit 1 ;;
  esac
  case "$host_common" in
    /*) ;;
    *) echo "ERROR: linked-worktree host commondir must be absolute." >&2; exit 1 ;;
  esac
  case "$host_gitdir" in *:*|*,*) echo "ERROR: unsafe host gitdir." >&2; exit 1 ;; esac
  case "$host_common" in *:*|*,*) echo "ERROR: unsafe host commondir." >&2; exit 1 ;; esac
  case "$host_gitdir" in
    "$host_common"/*) gitdir_relative="${host_gitdir#"$host_common"/}" ;;
    *)
      echo "ERROR: linked-worktree gitdir is outside its commondir." >&2
      exit 1
      ;;
  esac
  case "$gitdir_relative" in
    ""|/*|*:*|*,*|../*|*/../*|*/..)
      echo "ERROR: unsafe relative linked-worktree gitdir." >&2
      exit 1
      ;;
  esac

  if [ -n "${GIT_DIR:-}" ] && [ ! -d "$GIT_DIR" ]; then
    echo "ERROR: mounted linked-worktree gitdir is unavailable." >&2
    exit 1
  fi
  if [ -n "${GIT_COMMON_DIR:-}" ] && [ ! -d "$GIT_COMMON_DIR" ]; then
    echo "ERROR: mounted linked-worktree commondir is unavailable." >&2
    exit 1
  fi

  nested_git_args=(
    -v "${host_common}:/run/wunder-git/common:ro"
    -e "GIT_DIR=/run/wunder-git/common/${gitdir_relative}"
    -e GIT_COMMON_DIR=/run/wunder-git/common
    -e GIT_WORK_TREE=/repo
  )
}

require_docker() {
  if docker info >/dev/null 2>&1; then
    return 0
  fi

  echo "ERROR: Docker API is required for container CI parity checks." >&2
  exit 1
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
  local -a queue_validator_args=(--workflows-dir .github/workflows)
  if [ -f .github/workflows/security-release-finalize.yml ]; then
    queue_validator_args+=(--mlx90-workflows-dir .github/workflows)
  fi
  python3 "$script_dir/validate-actionlint-queue-extension.py" \
    "${queue_validator_args[@]}"
  require_docker
  # actionlint 1.7.12 predates GitHub's 2026-05-07 concurrency.queue release.
  # The exact stale diagnostic is ignored only after the validator above passes.
  docker run --rm \
    "${validation_container_args[@]}" \
    "${readonly_workspace_args[@]}" \
    "$actionlint_image" \
    -ignore 'unexpected key "queue" for "concurrency" section'
}

run_hadolint() {
  load_container_inputs
  require_docker
  docker run --rm -i \
    "${validation_container_args[@]}" \
    "$hadolint_image" \
    hadolint --failure-threshold error --ignore DL3041 - < "$containerfile"
}

run_container_build() {
  load_container_inputs
  require_docker
  set_nested_socket_args
  docker run --rm \
    "${engine_container_args[@]}" \
    --tmpfs "/root/.docker:rw,noexec,nosuid,nodev,size=64m" \
    "${readonly_workspace_args[@]}" \
    "${nested_socket_args[@]}" \
    "$docker_cli_image" \
    docker buildx build --load \
    --build-arg COLLECTION_PROFILE=public \
    --build-arg "TARGETARCH=${target_arch}" \
    --label "org.opencontainers.image.source=https://github.com/${github_repository}" \
    --label "org.opencontainers.image.revision=${github_sha}" \
    --label "org.opencontainers.image.version=ci-${short_sha}" \
    --label "org.opencontainers.image.created=${created}" \
    --label "org.opencontainers.image.title=${repo_name}" \
    -t "$image" \
    -f "$containerfile" \
    "$container_build_context"
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
      if [ -d tests ] \
        && find tests -type f -name 'test_*.py' -print -quit | grep -q .
      then
        python3 -m unittest discover -s tests -p 'test_*.py'
      fi
      # Copilot extracts and maps a signed native runtime from its cache.
      docker run --rm "${validation_container_args[@]}" \
        --tmpfs "/copilot-cache:rw,exec,nosuid,nodev,size=256m" \
        -e XDG_CACHE_HOME=/copilot-cache \
        "$image" bash -lc '
        set -euo pipefail
        export XDG_CACHE_HOME="${XDG_CACHE_HOME:-/tmp/.cache}"
        mkdir -p "$XDG_CACHE_HOME"
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
      docker run --rm "${validation_container_args[@]}" "$image" bash -lc '
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
      docker run --rm "${validation_container_args[@]}" "$image" bash -lc '
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

  # Ephemeral CI runners can reclaim completed BuildKit cache before Trivy
  # downloads its database. Local and shared runners retain their caches
  # unless the caller explicitly opts in.
  if [ "${WUNDER_DEVTOOLS_PRUNE_BUILDKIT_CACHE:-false}" = "true" ]; then
    docker builder prune --force
  fi

  set_nested_socket_args
  trivy_ignore_args=()
  if [ -f .trivyignore ]; then
    trivy_ignore_args=(--ignorefile .trivyignore)
  fi

  docker run --rm \
    "${engine_container_args[@]}" \
    --mount "type=volume,destination=/var/cache/trivy" \
    --env TMPDIR=/var/cache/trivy \
    "${readonly_workspace_args[@]}" \
    "${nested_socket_args[@]}" \
    "$trivy_image" image \
      --cache-dir /var/cache/trivy \
      --scanners vuln \
      --ignore-unfixed \
      ${trivy_ignore_args[@]+"${trivy_ignore_args[@]}"} \
      --severity HIGH \
      --exit-code 0 \
      "$image"

  docker run --rm \
    "${engine_container_args[@]}" \
    --mount "type=volume,destination=/var/cache/trivy" \
    --env TMPDIR=/var/cache/trivy \
    "${readonly_workspace_args[@]}" \
    "${nested_socket_args[@]}" \
    "$trivy_image" image \
      --cache-dir /var/cache/trivy \
      --scanners vuln \
      --ignore-unfixed \
      ${trivy_ignore_args[@]+"${trivy_ignore_args[@]}"} \
      --severity CRITICAL \
      --exit-code 1 \
      "$image"
}

run_renovate_config() {
  if [ ! -f renovate.json ] && [ ! -f renovate-container.json ]; then
    return 0
  fi

  require_docker
  docker run --rm \
    "${validation_container_args[@]}" \
    "${readonly_workspace_args[@]}" \
    "$renovate_image" renovate-config-validator
}

run_semantic_release_dry_run() {
  if [ ! -f .releaserc ]; then
    echo "ERROR: .releaserc is required for semantic-release validation." >&2
    exit 1
  fi

  require_docker
  set_nested_git_args

  docker run --rm \
    --read-only \
    --cap-drop ALL \
    --security-opt no-new-privileges=true \
    --security-opt label=disable \
    --pids-limit 256 \
    --tmpfs "/tmp:rw,noexec,nosuid,nodev,size=256m" \
    --tmpfs "/root:rw,nosuid,nodev,size=1g" \
    "${readonly_workspace_args[@]}" \
    "${nested_git_args[@]}" \
    "$node_image" \
    sh -lc 'set -eu
      git config --global --add safe.directory /repo
      git config --global --add safe.directory /repo/.git
      if [ -n "${GIT_DIR:-}" ]; then
        git bundle create /tmp/repository.bundle --all
        unset GIT_DIR GIT_COMMON_DIR GIT_WORK_TREE
        git clone /tmp/repository.bundle /tmp/release-check
      else
        git clone --no-hardlinks /repo /tmp/release-check
      fi
      git init --bare /tmp/release-origin.git
      cd /tmp/release-check
      git checkout -B main HEAD
      git remote set-url origin file:///tmp/release-origin.git
      git push --force origin main
      git --git-dir=/tmp/release-origin.git symbolic-ref HEAD refs/heads/main
      public_remote=https://github.com/lightning-it/release-dry-run.git
      git remote set-url origin "$public_remote"
      git config protocol.file.allow always
      git config url.file:///tmp/release-origin.git.insteadOf "$public_remote"
      cat >/tmp/github-api.mjs <<"JS"
import http from "node:http";
import fs from "node:fs";
const repository = "lightning-it/release-dry-run";
const server = http.createServer((request, response) => {
  if (request.method === "GET" && request.url === `/repos/${repository}`) {
    response.writeHead(200, {"content-type": "application/json"});
    response.end(JSON.stringify({
      clone_url: `https://github.com/${repository}.git`,
      permissions: {push: true},
    }));
    return;
  }
  response.writeHead(404, {"content-type": "application/json"});
  response.end(JSON.stringify({message: "Not Found"}));
});
server.listen(0, "127.0.0.1", () => {
  fs.writeFileSync("/tmp/github-api-port", String(server.address().port));
});
JS
      node /tmp/github-api.mjs &
      api_pid=$!
      trap "kill $api_pid" EXIT INT TERM
      attempt=0
      while [ ! -s /tmp/github-api-port ]; do
        attempt=$((attempt + 1))
        if [ "$attempt" -gt 100 ]; then
          echo "ERROR: local GitHub API stub did not start." >&2
          exit 1
        fi
        sleep 0.1
      done
      github_api_url="http://127.0.0.1:$(cat /tmp/github-api-port)"
      GITHUB_ACTION=true \
      GITHUB_API_URL="$github_api_url" \
      GH_TOKEN=local-api-stub-placeholder \
      npx --yes \
      --package semantic-release@25 \
      --package @semantic-release/commit-analyzer@13 \
      --package @semantic-release/github@12 \
      --package @semantic-release/release-notes-generator@14 \
      --package conventional-changelog-conventionalcommits@9 \
      --call="semantic_release_path=\$(command -v semantic-release); node \"\$(readlink -f \"\$semantic_release_path\")\" --dry-run --no-ci"'
}

run_ci() {
  load_container_inputs
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
