#!/usr/bin/env bash
set -euo pipefail

IMAGE="quay.io/l-it/ee-wunder-devtools-ubi9:v1.16.0@sha256:7674d82bf7c0f87064196e333f994613ca6e23d9fdee9157ae037f2209d2343a"
CONTAINER_HOME="${CONTAINER_HOME:-/tmp/wunder}"
WORKSPACE_MODE="${WUNDER_DEVTOOLS_WORKSPACE_MODE:-ro}"
RUN_AS_HOST_UID_POLICY="${WUNDER_DEVTOOLS_RUN_AS_HOST_UID:-0}"
NETWORK_MODE="${WUNDER_DEVTOOLS_NETWORK:-none}"
PRIVILEGED_POLICY="${WUNDER_DEVTOOLS_PRIVILEGED:-0}"
SOCKET_POLICY="${WUNDER_DEVTOOLS_DOCKER_SOCKET:-disabled}"
SOURCE_ROOT_POLICY="${WUNDER_DEVTOOLS_MOUNT_SOURCE_ROOT:-disabled}"
CAPABILITY_POLICY="${WUNDER_DEVTOOLS_CAP_ADD:-}"
VAGRANT_SSH_POLICY="${WUNDER_DEVTOOLS_FORWARD_VAGRANT_SSH:-disabled}"
case "$WORKSPACE_MODE" in ro|rw) ;; *) echo "Error: unsupported workspace mode: $WORKSPACE_MODE" >&2; exit 1 ;; esac
case "$NETWORK_MODE" in none|bridge) ;; *) echo "Error: unsupported network mode: $NETWORK_MODE" >&2; exit 1 ;; esac
case "$PRIVILEGED_POLICY" in 0|1) ;; *) echo "Error: unsupported privileged policy: $PRIVILEGED_POLICY" >&2; exit 1 ;; esac
case "$RUN_AS_HOST_UID_POLICY" in 0|1) ;; *) echo "Error: unsupported host UID policy: $RUN_AS_HOST_UID_POLICY" >&2; exit 1 ;; esac
case "$SOCKET_POLICY" in disabled|required|auto) ;; *) echo "Error: unsupported socket policy: $SOCKET_POLICY" >&2; exit 1 ;; esac
case "$SOURCE_ROOT_POLICY" in disabled|enabled) ;; *) echo "Error: unsupported source-root policy: $SOURCE_ROOT_POLICY" >&2; exit 1 ;; esac
case "$CAPABILITY_POLICY" in ""|CHOWN,FOWNER|CHOWN,DAC_OVERRIDE,FOWNER) ;; *) echo "Error: unsupported capability policy: $CAPABILITY_POLICY" >&2; exit 1 ;; esac
case "$VAGRANT_SSH_POLICY" in disabled|enabled) ;; *) echo "Error: unsupported Vagrant SSH forwarding policy: $VAGRANT_SSH_POLICY" >&2; exit 1 ;; esac
if [ -n "$CAPABILITY_POLICY" ] && {
  [ "$WORKSPACE_MODE" != ro ] \
    || [ "$NETWORK_MODE" != none ] \
    || [ "$SOCKET_POLICY" != disabled ] \
    || [ "$SOURCE_ROOT_POLICY" != disabled ] \
    || [ "$VAGRANT_SSH_POLICY" != disabled ] \
    || [ "$PRIVILEGED_POLICY" != 0 ];
}; then
  echo "Error: capability mode requires a read-only, offline, socket-free sandbox" >&2
  exit 1
fi
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

WORKSPACE_ROOT="$(pwd -P)"
case "$WORKSPACE_ROOT" in
  *:*|*,*)
    echo "Error: workspace path contains an unsafe mount delimiter" >&2
    exit 1
    ;;
esac
WORKSPACE_MOUNT="${WORKSPACE_ROOT}:/workspace:${WORKSPACE_MODE}"
# Never bind a host home directory here. A fresh tmpfs prevents one invocation
# or repository from supplying Ansible plugins/configuration to a later run.
# Molecule stages executable shims below HOME, so make exec explicit while
# retaining nosuid/nodev for identical Docker and Podman behavior.
HOME_TMPFS_MOUNT="${CONTAINER_HOME}:rw,exec,nosuid,nodev,size=1g,mode=1777"
RUN_TMPFS_MOUNT="/run:rw,nosuid,nodev,size=256m"

fail_closed() {
  local msg="$1"
  echo "Error: ${msg}" >&2
  exit 1
}

LINKED_WORKTREE_GIT_POINTER=""
cleanup_linked_worktree_git_pointer() {
  if [ -n "$LINKED_WORKTREE_GIT_POINTER" ]; then
    rm -f -- "$LINKED_WORKTREE_GIT_POINTER"
  fi
}
trap cleanup_linked_worktree_git_pointer EXIT

sanitize_docker_host_env() {
  local host_sock
  case "${DOCKER_HOST:-}" in
    "") ;;
    unix://*)
      host_sock="${DOCKER_HOST#unix://}"
      if [ ! -S "$host_sock" ]; then
        unset DOCKER_HOST
      fi
      ;;
    *) fail_closed "DOCKER_HOST must reference a local unix:// socket" ;;
  esac
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

sanitize_docker_host_env

EXPLICIT_CONTAINER_ENGINE=0
CONTAINER_BIN="${WUNDER_CONTAINER_ENGINE:-}"
if [ -n "$CONTAINER_BIN" ]; then
  EXPLICIT_CONTAINER_ENGINE=1
fi
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

PODMAN_ROOTLESS=0
if [ "$CONTAINER_BIN" = "podman" ]; then
  if ! podman_rootless="$(podman info --format '{{.Host.Security.Rootless}}' 2>/dev/null)"; then
    fail_closed "selected podman engine is not usable"
  fi
  if [ "${podman_rootless}" = "true" ]; then
    PODMAN_ROOTLESS=1
  fi
fi

if [ "$RUN_AS_HOST_UID_POLICY" = "1" ]; then
  if [ "$CONTAINER_BIN" = "podman" ] && [ "$PODMAN_ROOTLESS" = "1" ]; then
    # Rootless Podman maps container UID/GID 0 to the invoking host user.
    CONTAINER_UID=0
    CONTAINER_GID=0
  else
    # Hosted Docker and rootful Podman preserve numeric bind-mount ownership.
    CONTAINER_UID="$(id -u)"
    CONTAINER_GID="$(id -g)"
  fi
  # Keep /run private to the selected controller identity instead of making
  # it writable by every account in the container.
  RUN_TMPFS_MOUNT="${RUN_TMPFS_MOUNT},uid=${CONTAINER_UID},gid=${CONTAINER_GID},mode=0755"
fi

DOCKER_ARGS=(
  -w /workspace
  -e HOME="${CONTAINER_HOME}"
  --read-only
  --network "$NETWORK_MODE"
  --cap-drop ALL
  --security-opt no-new-privileges=true
  --pids-limit 1024
  --tmpfs "/tmp:rw,nosuid,nodev,noexec,size=2g"
  --tmpfs "$RUN_TMPFS_MOUNT"
  --tmpfs "$HOME_TMPFS_MOUNT"
)

if [ "$PRIVILEGED_POLICY" = "1" ]; then
  DOCKER_ARGS+=(--privileged)
elif [ "$CAPABILITY_POLICY" = "CHOWN,FOWNER" ]; then
  DOCKER_ARGS+=(--cap-add CHOWN --cap-add FOWNER)
elif [ "$CAPABILITY_POLICY" = "CHOWN,DAC_OVERRIDE,FOWNER" ]; then
  DOCKER_ARGS+=(--cap-add CHOWN --cap-add DAC_OVERRIDE --cap-add FOWNER)
fi

if [ "$CONTAINER_BIN" = "podman" ] && [ "$(uname -s)" = "Linux" ]; then
  DOCKER_ARGS+=(--read-only-tmpfs=false)
  WORKSPACE_MOUNT="${WORKSPACE_MOUNT},z"
fi

DOCKER_ARGS+=(-v "$WORKSPACE_MOUNT")

WORKSPACE_REAL="$(pwd -P)"
DOCKER_ARGS+=(-e "WUNDER_DEVTOOLS_HOST_WORKSPACE=${WORKSPACE_REAL}")

configure_linked_worktree_git_mounts() {
  local git_file="${WORKSPACE_REAL}/.git"
  local gitdir_raw gitdir_host common_raw common_host reported_gitdir reported_common
  local gitdir_relative common_mount git_pointer_mount pointer_root
  local line_count

  [ -f "$git_file" ] || return 0
  line_count="$(awk 'END { print NR }' "$git_file")"
  if [ "$line_count" -ne 1 ]; then
    fail_closed "linked-worktree .git must contain exactly one gitdir line"
  fi
  IFS= read -r gitdir_raw <"$git_file" || [ -n "$gitdir_raw" ] \
    || fail_closed "linked-worktree .git has an empty gitdir declaration"
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

  line_count="$(awk 'END { print NR }' "${gitdir_host}/commondir")"
  if [ "$line_count" -ne 1 ]; then
    fail_closed "linked-worktree commondir must contain exactly one path"
  fi
  IFS= read -r common_raw <"${gitdir_host}/commondir" || [ -n "$common_raw" ] \
    || fail_closed "linked-worktree commondir is empty"
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

  case "$gitdir_host" in
    "$common_host"/*) gitdir_relative="${gitdir_host#"$common_host"/}" ;;
    *) fail_closed "linked-worktree gitdir is outside its common Git directory" ;;
  esac
  case "$gitdir_relative" in
    ""|/*|*:*|*,*|../*|*/../*|*/..)
      fail_closed "linked-worktree gitdir has an unsafe relative path"
      ;;
  esac
  common_mount="${common_host}:/run/wunder-git/common:ro"
  # Some repository tools deliberately discard GIT_DIR, GIT_COMMON_DIR, and
  # GIT_WORK_TREE before invoking Git. Overlay the worktree's host-absolute
  # .git pointer with a minimal container-local pointer instead of mounting the
  # common directory at an arbitrary host path in the read-only rootfs.
  pointer_root="${TMPDIR:-/tmp}"
  case "$pointer_root" in
    /*) ;;
    *) fail_closed "TMPDIR must be an absolute host path" ;;
  esac
  case "$pointer_root" in
    *:*|*,*) fail_closed "TMPDIR contains an unsafe mount delimiter" ;;
  esac
  LINKED_WORKTREE_GIT_POINTER="$(mktemp "${pointer_root%/}/wunder-devtools-git-pointer.XXXXXX")" \
    || fail_closed "cannot create linked-worktree Git pointer"
  if [ ! -f "$LINKED_WORKTREE_GIT_POINTER" ] || [ -L "$LINKED_WORKTREE_GIT_POINTER" ]; then
    fail_closed "linked-worktree Git pointer is not a regular file"
  fi
  printf 'gitdir: /run/wunder-git/common/%s\n' "$gitdir_relative" \
    >"$LINKED_WORKTREE_GIT_POINTER"
  chmod 0444 "$LINKED_WORKTREE_GIT_POINTER"
  git_pointer_mount="${LINKED_WORKTREE_GIT_POINTER}:/workspace/.git:ro"
  if [ "$CONTAINER_BIN" = "podman" ] && [ "$(uname -s)" = "Linux" ]; then
    common_mount="${common_mount},z"
    git_pointer_mount="${git_pointer_mount},z"
  fi
  DOCKER_ARGS+=(
    -v "$common_mount"
    -v "$git_pointer_mount"
    -e "GIT_DIR=/run/wunder-git/common/${gitdir_relative}"
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
  case "$SOURCE_ROOT_CONTAINER" in
    /*) ;;
    *) fail_closed "source-root container path must be absolute" ;;
  esac
  case "$SOURCE_ROOT_CONTAINER" in
    *:*)
      fail_closed "source-root container path contains an unsafe mount delimiter"
      ;;
  esac
  shopt -s nullglob
  for collection_dir in "$SOURCE_ROOT_HOST"/ansible-collection-*; do
    [ -d "$collection_dir" ] || continue
    collection_real="$(cd "$collection_dir" && pwd -P)"
    [ "$collection_real" = "$WORKSPACE_REAL" ] && continue
    case "$collection_real" in
      *:*)
        fail_closed "resolved collection source path contains an unsafe mount delimiter"
        ;;
    esac
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
  DOCKER_ARGS+=(--user "${CONTAINER_UID}:${CONTAINER_GID}")
fi

if [ -n "$DOCKER_SOCKET" ]; then
  case "$DOCKER_SOCKET" in
    /*) ;;
    *) fail_closed "Docker-compatible socket path must be absolute" ;;
  esac
  if ! command -v realpath >/dev/null 2>&1; then
    fail_closed "realpath is required to validate the Docker-compatible socket path"
  fi
  if ! DOCKER_SOCKET_REAL="$(realpath "$DOCKER_SOCKET" 2>/dev/null)"; then
    fail_closed "unable to resolve Docker-compatible socket path"
  fi

  if [ -z "$DOCKER_SOCKET_REAL" ]; then
    fail_closed "resolved Docker-compatible socket path is empty"
  fi
  case "$DOCKER_SOCKET_REAL" in
    *:*)
      fail_closed "resolved Docker-compatible socket path contains an unsafe mount delimiter"
      ;;
  esac
  if [ ! -S "$DOCKER_SOCKET_REAL" ]; then
    fail_closed "resolved Docker-compatible socket path is not a socket"
  fi

  DOCKER_ARGS+=(-v "${DOCKER_SOCKET_REAL}:/var/run/docker.sock")
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
elif [ "$RUN_AS_HOST_UID_POLICY" = "0" ] && [ -n "$CAPABILITY_POLICY" ]; then
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

if [ "$EXPLICIT_CONTAINER_ENGINE" = "1" ] && [ "$CONTAINER_BIN" = "docker" ]; then
  if ! docker_usable; then
    fail_closed "selected docker engine is not usable"
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
  ${VAGRANT_SSH_ENV_ARGS[@]+"${VAGRANT_SSH_ENV_ARGS[@]}"} \
  "$IMAGE" "$@"
