#!/usr/bin/env bash
# Assemble only the two platform indices produced by this workflow run.
set -euo pipefail

for name in IMAGE_NAME RELEASE_TAG VERSION SHORT_SHA DIGEST_DIRECTORY GITHUB_OUTPUT; do
  if [ -z "${!name:-}" ]; then
    echo "ERROR: $name is required" >&2
    exit 1
  fi
done

work="$(mktemp -d)"
trap 'rm -rf "$work"' EXIT
sources=()
for arch in amd64 arm64; do
  file="$DIGEST_DIRECTORY/$arch"
  if [ ! -f "$file" ] || [ -L "$file" ]; then
    echo "ERROR: missing regular digest file for $arch" >&2
    exit 1
  fi
  digest="$(cat "$file")"
  if [[ ! "$digest" =~ ^sha256:[a-f0-9]{64}$ ]]; then
    echo "ERROR: malformed digest for $arch" >&2
    exit 1
  fi
  source="$IMAGE_NAME@$digest"
  docker buildx imagetools inspect "$source" --raw > "$work/$arch.json"
  # Buildx emits a platform index containing one runnable image and attestations.
  # Reject a wrong architecture, extra runnable image or detached attestation.
  jq -e --arg arch "$arch" '
    [.manifests[] | select(.platform.os != "unknown")] as $images
    | ($images | length) == 1
      and $images[0].platform.os == "linux"
      and $images[0].platform.architecture == $arch
      and ([.manifests[] | select(.platform.os == "unknown")] | length) >= 1
      and all(.manifests[] | select(.platform.os == "unknown");
        .platform.architecture == "unknown"
        and .annotations["vnd.docker.reference.type"] == "attestation-manifest"
        and .annotations["vnd.docker.reference.digest"] == $images[0].digest)
  ' "$work/$arch.json" >/dev/null
  sources+=("$source")
done

# A dry-run verifies the assembled descriptor set before any release tag changes.
docker buildx imagetools create --dry-run "${sources[@]}" > "$work/index.json"
jq -e -s '
  ([.[0].manifests[], .[1].manifests[]] | sort_by(.digest))
    == (.[2].manifests | sort_by(.digest))
' "$work/amd64.json" "$work/arm64.json" "$work/index.json" >/dev/null

docker buildx imagetools create \
  --tag "$IMAGE_NAME:$RELEASE_TAG" \
  --tag "$IMAGE_NAME:$VERSION" \
  --tag "$IMAGE_NAME:sha-$SHORT_SHA" \
  --tag "$IMAGE_NAME:latest" \
  "${sources[@]}"
digest="$(docker buildx imagetools inspect "$IMAGE_NAME:$RELEASE_TAG" --format '{{ .Manifest.Digest }}')"
[[ "$digest" =~ ^sha256:[a-f0-9]{64}$ ]]
printf 'digest=%s\n' "$digest" >> "$GITHUB_OUTPUT"
