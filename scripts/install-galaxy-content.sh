#!/usr/bin/env bash
set -euo pipefail

mode="${1:?usage: install-galaxy-content.sh collections|controller|roles}"
profile="${COLLECTION_PROFILE:-public}"
collection_opts="${ANSIBLE_GALAXY_CLI_COLLECTION_OPTS:-}"
collection_args=()
attempts="${ANSIBLE_GALAXY_INSTALL_RETRIES:-5}"
delay="${ANSIBLE_GALAXY_RETRY_DELAY_SECONDS:-10}"
hub_url="${AUTOMATION_HUB_URL:-https://console.redhat.com/api/automation-hub/content/published/}"
hub_sso_url="${AUTOMATION_HUB_SSO_URL:-${AUTOMATION_HUB_TOKEN_URL:-${AUTOMATION_HUB_AUTH_URL:-https://sso.redhat.com/auth/realms/redhat-external/protocol/openid-connect/token}}}"
config_path="/tmp/ansible-galaxy.cfg"

if [ -n "$collection_opts" ]; then
  read -r -a collection_args <<< "$collection_opts"
fi

install_with_retry() {
  local try=1

  until "$@"; do
    if [ "$try" -ge "$attempts" ]; then
      return 1
    fi
    echo "ansible-galaxy failed (attempt ${try}/${attempts}); retrying in ${delay}s..."
    sleep "$delay"
    try=$((try + 1))
  done
}

galaxy_cmd() {
  if [ -f "$config_path" ]; then
    ANSIBLE_CONFIG="$config_path" ansible-galaxy "$@"
  else
    ansible-galaxy "$@"
  fi
}

has_collection_requirements() {
  grep -Eq '^[[:space:]]*collections:[[:space:]]*$|^[[:space:]]*-[[:space:]]*name:' "$1"
}

has_role_requirements() {
  grep -Eq '^[[:space:]]*-[[:space:]]*(src|name):' "$1"
}

read_automation_hub_token() {
  local token_file="/run/secrets/rh_automation_hub_token"

  if [ ! -s "$token_file" ]; then
    echo "ERROR: missing required build secret for certified profile: rh_automation_hub_token" >&2
    return 1
  fi

  token="$(tr -d '\r\n' < "$token_file")"
  if [ -z "$token" ]; then
    echo "ERROR: build secret rh_automation_hub_token is empty" >&2
    return 1
  fi
}

configure_automation_hub() {
  read_automation_hub_token
  {
    echo "[galaxy]"
    echo "server_list = automation_hub,galaxy"
    echo
    echo "[galaxy_server.automation_hub]"
    echo "url=${hub_url}"
    echo "auth_url=${hub_sso_url}"
    echo "token=${token}"
    echo
    echo "[galaxy_server.galaxy]"
    echo "url=https://galaxy.ansible.com/"
  } > "$config_path"
}

validate_profile() {
  case "$profile" in
    public|certified|bootstrap) ;;
    *)
      echo "ERROR: invalid COLLECTION_PROFILE='${profile}' (use: public|certified|bootstrap)" >&2
      return 1
      ;;
  esac
}

install_collections() {
  local base_req="/build/collections-requirements-base.yml"
  local certified_req="/build/collections-requirements-certified-extra.yml"

  validate_profile

  case "$profile" in
    bootstrap)
      echo "COLLECTION_PROFILE=bootstrap selected: skipping collections install"
      ;;
    public|certified)
      if [ ! -f "$base_req" ]; then
        echo "ERROR: base collections requirements file not found: ${base_req}" >&2
        return 1
      fi
      install_with_retry galaxy_cmd collection install "${collection_args[@]}" \
        -r "$base_req" \
        --collections-path /usr/share/ansible/collections
      ;;
  esac

  if [ "$profile" = "certified" ]; then
    if [ ! -f "$certified_req" ]; then
      echo "ERROR: certified extra requirements file not found: ${certified_req}" >&2
      return 1
    fi
    configure_automation_hub
    install_with_retry galaxy_cmd collection install "${collection_args[@]}" \
      -r "$certified_req" \
      --collections-path /usr/share/ansible/collections
  fi

  galaxy_cmd collection list -p /usr/share/ansible/collections
}

install_controller_collections() {
  local req="/build/controller-requirements.yml"

  validate_profile

  if ! has_collection_requirements "$req"; then
    echo "No controller collections to install (${req} empty or no valid entries). Skipping."
    return 0
  fi

  if [ "$profile" = "bootstrap" ]; then
    echo "COLLECTION_PROFILE=bootstrap selected: skipping controller collections install"
    return 0
  fi

  if [ "$profile" = "certified" ]; then
    configure_automation_hub
  fi

  install_with_retry galaxy_cmd collection install "${collection_args[@]}" \
    -r "$req" \
    --collections-path /usr/share/automation-controller/collections
  galaxy_cmd collection list -p /usr/share/automation-controller/collections
}

install_roles() {
  local req="/build/roles-requirements.yml"

  if has_role_requirements "$req"; then
    ansible-galaxy role install \
      -r "$req" \
      -p /usr/share/ansible/roles
    ansible-galaxy role list -p /usr/share/ansible/roles
  else
    echo "No roles to install (${req} empty or no valid entries). Skipping."
  fi
}

trap 'rm -f "$config_path"' EXIT

case "$mode" in
  collections) install_collections ;;
  controller) install_controller_collections ;;
  roles) install_roles ;;
  *)
    echo "ERROR: unsupported mode '${mode}' (use: collections|controller|roles)" >&2
    exit 1
    ;;
esac
