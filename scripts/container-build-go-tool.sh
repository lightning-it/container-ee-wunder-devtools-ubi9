#!/usr/bin/env bash
set -euo pipefail

if [ "$#" -lt 4 ]; then
  echo "usage: $0 <module> <version> <package> <output> [module@version ...]" >&2
  exit 2
fi

module="$1"
version="$2"
package="$3"
output="$4"
shift 4

if [[ ! "$module" =~ ^[A-Za-z0-9._/~+-]+$ ]] \
  || [[ ! "$version" =~ ^v[0-9A-Za-z._+-]+$ ]] \
  || [[ ! "$package" =~ ^(\.|\./[A-Za-z0-9._/~+-]+)$ ]] \
  || [[ ! "$output" =~ ^[A-Za-z0-9._+-]+$ ]]
then
  echo "ERROR: invalid Go tool build coordinate" >&2
  exit 2
fi

module_json="$(go mod download -json "${module}@${version}")"
module_dir="$({
  printf '%s' "$module_json" | python3 -c '
import json
import sys

metadata = json.load(sys.stdin)
directory = metadata.get("Dir", "")
if not directory:
    raise SystemExit("downloaded Go module has no source directory")
print(directory, end="")
'
})"

build_dir="$(mktemp -d "/tmp/lit-go-build.${output}.XXXXXX")"
case "$build_dir" in
  "/tmp/lit-go-build.${output}."*) ;;
  *) echo "ERROR: unsafe temporary Go build directory" >&2; exit 2 ;;
esac
cp -a "${module_dir}/." "$build_dir/"
chmod -R u+rwX "$build_dir"
cd "$build_dir"

for replacement in "$@"; do
  replacement_module="${replacement%@*}"
  replacement_version="${replacement##*@}"
  if [ "$replacement_module" = "$replacement" ] \
    || [[ ! "$replacement_module" =~ ^[A-Za-z0-9._/~+-]+$ ]] \
    || [[ ! "$replacement_version" =~ ^v[0-9A-Za-z._+-]+$ ]]
  then
    echo "ERROR: invalid Go module replacement: ${replacement}" >&2
    exit 2
  fi
  go mod edit "-replace=${replacement_module}=${replacement}"
done

go mod tidy
CGO_ENABLED=0 go build \
  -trimpath \
  -buildvcs=false \
  -ldflags="-s -w ${GO_TOOL_LDFLAGS:-}" \
  -o "/out/${output}" \
  "$package"
go version -m "/out/${output}"

cd /
rm -rf -- "$build_dir"
