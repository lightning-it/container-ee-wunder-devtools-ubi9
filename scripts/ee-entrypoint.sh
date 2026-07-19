#!/usr/bin/env bash
set -euo pipefail

if [ "$#" -eq 0 ]; then
  set -- /bin/bash
fi

if ! whoami >/dev/null 2>&1; then
  uid="$(id -u)"
  gid="$(id -g)"
  home="${HOME:-/tmp}"

  export NSS_WRAPPER_PASSWD="${TMPDIR:-/tmp}/passwd.nss_wrapper"
  export NSS_WRAPPER_GROUP="${TMPDIR:-/tmp}/group.nss_wrapper"

  if [ -r /etc/passwd ]; then
    cat /etc/passwd > "$NSS_WRAPPER_PASSWD"
  else
    : > "$NSS_WRAPPER_PASSWD"
  fi
  echo "eeuser:x:${uid}:${gid}:EE User:${home}:/bin/bash" >> "$NSS_WRAPPER_PASSWD"

  if [ -r /etc/group ]; then
    cat /etc/group > "$NSS_WRAPPER_GROUP"
  else
    : > "$NSS_WRAPPER_GROUP"
  fi
  echo "eegroup:x:${gid}:" >> "$NSS_WRAPPER_GROUP"

  wrapper="/usr/lib64/libnss_wrapper.so"
  if [ -f "$wrapper" ]; then
    export LD_PRELOAD="${wrapper}${LD_PRELOAD:+:${LD_PRELOAD}}"
  fi
fi

exec "$@"
