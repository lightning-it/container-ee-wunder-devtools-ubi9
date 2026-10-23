FROM registry.access.redhat.com/ubi9/python-311:9.8-1779945715@sha256:a0bdb55576fc5b8d6704279307817828ef027e1065533ceba133fe9516003a6c AS go-toolchain

LABEL maintainer="Lightning IT"
LABEL org.opencontainers.image.title="ee-wunder-devtools-ubi9"
LABEL org.opencontainers.image.description="Devtools Execution Environment (UBI 9) for Wunder automation: ansible-lint, yamllint, molecule (docker), and supporting CLI tooling for local + CI workflows."
LABEL org.opencontainers.image.source="https://github.com/lightning-it/container-ee-wunder-devtools-ubi9"

ARG TARGETARCH
ARG GO_VERSION=1.26.10
ARG GO_AMD64_SHA256=ccfe7ae822d2c2f41f4fe7c956199967a4dac22d0ee0d2b2bfdb440aab3b20c5
ARG GO_ARM64_SHA256=3f4227ce7b206a513e794f1393adb473a07b46e94d18bd15d1c684bbb7319797
ARG GO_X_CRYPTO_VERSION=0.57.0
ARG GO_X_MOD_VERSION=0.40.0
ARG GO_X_NET_VERSION=0.60.0
ARG GO_X_TEXT_VERSION=0.42.0
ARG GO_GRPC_VERSION=1.83.2
ARG GO_KLAUSPOST_COMPRESS_VERSION=1.18.7

# hadolint ignore=DL3002
USER 0
SHELL ["/bin/bash", "-o", "pipefail", "-c"]

COPY scripts/container-download-verified.sh /usr/local/lib/container-download-verified.sh
COPY scripts/container-build-go-tool.sh /usr/local/lib/container-build-go-tool.sh
COPY scripts/container-build-compose.sh /usr/local/lib/container-build-compose.sh
COPY scripts/download_go_modules.py /usr/local/lib/download_go_modules.py
COPY container-toolchain/package.json container-toolchain/pnpm-lock.yaml container-toolchain/pnpm-workspace.yaml /opt/node-toolchain/
COPY scripts/verify-renovate-git-runtime.mjs /usr/local/lib/verify-renovate-git-runtime.mjs

RUN dnf --setopt=retries=2 -y update && \
    dnf --setopt=retries=2 -y install --allowerasing ca-certificates curl tar unzip xz && \
    dnf --setopt=retries=2 clean all && rm -rf /var/cache/dnf /var/cache/yum

# Install the official patched Go compiler with architecture-specific hashes
# published by go.dev. Every shipped Go CLI is rebuilt below so Trivy binds
# its evidence to this compiler and the explicitly replaced fixed modules.
RUN source /usr/local/lib/container-download-verified.sh && \
    detect_container_arch && \
    echo "ARCH=${CONTAINER_ARCH}" > /tmp/arch.env && \
    case "${CONTAINER_ARCH}" in \
      amd64) GO_SHA256="${GO_AMD64_SHA256}" ;; \
      arm64) GO_SHA256="${GO_ARM64_SHA256}" ;; \
      *) exit 1 ;; \
    esac && \
    curl -fsSLo /tmp/go.tar.gz \
      "https://go.dev/dl/go${GO_VERSION}.linux-${CONTAINER_ARCH}.tar.gz" && \
    printf '%s  %s\n' "${GO_SHA256}" /tmp/go.tar.gz | sha256sum -c - && \
    tar -C /usr/local -xzf /tmp/go.tar.gz && \
    rm -f /tmp/go.tar.gz && \
    /usr/local/go/bin/go version

ENV PATH=/usr/local/go/bin:$PATH \
    GOTOOLCHAIN=local \
    GOPROXY=https://proxy.golang.org \
    GOSUMDB=sum.golang.org \
    CGO_ENABLED=0

FROM go-toolchain AS cosign-builder

ARG COSIGN_VERSION=3.0.6
ARG COSIGN_SOURCE_COMMIT=f1ad3ee952313be5d74a49d67ba0aa8d0d5e351f
ARG COSIGN_SOURCE_SHA256=8be1ce19a8865baaa7e4aa44fcee27ae6a3247ba9ce05f145c2f3f5b2ed485d9
ARG COSIGN_FULCIO_VERSION=1.8.6
ARG COSIGN_REKOR_VERSION=1.5.5

# The signed tag binds the unchanged CLI source. Apply explicit security
# dependency replacements, then bind the resulting locks before offline build.
RUN curl -fsSLo /tmp/cosign-tag.json \
      https://api.github.com/repos/sigstore/cosign/git/tags/77891cd80a8f2bac1a2bf2f37f2e6005df38e51a && \
    python3 -c 'import json,sys; t=json.load(open(sys.argv[1])); assert t["tag"] == "v"+sys.argv[2] and t["object"]["type"] == "commit" and t["object"]["sha"] == sys.argv[3] and t["verification"]["verified"] is True' \
      /tmp/cosign-tag.json "${COSIGN_VERSION}" "${COSIGN_SOURCE_COMMIT}" && \
    curl -fsSLo /tmp/cosign.tar.gz \
      "https://github.com/sigstore/cosign/archive/${COSIGN_SOURCE_COMMIT}.tar.gz" && \
    printf '%s  %s\n' "${COSIGN_SOURCE_SHA256}" /tmp/cosign.tar.gz | sha256sum -c - && \
    mkdir -p /tmp/cosign-source /out && \
    tar -xzf /tmp/cosign.tar.gz --strip-components=1 -C /tmp/cosign-source && \
    cd /tmp/cosign-source && \
    go mod edit \
      "-replace=github.com/sigstore/fulcio=github.com/sigstore/fulcio@v${COSIGN_FULCIO_VERSION}" \
      "-replace=github.com/sigstore/rekor=github.com/sigstore/rekor@v${COSIGN_REKOR_VERSION}" \
      "-replace=github.com/klauspost/compress=github.com/klauspost/compress@v${GO_KLAUSPOST_COMPRESS_VERSION}" \
      "-replace=golang.org/x/crypto=golang.org/x/crypto@v${GO_X_CRYPTO_VERSION}" \
      "-replace=golang.org/x/mod=golang.org/x/mod@v${GO_X_MOD_VERSION}" \
      "-replace=golang.org/x/net=golang.org/x/net@v${GO_X_NET_VERSION}" \
      "-replace=golang.org/x/text=golang.org/x/text@v${GO_X_TEXT_VERSION}" \
      "-replace=google.golang.org/grpc=google.golang.org/grpc@v${GO_GRPC_VERSION}" && \
    mkdir /tmp/cosign-module-prefetch && \
    cp go.mod go.sum /tmp/cosign-module-prefetch/ && \
    cd /tmp/cosign-module-prefetch && \
    python3 /usr/local/lib/download_go_modules.py && \
    cd /tmp/cosign-source && \
    GOPROXY=off go mod tidy && \
    GOPROXY=off go mod verify && \
    sha256sum go.mod go.sum > /tmp/cosign-module-locks.sha256 && \
    rm -rf /tmp/cosign-module-prefetch

RUN --network=none cd /tmp/cosign-source && \
    CGO_ENABLED=0 GOPROXY=off go build \
      -mod=readonly -trimpath -buildvcs=false \
      -ldflags="-buildid= -s -w \
        -X sigs.k8s.io/release-utils/version.gitVersion=v${COSIGN_VERSION} \
        -X sigs.k8s.io/release-utils/version.gitCommit=${COSIGN_SOURCE_COMMIT} \
        -X sigs.k8s.io/release-utils/version.gitTreeState=dirty" \
      -o /out/cosign ./cmd/cosign && \
    sha256sum -c /tmp/cosign-module-locks.sha256 && \
    /out/cosign version --json | python3 -c 'import json,sys; v=json.load(sys.stdin); assert v["gitVersion"] == "v"+sys.argv[1] and v["gitCommit"] == sys.argv[2] and v["gitTreeState"] == "dirty"' \
      "${COSIGN_VERSION}" "${COSIGN_SOURCE_COMMIT}" && \
    for coordinate in \
      "github.com/sigstore/fulcio@v${COSIGN_FULCIO_VERSION}" \
      "github.com/sigstore/rekor@v${COSIGN_REKOR_VERSION}" \
      "github.com/klauspost/compress@v${GO_KLAUSPOST_COMPRESS_VERSION}" \
      "golang.org/x/crypto@v${GO_X_CRYPTO_VERSION}" \
      "golang.org/x/mod@v${GO_X_MOD_VERSION}" \
      "golang.org/x/net@v${GO_X_NET_VERSION}" \
      "golang.org/x/text@v${GO_X_TEXT_VERSION}" \
      "google.golang.org/grpc@v${GO_GRPC_VERSION}"; do \
        module="${coordinate%@*}"; expected="${coordinate##*@}"; \
        effective="$(go version -m /out/cosign | awk -v module="$module" \
          '$1 == "dep" && $2 == module { version = $3 } $1 == "=>" && $2 == module { version = $3 } END { print version }')"; \
        if [ "$effective" != "$expected" ]; then \
          printf 'ERROR: cosign links %s %s, expected %s\n' "$module" "${effective:-<missing>}" "$expected" >&2; \
          exit 1; \
        fi; \
    done && \
    cd / && rm -rf /tmp/cosign-source /tmp/cosign.tar.gz \
      /tmp/cosign-tag.json /tmp/cosign-module-locks.sha256

FROM go-toolchain AS incus-client

ARG INCUS_VERSION=7.0.2
ARG INCUS_SOURCE_COMMIT=01f81e5e607bbb5818410318e4b3496ad1820824
ARG INCUS_SOURCE_SHA256=f2319b13151c3b4181b025a55e4199d60a1c829a24e422d8c6448a63da8a0ed9

# Build only the Incus client with its unchanged upstream module lock.
# This supplies no daemon, connection configuration, socket or credentials.
RUN mkdir -p /out && \
    curl -fsSLo /tmp/incus.tar.gz \
      "https://github.com/lxc/incus/archive/${INCUS_SOURCE_COMMIT}.tar.gz" && \
    printf '%s  %s\n' "${INCUS_SOURCE_SHA256}" /tmp/incus.tar.gz | sha256sum -c - && \
    mkdir -p /tmp/incus-source && \
    tar -xzf /tmp/incus.tar.gz --strip-components=1 -C /tmp/incus-source && \
    cd /tmp/incus-source && \
    grep -Fx "var Version = \"${INCUS_VERSION}\"" internal/version/flex.go && \
    python3 /usr/local/lib/download_go_modules.py && \
    GOPROXY=off go mod verify && \
    CGO_ENABLED=0 GOPROXY=off go build \
      -mod=readonly -trimpath -buildvcs=false -ldflags="-s -w" \
      -o /out/incus ./cmd/incus && \
    test "$(/out/incus --version)" = "${INCUS_VERSION}" && \
    cd / && \
    rm -rf /tmp/incus.tar.gz /tmp/incus-source

FROM incus-client AS tools

ARG TF_VERSION=1.15.9
ARG TF_SOURCE_COMMIT=87488977e32a400445e0c0b4d95c0713a5eee941
ARG TF_SOURCE_SHA256=b4036b35e69a57e4a4b83bafba337a5c8e3ab2c0b1812df92528dec0958ed61e
ARG PACKER_VERSION=1.16.1
ARG PACKER_SOURCE_COMMIT=8d3617fc870d5f08a598806a43d49ed6ee4d08ab
ARG PACKER_SOURCE_SHA256=8d704ef397531cb29ce5f7e9b4b0754be2ddffaaa3a52bd84fefdc75caa20aa6
ARG TFLINT_VERSION=0.64.0
ARG TF_DOCS_VERSION=0.24.0
ARG HELM_VERSION=4.2.4
ARG GH_VERSION=2.98.0
ARG ACTIONLINT_VERSION=1.7.12
ARG DOCKER_SOURCE_COMMIT=a7dcaa6fdb6ed04aacbfdc76357fdae01605609e
ARG DOCKER_SOURCE_SHA256=6e5c91d3a5a79db78cf989d07727d00e757aa0da4d135a3ce4b86061b83fb511
ARG COMPOSE_VERSION=5.5.1
ARG BUILDX_VERSION=0.36.1
ARG MOBY_V2_VERSION=2.0.0-beta.21
ARG MOBY_NAMESGENERATOR_SHA256=79ed19fb5afd19ccb3284213961335ec2f22ac9e8181971cab377de740361bbb
ARG NODE_VERSION=24.19.0
ARG WEBSITE_NODE_VERSION=24.18.0
ARG ORAS_GO_VERSION=2.6.2

RUN mkdir -p /out && \
    /usr/local/lib/container-build-go-tool.sh \
      github.com/rhysd/actionlint "v${ACTIONLINT_VERSION}" ./cmd/actionlint actionlint

RUN curl -fsSLo /tmp/terraform.tar.gz \
      "https://github.com/hashicorp/terraform/archive/${TF_SOURCE_COMMIT}.tar.gz" && \
    printf '%s  %s\n' "${TF_SOURCE_SHA256}" /tmp/terraform.tar.gz | sha256sum -c - && \
    mkdir -p /tmp/terraform-source && \
    tar -xzf /tmp/terraform.tar.gz --strip-components=1 -C /tmp/terraform-source && \
    cd /tmp/terraform-source && \
    go mod edit "-require=google.golang.org/grpc@v${GO_GRPC_VERSION}" && \
    go mod edit \
      "-replace=golang.org/x/crypto=golang.org/x/crypto@v${GO_X_CRYPTO_VERSION}" \
      "-replace=golang.org/x/net=golang.org/x/net@v${GO_X_NET_VERSION}" \
      "-replace=golang.org/x/text=golang.org/x/text@v${GO_X_TEXT_VERSION}" && \
    python3 /usr/local/lib/download_go_modules.py && \
    GOPROXY=off go get "google.golang.org/grpc@v${GO_GRPC_VERSION}" && \
    test "$(GOPROXY=off go list -m -f '{{.Version}}' google.golang.org/grpc)" = \
      "v${GO_GRPC_VERSION}" && \
    GOPROXY=off go mod verify && \
    CGO_ENABLED=0 GOPROXY=off go build \
      -trimpath -buildvcs=false \
      -ldflags="-s -w -X github.com/hashicorp/terraform/version.dev=no" \
      -o /out/terraform . && \
    test "$(/out/terraform version | head -n 1)" = "Terraform v${TF_VERSION}" && \
    cd / && \
    rm -rf /tmp/terraform.tar.gz /tmp/terraform-source

# Build the same Packer release from its immutable source commit so the
# shipped binary uses the patched Go standard library and x/net module.
RUN curl -fsSLo /tmp/packer.tar.gz \
      "https://github.com/hashicorp/packer/archive/${PACKER_SOURCE_COMMIT}.tar.gz" && \
    printf '%s  %s\n' "${PACKER_SOURCE_SHA256}" /tmp/packer.tar.gz | sha256sum -c - && \
    mkdir -p /tmp/packer-source && \
    tar -xzf /tmp/packer.tar.gz --strip-components=1 -C /tmp/packer-source && \
    cd /tmp/packer-source && \
    go mod edit \
      "-replace=golang.org/x/crypto=golang.org/x/crypto@v${GO_X_CRYPTO_VERSION}" \
      "-replace=golang.org/x/net=golang.org/x/net@v${GO_X_NET_VERSION}" \
      "-replace=golang.org/x/text=golang.org/x/text@v${GO_X_TEXT_VERSION}" && \
    python3 /usr/local/lib/download_go_modules.py && \
    GOPROXY=off go mod tidy && \
    CGO_ENABLED=0 GOPROXY=off go build \
      -trimpath -buildvcs=false \
      -ldflags="-s -w -X github.com/hashicorp/packer/version.GitCommit=${PACKER_SOURCE_COMMIT}" \
      -o /out/packer . && \
    test "$(CHECKPOINT_DISABLE=1 /out/packer version | head -n 1)" = \
      "Packer v${PACKER_VERSION}" && \
    cd / && \
    rm -rf /tmp/packer.tar.gz /tmp/packer-source

RUN /usr/local/lib/container-build-go-tool.sh \
      github.com/terraform-linters/tflint "v${TFLINT_VERSION}" . tflint \
      "golang.org/x/mod@v${GO_X_MOD_VERSION}" \
      "golang.org/x/net@v${GO_X_NET_VERSION}" \
      "google.golang.org/grpc@v${GO_GRPC_VERSION}" \
      "github.com/klauspost/compress@v${GO_KLAUSPOST_COMPRESS_VERSION}" && \
    test "$(go version -m /out/tflint | awk \
      '$1 == "dep" && $2 == "github.com/klauspost/compress" { version = $3 } \
       $1 == "=>" && $2 == "github.com/klauspost/compress" { version = $3 } \
       END { print version }')" = "v${GO_KLAUSPOST_COMPRESS_VERSION}"

RUN /usr/local/lib/container-build-go-tool.sh \
      github.com/terraform-docs/terraform-docs "v${TF_DOCS_VERSION}" . terraform-docs \
      "golang.org/x/crypto@v${GO_X_CRYPTO_VERSION}" \
      "golang.org/x/net@v${GO_X_NET_VERSION}" \
      "golang.org/x/text@v${GO_X_TEXT_VERSION}" \
      "google.golang.org/grpc@v${GO_GRPC_VERSION}"

RUN /usr/local/lib/container-build-go-tool.sh \
      helm.sh/helm/v4 "v${HELM_VERSION}" ./cmd/helm helm \
      "golang.org/x/crypto@v${GO_X_CRYPTO_VERSION}" \
      "golang.org/x/net@v${GO_X_NET_VERSION}" \
      "golang.org/x/text@v${GO_X_TEXT_VERSION}" \
      "oras.land/oras-go/v2@v${ORAS_GO_VERSION}"

RUN /usr/local/lib/container-build-go-tool.sh \
      github.com/cli/cli/v2 "v${GH_VERSION}" ./cmd/gh gh \
      "golang.org/x/mod@v${GO_X_MOD_VERSION}" \
      "golang.org/x/net@v${GO_X_NET_VERSION}" \
      "google.golang.org/grpc@v${GO_GRPC_VERSION}"

RUN curl -fsSLo /tmp/docker-cli.tar.gz \
      "https://github.com/docker/cli/archive/${DOCKER_SOURCE_COMMIT}.tar.gz" && \
    printf '%s  %s\n' "${DOCKER_SOURCE_SHA256}" /tmp/docker-cli.tar.gz | sha256sum -c - && \
    mkdir -p /tmp/docker-cli-source && \
    tar -xzf /tmp/docker-cli.tar.gz --strip-components=1 -C /tmp/docker-cli-source && \
    cd /tmp/docker-cli-source && \
    docker_source_version="$(tr -d '\r\n' < VERSION)" && \
    [[ "$docker_source_version" =~ ^[0-9]+\.[0-9]+\.[0-9]+([.-][0-9A-Za-z.-]+)?$ ]] && \
    cp vendor.mod go.mod && \
    cp vendor.sum go.sum && \
    GOFLAGS=-mod=mod go get \
      "golang.org/x/net@v${GO_X_NET_VERSION}" \
      "google.golang.org/grpc@v${GO_GRPC_VERSION}" && \
    test "$(GOFLAGS=-mod=mod go list -m -f '{{.Version}}' golang.org/x/net)" = \
      "v${GO_X_NET_VERSION}" && \
    test "$(GOFLAGS=-mod=mod go list -m -f '{{.Version}}' google.golang.org/grpc)" = \
      "v${GO_GRPC_VERSION}" && \
    CGO_ENABLED=0 GOFLAGS=-mod=mod go build \
      -trimpath -buildvcs=false \
      -ldflags="-s -w \
        -X github.com/docker/cli/cli/version.Version=${docker_source_version} \
        -X github.com/docker/cli/cli/version.GitCommit=${DOCKER_SOURCE_COMMIT}" \
      -o /out/docker ./cmd/docker && \
    docker_version="$(/out/docker --version)" && \
    [[ "$docker_version" == "Docker version ${docker_source_version},"* ]] && \
    cd / && \
    rm -rf /tmp/docker-cli.tar.gz /tmp/docker-cli-source

RUN /usr/local/lib/container-build-compose.sh \
      "${COMPOSE_VERSION}" \
      "${BUILDX_VERSION}" \
      "${MOBY_V2_VERSION}" \
      "${MOBY_NAMESGENERATOR_SHA256}" \
      "${GO_X_MOD_VERSION}" \
      "${GO_X_NET_VERSION}" \
      "${GO_GRPC_VERSION}"

RUN set -euo pipefail; \
    for binary in terraform tflint terraform-docs gh docker docker-compose; do \
      effective_version="$( \
        go version -m "/out/${binary}" | \
          awk -v module='google.golang.org/grpc' ' \
            $1 == "dep" && $2 == module { version = $3 } \
            $1 == "=>" && $2 == module { version = $3 } \
            END { print version } \
          ' \
      )"; \
      if [ "${effective_version}" != "v${GO_GRPC_VERSION}" ]; then \
        printf 'ERROR: %s links google.golang.org/grpc %s, expected v%s\n' \
          "${binary}" "${effective_version:-<missing>}" "${GO_GRPC_VERSION}" >&2; \
        exit 1; \
      fi; \
    done

RUN set -euo pipefail; \
    for binary in packer terraform tflint terraform-docs helm gh docker docker-compose; do \
      effective_version="$( \
        go version -m "/out/${binary}" | \
          awk -v module='golang.org/x/net' ' \
            $1 == "dep" && $2 == module { version = $3 } \
            $1 == "=>" && $2 == module { version = $3 } \
            END { print version } \
          ' \
      )"; \
      if [ "${effective_version}" != "v${GO_X_NET_VERSION}" ]; then \
        printf 'ERROR: %s links golang.org/x/net %s, expected v%s\n' \
          "${binary}" "${effective_version:-<missing>}" "${GO_X_NET_VERSION}" >&2; \
        exit 1; \
      fi; \
    done

# Keep repository configuration changes out of the expensive DNF and Go build
# cache boundary while validating them with the exact shipped Renovate runtime.
COPY renovate.json /tmp/renovate.json

# Node.js LTS plus deterministic repository validators. The independently
# selected website runtime remains bundled so repositories declaring its exact
# .node-version never need a host or worktree-local bootstrap. Node release
# checksums and the committed pnpm lock cover both target architectures.
# The image deliberately contains no local AI client or AI credentials.
RUN source /usr/local/lib/container-download-verified.sh && \
    source /tmp/arch.env && \
    case "${ARCH}" in amd64) NODE_ARCH=x64 ;; arm64) NODE_ARCH=arm64 ;; *) exit 1 ;; esac && \
    download_verified \
      "https://nodejs.org/download/release/v${NODE_VERSION}/node-v${NODE_VERSION}-linux-${NODE_ARCH}.tar.xz" \
      /tmp/node.tar.xz \
      "https://nodejs.org/download/release/v${NODE_VERSION}/SHASUMS256.txt" \
      "node-v${NODE_VERSION}-linux-${NODE_ARCH}.tar.xz" && \
    mkdir -p /opt/node && \
    tar -xJf /tmp/node.tar.xz --strip-components=1 -C /opt/node && \
    download_verified \
      "https://nodejs.org/download/release/v${WEBSITE_NODE_VERSION}/node-v${WEBSITE_NODE_VERSION}-linux-${NODE_ARCH}.tar.xz" \
      /tmp/node-website.tar.xz \
      "https://nodejs.org/download/release/v${WEBSITE_NODE_VERSION}/SHASUMS256.txt" \
      "node-v${WEBSITE_NODE_VERSION}-linux-${NODE_ARCH}.tar.xz" && \
    mkdir -p /opt/node-website && \
    tar -xJf /tmp/node-website.tar.xz --strip-components=1 -C /opt/node-website && \
    export PATH="/opt/node/bin:${PATH}" && \
    cd /opt/node-toolchain && \
    pnpm_version="$(/opt/node/bin/node -p \
      "require('/opt/node-toolchain/package.json').dependencies.pnpm")" && \
    [[ "$pnpm_version" =~ ^[0-9]+\.[0-9]+\.[0-9]+$ ]] && \
    /opt/node/bin/corepack "pnpm@${pnpm_version}" install \
      --frozen-lockfile --ignore-scripts --strict-peer-dependencies \
      --store-dir /tmp/pnpm-store && \
    for npm_tree in npm npm-website; do \
      for package in brace-expansion ip-address tar undici; do \
        version="$(/opt/node/bin/node -p \
          'require(process.argv[1]).version' \
          "/opt/node-toolchain/node_modules/${package}/package.json")" && \
        rm -rf "/opt/node-toolchain/node_modules/${npm_tree}/node_modules/${package}" && \
        cp -aL "/opt/node-toolchain/node_modules/${package}" \
          "/opt/node-toolchain/node_modules/${npm_tree}/node_modules/${package}" && \
        test "$(/opt/node/bin/node -p \
          'require(process.argv[1]).version' \
          "/opt/node-toolchain/node_modules/${npm_tree}/node_modules/${package}/package.json")" \
          = "${version}" || exit 1; \
      done; \
    done && \
    for package in pacote; do \
      version="$(/opt/node/bin/node -p \
        'require(process.argv[1]).version' \
        "/opt/node-toolchain/node_modules/${package}/package.json")" && \
      rm -rf "/opt/node-toolchain/node_modules/npm-website/node_modules/${package}" && \
      cp -aL "/opt/node-toolchain/node_modules/${package}" \
        "/opt/node-toolchain/node_modules/npm-website/node_modules/${package}" && \
      test "$(/opt/node/bin/node -p \
        'require(process.argv[1]).version' \
        "/opt/node-toolchain/node_modules/npm-website/node_modules/${package}/package.json")" \
          = "${version}" || exit 1; \
    done && \
    undici_version="$(/opt/node/bin/node -p \
      "require('/opt/node-toolchain/package.json').dependencies.undici")" && \
    [[ "$undici_version" =~ ^[0-9]+\.[0-9]+\.[0-9]+$ ]] && \
    for pnpm_tree in \
      /opt/node-toolchain/node_modules/pnpm/dist \
      /opt/node-toolchain/node_modules/pnpm/artifacts/exe/dist; do \
      rm -rf "${pnpm_tree}/node_modules/undici" && \
      cp -aL /opt/node-toolchain/node_modules/undici \
        "${pnpm_tree}/node_modules/undici" && \
      test "$(/opt/node/bin/node -p \
        'require(process.argv[1]).version' \
        "${pnpm_tree}/node_modules/undici/package.json")" \
        = "${undici_version}" || exit 1; \
    done && \
    rm -rf /opt/node/lib/node_modules/npm && \
    rm -f /opt/node/bin/npm /opt/node/bin/npx /opt/node/bin/pnpm && \
    rm -rf /opt/node-website/lib/node_modules/npm && \
    rm -f /opt/node-website/bin/npm /opt/node-website/bin/npx && \
    chmod 0755 /opt/node-toolchain/node_modules/pnpm/bin/pnpm.cjs && \
    ln -s /opt/node-toolchain/node_modules/npm/bin/npm-cli.js /opt/node/bin/npm && \
    ln -s /opt/node-toolchain/node_modules/npm/bin/npx-cli.js /opt/node/bin/npx && \
    ln -s /opt/node-toolchain/node_modules/pnpm/bin/pnpm.cjs /opt/node/bin/pnpm && \
    ln -s /opt/node-toolchain/node_modules/renovate/dist/renovate.js /opt/node/bin/renovate && \
    ln -s /opt/node-toolchain/node_modules/renovate/dist/config-validator.js /opt/node/bin/renovate-config-validator && \
    ln -s /opt/node-toolchain/node_modules/markdownlint-cli2/markdownlint-cli2-bin.mjs /opt/node/bin/markdownlint-cli2 && \
    ln -s /opt/node-toolchain/node_modules/prettier/bin/prettier.cjs /opt/node/bin/prettier && \
    ln -s /opt/node-toolchain/node_modules/npm-website/bin/npm-cli.js /opt/node-website/bin/npm && \
    ln -s /opt/node-toolchain/node_modules/npm-website/bin/npx-cli.js /opt/node-website/bin/npx && \
    /opt/node/bin/node --version && \
    /opt/node/bin/npm --version && \
    /opt/node/bin/pnpm --version && \
    /opt/node/bin/renovate-config-validator --version && \
    /opt/node/bin/node /usr/local/lib/verify-renovate-git-runtime.mjs && \
    /opt/node/bin/renovate-config-validator --strict --no-global /tmp/renovate.json && \
    /opt/node/bin/markdownlint-cli2 --version && \
    /opt/node/bin/prettier --version && \
    test "$(/opt/node-website/bin/node --version)" = "v${WEBSITE_NODE_VERSION}" && \
    test "$(PATH=/opt/node-website/bin:${PATH} /opt/node-website/bin/npm --version)" = "11.16.0" && \
    rm -f /tmp/node.tar.xz /tmp/node-website.tar.xz /tmp/renovate.json && \
    rm -rf /tmp/pnpm-store /opt/node-toolchain/.npm

# Isolate the validator build from the large Devtools toolchain. This stage uses
# immutable upstream archives for Java, Maven, and Ant instead of installing the
# full graphical OpenJDK dependency tree from the UBI repositories.
FROM registry.access.redhat.com/ubi9/python-311:9.8-1779945715@sha256:a0bdb55576fc5b8d6704279307817828ef027e1065533ceba133fe9516003a6c AS vnu-builder

ARG TARGETARCH
ARG VNU_SOURCE_COMMIT=c4720cafffd1f93358ca824163fc5bbdb35fb0e0
ARG VNU_SOURCE_SHA256=8838c4842d084792221832f52872ffc58208eeee84200c3064a1fb0ea7f87d96
ARG VNU_VERSION=26.8.29
ARG VNU_JAR_SHA256=013e20d82c99326b08cb59281ca68b4eb1dad007fcacc38d76d7ed0c5c200353
ARG VNU_JETTY_VERSION=12.0.38
ARG VNU_RELOAD4J_VERSION=1.2.26
ARG VNU_JDK_VERSION=17.0.20_8
ARG VNU_JDK_AMD64_SHA256=be7668bc030d578b83d6d5ef9221d6d6729bbbca8cf94a7d52e16ac68b5a5a35
ARG VNU_JDK_ARM64_SHA256=d143936f473a4cb24e3b0e247d6d0775769d55ec9775c339540e753059a8d77a
ARG VNU_MAVEN_VERSION=3.9.11
ARG VNU_MAVEN_SHA512=bcfe4fe305c962ace56ac7b5fc7a08b87d5abd8b7e89027ab251069faebee516b0ded8961445d6d91ec1985dfe30f8153268843c89aa392733d1a3ec956c9978
ARG VNU_ANT_VERSION=1.10.15
ARG VNU_ANT_SHA256=4d5bb20cee34afbad17782de61f4f422c5a03e4d2dffc503bcbd0651c3d3c396
ARG VNU_JRE_VERSION=17.0.20_8
ARG VNU_JRE_AMD64_SHA256=ef491a51a46ef90cc47fbc4abb219fde32483ff91be5ec66ddc896df43524b27
ARG VNU_JRE_ARM64_SHA256=9d14a95e07c44bc48666625162baf40db9da4dcb192bfc3e43047790693061a2

USER 0
SHELL ["/bin/bash", "-o", "pipefail", "-c"]

RUN dnf --setopt=retries=2 -y install --allowerasing --setopt=install_weak_deps=False \
      ca-certificates curl gzip patch tar unzip xz && \
    dnf --setopt=retries=2 clean all && rm -rf /var/cache/dnf /var/cache/yum

RUN test -n "${TARGETARCH}" && \
    case "${TARGETARCH}" in \
      amd64) \
        VNU_JDK_SHA256="${VNU_JDK_AMD64_SHA256}"; \
        VNU_JDK_ARCH=x64; \
        ;; \
      arm64) \
        VNU_JDK_SHA256="${VNU_JDK_ARM64_SHA256}"; \
        VNU_JDK_ARCH=aarch64; \
        ;; \
      *) exit 1 ;; \
    esac && \
    curl --fail --show-error --silent --location --retry 2 --retry-delay 2 \
      --output /tmp/vnu-jdk.tar.gz \
      "https://github.com/adoptium/temurin17-binaries/releases/download/jdk-${VNU_JDK_VERSION/_/%2B}/OpenJDK17U-jdk_${VNU_JDK_ARCH}_linux_hotspot_${VNU_JDK_VERSION}.tar.gz" && \
    printf '%s  %s\n' "${VNU_JDK_SHA256}" /tmp/vnu-jdk.tar.gz | \
      sha256sum --check --status && \
    mkdir -p /opt/jdk && \
    tar -xzf /tmp/vnu-jdk.tar.gz --strip-components=1 -C /opt/jdk && \
    test -x /opt/jdk/bin/java && \
    test "$(/opt/jdk/bin/javac -version 2>&1)" = \
      "javac ${VNU_JDK_VERSION%_*}" && \
    grep -Fq "IMPLEMENTOR=\"Eclipse Adoptium\"" /opt/jdk/release && \
    grep -Fq "JAVA_RUNTIME_VERSION=\"${VNU_JDK_VERSION/_/+}\"" /opt/jdk/release && \
    rm -f /tmp/vnu-jdk.tar.gz

RUN curl --fail --show-error --location --retry 2 --retry-delay 2 \
      --output /tmp/apache-maven.tar.gz \
      "https://archive.apache.org/dist/maven/maven-3/${VNU_MAVEN_VERSION}/binaries/apache-maven-${VNU_MAVEN_VERSION}-bin.tar.gz" && \
    printf '%s  %s\n' "${VNU_MAVEN_SHA512}" /tmp/apache-maven.tar.gz | \
      sha512sum --check --status && \
    mkdir -p /opt/maven && \
    tar -xzf /tmp/apache-maven.tar.gz --strip-components=1 -C /opt/maven && \
    JAVA_HOME=/opt/jdk /opt/maven/bin/mvn --version | \
      grep -Fq "Apache Maven ${VNU_MAVEN_VERSION}" && \
    rm -f /tmp/apache-maven.tar.gz && \
    curl --fail --show-error --location --retry 2 --retry-delay 2 \
      --output /tmp/apache-ant.tar.xz \
      "https://archive.apache.org/dist/ant/binaries/apache-ant-${VNU_ANT_VERSION}-bin.tar.xz" && \
    printf '%s  %s\n' "${VNU_ANT_SHA256}" /tmp/apache-ant.tar.xz | \
      sha256sum --check --status && \
    mkdir -p /opt/ant && \
    tar -xJf /tmp/apache-ant.tar.xz --strip-components=1 -C /opt/ant && \
    ant_version="$(JAVA_HOME=/opt/jdk PATH=/opt/jdk/bin:${PATH} \
      /opt/ant/bin/ant -version)" && \
    [[ "${ant_version}" == \
      "Apache Ant(TM) version ${VNU_ANT_VERSION} compiled on "* ]] && \
    rm -f /tmp/apache-ant.tar.xz

# Build the W3C Nu HTML Checker from its immutable upstream source. The rolling
# release fat JAR currently embeds end-of-life Log4j 1.2 and a vulnerable Jetty
# patch level. The narrow, reviewed patch retains Nu's CLI while moving those
# dependencies to Reload4j and the fixed Jetty 12.0 line. Every source input is
# checksum-bound and the final image is still subject to the mandatory scan.
COPY patches/vnu-secure-dependencies.patch /tmp/vnu-secure-dependencies.patch
COPY scripts/normalize-vnu-jar.py /tmp/normalize-vnu-jar.py
RUN test "${#VNU_SOURCE_COMMIT}" -eq 40 && \
    [[ "${VNU_SOURCE_COMMIT}" =~ ^[a-f0-9]{40}$ ]] && \
    curl --fail --show-error --silent --location --retry 2 --retry-delay 2 \
      --output /tmp/vnu-source.tar.gz \
      "https://codeload.github.com/validator/validator/tar.gz/${VNU_SOURCE_COMMIT}" && \
    printf '%s  %s\n' "${VNU_SOURCE_SHA256}" /tmp/vnu-source.tar.gz | \
      sha256sum --check --status && \
    mkdir -p /tmp/vnu-source /opt/vnu && \
    tar -xzf /tmp/vnu-source.tar.gz --strip-components=1 -C /tmp/vnu-source && \
    cd /tmp/vnu-source && \
    patch --batch --forward -p1 < /tmp/vnu-secure-dependencies.patch && \
    grep -Fq \
      "<property name=\"jetty-version\" value=\"${VNU_JETTY_VERSION}\" />" \
      build/build.xml && \
    grep -Fq \
      "<property name=\"reload4j-version\" value=\"${VNU_RELOAD4J_VERSION}\" />" \
      build/build.xml && \
    export JAVA_HOME=/opt/jdk && \
    export PATH=/opt/maven/bin:/opt/ant/bin:${PATH} && \
    python checker.py dldeps && \
    python checker.py --version="${VNU_VERSION} (${VNU_SOURCE_COMMIT:0:7})" build && \
    cp build/dist/vnu.jar /opt/vnu/vnu.jar && \
    python /tmp/normalize-vnu-jar.py /opt/vnu/vnu.jar && \
    printf '%s  %s\n' "${VNU_JAR_SHA256}" /opt/vnu/vnu.jar | \
      sha256sum --check --status && \
    test "$(/opt/jdk/bin/java -jar /opt/vnu/vnu.jar --version)" = \
      "${VNU_VERSION} (${VNU_SOURCE_COMMIT:0:7})" && \
    /opt/jdk/bin/jar tf /opt/vnu/vnu.jar > /tmp/vnu-entries.txt && \
    grep -Fxq \
      'META-INF/maven/ch.qos.reload4j/reload4j/pom.properties' \
      /tmp/vnu-entries.txt && \
    ! grep -Fxq \
      'META-INF/maven/log4j/log4j/pom.properties' \
      /tmp/vnu-entries.txt && \
    unzip -p /opt/vnu/vnu.jar \
      'META-INF/maven/org.eclipse.jetty/jetty-security/pom.properties' \
      > /tmp/vnu-jetty-security.properties && \
    grep -Fxq "version=${VNU_JETTY_VERSION}" \
      /tmp/vnu-jetty-security.properties && \
    chmod 0444 /opt/vnu/vnu.jar && \
    cd / && \
    rm -rf /tmp/vnu-source /tmp/vnu-source.tar.gz /tmp/vnu-entries.txt \
      /tmp/vnu-jetty-security.properties \
      /tmp/vnu-secure-dependencies.patch /tmp/normalize-vnu-jar.py && \
    case "${TARGETARCH}" in \
      amd64) \
        VNU_JRE_SHA256="${VNU_JRE_AMD64_SHA256}"; \
        VNU_JRE_ARCH=x64; \
        VNU_JRE_OS_ARCH=x86_64; \
        ;; \
      arm64) \
        VNU_JRE_SHA256="${VNU_JRE_ARM64_SHA256}"; \
        VNU_JRE_ARCH=aarch64; \
        VNU_JRE_OS_ARCH=aarch64; \
        ;; \
      *) exit 1 ;; \
    esac && \
    curl --fail --show-error --silent --location --retry 2 --retry-delay 2 \
      --output /tmp/vnu-jre.tar.gz \
      "https://github.com/adoptium/temurin17-binaries/releases/download/jdk-${VNU_JRE_VERSION/_/%2B}/OpenJDK17U-jre_${VNU_JRE_ARCH}_linux_hotspot_${VNU_JRE_VERSION}.tar.gz" && \
    printf '%s  %s\n' "${VNU_JRE_SHA256}" /tmp/vnu-jre.tar.gz | \
      sha256sum --check --status && \
    mkdir -p /opt/java && \
    tar -xzf /tmp/vnu-jre.tar.gz --strip-components=1 -C /opt/java && \
    test -x /opt/java/bin/java && \
    test -r "/opt/java/release" && \
    grep -Fq "IMPLEMENTOR=\"Eclipse Adoptium\"" /opt/java/release && \
    grep -Fq "JAVA_RUNTIME_VERSION=\"${VNU_JRE_VERSION/_/+}\"" /opt/java/release && \
    grep -Fq "OS_ARCH=\"${VNU_JRE_OS_ARCH}\"" /opt/java/release && \
    rm -f /tmp/vnu-jre.tar.gz


FROM registry.access.redhat.com/ubi9/python-311:9.8-1779945715@sha256:a0bdb55576fc5b8d6704279307817828ef027e1065533ceba133fe9516003a6c

LABEL maintainer="Lightning IT"
LABEL org.opencontainers.image.title="ee-wunder-devtools-ubi9"
LABEL org.opencontainers.image.description="Devtools Execution Environment (UBI 9) for Wunder automation."
LABEL org.opencontainers.image.source="https://github.com/lightning-it/container-ee-wunder-devtools-ubi9"

ARG ANSIBLE_CORE_VERSION=2.21.1
ARG PIP_VERSION=25.3
ARG CENTOS_STREAM_COMPOSE=CentOS-Stream-9-20261012.0

USER 0
SHELL ["/bin/bash", "-o", "pipefail", "-c"]

# Base tools you *actually* need at runtime.
# UBI 9 does not publish qemu-img/libguestfs packages. Use one immutable,
# official CentOS Stream 9 production compose only for VM image tooling so
# public GitHub builds neither depend on RHEL host entitlement nor race mutable
# mirror metadata.
RUN dnf --setopt=retries=2 -y update && \
    printf '%s\n' \
      "[centos-stream-compose-baseos]" \
      "name=CentOS Stream 9 immutable production compose BaseOS" \
      "baseurl=https://composes.stream.centos.org/stream-9/production/${CENTOS_STREAM_COMPOSE}/compose/BaseOS/\$basearch/os/" \
      "enabled=0" \
      "gpgcheck=1" \
      "gpgkey=https://www.centos.org/keys/RPM-GPG-KEY-CentOS-Official" \
      "" \
      "[centos-stream-compose-appstream]" \
      "name=CentOS Stream 9 immutable production compose AppStream" \
      "baseurl=https://composes.stream.centos.org/stream-9/production/${CENTOS_STREAM_COMPOSE}/compose/AppStream/\$basearch/os/" \
      "enabled=0" \
      "gpgcheck=1" \
      "gpgkey=https://www.centos.org/keys/RPM-GPG-KEY-CentOS-Official" \
      "" \
      "[centos-stream-compose-crb]" \
      "name=CentOS Stream 9 immutable production compose CRB" \
      "baseurl=https://composes.stream.centos.org/stream-9/production/${CENTOS_STREAM_COMPOSE}/compose/CRB/\$basearch/os/" \
      "enabled=0" \
      "gpgcheck=1" \
      "gpgkey=https://www.centos.org/keys/RPM-GPG-KEY-CentOS-Official" \
      > /etc/yum.repos.d/centos-stream-vm-image-tools.repo && \
    dnf --setopt=retries=2 -y install --allowerasing --setopt=install_weak_deps=False \
      bash git openssh-clients rsync which findutils ca-certificates \
      rpm-build && \
    dnf --setopt=retries=2 -y install --allowerasing --setopt=install_weak_deps=False \
      --enablerepo="centos-stream-compose-baseos" \
      --enablerepo="centos-stream-compose-appstream" \
      --enablerepo="centos-stream-compose-crb" \
      qemu-img guestfs-tools libguestfs && \
    old_node_rpms=() && \
    for package in nodejs nodejs-docs nodejs-full-i18n nodejs-libs npm; do \
      if rpm -q "$package" >/dev/null 2>&1; then old_node_rpms+=("$package"); fi; \
    done && \
    if [ "${#old_node_rpms[@]}" -gt 0 ]; then dnf --setopt=retries=2 -y remove "${old_node_rpms[@]}"; fi && \
    rm -f /etc/yum.repos.d/centos-stream-vm-image-tools.repo && \
    dnf --setopt=retries=2 clean all && rm -rf /var/cache/dnf /var/cache/yum

# Copy toolchain from builder (no curl/unzip in final image)
COPY --from=tools /out/terraform /usr/local/bin/terraform
COPY --from=tools /out/packer /usr/local/bin/packer
COPY --from=tools /out/incus /usr/local/bin/incus
COPY --from=cosign-builder /out/cosign /usr/local/bin/cosign
COPY --from=tools /out/tflint /usr/local/bin/tflint
COPY --from=tools /out/terraform-docs /usr/local/bin/terraform-docs
COPY --from=tools /out/helm /usr/local/bin/helm
COPY --from=tools /out/gh /usr/local/bin/gh
COPY --from=tools /out/actionlint /usr/local/bin/actionlint
COPY --from=tools /out/docker /usr/local/bin/docker
COPY --from=tools /out/docker-compose /usr/local/lib/docker/cli-plugins/docker-compose
COPY --from=tools /opt/node /opt/node
COPY --from=tools /opt/node-website /opt/node-website
COPY --from=tools /opt/node-toolchain /opt/node-toolchain
COPY --from=vnu-builder /opt/vnu/vnu.jar /opt/vnu/vnu.jar
COPY --from=vnu-builder /opt/java /opt/java
COPY scripts/devtools-node-selector.sh /usr/local/bin/devtools-node-selector.sh
COPY scripts/vnu /usr/local/bin/vnu
ENV JAVA_HOME=/opt/java \
    PATH=/opt/java/bin:/opt/node/bin:$PATH

# Python deps: this *is* the right place for pip
COPY requirements.in /tmp/requirements.in
COPY requirements.lock /tmp/requirements.lock
COPY scripts/verify-bandit-runtime.py /usr/local/bin/verify-bandit-runtime.py
COPY collections/offline-requirements.lock.yml /usr/local/share/wunder-devtools/collections.lock.yml
COPY scripts/devtools_collection_inventory.py /usr/local/bin/devtools_collection_inventory.py
COPY scripts/install_devtools_collections.py /usr/local/bin/install_devtools_collections.py
COPY scripts/verify_devtools_collection_python.py /usr/local/bin/verify_devtools_collection_python.py
RUN python -m pip install --retries 2 --no-cache-dir --upgrade "pip==${PIP_VERSION}" && \
    python -m pip install --retries 2 --resume-retries 0 --no-cache-dir --require-hashes -r /tmp/requirements.lock && \
    python /usr/local/bin/verify-bandit-runtime.py && \
    rm -f /tmp/requirements.in /tmp/requirements.lock && \
    python /usr/local/bin/install_devtools_collections.py \
      --lock /usr/local/share/wunder-devtools/collections.lock.yml \
      --collections-path /usr/share/ansible/collections && \
    python /usr/local/bin/devtools_collection_inventory.py \
      --lock /usr/local/share/wunder-devtools/collections.lock.yml \
      --collections-root /usr/share/ansible/collections/ansible_collections && \
    python -m pip check && \
    python /usr/local/bin/verify_devtools_collection_python.py \
      --collection-lock /usr/local/share/wunder-devtools/collections.lock.yml \
      --installed-root /usr/share/ansible/collections/ansible_collections && \
    PYTHONPATH=/usr/share/ansible/collections python -c \
      "from ansible_collections.hetzner.hcloud.plugins.module_utils._client import client_check_required_lib; client_check_required_lib()" && \
    ansible --version && ansible-galaxy --version && antsibull-changelog --version && \
    shellcheck --version && actionlint --version && pre-commit --version && \
    ruff --version && mypy --version && uv --version && \
    renovate-config-validator --version && \
    markdownlint-cli2 --version && prettier --version && pnpm --version && \
    java -version && vnu --version && \
    helm version --short && gh --version && \
    CHECKPOINT_DISABLE=1 packer version && \
    copr-cli --version && rpmspec --version && qemu-img --version && \
    virt-customize --version && virt-sysprep --version && guestfish --version

COPY tests/fixtures/vnu /tmp/vnu-fixtures
RUN vnu --errors-only /tmp/vnu-fixtures/valid.html && \
    if vnu --errors-only /tmp/vnu-fixtures/invalid.html; then \
      echo "ERROR: Nu accepted the intentionally invalid fixture." >&2; \
      exit 1; \
    fi && \
    rm -rf /tmp/vnu-fixtures

WORKDIR /workspace
RUN useradd -m wunder && \
    mkdir -p /home/wunder/.ansible/tmp /tmp/ansible/tmp && \
    chown -R wunder:wunder /workspace /home/wunder && \
    chmod 1777 /tmp/ansible /tmp/ansible/tmp

ENV HOME=/home/wunder \
    ANSIBLE_LOCAL_TEMP=/tmp/ansible/tmp \
    ANSIBLE_REMOTE_TEMP=/tmp/ansible/tmp

USER wunder
ENTRYPOINT ["/usr/local/bin/devtools-node-selector.sh"]
CMD ["/bin/bash"]
