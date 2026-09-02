# AGENTS.md

## Shared-assets ownership

- This repository receives centrally managed baseline files from `lightning-it/shared-assets-lit`.
- Do not hand-edit shared-managed files in downstream container repositories unless the same change is made in `shared-assets-lit`.
- For container CI changes, treat `shared-assets-lit` as source of truth first.

## Managed files

- Managed default files from `shared-assets-lit/default`:
  - `LICENSE`
  - `CODE_OF_CONDUCT.md`
  - `scripts/wunder-devtools-ee.sh`
  - `scripts/lit-push-ready.py`
- The push-ready engine is upgraded only together with the matching
  `.lit/push-ready.json` schema and `scripts/lit-ci-profile.sh`; specialized
  container sync must not replace the engine by itself during the v2 bootstrap.
- Managed container baseline files from `shared-assets-lit/container/base`:
  - `AGENTS.md`
  - `.gitignore`
  - `.pre-commit-config.yaml`
  - `renovate.json`
  - `.releaserc`
  - `.yamllint`
  - `CONTRIBUTING.md`
  - `.lit/push-ready.json`
  - `scripts/lit-ci-profile.sh`
  - `.github/workflows/container-ci.yml`
  - `.github/workflows/container-build-publish.yml`
  - `.github/workflows/renovate-guarded-automerge.yml`
  - `.github/workflows/shared-assets-guarded-automerge.yml`
  - `.github/workflows/semantic-release.yml`
  - `scripts/devtools-container-ci.sh`
  - `scripts/devtools-container-release-verify.sh`
  - `scripts/container-download-verified.sh`
  - `scripts/ee-entrypoint.sh`
  - `scripts/install-galaxy-content.sh`

## Branch and release model

- `develop` is the default development and integration branch.
- Feature, Renovate, and shared-assets sync PRs target `develop`.
- `main` is the stable production release branch.
- Promotion from `develop` to `main` happens only through a pull request.
- Normal promotion PRs remain a human-visible manual checkpoint. In
  `container-ee-wunder-ansible-ubi9`, that checkpoint is a protected,
  current-head human environment approval. Its reviewer-free authorization
  environment is reserved for exact App-authored, evidence-bound MLX-90
  Security branches and does not bypass any required check or branch rule.
- Merging `develop` into `main` is the container release trigger.
- Use merge commits for `develop` to `main` promotion PRs so branch ancestry remains clear.
- After `main` changes, the shared `sync-main-to-develop` workflow must open a back-sync PR from `main` to `develop` so
  the next promotion PR can be opened without branch drift.
- Repository settings, default branches, branch protection, and workflow permissions belong in `github-management-lit`.
- Container repository cleanup and policy changes must be configured through `github-management-lit` first. Do not
  directly adjust downstream container repository settings or branch enforcement unless the matching desired state is
  represented in `github-management-lit` or an emergency exception is documented in the change summary.

## Semantic release and container publishing

- Container repositories use `semantic-release` on `main` for version calculation, Git tag creation, GitHub Release
  creation, and release notes.
- Do not use `@semantic-release/changelog`, `@semantic-release/git`, or committed `CHANGELOG.md` for container
  repositories unless a repository has an explicit, documented exception.
- The container publish workflow must build from the exact semantic-release tag.
- Released images must publish immutable release-version and commit-SHA tags plus the repository's moving production
  tag, usually `latest`.
- Released images must include OCI labels for source repository, revision, version, creation time, title/name, and any
  repo-specific description/license metadata already in use.
- Release builds must publish SBOM and maximum provenance attestations through Buildx.
- Release images must be signed by digest with keyless Sigstore/Cosign using GitHub OIDC.
- Release verification must inspect all expected tags, compare them to the pushed digest, verify the Cosign identity for
  the repository workflow/tag ref, and record the digest in the workflow summary.
- The repository-specific canonical `scripts/lit-ci-profile.sh repository-quality`
  entrypoint used by PR CI and local push readiness must run the shared
  `scripts/devtools-container-ci.sh all` parity script through the devtools
  container. The workflow uses that canonical profile as its only full-parity
  invocation; prerequisite checkout/ref-refresh steps may precede it, but must
  not duplicate the parity script. Add new PR checks to the parity script first
  so local validation and GitHub validation stay aligned.
- Promotion and ancestry-backmerge controllers are not copied from
  `container/base`. The protected synchronizer renders the canonical root
  promotion workflow to an exact target-repository binding and installs the
  canonical `default` backmerge workflow only after a fail-closed preflight.
- Container vulnerability scans fail on every fixed `HIGH` or `CRITICAL`
  finding. Exceptions require a versioned, evidence-bound VEX or exact ignore
  entry owned centrally in `shared-assets-lit`; report-only HIGH findings are
  forbidden.
- Dockerfiles must not download executable tools without checksum or signature verification. Use the shared
  `scripts/container-download-verified.sh` helper when possible.
- Larger entrypoints and repeated build helpers should be tracked scripts, not embedded heredocs, so shell linting and
  shared review rules can cover them.
- Non-secret ARG names must avoid secret-looking words such as `AUTH`, `TOKEN`, or `PASSWORD` unless the ARG really is a
  secret. Real secrets must use BuildKit secrets or GitHub secrets and must not persist in image layers.

## Dependency pinning

- Keep Dockerfile tool/runtime versions pinned (`ARG ..._VERSION=` or pinned image refs).
- Treat a source-built tool's declared version, immutable source ref or commit,
  and archive checksum as one atomic pin. Its build must derive the reported
  version from that source ref or independently verify the source version;
  never let build flags merely relabel unrelated source. Renovate must update
  the complete tuple atomically, or leave that tuple unmanaged for a reviewed
  manual update. Standalone version managers for such tuples are forbidden.
- For every change to pinned versions in managed files (workflows, scripts, container files), maintain Renovate in the same change (`renovate.json` package rules/custom managers, or the shared-assets-lit Renovate source).
- Validate Renovate config changes before commit (for example: `pre-commit run renovate-config-validate --files renovate.json`).
- Do not relax version pinning in managed container templates without an explicit decision in `shared-assets-lit`.
- Pin third-party GitHub Actions to full-length commit SHAs in shared workflow templates. Keep the human-readable version
  in a YAML comment and ensure Renovate can maintain the pin.
- Pin helper container images used by validation scripts; do not use `latest` for CI linters, scanners, or release
  tooling.

## Push-ready validation

<!-- LIT REP-60 evidence lifecycle: start -->

### REP-60 evidence lifecycle (mandatory)

- Every pull request into `develop` retains its exact-final-head native GitHub
  CI, required-check, and review history as the authoritative evidence for
  acceptance into `develop`.
- A pull request into `develop` MUST NOT create or retain an additional durable
  release-evidence package, duplicate WORM artifact, or second AI-review
  evidence outside that native GitHub history.
- Only the protected `develop` to `main` promotion creates exactly one durable,
  complete release-evidence package. It binds the full integrated promotion
  diff, base, head, merge base, integration tree, policy, reviewer result, and
  all release and audit checks.
- Agents, workflows, and repository-local rules MUST NOT duplicate that durable
  evidence per `develop` pull request or invoke local AI to create evidence.
  Repository-local rules may only make this lifecycle stricter.

<!-- LIT REP-60 evidence lifecycle: end -->

- Before push, run `python3 scripts/lit-push-ready.py push-ready`.
- The only deterministic push-ready and required-CI entrypoint is
  `scripts/lit-ci-profile.sh repository-quality`.
- The profile runs the complete container CI contract through the pinned
  Devtool wrapper. It uses a required local container socket, bridge networking,
  and a read-write workspace only for the nested build/test lifecycle, then
  fails if that lifecycle leaves any Git worktree change behind.
- The Devtools image is the mandatory execution environment for every
  deterministic lint, format, type-check, test, build, packaging, policy, and
  validation command. The host supplies only Git, the supported container
  engine, and the managed Devtools, push-ready, and pre-commit dispatchers. A
  dispatcher may inspect Git state and start the pinned container; it may not
  run a repository validator on the host. Host language runtimes are never
  valid acceptance evidence.
- If the image lacks a command or compatible version, fail closed and update,
  normally release, and centrally repin the image before rerunning the gate.
  Never use a host fallback, ad-hoc virtual environment, or unpinned helper
  image. Keep the default container read-only, offline, socket-free,
  capability-dropped, and non-privileged; grant only a gate's explicit tested
  minimum. Linked-worktree Git metadata stays read-only and container Git may
  trust only `/workspace`, never `*`. Executable temporary fixtures use the
  isolated container home while generic `/tmp` remains non-executable.
- BuildKit cache pruning is GitHub Actions cleanup, not a local validation
  result. Local runs retain their developer cache.
- `AGENTS.md` is the canonical Codex and Copilot contract.
- `.github/copilot-instructions.md` must contain the current managed
  `AGENTS_SHA256` binding.
- Local Push-Ready and `review` execution is deterministic-only. It MUST NOT
  invoke Codex, GitHub Copilot, another model, or any external AI endpoint, and
  it MUST NOT copy personal AI credentials into an isolated home or container.
- Any content change after successful validation invalidates the local evidence.
- GitHub Actions required checks and the current-head review gate remain
  authoritative for merge. Human, community, and unknown-automation PRs
  require an actual Copilot review of the current head. Only explicitly
  allowlisted Renovate and shared-assets changes may use a documented
  deterministic, evidence-bound exception; unknown bots fail closed.
- Automated GitHub Copilot requests funded by Lightning IT are restricted to
  pull requests whose exact author login is `litroc`. Every other human or
  external contributor must supply a valid current-head review under their own
  entitlement; Lightning IT automation verifies that review but never requests
  or funds it. Personal tokens and personal provider keys never enter Actions.
- Every exact same-repository PR authored by
  `lightning-it-release-automation[bot]` uses only the ADR-defined, protected
  MLX-90 §7.2 Exact-Revision Codex review. No deterministic release exemption
  and no GitHub Copilot fallback is permitted. The review binds the live base,
  head, unique merge base, integration tree, and SHA-256 of the complete binary
  Git-object diff. It MUST run from the protected base copy of
  `.github/workflows/release-bot-exact-head-review.yml`, receive no checkout,
  history, or credentials, and emit only the neutral `Current revision review`
  check on the exact head. It MUST never emit or synthesize `Successful Copilot
  review`. The built-in `:read-only` permission profile technically denies
  writes and command network access. This path never applies to human,
  community, or other automation authors.
- Reusable `pull_request_target` re-evaluation binds its executed controller
  SHA and ref to the live protected default branch, even when the PR base is
  different; PR base and head remain separately exact. A `workflow_run`
  finalizer separately re-reads that controller and its runner-backed guard
  job while binding the triggering helper to the exact protected PR base.
  One trust-boundary SHA never substitutes for another.
- A deterministic ancestry-backmerge retry MUST exhaustively read the open and
  closed pull-request history for its exact repository-owned branch, base and
  head before it creates a pull request. Any closed exact match, unexpected
  response shape, or ambiguous inventory fails before PR creation and before
  review dispatch. One already-open exact match may be identity- and
  revision-validated, but the controller MUST exit without redispatching AI or
  re-enabling a failed workflow path. Recovery after terminal evidence uses a
  fresh revision through the normal correction, promotion and backmerge chain;
  it never attaches the same commit to a successor PR.
- Review-authored refresh events are forbidden. During the bounded protected
  cutover, a current write-authorized maintainer may dispatch only the
  protected `develop` refresh for a previously blocked exact Copilot refresh.
  Before any Check API operation it must revalidate that live permission,
  re-read that the live default branch remains protected, and bind the exact
  PR, base, head and review ID. Recovery must prove the blocked refresh and
  request/review time window, then rerun only the failed verifier job. It never
  requests another review or reruns the full workflow.
- `pre-commit` may provide fast feedback, but it is optional and never
  authorizes a push or substitutes for push-ready evidence.

## Repo-specific overrides

- Some container repositories use repo-specific overrides from:
  - `shared-assets-lit/container/overrides/<repo>/...`
- If a file exists in an override path, it supersedes the baseline file from `shared-assets-lit/container/base`.
- For `.github/workflows/container-build-publish.yml`, always check for an override before changing downstream repo copies.
- The Ansible and Toolbox container overrides own repository-specific
  `renovate.json` files whenever a builder image version and digest or a
  release version and immutable Git commit are coupled Dockerfile source pins.
  Renovate must update each pair atomically; never restore a version-only
  manager downstream or hand-edit these managed policies in a target
  repository.
- The Ansible and Toolbox overrides own their clean-rebuild security surfaces:
  `Dockerfile`,
  `scripts/build-patched-go-tools.sh`,
  `rpm-security-updates.lock`, and the required Python dependency manifests.
  Every repository-specific local source referenced by the Dockerfile,
  including RPM and COPR package manifests and `scripts/ee-entrypoint.sh`, must
  be a regular, source-owned file in the same exact override. The override must
  not depend on an unowned downstream build-context file.
  The protected Shared-Assets App distributes the complete repository-specific
  surfaces byte-for-byte. Do not hand-edit or duplicate those files downstream.
- `container-ee-wunder-devtools-ubi9` receives its pipeline-only
  `.lit/push-ready.json`, Dockerfile-specific `renovate.json`, and clean,
  pull-through `scripts/devtools-container-ci.sh` from its repository-specific
  override. Make those changes in `shared-assets-lit` first; never hand-edit
  the downstream managed copies.
- When any managed container repository's installed push-ready engine differs
  from the protected canonical engine, the shared-assets App first opens a
  policy-only bootstrap containing exactly the engine, `.lit/push-ready.json`,
  this `AGENTS.md`, and the rebound Copilot instructions. A later protected source
  run performs the full runtime sync only after the bootstrap is part of the
  target base; the two phases must never be collapsed past the 200,000-byte
  fail-closed review limit.
- `container-ee-wunder-ansible-ubi9` receives its MLX-90 chain only from the
  repository-specific override. Its repo-specific `.releaserc` is a read-only
  version-and-notes plan: the release App persists the draft before it creates
  or reuses the exact lightweight tag. The managed workflow set is:
  - `.github/workflows/semantic-release.yml`
  - `.github/workflows/container-build-publish.yml`
  - `.github/workflows/security-release-update.yml`
  - `.github/workflows/security-release-guard.yml`
  - `.github/workflows/security-release-finalize.yml`
  - `.github/workflows/security-release-reconcile.yml`
  - `.github/workflows/security-release-promote-tags.yml`
  - `.github/workflows/main-promotion-authorization.yml`
- The matching managed MLX-90 scripts include
  `security-release-consumer.py`, `security-release-container-acceptance.sh`,
  `enrich-mlx90-release-evidence.py`, `promote-mlx90-convenience-tags.py`,
  `promote-container-latest.py`, `semantic-release-plan.mjs`,
  `main-promotion-authorization.py`,
  `mlx90_resolve_consumer_merge.py`,
  `validate-semantic-release-boundary.sh`, and the repository-specific
  `devtools-container-release-verify.sh`.
- Keep these files in the override: the container sync intentionally deletes
  downstream workflows to match `container/base` before applying this
  repository-specific layer.
- Governance Apply and a separate live audit of GitHub Release Immutability are
  release preconditions. The release App intentionally has no Administration
  permission and does not call the settings endpoint. The repo-specific
  workflow uses only the job's read token immediately after checkout to verify
  source ancestry plus a byte-identical source/live/default critical surface:
  all workflows, `.releaserc`, `.npmrc`, both package manifests,
  `npm-shrinkwrap.json`, the planner, and the boundary validator. Optional npm
  control files are bound by exact presence or absence. Only then may it mint
  the release App token or install dependencies. Later checks repeat that
  critical-surface comparison and bind
  source/live receipt state. It runs the locked
  semantic-release JS API with `dryRun=true` in an isolated repository, binds
  the returned source SHA, version, tag, notes, and deterministic plan digest,
  then creates or exactly reuses the App-authored draft before it creates or
  verifies the lightweight tag. A shared no-drop concurrency queue serializes
  the mutating planner job with the publisher while leaving PR dry-runs
  independent. A current-source retry must reproduce the exact draft body and
  plan. The exact release name and body SHA-256 remain bound at initial build
  validation, before registry mutation, during attachment retries, immediately
  before publication, and atomically in the publish mutation itself. The PATCH
  response, immutable poll, and finalizer must retain the same name and body
  digest. An
  older draft stranded before dispatch blocks vNext and requires
  human-on-exception completion or reconciliation before rerun.
- The build uploads and byte-verifies the complete release asset allowlist
  while the release is still a draft. It publishes by release ID only after
  the final live receipt and producer-revocation checks, then requires REST
  `immutable=true` on that concrete release before generic tag promotion or
  MLX-90 finalization. A false value fails closed after publication; no
  finalizer, delivered status, or convenience-tag promotion may follow.
- The MLX-90 Security path is digest-authoritative and is an explicit exception
  to generic convenience-tag publication. Each build attempt uses a unique
  `mlx90-candidate-<sha>-<run-id>-<attempt>` tag and never reuses a prior
  candidate. After durable final acceptance, the callback revalidates the exact
  accepted digests, signatures, source identities, and revocation state but
  performs no Quay tag mutation. Quay offers no atomic create-if-absent alias
  operation, so release/version/source-SHA and `latest` aliases are not created
  or retargeted by the Security path.
