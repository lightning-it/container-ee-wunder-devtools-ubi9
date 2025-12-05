FROM registry.access.redhat.com/ubi9/ubi

LABEL maintainer="Lightning IT"
LABEL org.opencontainers.image.title="container-wunder-devtools-ee"
LABEL org.opencontainers.image.description="Shared development tools container for local and CI workflows (Ansible + Terraform)."
LABEL org.opencontainers.image.source="https://github.com/lightning-it/container-wunder-devtools-ee"

########################
# Base tools & Python  #
########################

USER 0

# Base tools + Python for Ansible
RUN dnf -y update && \
    dnf -y install \
      git \
      ca-certificates \
      tar \
      unzip \
      which \
      python3 \
      python3-pip && \
    dnf clean all && \
    rm -rf /var/cache/dnf

########################
# Ansible & Lint-Tools #
########################

# Ansible Core, ansible-lint, yamllint
RUN pip3 install --no-cache-dir \
      "ansible-core>=2.16,<2.17" \
      "ansible-lint>=24.0.0" \
      "yamllint>=1.35.0"

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
ENV TFLINT_VERSION=0.53.0
RUN curl -sSLo /tmp/tflint.zip \
      "https://github.com/terraform-linters/tflint/releases/download/v${TFLINT_VERSION}/tflint_linux_amd64.zip" \
    && unzip /tmp/tflint.zip -d /usr/local/bin \
    && rm /tmp/tflint.zip

# terraform-docs
ENV TF_DOCS_VERSION=0.19.0
RUN curl -sSLo /tmp/terraform-docs.tar.gz \
      "https://github.com/terraform-docs/terraform-docs/releases/download/v${TF_DOCS_VERSION}/terraform-docs-v${TF_DOCS_VERSION}-linux-amd64.tar.gz" \
    && tar -xzf /tmp/terraform-docs.tar.gz -C /usr/local/bin terraform-docs \
    && chmod +x /usr/local/bin/terraform-docs \
    && rm /tmp/terraform-docs.tar.gz

########################
# User & Workdir       #
########################

WORKDIR /workspace

RUN useradd -m wunder && chown -R wunder /workspace
USER wunder

# Default entrypoint: shell 
ENTRYPOINT ["/bin/bash"]
