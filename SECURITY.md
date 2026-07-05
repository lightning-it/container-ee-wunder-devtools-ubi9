# Security Policy

Lightning IT builds and maintains software, automation, and reference
implementations to help customers deliver secure, policy-driven IT services
(e.g. infrastructure building blocks, DevSecOps tooling, blueprints, and
platform integrations). Because our repositories can influence how systems are
deployed, configured, and operated, we treat security-relevant reports
seriously.

This document describes which versions of this **Lightning IT repository** are
supported with security updates and how to report a vulnerability.

> **Note:** Lightning IT maintains multiple repositories (e.g. Ansible
> Collections, Terraform modules, container images, templates, documentation).
> Each repository may have its own lifecycle and release cadence, but the same
> reporting and disclosure principles apply across all Lightning IT projects.

---

## Supported Versions

Lightning IT repositories generally follow semantic versioning
(`MAJOR.MINOR.PATCH`) where applicable:

- **MAJOR** – breaking changes (interfaces, structures, behavior)
- **MINOR** – new features or non-breaking improvements
- **PATCH** – bug fixes and security-related corrections

We currently provide security fixes for:

| Version range | Status |
| --- | --- |
| `main` (or default) branch | ✅ actively supported (security + bugfixes) |
| latest tagged release | ✅ supported (security fixes as needed) |
| older tags / branches | ❌ no guaranteed security updates |

If you are using an older tag or branch, we strongly recommend upgrading to
the latest version from the default branch or the most recent tag before
requesting security fixes.

---

## Reporting a Vulnerability

If you believe you have found a security issue in this repository, for example:

- insecure defaults in automation, templates, or code,
- documentation that encourages unsafe configuration,
- misconfigurations that could weaken security controls,
- leaked credentials, tokens, or sensitive information,
- dependency or supply-chain concerns,

please **do not** open a public issue or pull request.

Instead:

1. Prepare a short report including:
   - a description of the issue and potential impact,
   - which files/components are affected,
   - steps to reproduce (if applicable),
   - any relevant logs/config snippets (redacted as needed).

2. Send your report to:

   - 📧 **security@l-it.io** (preferred), or
   - your existing Lightning IT contact with the subject:
     `Security Report`

3. You will receive an acknowledgement within **3 business days**.

We will then:
- triage the issue (severity, impact, affected versions),
- confirm whether we can reproduce it,
- propose remediation options and an appropriate timeline.

If the vulnerability is confirmed, we will:

- prepare and review a fix (often in a private branch),
- ship a patch or minor release depending on impact,
- document the fix in release notes and/or a changelog where appropriate,
- optionally credit you by name or pseudonym if you wish.

If the report is determined to be a false positive or out of scope, we will
still reply with an explanation.

---

## Scope

This security policy covers:

- the **content of this repository**, including (as applicable):
  - source code,
  - automation definitions (e.g. playbooks, roles, pipelines),
  - container build definitions,
  - templates, configuration, and documentation shipped with the repository.

It does **not** cover:

- upstream products and dependencies (e.g. RHEL, OpenShift, Kubernetes,
  Keycloak, Vault, GitLab, etc.), which follow their own vendor security
  processes.

However, if you discover a vulnerability in a third-party component that is
**introduced or made exploitable** by Lightning IT configuration, packaging,
or guidance, please report it via the process above so we can assess impact and
publish mitigations.

---

## Coordinated Disclosure

We follow responsible, coordinated disclosure principles. Please allow us a
reasonable timeframe to investigate and remediate issues before public
disclosure. If you have a disclosure deadline, include it in your report so we
can coordinate appropriately.
