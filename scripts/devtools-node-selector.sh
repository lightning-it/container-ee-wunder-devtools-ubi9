#!/usr/bin/env bash
set -euo pipefail

readonly version_file="/workspace/.node-version"
readonly website_node_bin="/opt/node-website/bin"

fail_closed() {
  printf 'Error: %s\n' "$1" >&2
  exit 64
}

if [ -e "$version_file" ]; then
  [ -f "$version_file" ] && [ ! -L "$version_file" ] \
    || fail_closed ".node-version must be one regular, non-symlinked file"
  [ "$(awk 'END { print NR }' "$version_file")" -eq 1 ] \
    || fail_closed ".node-version must contain exactly one line"
  IFS= read -r requested_version <"$version_file" \
    || [ -n "$requested_version" ] \
    || fail_closed ".node-version must not be empty"
  [[ "$requested_version" =~ ^[0-9]+\.[0-9]+\.[0-9]+$ ]] \
    || fail_closed ".node-version must contain one exact semantic version"

  default_version="$(node -p 'process.versions.node')"
  website_version="$($website_node_bin/node -p 'process.versions.node')"
  case "$requested_version" in
    "$default_version") ;;
    "$website_version") export PATH="$website_node_bin:$PATH" ;;
    *) fail_closed "requested Node.js version is not bundled: $requested_version" ;;
  esac
fi

exec "$@"
