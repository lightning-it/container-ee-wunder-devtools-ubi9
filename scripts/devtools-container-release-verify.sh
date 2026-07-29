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
    trivy_default="docker.io/aquasec/trivy:0.72.0@sha256:c6e969c5662a546ad5de4a73c2a6b7a7c627f86d916903e175aa623af5b97ada"
    ;;
  arm64)
    trivy_default="docker.io/aquasec/trivy:0.72.0@sha256:405015d1cd07a2630301169e694a5a420afc4dd553fb462189d4f109ba56a6df"
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

echo "Scanning ${IMAGE_NAME}:${RELEASE_TAG} for HIGH findings (report only)..."
docker run --rm \
  "${trivy_container_args[@]}" \
  "${trivy_workspace_args[@]}" \
  "$trivy_image" image \
  --cache-dir /tmp/trivy-cache \
  --scanners vuln \
  --ignore-unfixed \
  "${trivy_ignore_args[@]}" \
  --severity HIGH \
  --exit-code 0 \
  "${IMAGE_NAME}:${RELEASE_TAG}"

echo "Scanning ${IMAGE_NAME}:${RELEASE_TAG} for CRITICAL findings (release gate)..."
docker run --rm \
  "${trivy_container_args[@]}" \
  "${trivy_workspace_args[@]}" \
  "$trivy_image" image \
  --cache-dir /tmp/trivy-cache \
  --scanners vuln \
  --ignore-unfixed \
  "${trivy_ignore_args[@]}" \
  --severity CRITICAL \
  --exit-code 1 \
  "${IMAGE_NAME}:${RELEASE_TAG}"

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
    echo "- Vulnerability gate: CRITICAL findings fail; HIGH findings are report-only"
    echo
  } >> "$GITHUB_STEP_SUMMARY"
fi
