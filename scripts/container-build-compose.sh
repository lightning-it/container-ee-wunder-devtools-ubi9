#!/usr/bin/env bash
set -euo pipefail

report_error() {
  local status="$?"
  local line="$1"
  printf 'ERROR: Compose source build failed at line %s (exit %s)\n' \
    "$line" "$status" >&2
  exit "$status"
}
trap 'report_error "$LINENO"' ERR

if [ "$#" -ne 6 ]; then
  echo "usage: $0 <compose-version> <buildx-version> <moby-v2-version> <namesgenerator-sha256> <x-mod-version> <grpc-version>" >&2
  exit 2
fi

compose_version="$1"
buildx_version="$2"
moby_v2_version="$3"
namesgenerator_sha256="$4"
x_mod_version="$5"
grpc_version="$6"

for coordinate in \
  "$compose_version" \
  "$buildx_version" \
  "$moby_v2_version" \
  "$x_mod_version" \
  "$grpc_version"
do
  if [[ ! "$coordinate" =~ ^[0-9A-Za-z._+-]+$ ]]; then
    echo "ERROR: invalid container build coordinate: ${coordinate}" >&2
    exit 2
  fi
done
if [[ ! "$namesgenerator_sha256" =~ ^[a-f0-9]{64}$ ]]; then
  echo "ERROR: invalid Moby namesgenerator SHA-256" >&2
  exit 2
fi

module_source_dir() {
  local module="$1"
  local version="$2"
  local module_json

  module_json="$(go mod download -json "${module}@v${version}")"
  printf '%s' "$module_json" | python3 -c '
import json
import sys

metadata = json.load(sys.stdin)
directory = metadata.get("Dir", "")
if not directory:
    raise SystemExit("downloaded Go module has no source directory")
print(directory, end="")
'
}

compose_module_dir="$(module_source_dir github.com/docker/compose/v5 "$compose_version")"
buildx_module_dir="$(module_source_dir github.com/docker/buildx "$buildx_version")"
moby_module_dir="$(module_source_dir github.com/moby/moby/v2 "$moby_v2_version")"

compose_build_dir="$(mktemp -d /tmp/lit-compose-build.XXXXXX)"
buildx_build_dir="$(mktemp -d /tmp/lit-buildx-build.XXXXXX)"
case "$compose_build_dir" in /tmp/lit-compose-build.*) ;; *) exit 2 ;; esac
case "$buildx_build_dir" in /tmp/lit-buildx-build.*) ;; *) exit 2 ;; esac

cp -a "${compose_module_dir}/." "$compose_build_dir/"
cp -a "${buildx_module_dir}/." "$buildx_build_dir/"
chmod -R u+rwX "$compose_build_dir" "$buildx_build_dir"

readonly legacy_import='"github.com/docker/docker/pkg/namesgenerator"'
readonly local_import='"github.com/docker/buildx/store/namesgenerator"'
buildx_import_file="${buildx_build_dir}/store/util.go"
if [ "$(grep -RFl "$legacy_import" "$buildx_build_dir" || true)" != "$buildx_import_file" ]; then
  echo "ERROR: unexpected Buildx legacy namesgenerator import set" >&2
  exit 1
fi
sed -i "s|${legacy_import}|${local_import}|" "$buildx_import_file"
grep -Fq "$local_import" "$buildx_import_file"
if grep -RFq "$legacy_import" "$buildx_build_dir"; then
  echo "ERROR: legacy docker/docker import remains in Buildx source" >&2
  exit 1
fi

moby_namesgenerator="${moby_module_dir}/internal/namesgenerator/names-generator.go"
printf '%s  %s\n' "$namesgenerator_sha256" "$moby_namesgenerator" | sha256sum -c -
mkdir -p "${buildx_build_dir}/store/namesgenerator"
cp "$moby_namesgenerator" \
  "${buildx_build_dir}/store/namesgenerator/names-generator.go"

cd "$buildx_build_dir"
go mod edit -droprequire=github.com/docker/docker
go mod tidy

cd "$compose_build_dir"
go mod edit "-replace=github.com/docker/buildx=${buildx_build_dir}"
go mod edit \
  "-replace=golang.org/x/mod=golang.org/x/mod@v${x_mod_version}"
go mod edit \
  "-replace=google.golang.org/grpc=google.golang.org/grpc@v${grpc_version}"
go mod tidy
if go list -m all | grep -Eq '^github.com/docker/docker([[:space:]]|$)'; then
  echo "ERROR: deprecated github.com/docker/docker remains in Compose module graph" >&2
  exit 1
fi

CGO_ENABLED=0 go build \
  -trimpath \
  -buildvcs=false \
  -ldflags="-s -w" \
  -o /out/docker-compose \
  ./cmd
go version -m /out/docker-compose
if go version -m /out/docker-compose \
  | grep -Eq $'\tdep\tgithub.com/docker/docker\t'
then
  echo "ERROR: deprecated github.com/docker/docker linked into Compose" >&2
  exit 1
fi
effective_grpc_version="$(
  go version -m /out/docker-compose | awk -v module='google.golang.org/grpc' '
    $1 == "dep" && $2 == module { version = $3 }
    $1 == "=>" && $2 == module { version = $3 }
    END { print version }
  '
)"
if [ "$effective_grpc_version" != "v${grpc_version}" ]; then
  echo "ERROR: docker-compose does not link google.golang.org/grpc v${grpc_version}" >&2
  exit 1
fi

cd /
rm -rf -- "$compose_build_dir" "$buildx_build_dir"
