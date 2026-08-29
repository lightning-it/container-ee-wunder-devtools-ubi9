FROM registry.access.redhat.com/ubi9/python-311:9.8-1779945715@sha256:a0bdb55576fc5b8d6704279307817828ef027e1065533ceba133fe9516003a6c AS tools

LABEL maintainer="Lightning IT"
LABEL org.opencontainers.image.title="ee-wunder-devtools-ubi9"
LABEL org.opencontainers.image.description="Devtools Execution Environment (UBI 9) for Wunder automation: ansible-lint, yamllint, molecule (docker), and supporting CLI tooling for local + CI workflows."
LABEL org.opencontainers.image.source="https://github.com/lightning-it/container-ee-wunder-devtools-ubi9"

ARG TARGETARCH
ARG GO_VERSION=1.26.7
ARG GO_AMD64_SHA256=ffb5f8de10c62550dfddab66b36b57030721e0a44a3218e9e1181d7b59f121ca
ARG GO_ARM64_SHA256=5a4ec883379d51ee9ce1040d5e87f8d35e20387574dd8c947feb01eabc3c1b37
ARG TF_VERSION=1.15.9
ARG TF_SOURCE_COMMIT=87488977e32a400445e0c0b4d95c0713a5eee941
ARG TF_SOURCE_SHA256=b4036b35e69a57e4a4b83bafba337a5c8e3ab2c0b1812df92528dec0958ed61e
ARG TFLINT_VERSION=0.64.0
ARG TF_DOCS_VERSION=0.24.0
ARG HELM_VERSION=4.2.4
ARG GH_VERSION=2.98.0
ARG ACTIONLINT_VERSION=1.7.12
ARG DOCKER_SOURCE_COMMIT=a7dcaa6fdb6ed04aacbfdc76357fdae01605609e
ARG DOCKER_SOURCE_SHA256=6e5c91d3a5a79db78cf989d07727d00e757aa0da4d135a3ce4b86061b83fb511
ARG COMPOSE_VERSION=5.5.0
ARG BUILDX_VERSION=0.36.1
ARG MOBY_V2_VERSION=2.0.0-beta.21
ARG MOBY_NAMESGENERATOR_SHA256=79ed19fb5afd19ccb3284213961335ec2f22ac9e8181971cab377de740361bbb
ARG NODE_VERSION=24.19.0
ARG WEBSITE_NODE_VERSION=24.18.0
ARG VNU_SOURCE_COMMIT=c4720cafffd1f93358ca824163fc5bbdb35fb0e0
ARG VNU_RELEASE_ID=258370454
ARG VNU_ASSET_ID=534958489
ARG VNU_JAR_SHA256=6df33484013072856456a9c1fa32ae3da96c3069041d9b61c026f57b04bd23c3
ARG VNU_JRE_VERSION=17.0.20_8
ARG VNU_JRE_AMD64_ASSET_ID=488632381
ARG VNU_JRE_AMD64_SHA256=ef491a51a46ef90cc47fbc4abb219fde32483ff91be5ec66ddc896df43524b27
ARG VNU_JRE_ARM64_ASSET_ID=492545197
ARG VNU_JRE_ARM64_SHA256=9d14a95e07c44bc48666625162baf40db9da4dcb192bfc3e43047790693061a2
ARG GO_X_CRYPTO_VERSION=0.52.0
ARG GO_X_MOD_VERSION=0.40.0
ARG GO_X_NET_VERSION=0.56.0
ARG GO_X_TEXT_VERSION=0.39.0
ARG GO_GRPC_VERSION=1.82.1
ARG ORAS_GO_VERSION=2.6.2

# hadolint ignore=DL3002
USER 0
SHELL ["/bin/bash", "-o", "pipefail", "-c"]

COPY scripts/container-download-verified.sh /usr/local/lib/container-download-verified.sh
COPY scripts/container-build-go-tool.sh /usr/local/lib/container-build-go-tool.sh
COPY scripts/container-build-compose.sh /usr/local/lib/container-build-compose.sh
COPY container-toolchain/package.json container-toolchain/pnpm-lock.yaml container-toolchain/pnpm-workspace.yaml /opt/node-toolchain/

RUN dnf -y update && \
    dnf -y install --allowerasing ca-certificates curl tar xz && \
    dnf clean all && rm -rf /var/cache/dnf /var/cache/yum

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

RUN mkdir -p /out && \
    /usr/local/lib/container-build-go-tool.sh \
      github.com/rhysd/actionlint "v${ACTIONLINT_VERSION}" ./cmd/actionlint actionlint

RUN curl -fsSLo /tmp/terraform.tar.gz \
      "https://github.com/hashicorp/terraform/archive/${TF_SOURCE_COMMIT}.tar.gz" && \
    printf '%s  %s\n' "${TF_SOURCE_SHA256}" /tmp/terraform.tar.gz | sha256sum -c - && \
    mkdir -p /tmp/terraform-source && \
    tar -xzf /tmp/terraform.tar.gz --strip-components=1 -C /tmp/terraform-source && \
    cd /tmp/terraform-source && \
    CGO_ENABLED=0 go build \
      -trimpath -buildvcs=false \
      -ldflags="-s -w -X github.com/hashicorp/terraform/version.dev=no" \
      -o /out/terraform . && \
    test "$(/out/terraform version | head -n 1)" = "Terraform v${TF_VERSION}" && \
    cd / && \
    rm -rf /tmp/terraform.tar.gz /tmp/terraform-source

RUN /usr/local/lib/container-build-go-tool.sh \
      github.com/terraform-linters/tflint "v${TFLINT_VERSION}" . tflint \
      "golang.org/x/mod@v${GO_X_MOD_VERSION}" \
      "google.golang.org/grpc@v${GO_GRPC_VERSION}"

RUN /usr/local/lib/container-build-go-tool.sh \
      github.com/terraform-docs/terraform-docs "v${TF_DOCS_VERSION}" . terraform-docs \
      "golang.org/x/crypto@v${GO_X_CRYPTO_VERSION}" \
      "golang.org/x/net@v${GO_X_NET_VERSION}" \
      "golang.org/x/text@v${GO_X_TEXT_VERSION}" \
      "google.golang.org/grpc@v${GO_GRPC_VERSION}"

RUN /usr/local/lib/container-build-go-tool.sh \
      helm.sh/helm/v4 "v${HELM_VERSION}" ./cmd/helm helm \
      "oras.land/oras-go/v2@v${ORAS_GO_VERSION}"

RUN /usr/local/lib/container-build-go-tool.sh \
      github.com/cli/cli/v2 "v${GH_VERSION}" ./cmd/gh gh \
      "golang.org/x/mod@v${GO_X_MOD_VERSION}"

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
    CGO_ENABLED=0 go build \
      -mod=vendor -trimpath -buildvcs=false \
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
      "${GO_X_MOD_VERSION}"

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
      for package in brace-expansion ip-address tar; do \
        version="$(/opt/node/bin/node -p \
          'require(process.argv[1]).version' \
          "/opt/node-toolchain/node_modules/${package}/package.json")" && \
        rm -rf "/opt/node-toolchain/node_modules/${npm_tree}/node_modules/${package}" && \
        cp -aL "/opt/node-toolchain/node_modules/${package}" \
          "/opt/node-toolchain/node_modules/${npm_tree}/node_modules/${package}" && \
        test "$(/opt/node/bin/node -p \
          'require(process.argv[1]).version' \
          "/opt/node-toolchain/node_modules/${npm_tree}/node_modules/${package}/package.json")" \
          = "${version}"; \
      done; \
    done && \
    for package in pacote undici; do \
      version="$(/opt/node/bin/node -p \
        'require(process.argv[1]).version' \
        "/opt/node-toolchain/node_modules/${package}/package.json")" && \
      rm -rf "/opt/node-toolchain/node_modules/npm-website/node_modules/${package}" && \
      cp -aL "/opt/node-toolchain/node_modules/${package}" \
        "/opt/node-toolchain/node_modules/npm-website/node_modules/${package}" && \
      test "$(/opt/node/bin/node -p \
        'require(process.argv[1]).version' \
        "/opt/node-toolchain/node_modules/npm-website/node_modules/${package}/package.json")" \
        = "${version}"; \
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
    /opt/node/bin/markdownlint-cli2 --version && \
    /opt/node/bin/prettier --version && \
    test "$(/opt/node-website/bin/node --version)" = "v${WEBSITE_NODE_VERSION}" && \
    test "$(PATH=/opt/node-website/bin:${PATH} /opt/node-website/bin/npm --version)" = "11.16.0" && \
    rm -f /tmp/node.tar.xz /tmp/node-website.tar.xz && \
    rm -rf /tmp/pnpm-store /opt/node-toolchain/.npm

# The W3C Nu HTML Checker publishes a rolling release. Bind the downloaded
# artifact to both the immutable upstream source revision and its exact
# SHA-256 so a changed rolling asset fails closed until this tuple is reviewed.
RUN test "${#VNU_SOURCE_COMMIT}" -eq 40 && \
    [[ "${VNU_SOURCE_COMMIT}" =~ ^[a-f0-9]{40}$ ]] && \
    mkdir -p /opt/vnu && \
    curl --fail --show-error --silent --location --retry 5 --retry-delay 2 \
      --output /tmp/vnu-release.json \
      "https://api.github.com/repos/validator/validator/releases/${VNU_RELEASE_ID}" && \
    python -c 'import json,sys; data=json.load(open(sys.argv[1], encoding="utf-8")); expected_commit, expected_asset, expected_digest=sys.argv[2:]; assert data["target_commitish"] == expected_commit; asset=next(item for item in data["assets"] if str(item["id"]) == expected_asset); assert asset["name"] == "vnu.jar"; assert asset["digest"] == "sha256:" + expected_digest' \
      /tmp/vnu-release.json "${VNU_SOURCE_COMMIT}" "${VNU_ASSET_ID}" \
      "${VNU_JAR_SHA256}" && \
    curl --fail --show-error --silent --location --retry 5 --retry-delay 2 \
      --header "Accept: application/octet-stream" \
      --output /opt/vnu/vnu.jar \
      "https://api.github.com/repos/validator/validator/releases/assets/${VNU_ASSET_ID}" && \
    printf '%s  %s\n' "${VNU_JAR_SHA256}" /opt/vnu/vnu.jar | \
      sha256sum --check --status && \
    chmod 0444 /opt/vnu/vnu.jar && \
    rm -f /tmp/vnu-release.json && \
    source /tmp/arch.env && \
    case "${ARCH}" in \
      amd64) \
        VNU_JRE_ASSET_ID="${VNU_JRE_AMD64_ASSET_ID}"; \
        VNU_JRE_SHA256="${VNU_JRE_AMD64_SHA256}"; \
        VNU_JRE_ARCH=x64; \
        ;; \
      arm64) \
        VNU_JRE_ASSET_ID="${VNU_JRE_ARM64_ASSET_ID}"; \
        VNU_JRE_SHA256="${VNU_JRE_ARM64_SHA256}"; \
        VNU_JRE_ARCH=aarch64; \
        ;; \
      *) exit 1 ;; \
    esac && \
    curl --fail --show-error --silent --location --retry 5 --retry-delay 2 \
      --header "Accept: application/octet-stream" \
      --output /tmp/vnu-jre.tar.gz \
      "https://api.github.com/repos/adoptium/temurin17-binaries/releases/assets/${VNU_JRE_ASSET_ID}" && \
    printf '%s  %s\n' "${VNU_JRE_SHA256}" /tmp/vnu-jre.tar.gz | \
      sha256sum --check --status && \
    mkdir -p /opt/java && \
    tar -xzf /tmp/vnu-jre.tar.gz --strip-components=1 -C /opt/java && \
    test "$(/opt/java/bin/java -version 2>&1 | head -n 1)" = \
      "openjdk version \"${VNU_JRE_VERSION%_*}\" 2026-07-21" && \
    test -r "/opt/java/release" && \
    grep -Fq "IMPLEMENTOR=\"Eclipse Adoptium\"" /opt/java/release && \
    grep -Fq "JAVA_RUNTIME_VERSION=\"${VNU_JRE_VERSION/_/+}\"" /opt/java/release && \
    grep -Fq "OS_ARCH=\"${VNU_JRE_ARCH}\"" /opt/java/release && \
    rm -f /tmp/vnu-jre.tar.gz


FROM registry.access.redhat.com/ubi9/python-311:9.8-1779945715@sha256:a0bdb55576fc5b8d6704279307817828ef027e1065533ceba133fe9516003a6c

LABEL maintainer="Lightning IT"
LABEL org.opencontainers.image.title="ee-wunder-devtools-ubi9"
LABEL org.opencontainers.image.description="Devtools Execution Environment (UBI 9) for Wunder automation."
LABEL org.opencontainers.image.source="https://github.com/lightning-it/container-ee-wunder-devtools-ubi9"

ARG ANSIBLE_CORE_VERSION=2.21.1
ARG PIP_VERSION=25.3
ARG CENTOS_STREAM_VERSION=9-stream

USER 0
SHELL ["/bin/bash", "-o", "pipefail", "-c"]

# Base tools you *actually* need at runtime.
# UBI 9 does not publish qemu-img/libguestfs packages. Use a narrow CentOS
# Stream 9 overlay only for VM image tooling so public GitHub builds do not
# depend on RHEL host entitlement.
RUN dnf -y update && \
    printf '%s\n' \
      "[centos-stream-${CENTOS_STREAM_VERSION}-baseos]" \
      "name=CentOS Stream ${CENTOS_STREAM_VERSION} BaseOS" \
      "baseurl=https://mirror.stream.centos.org/${CENTOS_STREAM_VERSION}/BaseOS/\$basearch/os/" \
      "enabled=0" \
      "gpgcheck=1" \
      "gpgkey=https://www.centos.org/keys/RPM-GPG-KEY-CentOS-Official" \
      "" \
      "[centos-stream-${CENTOS_STREAM_VERSION}-appstream]" \
      "name=CentOS Stream ${CENTOS_STREAM_VERSION} AppStream" \
      "baseurl=https://mirror.stream.centos.org/${CENTOS_STREAM_VERSION}/AppStream/\$basearch/os/" \
      "enabled=0" \
      "gpgcheck=1" \
      "gpgkey=https://www.centos.org/keys/RPM-GPG-KEY-CentOS-Official" \
      "" \
      "[centos-stream-${CENTOS_STREAM_VERSION}-crb]" \
      "name=CentOS Stream ${CENTOS_STREAM_VERSION} CRB" \
      "baseurl=https://mirror.stream.centos.org/${CENTOS_STREAM_VERSION}/CRB/\$basearch/os/" \
      "enabled=0" \
      "gpgcheck=1" \
      "gpgkey=https://www.centos.org/keys/RPM-GPG-KEY-CentOS-Official" \
      > /etc/yum.repos.d/centos-stream-vm-image-tools.repo && \
    dnf -y install --allowerasing --setopt=install_weak_deps=False \
      bash git openssh-clients rsync which findutils ca-certificates \
      rpm-build && \
    dnf -y install --allowerasing --setopt=install_weak_deps=False \
      --enablerepo="centos-stream-${CENTOS_STREAM_VERSION}-baseos" \
      --enablerepo="centos-stream-${CENTOS_STREAM_VERSION}-appstream" \
      --enablerepo="centos-stream-${CENTOS_STREAM_VERSION}-crb" \
      qemu-img guestfs-tools libguestfs && \
    old_node_rpms=() && \
    for package in nodejs nodejs-docs nodejs-full-i18n nodejs-libs npm; do \
      if rpm -q "$package" >/dev/null 2>&1; then old_node_rpms+=("$package"); fi; \
    done && \
    if [ "${#old_node_rpms[@]}" -gt 0 ]; then dnf -y remove "${old_node_rpms[@]}"; fi && \
    rm -f /etc/yum.repos.d/centos-stream-vm-image-tools.repo && \
    dnf clean all && rm -rf /var/cache/dnf /var/cache/yum

# Copy toolchain from builder (no curl/unzip in final image)
COPY --from=tools /out/terraform /usr/local/bin/terraform
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
COPY --from=tools /opt/vnu/vnu.jar /opt/vnu/vnu.jar
COPY --from=tools /opt/java /opt/java
COPY scripts/devtools-node-selector.sh /usr/local/bin/devtools-node-selector.sh
COPY scripts/vnu /usr/local/bin/vnu
ENV JAVA_HOME=/opt/java \
    PATH=/opt/java/bin:/opt/node/bin:$PATH

# Python deps: this *is* the right place for pip
COPY requirements.txt /tmp/requirements.txt
COPY requirements.lock /tmp/requirements.lock
RUN python -m pip install --no-cache-dir --upgrade "pip==${PIP_VERSION}" && \
    python -m pip install --no-cache-dir --require-hashes -r /tmp/requirements.lock && \
    rm -f /tmp/requirements.txt /tmp/requirements.lock && \
    ansible --version && ansible-galaxy --version && antsibull-changelog --version && \
    shellcheck --version && actionlint --version && pre-commit --version && \
    ruff --version && mypy --version && uv --version && \
    renovate-config-validator --version && \
    markdownlint-cli2 --version && prettier --version && pnpm --version && \
    java -version && vnu --version && \
    helm version --short && gh --version && \
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
