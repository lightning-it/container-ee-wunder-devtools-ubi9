# GitHub Copilot review instructions

Review every change for correctness, security, least privilege, and failure behavior. Treat malformed external input as an error rather than coercing it. Check that credentials are scoped to the smallest required job and that GitHub Actions dependencies are pinned to immutable SHAs. For every finding, explain the impact and propose a concrete fix; prefer a regression test for bugs and security issues.
