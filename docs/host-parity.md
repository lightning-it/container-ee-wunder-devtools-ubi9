# Host parity and Dev Container support

The repository Dev Container and the host-parity probe build the image from
the current commit. Downstream repositories must continue to use an immutable
published digest; their Dev Container reference is updated only after this
change has been released.

Managed baseline changes in this implementation are sourced by
[shared-assets-lit#602](https://github.com/lightning-it/shared-assets-lit/pull/602);
they are not downstream-only overrides.

## Acceptance matrix

| Host | Architecture | Runtime | Current evidence |
| --- | --- | --- | --- |
| RHEL supported major | x86_64 | Podman | Pending execution on the target host |
| Ubuntu LTS | x86_64 | Docker | Pending execution on the target host |
| macOS supported major | Apple Silicon | Docker Desktop | Pending execution on the target host |
| macOS supported major | Apple Silicon | Podman machine | Provisional; not supported until separately proven |

Run the host probe from a clean checkout:

```bash
bash scripts/verify-host-parity.sh
```

The command fails closed for unsupported hosts and runtimes, builds the current
commit, launches it without a container-runtime socket, verifies the non-root
toolchain including Node.js and Copilot CLI, and emits a JSON result. Store the
output with the exact commit and workflow evidence in issue
[container-ee-wunder-devtools-ubi9#361](https://github.com/lightning-it/container-ee-wunder-devtools-ubi9/issues/361).

The Dev Container provides Linux toolchain parity. It does not prove
host-kernel behavior or GitHub permissions, secrets, OIDC, registry
availability, signing identity, or GitHub-hosted runner state.
