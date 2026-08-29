#!/usr/bin/env bash
set -euo pipefail

command -v git >/dev/null 2>&1 || {
  echo "git is required for the host parity probe." >&2
  exit 1
}
command -v python3 >/dev/null 2>&1 || {
  echo "python3 is required for the host parity probe." >&2
  exit 1
}
repo_root="$(git rev-parse --show-toplevel 2>/dev/null)" || {
  echo "The host parity probe must run inside a Git working tree." >&2
  exit 1
}
cd "$repo_root"

engine="${WUNDER_CONTAINER_ENGINE:-}"
if [ -z "$engine" ]; then
  if command -v docker >/dev/null 2>&1 && docker info >/dev/null 2>&1; then
    engine=docker
  elif command -v podman >/dev/null 2>&1 && podman info >/dev/null 2>&1; then
    engine=podman
  else
    echo "No usable Docker or Podman runtime found." >&2
    exit 1
  fi
fi

case "$engine" in
  docker|podman) ;;
  *) echo "Unsupported runtime: $engine" >&2; exit 1 ;;
esac

os="$(uname -s)"
arch="$(uname -m)"
case "${os}/${arch}" in
  Linux/x86_64|Darwin/arm64) ;;
  *)
    echo "Host ${os}/${arch} is outside the REP-50 acceptance matrix." >&2
    exit 1
    ;;
esac

started="$(date +%s)"
image="local/lightning-it-devtools:host-parity"
"$engine" build --build-arg COLLECTION_PROFILE=public -t "$image" .
# The single-quoted command is intentionally expanded in the container.
# shellcheck disable=SC2016
"$engine" run --rm \
  --network none \
  --read-only \
  --cap-drop ALL \
  --security-opt no-new-privileges=true \
  --tmpfs /tmp:rw,exec,nosuid,nodev,size=2g \
  "$image" sh -ec '
    export XDG_CACHE_HOME=/tmp/.cache
    mkdir -p "$XDG_CACHE_HOME"
    test "$(id -u)" != 0
    python3 --version
    terraform version
    ansible --version
    actionlint --version
    pre-commit --version
    ruff --version
    mypy --version
    uv --version
    renovate-config-validator --version
    markdownlint-cli2 --version
    prettier --version
    pnpm --version
    node --version
    vnu --version
  '
finished="$(date +%s)"

python3 - "$os" "$arch" "$engine" "$started" "$finished" <<'PY'
import json
import sys

os_name, arch, runtime, started, finished = sys.argv[1:]
print(json.dumps({
    "version": 1,
    "host_os": os_name,
    "host_arch": arch,
    "runtime": runtime,
    "duration_seconds": int(finished) - int(started),
    "result": "pass",
}, sort_keys=True))
PY
