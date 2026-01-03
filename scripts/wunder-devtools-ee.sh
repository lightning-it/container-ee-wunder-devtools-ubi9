#!/usr/bin/env bash
set -euo pipefail

IMAGE="${WUNDER_DEVTOOLS_EE_IMAGE:-ghcr.io/lightning-it/wunder-devtools-ee:v1.1.7}"
CONTAINER_HOME="${CONTAINER_HOME:-/tmp/wunder}"
HOST_HOME_CACHE="${XDG_CACHE_HOME:-$HOME/.cache}/wunder-devtools-ee/home"

mkdir -p "$HOST_HOME_CACHE"

DOCKER_ARGS=(
  -v "$PWD":/workspace
  -w /workspace
  -e HOME="${CONTAINER_HOME}"
  -v "$HOST_HOME_CACHE":"${CONTAINER_HOME}"
)

DOCKER_SOCKET=""
if [ -S "$HOME/.docker/run/docker.sock" ]; then
  DOCKER_SOCKET="$HOME/.docker/run/docker.sock"
elif [ -S /var/run/docker.sock ]; then
  DOCKER_SOCKET="/var/run/docker.sock"
elif [[ "${DOCKER_HOST:-}" == unix://* ]]; then
  host_sock="${DOCKER_HOST#unix://}"
  if [ -S "$host_sock" ]; then
    DOCKER_SOCKET="$host_sock"
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

  DOCKER_ARGS+=(
    -e HTTP_PROXY=
    -e HTTPS_PROXY=
    -e NO_PROXY=
    -e http_proxy=
    -e https_proxy=
    -e no_proxy=
  )

  if [ "${WUNDER_DEVTOOLS_RUN_AS_HOST_UID:-0}" = "1" ]; then
    DOCKER_ARGS+=(--user "$(id -u):$(id -g)")
    DOCKER_ARGS+=(--group-add 0)

    socket_gid="$(
      stat -c %g "$DOCKER_SOCKET_REAL" 2>/dev/null \
      || stat -f %g "$DOCKER_SOCKET_REAL" 2>/dev/null \
      || true
    )"
    if [ -n "${socket_gid:-}" ]; then
      DOCKER_ARGS+=(--group-add "$socket_gid")
    fi
  else
    DOCKER_ARGS+=(--user 0:0)
    DOCKER_ARGS+=(--group-add 0)
  fi
fi

if [ "$(uname -s)" = "Linux" ]; then
  DOCKER_ARGS+=(--add-host=host.docker.internal:host-gateway)
fi

docker run --rm \
  --entrypoint "" \
  "${DOCKER_ARGS[@]}" \
  ${ANSIBLE_COLLECTIONS_PATHS:+-e ANSIBLE_COLLECTIONS_PATHS} \
  ${ANSIBLE_ROLES_PATH:+-e ANSIBLE_ROLES_PATH} \
  ${ANSIBLE_CORE_VERSION:+-e ANSIBLE_CORE_VERSION} \
  ${ANSIBLE_LINT_VERSION:+-e ANSIBLE_LINT_VERSION} \
  ${COLLECTION_NAMESPACE:+-e COLLECTION_NAMESPACE} \
  ${COLLECTION_NAME:+-e COLLECTION_NAME} \
  ${EXAMPLE_PLAYBOOK:+-e EXAMPLE_PLAYBOOK} \
  ${MOLECULE_NO_LOG:+-e MOLECULE_NO_LOG} \
  ${VAGRANT_SSH_HOST:+-e VAGRANT_SSH_HOST} \
  ${VAGRANT_SSH_PORT:+-e VAGRANT_SSH_PORT} \
  ${VAGRANT_SSH_USER:+-e VAGRANT_SSH_USER} \
  ${VAGRANT_SSH_KEY:+-e VAGRANT_SSH_KEY} \
  "$IMAGE" "$@"
