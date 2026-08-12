---
id: adr-renovate-guarded-automerge
title: Guarded automatic merge for Renovate
description: Defines the exact trust and CI boundary for unattended Renovate merges.
slug: /adr/renovate-guarded-automerge/
document:
  status: maintained
  approval_status: approved
  version: "1.0"
  classification: PUBLIC
  owner: Lightning IT Documentation Maintainers
  approver: Lightning IT Product Owners
  audience:
    - repository maintainers
    - platform engineers
  last_reviewed: "2026-08-11"
  review_cadence: annual
---

<!-- Managed by lightning-it/shared-assets-lit. Change the canonical file there. -->

# ADR: Guarded automatic merge for Renovate

- Status: Accepted
- Date: 2026-08-11
- Scope: Active repositories managed by `lightning-it/shared-assets-lit`

## Context

Renovate keeps dependency updates small and current, but unattended merges are
safe only when the pull request identity, update class, current revision, and
required checks are verified. A workflow using the repository `GITHUB_TOKEN`
cannot submit an approving review when GitHub Actions review approval is
disabled. Such a synthetic review is also unnecessary when the protected
integration branch requires zero approving reviews and relies on required
current-head checks.

Ansible Collection dependency updates can modify `galaxy.yml`. The ordinary
collection changelog policy treats that path as user-visible, although a
trusted non-major Renovate dependency-metadata update does not describe a new
collection feature, fix, deprecation, removal, or security change.

## Decision

Repositories whose centrally managed policy enables Renovate use a guarded
workflow rendered as `.github/workflows/renovate-guarded-automerge.yml`.

The workflow may enable auto-merge only when all of these conditions hold:

1. The pull request author and triggering actor are `renovate[bot]`.
2. The source repository is the target repository, the source branch matches
   `renovate/*`, the target branch is `develop`, and the pull request is not a
   draft.
3. The pull request has `renovate`, `dependencies`, and `safe-automerge`, and
   does not have `breaking-update`.
4. The latest `safe-automerge` label event was created by `renovate[bot]`, and
   no `breaking-update` label event exists in the pull-request history.
5. Every commit in the current pull-request head is attributed to
   `renovate[bot]`, committed by GitHub `web-flow`, and has a valid verified
   signature. The newest verified commit equals the live head.
6. The live pull-request head still equals the event head immediately before
   auto-merge is enabled.

The workflow must not create or imitate an approving review. It uses the
least-privilege repository token to enable or revoke GitHub auto-merge and
binds the request to the exact head commit. GitHub performs the eventual merge
only after every protected-branch requirement and required current-head check
passes. A later event that makes the pull request unsafe revokes auto-merge.
A `synchronize` event triggered by any actor other than `renovate[bot]`
revokes auto-merge unconditionally, even when the labels remain unchanged.
The commit-provenance check applies again on every later event, so a bot event
cannot rehabilitate a head whose history contains a human-authored commit.

Major updates, community or human-authored pull requests, cross-repository
pull requests, drafts, updates to `main`, and `develop`-to-`main` promotions
remain manual and are not admitted by this decision.

For Ansible Collections, the changelog-fragment requirement is waived only
when the event satisfies the trusted non-major Renovate identity above and
the only otherwise user-visible changed path is `galaxy.yml`. Any other
user-visible path still requires a normal changelog fragment.

The canonical workflow, this ADR, and the collection changelog policy are
owned by `shared-assets-lit` and distributed as ordinary files. Downstream
repositories must not maintain divergent copies.

## Consequences

- Safe dependency maintenance can merge after CI without a human click.
- Repository settings need not permit GitHub Actions to approve reviews.
- Required checks and exact-head binding remain the merge boundary.
- Major or ambiguously classified updates fail closed and remain visible for
  manual review.
- Merged Renovate branches are deleted according to repository merge policy.
