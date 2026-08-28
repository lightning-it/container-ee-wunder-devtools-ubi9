#!/usr/bin/env bash
set -euo pipefail

readonly version_file="/workspace/.node-version"
readonly default_node_bin="/opt/node/bin"
readonly website_node_bin="/opt/node-website/bin"

fail_closed() {
  printf 'Error: %s\n' "$1" >&2
  exit 64
}

if [ -e "$version_file" ] || [ -L "$version_file" ]; then
  [ -f "$version_file" ] && [ ! -L "$version_file" ] \
    || fail_closed ".node-version must be one regular, non-symlinked file"
  [ -r "$version_file" ] \
    || fail_closed ".node-version must be readable"

  requested_version=""
  extra_line=""
  exec 3<"$version_file" \
    || fail_closed ".node-version must be readable"
  if ! IFS= read -r requested_version <&3 && [ -z "$requested_version" ]; then
    exec 3<&-
    fail_closed ".node-version must not be empty"
  fi
  [ -n "$requested_version" ] \
    || fail_closed ".node-version must not be empty"
  if IFS= read -r extra_line <&3 || [ -n "$extra_line" ]; then
    exec 3<&-
    fail_closed ".node-version must contain exactly one line"
  fi
  exec 3<&-
  [[ "$requested_version" =~ ^[0-9]+\.[0-9]+\.[0-9]+$ ]] \
    || fail_closed ".node-version must contain one exact semantic version"

  default_version="$("$default_node_bin/node" -p 'process.versions.node')"
  website_version="$("$website_node_bin/node" -p 'process.versions.node')"
  case "$requested_version" in
    "$default_version") ;;
    "$website_version") export PATH="$website_node_bin:$PATH" ;;
    *) fail_closed "requested Node.js version is not bundled: $requested_version" ;;
  esac
fi

exec "$@"
