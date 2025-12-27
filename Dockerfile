FROM registry.access.redhat.com/ubi9/ubi:9.7-1764794285

LABEL maintainer="Lightning IT"
LABEL org.opencontainers.image.title="container-wunder-devtools-ee"
LABEL org.opencontainers.image.description="Shared development tools container for local and CI workflows."
LABEL org.opencontainers.image.source="https://github.com/lightning-it/container-wunder-devtools-ee"

########################
# Base tools & Python  #
########################

USER 0

# Base tools + Python for Ansible + Node for renovate validation
RUN dnf -y update && \
    dnf -y module enable nodejs:20 && \
    dnf -y install \
      bash \
      git \
      ca-certificates \
      tar \
      unzip \
      which \
      python3 \
      python3-pip \
      nodejs \
      npm && \
    dnf clean all && \
    rm -rf /var/cache/dnf

########################
# Ansible & Lint-Tools #
########################

COPY requirements.txt /tmp/requirements.txt

RUN pip3 install --no-cache-dir -r /tmp/requirements.txt && \
    rm /tmp/requirements.txt

# Node-based tooling (semantic-release, renovate, etc.)
WORKDIR /opt/devtools
COPY package.json package-lock.json ./
RUN npm ci && \
    npm cache clean --force
# Expose renovate CLI in PATH for convenience
RUN ln -sf /opt/devtools/node_modules/.bin/renovate /usr/local/bin/renovate
# Make npm-installed CLIs available in PATH
ENV PATH="/opt/devtools/node_modules/.bin:${PATH}"

########################
# Terraform Toolchain  #
########################

# Terraform
ENV TF_VERSION=1.6.6
RUN curl -sSLo /tmp/terraform.zip \
      "https://releases.hashicorp.com/terraform/${TF_VERSION}/terraform_${TF_VERSION}_linux_amd64.zip" \
    && unzip /tmp/terraform.zip -d /usr/local/bin \
    && rm /tmp/terraform.zip

# TFLint
ENV TFLINT_VERSION=0.60.0
RUN curl -sSLo /tmp/tflint.zip \
      "https://github.com/terraform-linters/tflint/releases/download/v${TFLINT_VERSION}/tflint_linux_amd64.zip" \
    && unzip /tmp/tflint.zip -d /usr/local/bin \
    && rm /tmp/tflint.zip

# terraform-docs
ENV TF_DOCS_VERSION=0.20.0
RUN curl -sSLo /tmp/terraform-docs.tar.gz \
      "https://github.com/terraform-docs/terraform-docs/releases/download/v${TF_DOCS_VERSION}/terraform-docs-v${TF_DOCS_VERSION}-linux-amd64.tar.gz" \
    && tar -xzf /tmp/terraform-docs.tar.gz -C /usr/local/bin terraform-docs \
    && chmod +x /usr/local/bin/terraform-docs \
    && rm /tmp/terraform-docs.tar.gz

########################
# Docker CLI + Compose #
########################

ENV DOCKER_CLI_VERSION=26.1.3
ENV DOCKER_COMPOSE_VERSION=2.29.2

# Docker CLI
RUN curl -sSLo /tmp/docker.tgz \
      "https://download.docker.com/linux/static/stable/x86_64/docker-${DOCKER_CLI_VERSION}.tgz" \
    && tar -xzf /tmp/docker.tgz -C /tmp docker/docker \
    && mv /tmp/docker/docker /usr/local/bin/docker \
    && chmod +x /usr/local/bin/docker \
    && rm -rf /tmp/docker.tgz /tmp/docker

# Docker Compose plugin
RUN mkdir -p /usr/local/lib/docker/cli-plugins && \
    curl -sSLo /usr/local/lib/docker/cli-plugins/docker-compose \
      "https://github.com/docker/compose/releases/download/v${DOCKER_COMPOSE_VERSION}/docker-compose-linux-x86_64" && \
    chmod +x /usr/local/lib/docker/cli-plugins/docker-compose

########################
# User & Workdir       #
########################

WORKDIR /workspace

RUN useradd -m wunder && chown -R wunder /workspace
USER wunder

# Default
CMD ["/bin/bash"]
