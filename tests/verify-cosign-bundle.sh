#!/usr/bin/env bash
# Public release fixture; verify only with standard Sigstore trust.
set -euo pipefail
umask 077

fixtures="${1:-$(dirname -- "${BASH_SOURCE[0]}")/fixtures/cosign}"
subject="${fixtures}/release-security-receipt.json"
bundle="${subject}.sigstore.json"
issuer="https://token.actions.githubusercontent.com"
identity="https://github.com/lightning-it/ansible-collection-supplementary/.github/workflows/collection-ci.yml@refs/heads/main"
workflow_sha="8f862e7ff7d20992735078274b5af2d88ff415f5"

work="$(mktemp -d "${TMPDIR:-/tmp}/cosign-bundle.XXXXXX")"
trap 'rm -rf -- "$work"' EXIT
export HOME="${work}/home"
export XDG_CACHE_HOME="${work}/cache"
mkdir -p "$HOME" "$XDG_CACHE_HOME"

verify() {
  cosign verify-blob --bundle "$bundle" \
    --certificate-oidc-issuer "$issuer" \
    --certificate-identity "$2" \
    --certificate-github-workflow-sha "$3" "$1"
}

reject() {
  local scenario="$1"
  local expected="$2"
  shift 2
  if verify "$@" > "${work}/${scenario}.log" 2>&1; then
    echo "ERROR: Cosign accepted ${scenario}." >&2
    return 1
  fi
  cat "${work}/${scenario}.log"
  if ! grep -Fq -- "$expected" "${work}/${scenario}.log"; then
    echo "ERROR: ${scenario} failed for an unexpected reason." >&2
    return 1
  fi
  printf 'Cosign rejected %s.\n' "$scenario"
}

# The genuine 994-byte subject and certificate bind the public Main workflow.
test "$(wc -c < "$subject" | tr -d ' ')" = 994
verify "$subject" "$identity" "$workflow_sha"
cp "$subject" "${work}/wrong-digest.json"
printf '\n' >> "${work}/wrong-digest.json"
reject wrong-digest 'failed to verify signature' "${work}/wrong-digest.json" "$identity" "$workflow_sha"
reject wrong-workflow-sha 'expected GithubWorkflowSHA to be' \
  "$subject" "$identity" 0000000000000000000000000000000000000000
reject wrong-identity 'expected SAN value' "$subject" \
  https://github.com/lightning-it/ansible-collection-supplementary/.github/workflows/collection-publish.yml@refs/heads/main \
  "$workflow_sha"
echo "Cosign public-bundle contract passed (one positive, three negatives)."
