FROM registry.access.redhat.com/ubi9/python-311@sha256:bb09d55bce99b839b0df565ab9e244cdc545037e612dad388569016137367cab AS tools

LABEL maintainer="Lightning IT"
LABEL org.opencontainers.image.title="ee-wunder-devtools-ubi9"
LABEL org.opencontainers.image.description="Devtools Execution Environment (UBI 9) for Wunder automation: ansible-lint, yamllint, molecule (docker), and supporting CLI tooling for local + CI workflows."
LABEL org.opencontainers.image.source="https://github.com/lightning-it/container-ee-wunder-devtools-ubi9"

ARG TARGETARCH
ARG TF_VERSION=1.14.5
ARG TFLINT_VERSION=0.61.0
ARG TF_DOCS_VERSION=0.21.0

# hadolint ignore=DL3002
USER 0
SHELL ["/bin/bash", "-o", "pipefail", "-c"]

RUN dnf -y update && \
    dnf -y install --allowerasing ca-certificates curl unzip tar dnf-plugins-core && \
    curl -fsSL https://download.docker.com/linux/centos/docker-ce.repo -o /etc/yum.repos.d/docker-ce.repo && \
    dnf -y install docker-ce-cli docker-compose-plugin && \
    dnf clean all && rm -rf /var/cache/yum

# Map docker arch naming
RUN case "${TARGETARCH}" in \
      amd64)  export ARCH=amd64   DOCKER_ARCH=x86_64  ;; \
      arm64)  export ARCH=arm64   DOCKER_ARCH=aarch64 ;; \
      *) echo "Unsupported TARGETARCH=${TARGETARCH}" && exit 1 ;; \
    esac && \
    echo "ARCH=${ARCH} DOCKER_ARCH=${DOCKER_ARCH}" > /tmp/arch.env

# Terraform
RUN source /tmp/arch.env && \
    curl -fsSLo /tmp/terraform.zip \
      "https://releases.hashicorp.com/terraform/${TF_VERSION}/terraform_${TF_VERSION}_linux_${ARCH}.zip" && \
    unzip -q /tmp/terraform.zip -d /usr/local/bin && \
    rm -f /tmp/terraform.zip

# TFLint
RUN source /tmp/arch.env && \
    curl -fsSLo /tmp/tflint.zip \
      "https://github.com/terraform-linters/tflint/releases/download/v${TFLINT_VERSION}/tflint_linux_${ARCH}.zip" && \
    unzip -q /tmp/tflint.zip -d /usr/local/bin && \
    rm -f /tmp/tflint.zip

# terraform-docs
RUN source /tmp/arch.env && \
    curl -fsSLo /tmp/terraform-docs.tar.gz \
      "https://github.com/terraform-docs/terraform-docs/releases/download/v${TF_DOCS_VERSION}/terraform-docs-v${TF_DOCS_VERSION}-linux-${ARCH}.tar.gz" && \
    tar -xzf /tmp/terraform-docs.tar.gz -C /usr/local/bin terraform-docs && \
    chmod +x /usr/local/bin/terraform-docs && \
    rm -f /tmp/terraform-docs.tar.gz

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


FROM registry.access.redhat.com/ubi9/python-311@sha256:bb09d55bce99b839b0df565ab9e244cdc545037e612dad388569016137367cab

LABEL maintainer="Lightning IT"
LABEL org.opencontainers.image.title="ee-wunder-ansible-ubi9"
LABEL org.opencontainers.image.description="Ansible Execution Environment (UBI 9) for Wunder automation."
LABEL org.opencontainers.image.source="https://github.com/lightning-it/container-ee-wunder-ansible-ubi9"

ARG ANSIBLE_CORE_VERSION=2.18.12
ARG PIP_VERSION=25.3

USER 0
SHELL ["/bin/bash", "-o", "pipefail", "-c"]

# Base tools you *actually* need at runtime
RUN dnf -y update && \
    dnf -y install --allowerasing \
      bash git openssh-clients rsync which findutils ca-certificates && \
    dnf clean all && rm -rf /var/cache/yum

# Copy toolchain from builder (no curl/unzip in final image)
COPY --from=tools /usr/local/bin/terraform /usr/local/bin/terraform
COPY --from=tools /usr/local/bin/tflint /usr/local/bin/tflint
COPY --from=tools /usr/local/bin/terraform-docs /usr/local/bin/terraform-docs
COPY --from=tools /usr/local/bin/docker /usr/local/bin/docker
COPY --from=tools /usr/local/lib/docker/cli-plugins/docker-compose /usr/local/lib/docker/cli-plugins/docker-compose

# Python deps: this *is* the right place for pip
COPY requirements.txt /tmp/requirements.txt
RUN python -m pip install --no-cache-dir --upgrade "pip==${PIP_VERSION}" && \
    python -m pip install --no-cache-dir -r /tmp/requirements.txt && \
    rm -f /tmp/requirements.txt && \
    ansible --version && ansible-galaxy --version

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
