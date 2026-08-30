#!/usr/bin/env bash
set -euo pipefail

detect_targetarch() {
  case "$(uname -m)" in
    x86_64) echo "amd64" ;;
    aarch64|arm64) echo "arm64" ;;
    *)
      echo "ERROR: unsupported verification architecture: $(uname -m)" >&2
      exit 1
      ;;
  esac
}

require_digest_pinned_image() {
  local name="$1"
  local reference="$2"

  if [[ ! "$reference" =~ ^[^[:space:]@]+@sha256:[a-f0-9]{64}$ ]]; then
    echo "ERROR: ${name} must be an immutable image reference with a sha256 digest." >&2
    exit 1
  fi
}

required_env=(
  IMAGE_NAME
  IMAGE_DIGEST
  RELEASE_TAG
  VERSION
  SHORT_SHA
  GITHUB_REPOSITORY
)

for name in "${required_env[@]}"; do
  if [ -z "${!name:-}" ]; then
    echo "ERROR: ${name} is required." >&2
    exit 1
  fi
done

image_ref="${IMAGE_NAME}@${IMAGE_DIGEST}"
workflow_identity="https://github.com/${GITHUB_REPOSITORY}/.github/workflows/container-build-publish.yml@refs/tags/${RELEASE_TAG}"
workflow_identity_regexp="^https://github\\.com/${GITHUB_REPOSITORY}/\\.github/workflows/container-build-publish\\.yml@refs/tags/${RELEASE_TAG}$"
case "$(detect_targetarch)" in
  amd64)
    trivy_default="docker.io/aquasec/trivy:0.74.0@sha256:ee940acbf1f58ebadb42d01434ce4609530bf1b52536afbd1eee66cd7123c5c9"
    ;;
  arm64)
    trivy_default="docker.io/aquasec/trivy:0.74.0@sha256:55ad20f8a239a3e95427e60b8aaea38788550c18a3f1772976bebf732e6ae166"
    ;;
esac
trivy_image="${TRIVY_IMAGE:-$trivy_default}"
require_digest_pinned_image trivy "$trivy_image"
trivy_workspace_args=(-v "$(pwd -P):/repo:ro" -w /repo)
trivy_container_args=(
  --read-only
  --cap-drop ALL
  --security-opt no-new-privileges=true
  --security-opt label=disable
  --pids-limit 256
  --tmpfs "/tmp:rw,noexec,nosuid,nodev,size=4g"
)
trivy_ignore_args=()

if [ -f .trivyignore ]; then
  trivy_ignore_args=(--ignorefile .trivyignore)
fi

verify_tag_digest() {
  local tag="$1"
  local ref="${IMAGE_NAME}:${tag}"
  local digest

  digest="$(docker buildx imagetools inspect "$ref" --format '{{ .Manifest.Digest }}')"
  if [ "$digest" != "$IMAGE_DIGEST" ]; then
    echo "ERROR: ${ref} points to ${digest}, expected ${IMAGE_DIGEST}." >&2
    exit 1
  fi

  echo "${ref} -> ${digest}"
}

echo "Verifying pushed tags for ${IMAGE_NAME}..."
verify_tag_digest "$RELEASE_TAG"
verify_tag_digest "$VERSION"
verify_tag_digest "sha-${SHORT_SHA}"
verify_tag_digest "latest"

echo "Scanning ${IMAGE_NAME}:${RELEASE_TAG} for HIGH and CRITICAL findings (release gate)..."
docker run --rm \
  "${trivy_container_args[@]}" \
  "${trivy_workspace_args[@]}" \
  "$trivy_image" image \
  --cache-dir /tmp/trivy-cache \
  --scanners vuln \
  --ignore-unfixed \
  "${trivy_ignore_args[@]}" \
  --severity HIGH,CRITICAL \
  --exit-code 1 \
  "${IMAGE_NAME}:${RELEASE_TAG}"

echo "Generating CycloneDX SBOM with vulnerability and license data..."
mkdir -p dist
docker run --rm \
  "${trivy_container_args[@]}" \
  "${trivy_workspace_args[@]}" \
  "$trivy_image" image \
  --cache-dir /tmp/trivy-cache \
  --scanners vuln,license \
  --format cyclonedx \
  "${trivy_ignore_args[@]}" \
  "${IMAGE_NAME}:${RELEASE_TAG}" >dist/sbom.cdx.json
jq -e \
  '.bomFormat == "CycloneDX"
   and (.specVersion | type == "string")
   and (.components | type == "array")' \
  dist/sbom.cdx.json >/dev/null

echo "Signing ${image_ref} with keyless cosign..."
cosign sign --yes "$image_ref"

echo "Verifying keyless cosign signature for ${image_ref}..."
cosign verify \
  --certificate-identity-regexp "$workflow_identity_regexp" \
  --certificate-oidc-issuer "https://token.actions.githubusercontent.com" \
  "$image_ref" >/tmp/cosign-verify.json

cat /tmp/cosign-verify.json

if [ -n "${GITHUB_STEP_SUMMARY:-}" ]; then
  {
    echo "### ${IMAGE_NAME}"
    echo
    echo "- Digest: \`${IMAGE_DIGEST}\`"
    echo "- Signed reference: \`${image_ref}\`"
    echo "- Signing identity: \`${workflow_identity}\`"
    echo "- Tags verified: \`${RELEASE_TAG}\`, \`${VERSION}\`, \`sha-${SHORT_SHA}\`, \`latest\`"
    echo "- Vulnerability gate: HIGH and CRITICAL findings fail"
    echo
  } >> "$GITHUB_STEP_SUMMARY"
fi
