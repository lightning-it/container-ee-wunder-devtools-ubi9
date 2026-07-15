# Lightning IT contribution guidance

## Pull requests

- Every pull request must request review from GitHub Copilot (`copilot-pull-request-reviewer[bot]`).
- Treat Copilot findings as actionable review comments: reproduce the issue, fix it, and add a regression test where practical.
- Do not dismiss a finding without documenting why it is a false positive in the pull request.
- A pull request is mergeable only after the required human CODEOWNER approval and all automated checks pass.
- Keep changes scoped; do not make unrelated formatting or dependency changes while addressing review feedback.

## Security and fail-closed behavior

- Validate external/API input types explicitly; do not silently coerce malformed values.
- Prefer least-privilege credentials and pin third-party Actions to immutable commit SHAs.
- Add tests for authorization, secret scope, and failure paths when changing governance or release automation.
