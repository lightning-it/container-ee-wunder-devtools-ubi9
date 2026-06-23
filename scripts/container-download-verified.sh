#!/usr/bin/env bash
set -euo pipefail

detect_container_arch() {
  local arch="${TARGETARCH:-}"

  if [ -z "$arch" ]; then
    case "$(uname -m)" in
      x86_64) arch="amd64" ;;
      aarch64|arm64) arch="arm64" ;;
      *)
        echo "ERROR: unsupported build architecture: $(uname -m)" >&2
        return 1
        ;;
    esac
  fi

  case "$arch" in
    amd64)
      CONTAINER_ARCH="amd64"
      CONTAINER_RPM_ARCH="x86_64"
      ;;
    arm64)
      CONTAINER_ARCH="arm64"
      CONTAINER_RPM_ARCH="aarch64"
      ;;
    *)
      echo "ERROR: unsupported TARGETARCH=${arch}" >&2
      return 1
      ;;
  esac

  export CONTAINER_ARCH CONTAINER_RPM_ARCH
}

download_verified() {
  local url="$1"
  local output_path="$2"
  local checksum_url="$3"
  local checksum_name="${4:-$(basename "$url")}"
  local checksum_file
  local expected

  if [ -z "$checksum_url" ]; then
    echo "ERROR: checksum URL is required for ${url}" >&2
    return 1
  fi

  checksum_file="$(mktemp)"
  curl --fail --show-error --silent --location --retry 5 --retry-delay 2 \
    --output "$output_path" "$url"
  curl --fail --show-error --silent --location --retry 5 --retry-delay 2 \
    --output "$checksum_file" "$checksum_url"

  expected="$(
    awk -v wanted="$checksum_name" '
      NF == 1 && $1 ~ /^[A-Fa-f0-9]{64}$/ {
        print $1
        exit
      }
      NF >= 2 {
        file = $2
        sub(/^\*/, "", file)
        base = file
        sub(/^.*\//, "", base)
        if (file == wanted || base == wanted) {
          print $1
          exit
        }
      }
    ' "$checksum_file"
  )"

  rm -f "$checksum_file"

  if [ -z "$expected" ]; then
    echo "ERROR: checksum for ${checksum_name} not found in ${checksum_url}" >&2
    return 1
  fi

  printf '%s  %s\n' "$expected" "$output_path" | sha256sum --check --status
}
