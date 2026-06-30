FROM registry.access.redhat.com/ubi9/python-311@sha256:a0bdb55576fc5b8d6704279307817828ef027e1065533ceba133fe9516003a6c AS tools

LABEL maintainer="Lightning IT"
LABEL org.opencontainers.image.title="ee-wunder-devtools-ubi9"
LABEL org.opencontainers.image.description="Devtools Execution Environment (UBI 9) for Wunder automation: ansible-lint, yamllint, molecule (docker), and supporting CLI tooling for local + CI workflows."
LABEL org.opencontainers.image.source="https://github.com/lightning-it/container-ee-wunder-devtools-ubi9"

ARG TARGETARCH
ARG TF_VERSION=1.15.7
ARG TFLINT_VERSION=0.63.1
ARG TF_DOCS_VERSION=0.24.0
ARG HELM_VERSION=4.2.2
ARG GH_VERSION=2.95.0

# hadolint ignore=DL3002
USER 0
SHELL ["/bin/bash", "-o", "pipefail", "-c"]

COPY scripts/container-download-verified.sh /usr/local/lib/container-download-verified.sh

RUN dnf -y update && \
    dnf -y install --allowerasing ca-certificates curl unzip tar dnf-plugins-core && \
    curl -fsSL https://download.docker.com/linux/centos/docker-ce.repo -o /etc/yum.repos.d/docker-ce.repo && \
    dnf -y install docker-ce-cli docker-compose-plugin && \
    dnf clean all && rm -rf /var/cache/dnf /var/cache/yum

# Map docker arch naming
RUN source /usr/local/lib/container-download-verified.sh && \
    detect_container_arch && \
    echo "ARCH=${CONTAINER_ARCH} DOCKER_ARCH=${CONTAINER_RPM_ARCH}" > /tmp/arch.env

# Terraform
RUN source /usr/local/lib/container-download-verified.sh && \
    source /tmp/arch.env && \
    download_verified \
      "https://releases.hashicorp.com/terraform/${TF_VERSION}/terraform_${TF_VERSION}_linux_${ARCH}.zip" \
      /tmp/terraform.zip \
      "https://releases.hashicorp.com/terraform/${TF_VERSION}/terraform_${TF_VERSION}_SHA256SUMS" \
      "terraform_${TF_VERSION}_linux_${ARCH}.zip" && \
    unzip -q /tmp/terraform.zip -d /usr/local/bin && \
    rm -f /tmp/terraform.zip

# TFLint
RUN source /usr/local/lib/container-download-verified.sh && \
    source /tmp/arch.env && \
    download_verified \
      "https://github.com/terraform-linters/tflint/releases/download/v${TFLINT_VERSION}/tflint_linux_${ARCH}.zip" \
      /tmp/tflint.zip \
      "https://github.com/terraform-linters/tflint/releases/download/v${TFLINT_VERSION}/checksums.txt" \
      "tflint_linux_${ARCH}.zip" && \
    unzip -q /tmp/tflint.zip -d /usr/local/bin && \
    rm -f /tmp/tflint.zip

# terraform-docs
RUN source /usr/local/lib/container-download-verified.sh && \
    source /tmp/arch.env && \
    download_verified \
      "https://github.com/terraform-docs/terraform-docs/releases/download/v${TF_DOCS_VERSION}/terraform-docs-v${TF_DOCS_VERSION}-linux-${ARCH}.tar.gz" \
      /tmp/terraform-docs.tar.gz \
      "https://github.com/terraform-docs/terraform-docs/releases/download/v${TF_DOCS_VERSION}/terraform-docs-v${TF_DOCS_VERSION}.sha256sum" \
      "terraform-docs-v${TF_DOCS_VERSION}-linux-${ARCH}.tar.gz" && \
    tar -xzf /tmp/terraform-docs.tar.gz -C /usr/local/bin terraform-docs && \
    chmod +x /usr/local/bin/terraform-docs && \
    rm -f /tmp/terraform-docs.tar.gz

# Helm
RUN source /usr/local/lib/container-download-verified.sh && \
    source /tmp/arch.env && \
    download_verified \
      "https://get.helm.sh/helm-v${HELM_VERSION}-linux-${ARCH}.tar.gz" \
      /tmp/helm.tar.gz \
      "https://get.helm.sh/helm-v${HELM_VERSION}-linux-${ARCH}.tar.gz.sha256sum" \
      "helm-v${HELM_VERSION}-linux-${ARCH}.tar.gz" && \
    tar -xzf /tmp/helm.tar.gz -C /tmp && \
    install -m 0755 "/tmp/linux-${ARCH}/helm" /usr/local/bin/helm && \
    rm -rf /tmp/helm.tar.gz "/tmp/linux-${ARCH}"

# GitHub CLI
RUN source /usr/local/lib/container-download-verified.sh && \
    source /tmp/arch.env && \
    download_verified \
      "https://github.com/cli/cli/releases/download/v${GH_VERSION}/gh_${GH_VERSION}_linux_${ARCH}.tar.gz" \
      /tmp/gh.tar.gz \
      "https://github.com/cli/cli/releases/download/v${GH_VERSION}/gh_${GH_VERSION}_checksums.txt" \
      "gh_${GH_VERSION}_linux_${ARCH}.tar.gz" && \
    tar -xzf /tmp/gh.tar.gz -C /tmp && \
    install -m 0755 "/tmp/gh_${GH_VERSION}_linux_${ARCH}/bin/gh" /usr/local/bin/gh && \
    rm -rf /tmp/gh.tar.gz "/tmp/gh_${GH_VERSION}_linux_${ARCH}"

# Docker CLI + Compose plugin (from docker-ce packages)
RUN install -m 0755 /usr/bin/docker /usr/local/bin/docker && \
    mkdir -p /usr/local/lib/docker/cli-plugins && \
    if [ -x /usr/libexec/docker/cli-plugins/docker-compose ]; then \
      install -m 0755 /usr/libexec/docker/cli-plugins/docker-compose /usr/local/lib/docker/cli-plugins/docker-compose; \
    elif [ -x /usr/lib/docker/cli-plugins/docker-compose ]; then \
      install -m 0755 /usr/lib/docker/cli-plugins/docker-compose /usr/local/lib/docker/cli-plugins/docker-compose; \
    else \
      echo "docker-compose plugin not found" >&2; exit 1; \
    fi


FROM registry.access.redhat.com/ubi9/python-311@sha256:a0bdb55576fc5b8d6704279307817828ef027e1065533ceba133fe9516003a6c

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
    rm -f /etc/yum.repos.d/centos-stream-vm-image-tools.repo && \
    dnf clean all && rm -rf /var/cache/dnf /var/cache/yum

# Copy toolchain from builder (no curl/unzip in final image)
COPY --from=tools /usr/local/bin/terraform /usr/local/bin/terraform
COPY --from=tools /usr/local/bin/tflint /usr/local/bin/tflint
COPY --from=tools /usr/local/bin/terraform-docs /usr/local/bin/terraform-docs
COPY --from=tools /usr/local/bin/helm /usr/local/bin/helm
COPY --from=tools /usr/local/bin/gh /usr/local/bin/gh
COPY --from=tools /usr/local/bin/docker /usr/local/bin/docker
COPY --from=tools /usr/local/lib/docker/cli-plugins/docker-compose /usr/local/lib/docker/cli-plugins/docker-compose

# Python deps: this *is* the right place for pip
COPY requirements.txt /tmp/requirements.txt
RUN python -m pip install --no-cache-dir --upgrade "pip==${PIP_VERSION}" && \
    python -m pip install --no-cache-dir -r /tmp/requirements.txt && \
    rm -f /tmp/requirements.txt && \
    ansible --version && ansible-galaxy --version && antsibull-changelog --version && \
    shellcheck --version && helm version --short && gh --version && \
    copr-cli --version && rpmspec --version && qemu-img --version && \
    virt-customize --version && virt-sysprep --version && guestfish --version

WORKDIR /workspace
RUN useradd -m wunder && \
    mkdir -p /home/wunder/.ansible/tmp /tmp/ansible/tmp && \
    chown -R wunder:wunder /workspace /home/wunder && \
    chmod 1777 /tmp/ansible /tmp/ansible/tmp

ENV HOME=/home/wunder \
    ANSIBLE_LOCAL_TEMP=/tmp/ansible/tmp \
    ANSIBLE_REMOTE_TEMP=/tmp/ansible/tmp

USER wunder
CMD ["/bin/bash"]
