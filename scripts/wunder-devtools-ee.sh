#!/usr/bin/env bash
set -euo pipefail

IMAGE="quay.io/l-it/ee-wunder-devtools-ubi9:v1.9.2@sha256:58d5d45f7ea7405394edb00d4a77bf3e5d770532377fba6d80e8f641d27576b0"
CONTAINER_HOME="${CONTAINER_HOME:-/tmp/wunder}"
WORKSPACE_MODE="${WUNDER_DEVTOOLS_WORKSPACE_MODE:-ro}"
RUN_AS_HOST_UID_POLICY="${WUNDER_DEVTOOLS_RUN_AS_HOST_UID:-0}"
NETWORK_MODE="${WUNDER_DEVTOOLS_NETWORK:-none}"
SOCKET_POLICY="${WUNDER_DEVTOOLS_DOCKER_SOCKET:-disabled}"
SOURCE_ROOT_POLICY="${WUNDER_DEVTOOLS_MOUNT_SOURCE_ROOT:-disabled}"
CAPABILITY_POLICY="${WUNDER_DEVTOOLS_CAP_ADD:-}"
VAGRANT_SSH_POLICY="${WUNDER_DEVTOOLS_FORWARD_VAGRANT_SSH:-disabled}"
case "$WORKSPACE_MODE" in ro|rw) ;; *) echo "Error: unsupported workspace mode: $WORKSPACE_MODE" >&2; exit 1 ;; esac
case "$RUN_AS_HOST_UID_POLICY" in 0|1) ;; *) echo "Error: unsupported host UID policy: $RUN_AS_HOST_UID_POLICY" >&2; exit 1 ;; esac
if [ "$RUN_AS_HOST_UID_POLICY" = "1" ] && [ "$WORKSPACE_MODE" != rw ]; then
  echo "Error: host UID mapping requires a read-write workspace" >&2
  exit 1
fi
case "$SOCKET_POLICY" in disabled|required|auto) ;; *) echo "Error: unsupported socket policy: $SOCKET_POLICY" >&2; exit 1 ;; esac
case "$SOURCE_ROOT_POLICY" in disabled|enabled) ;; *) echo "Error: unsupported source-root policy: $SOURCE_ROOT_POLICY" >&2; exit 1 ;; esac
case "$CAPABILITY_POLICY" in ""|CHOWN,FOWNER|CHOWN,DAC_OVERRIDE,FOWNER) ;; *) echo "Error: unsupported capability policy: $CAPABILITY_POLICY" >&2; exit 1 ;; esac
case "$VAGRANT_SSH_POLICY" in disabled|enabled) ;; *) echo "Error: unsupported Vagrant SSH forwarding policy: $VAGRANT_SSH_POLICY" >&2; exit 1 ;; esac
case "$CONTAINER_HOME" in
  /*) ;;
  *) echo "Error: CONTAINER_HOME must be an absolute container path" >&2; exit 1 ;;
esac
case "$CONTAINER_HOME" in
  /|/tmp|/run|/workspace|*:*|*,*|*/../*|*/..|*/./*|*/.)
    echo "Error: unsafe CONTAINER_HOME: $CONTAINER_HOME" >&2
    exit 1
    ;;
esac

WORKSPACE_MOUNT="${PWD}:/workspace:${WORKSPACE_MODE}"
# Never bind a host home directory here. A fresh tmpfs prevents one invocation
# or repository from supplying Ansible plugins/configuration to a later run.
# Molecule stages executable shims below HOME, so make exec explicit while
# retaining nosuid/nodev for identical Docker and Podman behavior.
HOME_TMPFS_MOUNT="${CONTAINER_HOME}:rw,exec,nosuid,nodev,size=1g,mode=1777"
DOCKER_ARGS=(
  -w /workspace
  -e HOME="${CONTAINER_HOME}"
  --read-only
  --network "$NETWORK_MODE"
  --cap-drop ALL
  --security-opt no-new-privileges=true
  --pids-limit 1024
  --tmpfs "/tmp:rw,nosuid,nodev,size=2g"
  --tmpfs "/run:rw,nosuid,nodev,size=256m"
  --tmpfs "$HOME_TMPFS_MOUNT"
)

fail_closed() {
  local msg="$1"
  echo "Error: ${msg}" >&2
  exit 1
}

sanitize_docker_host_env() {
  if [[ "${DOCKER_HOST:-}" == unix://* ]]; then
    host_sock="${DOCKER_HOST#unix://}"
    if [ ! -S "$host_sock" ]; then
      unset DOCKER_HOST
    fi
  fi
}

docker_usable() {
  command -v docker >/dev/null 2>&1 || return 1
  sanitize_docker_host_env
  docker info >/dev/null 2>&1
}

podman_usable() {
  command -v podman >/dev/null 2>&1 || return 1
  podman info >/dev/null 2>&1
}

CONTAINER_BIN="${WUNDER_CONTAINER_ENGINE:-}"
if [ -z "$CONTAINER_BIN" ]; then
  if docker_usable; then
    CONTAINER_BIN="docker"
  elif podman_usable; then
    CONTAINER_BIN="podman"
  else
    fail_closed "no usable container engine found (docker/podman not running or unreachable)"
  fi
fi

case "$CONTAINER_BIN" in
  podman|docker) ;;
  *)
    fail_closed "unsupported engine '$CONTAINER_BIN' (use podman|docker)"
    ;;
esac

if [ "${WUNDER_DEVTOOLS_PRIVILEGED:-0}" = "1" ]; then
  DOCKER_ARGS+=(--privileged)
elif [ "$CAPABILITY_POLICY" = "CHOWN,FOWNER" ]; then
  DOCKER_ARGS+=(--cap-add CHOWN --cap-add FOWNER)
elif [ "$CAPABILITY_POLICY" = "CHOWN,DAC_OVERRIDE,FOWNER" ]; then
  DOCKER_ARGS+=(--cap-add CHOWN --cap-add DAC_OVERRIDE --cap-add FOWNER)
fi

if [ "$CONTAINER_BIN" = "podman" ] && [ "$(uname -s)" = "Linux" ]; then
  WORKSPACE_MOUNT="${WORKSPACE_MOUNT},z"
fi

DOCKER_ARGS+=(-v "$WORKSPACE_MOUNT")

WORKSPACE_REAL="$(pwd -P)"
DOCKER_ARGS+=(-e "WUNDER_DEVTOOLS_HOST_WORKSPACE=${WORKSPACE_REAL}")

configure_linked_worktree_git_mounts() {
  local git_file="${WORKSPACE_REAL}/.git"
  local gitdir_raw gitdir_host common_raw common_host reported_gitdir reported_common
  local gitdir_mount common_mount
  local -a git_file_lines=() common_file_lines=()

  [ -f "$git_file" ] || return 0
  mapfile -t git_file_lines <"$git_file"
  if [ "${#git_file_lines[@]}" -ne 1 ]; then
    fail_closed "linked-worktree .git must contain exactly one gitdir line"
  fi
  gitdir_raw="${git_file_lines[0]}"
  case "$gitdir_raw" in
    "gitdir: "*) gitdir_raw="${gitdir_raw#gitdir: }" ;;
    *) fail_closed "linked-worktree .git has an invalid gitdir declaration" ;;
  esac
  case "$gitdir_raw" in
    ""|*:*|*,*) fail_closed "linked-worktree gitdir contains unsafe mount characters" ;;
  esac
  if [[ "$gitdir_raw" = /* ]]; then
    gitdir_host="$gitdir_raw"
  else
    gitdir_host="${WORKSPACE_REAL}/${gitdir_raw}"
  fi
  if [ ! -d "$gitdir_host" ]; then
    fail_closed "linked-worktree gitdir is not a directory"
  fi
  gitdir_host="$(cd "$gitdir_host" && pwd -P)"
  if [ ! -f "${gitdir_host}/HEAD" ] || [ ! -f "${gitdir_host}/commondir" ]; then
    fail_closed "linked-worktree gitdir is missing required metadata"
  fi

  mapfile -t common_file_lines <"${gitdir_host}/commondir"
  if [ "${#common_file_lines[@]}" -ne 1 ]; then
    fail_closed "linked-worktree commondir must contain exactly one path"
  fi
  common_raw="${common_file_lines[0]}"
  case "$common_raw" in
    ""|*:*|*,*) fail_closed "linked-worktree commondir contains unsafe mount characters" ;;
  esac
  if [[ "$common_raw" = /* ]]; then
    common_host="$common_raw"
  else
    common_host="${gitdir_host}/${common_raw}"
  fi
  if [ ! -d "$common_host" ]; then
    fail_closed "linked-worktree common Git directory is not a directory"
  fi
  common_host="$(cd "$common_host" && pwd -P)"
  case "$gitdir_host" in *:*|*,*) fail_closed "resolved gitdir is unsafe to mount" ;; esac
  case "$common_host" in *:*|*,*) fail_closed "resolved commondir is unsafe to mount" ;; esac

  if ! reported_gitdir="$(git -C "$WORKSPACE_REAL" rev-parse --absolute-git-dir)" \
    || ! reported_common="$(git -C "$WORKSPACE_REAL" rev-parse --path-format=absolute --git-common-dir)";
  then
    fail_closed "Git rejected the linked-worktree metadata"
  fi
  reported_gitdir="$(cd "$reported_gitdir" && pwd -P)"
  reported_common="$(cd "$reported_common" && pwd -P)"
  if [ "$reported_gitdir" != "$gitdir_host" ] || [ "$reported_common" != "$common_host" ]; then
    fail_closed "linked-worktree metadata does not match Git's canonical paths"
  fi
  if [ "$(git -C "$WORKSPACE_REAL" rev-parse --is-inside-work-tree)" != "true" ]; then
    fail_closed "linked-worktree metadata does not describe this workspace"
  fi

  gitdir_mount="${gitdir_host}:/run/wunder-git/common/worktrees/current:ro"
  common_mount="${common_host}:/run/wunder-git/common:ro"
  if [ "$CONTAINER_BIN" = "podman" ] && [ "$(uname -s)" = "Linux" ]; then
    gitdir_mount="${gitdir_mount},z"
    common_mount="${common_mount},z"
  fi
  DOCKER_ARGS+=(
    -v "$common_mount"
    -v "$gitdir_mount"
    -e GIT_DIR=/run/wunder-git/common/worktrees/current
    -e GIT_COMMON_DIR=/run/wunder-git/common
    -e GIT_WORK_TREE=/workspace
    -e "WUNDER_DEVTOOLS_HOST_GIT_DIR=${gitdir_host}"
    -e "WUNDER_DEVTOOLS_HOST_GIT_COMMON_DIR=${common_host}"
  )
}

configure_linked_worktree_git_mounts
SOURCE_ROOT_HOST="${WUNDER_DEVTOOLS_SOURCE_ROOT_HOST:-${WUNDER_DEVTOOLS_SOURCE_ROOT:-}}"
if [ -z "${SOURCE_ROOT_HOST:-}" ]; then
  SOURCE_ROOT_HOST="$(cd "${WORKSPACE_REAL}/.." && pwd -P)"
fi
SOURCE_ROOT_CONTAINER="${WUNDER_DEVTOOLS_SOURCE_ROOT_CONTAINER:-/sources}"
mounted_source_root=0
if [ "$SOURCE_ROOT_POLICY" = enabled ] && [ -d "$SOURCE_ROOT_HOST" ]; then
  shopt -s nullglob
  for collection_dir in "$SOURCE_ROOT_HOST"/ansible-collection-*; do
    [ -d "$collection_dir" ] || continue
    collection_real="$(cd "$collection_dir" && pwd -P)"
    [ "$collection_real" = "$WORKSPACE_REAL" ] && continue
    collection_base="$(basename "$collection_real")"
    collection_mount="${collection_real}:${SOURCE_ROOT_CONTAINER}/${collection_base}:ro"
    if [ "$CONTAINER_BIN" = "podman" ] && [ "$(uname -s)" = "Linux" ]; then
      collection_mount="${collection_mount},z"
    fi
    DOCKER_ARGS+=(-v "$collection_mount")
    mounted_source_root=1
  done
  shopt -u nullglob
fi
if [ "$mounted_source_root" = "1" ]; then
  DOCKER_ARGS+=(-e "WUNDER_DEVTOOLS_SOURCE_ROOT=${SOURCE_ROOT_CONTAINER}")
fi

PODMAN_ROOTLESS=0
if [ "$CONTAINER_BIN" = "podman" ]; then
  if ! podman_rootless="$(podman info --format '{{.Host.Security.Rootless}}' 2>/dev/null)"; then
    fail_closed "selected podman engine is not usable"
  fi
  if [ "${podman_rootless}" = "true" ]; then
    PODMAN_ROOTLESS=1
  fi
fi

DOCKER_SOCKET=""
if [ "$SOCKET_POLICY" != disabled ] && [[ "${DOCKER_HOST:-}" == unix://* ]]; then
  host_sock="${DOCKER_HOST#unix://}"
  if [ -S "$host_sock" ]; then
    DOCKER_SOCKET="$host_sock"
  fi
elif [ "$SOCKET_POLICY" != disabled ] && [ -S "/run/user/$(id -u)/podman/podman.sock" ]; then
  DOCKER_SOCKET="/run/user/$(id -u)/podman/podman.sock"
elif [ "$SOCKET_POLICY" != disabled ] && [ -S "$HOME/.docker/run/docker.sock" ]; then
  DOCKER_SOCKET="$HOME/.docker/run/docker.sock"
elif [ "$SOCKET_POLICY" != disabled ] && [ -S /var/run/docker.sock ]; then
  DOCKER_SOCKET="/var/run/docker.sock"
fi
if [ "$SOCKET_POLICY" = required ] && [ -z "$DOCKER_SOCKET" ]; then
  fail_closed "a Docker-compatible socket is required for this devtools invocation"
fi

VAGRANT_SSH_ENV_ARGS=()
if [ "$VAGRANT_SSH_POLICY" = enabled ]; then
  for variable_name in VAGRANT_SSH_HOST VAGRANT_SSH_PORT VAGRANT_SSH_USER VAGRANT_SSH_KEY; do
    if [ -n "${!variable_name:-}" ]; then
      VAGRANT_SSH_ENV_ARGS+=(-e "$variable_name")
    fi
  done
fi

if [ "$RUN_AS_HOST_UID_POLICY" = "1" ]; then
  if [ "$CONTAINER_BIN" = "podman" ] && [ "$PODMAN_ROOTLESS" = "1" ]; then
    # Rootless Podman maps container UID/GID 0 to the invoking host user. Keep
    # that mapping explicit so a mode-0755 bind-mounted checkout is writable.
    DOCKER_ARGS+=(--user 0:0)
  else
    # Hosted Docker preserves numeric ownership on bind mounts.
    DOCKER_ARGS+=(--user "$(id -u):$(id -g)")
  fi
fi

if [ -n "$DOCKER_SOCKET" ]; then
  DOCKER_SOCKET_REAL="$DOCKER_SOCKET"
  if command -v python3 >/dev/null 2>&1; then
    DOCKER_SOCKET_REAL="$(
      python3 - <<PY
import os
print(os.path.realpath("${DOCKER_SOCKET}"))
PY
    )"
  fi

  DOCKER_ARGS+=(-v "$DOCKER_SOCKET_REAL":/var/run/docker.sock)
  DOCKER_ARGS+=(-e DOCKER_HOST=unix:///var/run/docker.sock)
  DOCKER_ARGS+=(-e "WUNDER_DEVTOOLS_DOCKER_SOCKET_HOST=${DOCKER_SOCKET_REAL}")

  DOCKER_ARGS+=(
    -e HTTP_PROXY=
    -e HTTPS_PROXY=
    -e NO_PROXY=
    -e http_proxy=
    -e https_proxy=
    -e no_proxy=
  )

  if [ "$RUN_AS_HOST_UID_POLICY" = "1" ]; then
    DOCKER_ARGS+=(--group-add 0)

    if [ "$CONTAINER_BIN" != "podman" ] || [ "$PODMAN_ROOTLESS" != "1" ]; then
      if socket_gid="$(stat -c %g "$DOCKER_SOCKET_REAL" 2>/dev/null)"; then
        :
      elif socket_gid="$(stat -f %g "$DOCKER_SOCKET_REAL" 2>/dev/null)"; then
        :
      else
        echo "Error: cannot determine Docker-compatible socket group" >&2
        exit 1
      fi
      if [ -n "${socket_gid:-}" ]; then
        DOCKER_ARGS+=(--group-add "$socket_gid")
      fi
    fi
  else
    DOCKER_ARGS+=(--user 0:0)
    DOCKER_ARGS+=(--group-add 0)
  fi
elif [ "$RUN_AS_HOST_UID_POLICY" = "0" ] && [ "${PODMAN_ROOTLESS}" = "1" ]; then
  DOCKER_ARGS+=(--user 0:0)
fi

if [ "$(uname -s)" = "Linux" ]; then
  DOCKER_ARGS+=(--add-host=host.docker.internal:host-gateway)
fi

if [ "$CONTAINER_BIN" = "docker" ]; then
  if [ -n "$DOCKER_SOCKET" ]; then
    export DOCKER_HOST="unix://${DOCKER_SOCKET_REAL}"
  else
    sanitize_docker_host_env
    if [ -z "${DOCKER_HOST:-}" ] && [ -S "/run/user/$(id -u)/podman/podman.sock" ]; then
      DOCKER_HOST="unix:///run/user/$(id -u)/podman/podman.sock"
      export DOCKER_HOST
    fi
  fi
fi

"$CONTAINER_BIN" run --rm \
  --entrypoint "" \
  "${DOCKER_ARGS[@]}" \
  ${ANSIBLE_COLLECTIONS_PATH:+-e ANSIBLE_COLLECTIONS_PATH} \
  ${ANSIBLE_ROLES_PATH:+-e ANSIBLE_ROLES_PATH} \
  ${ANSIBLE_CORE_VERSION:+-e ANSIBLE_CORE_VERSION} \
  ${ANSIBLE_LINT_VERSION:+-e ANSIBLE_LINT_VERSION} \
  ${ANSIBLE_LINT_SKIP_META_RUNTIME:+-e ANSIBLE_LINT_SKIP_META_RUNTIME} \
  ${COLLECTION_NAMESPACE:+-e COLLECTION_NAMESPACE} \
  ${COLLECTION_NAME:+-e COLLECTION_NAME} \
  ${SCENARIO_FILTER:+-e SCENARIO_FILTER} \
  ${EXAMPLE_PLAYBOOK:+-e EXAMPLE_PLAYBOOK} \
  ${MOLECULE_NO_LOG:+-e MOLECULE_NO_LOG} \
  ${BASE_SHA:+-e BASE_SHA} \
  ${HEAD_SHA:+-e HEAD_SHA} \
  ${LABELS_JSON:+-e LABELS_JSON} \
  ${REQUIRE_FRAGMENT:+-e REQUIRE_FRAGMENT} \
  ${GITHUB_HEAD_REF:+-e GITHUB_HEAD_REF} \
  ${GITHUB_BASE_REF:+-e GITHUB_BASE_REF} \
  ${PRE_COMMIT_FROM_REF:+-e PRE_COMMIT_FROM_REF} \
  ${PRE_COMMIT_TO_REF:+-e PRE_COMMIT_TO_REF} \
  ${CHANGELOG_BASE_REF:+-e CHANGELOG_BASE_REF} \
  ${CI:+-e CI} \
  ${GITHUB_ACTIONS:+-e GITHUB_ACTIONS} \
  ${WUNDER_DEVTOOLS_PRUNE_BUILDKIT_CACHE:+-e WUNDER_DEVTOOLS_PRUNE_BUILDKIT_CACHE} \
  "${VAGRANT_SSH_ENV_ARGS[@]}" \
  "$IMAGE" "$@"
