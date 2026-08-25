#!/usr/bin/env bash
set -euo pipefail

readonly PROFILE_NAME="repository-quality"
readonly AUTHORITATIVE_BASE_REF="refs/remotes/origin/develop"
readonly DEVTOOLS_WRAPPER="scripts/wunder-devtools-ee.sh"
readonly CONTAINER_CI_SCRIPT="scripts/devtools-container-ci.sh"

fail_closed() {
  printf 'Error: %s\n' "$1" >&2
  exit 1
}

if [ "$#" -ne 1 ] || [ "$1" != "$PROFILE_NAME" ]; then
  printf 'Usage: %s %s\n' "${0##*/}" "$PROFILE_NAME" >&2
  exit 2
fi

export LC_ALL=C
umask 077

case "$(uname -s)" in
  Darwin|Linux) ;;
  *) fail_closed "repository-quality supports only macOS and Linux hosts" ;;
esac
case "$(uname -m)" in
  x86_64|amd64|arm64|aarch64) ;;
  *) fail_closed "unsupported host architecture: $(uname -m)" ;;
esac

repository_root="$(git rev-parse --show-toplevel 2>/dev/null)" \
  || fail_closed "run the profile from a Git worktree"
repository_root="$(cd "$repository_root" && pwd -P)"
cd "$repository_root"

for required_path in \
  "$DEVTOOLS_WRAPPER" \
  "$CONTAINER_CI_SCRIPT" \
  "scripts/lit-push-ready.py"
do
  [ -f "$required_path" ] && [ ! -L "$required_path" ] \
    || fail_closed "required regular profile input is missing: $required_path"
done

[ -z "$(git status --porcelain=v1 --untracked-files=all)" ] \
  || fail_closed "repository-quality requires a clean committed worktree"
git show-ref --verify --quiet "$AUTHORITATIVE_BASE_REF" \
  || fail_closed "missing authoritative base ref: $AUTHORITATIVE_BASE_REF"
merge_base="$(git merge-base "$AUTHORITATIVE_BASE_REF" HEAD)" \
  || fail_closed "cannot resolve authoritative merge base"
[ -n "$merge_base" ] || fail_closed "authoritative merge base is empty"
readonly MERGE_BASE="$merge_base"

hidden_index_path=""
while IFS= read -r -d '' index_entry; do
  index_marker="${index_entry:0:1}"
  case "$index_marker" in
    S|[a-z])
      hidden_index_path="${index_entry:2}"
      break
      ;;
  esac
done < <(git ls-files -v -z)
[ -z "$hidden_index_path" ] \
  || fail_closed "hidden Git index flags are not supported: $hidden_index_path"

git_fingerprint() {
  {
    printf 'head\0'
    git rev-parse --verify HEAD
    printf 'tree\0'
    git write-tree
    printf 'status\0'
    git -c core.quotepath=false status \
      --porcelain=v1 --untracked-files=all -z
    printf 'tracked-diff\0'
    git diff --no-ext-diff --no-textconv --binary HEAD --
  } | git hash-object --stdin
}

initial_git_fingerprint="$(git_fingerprint)" \
  || fail_closed "cannot fingerprint initial Git worktree"
readonly INITIAL_GIT_FINGERPRINT="$initial_git_fingerprint"

if [ "${GITHUB_ACTIONS:-}" = "true" ]; then
  readonly PRUNE_BUILDKIT_CACHE="true"
else
  readonly PRUNE_BUILDKIT_CACHE="false"
fi

printf '==> Verify Codex and Copilot instruction binding\n'
env -i \
  PATH=/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin:/opt/homebrew/bin \
  CONTAINER_HOME=/tmp/wunder \
  WUNDER_DEVTOOLS_CAP_ADD= \
  WUNDER_DEVTOOLS_DOCKER_SOCKET=disabled \
  WUNDER_DEVTOOLS_FORWARD_VAGRANT_SSH=disabled \
  WUNDER_DEVTOOLS_MOUNT_SOURCE_ROOT=disabled \
  WUNDER_DEVTOOLS_NETWORK=none \
  WUNDER_DEVTOOLS_PRIVILEGED=0 \
  WUNDER_DEVTOOLS_RUN_AS_HOST_UID=1 \
  WUNDER_DEVTOOLS_WORKSPACE_MODE=ro \
  CI=true \
  GITHUB_ACTIONS= \
  "$DEVTOOLS_WRAPPER" \
  env \
  LC_ALL=C \
  python3 scripts/lit-push-ready.py instructions

printf '==> Run complete container CI contract in the pinned Devtool\n'
env \
  WUNDER_DEVTOOLS_DOCKER_SOCKET=required \
  WUNDER_DEVTOOLS_NETWORK=bridge \
  WUNDER_DEVTOOLS_PRUNE_BUILDKIT_CACHE="$PRUNE_BUILDKIT_CACHE" \
  WUNDER_DEVTOOLS_PRIVILEGED=0 \
  WUNDER_DEVTOOLS_RUN_AS_HOST_UID=0 \
  WUNDER_DEVTOOLS_WORKSPACE_MODE=rw \
  CI=true \
  "$DEVTOOLS_WRAPPER" "$CONTAINER_CI_SCRIPT" all

printf '==> Run committed, worktree, and index diff checks\n'
git diff --check "$MERGE_BASE"...HEAD --
git diff --check
git diff --cached --check

final_git_fingerprint="$(git_fingerprint)" \
  || fail_closed "cannot fingerprint final Git worktree"
readonly FINAL_GIT_FINGERPRINT="$final_git_fingerprint"
[ "$INITIAL_GIT_FINGERPRINT" = "$FINAL_GIT_FINGERPRINT" ] \
  || fail_closed "repository-quality profile changed the Git worktree"

printf 'Repository-quality profile passed.\n'
