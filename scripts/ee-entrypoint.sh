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

  (cat /etc/passwd 2>/dev/null || true) > "$NSS_WRAPPER_PASSWD"
  echo "eeuser:x:${uid}:${gid}:EE User:${home}:/bin/bash" >> "$NSS_WRAPPER_PASSWD"

  (cat /etc/group 2>/dev/null || true) > "$NSS_WRAPPER_GROUP"
  echo "eegroup:x:${gid}:" >> "$NSS_WRAPPER_GROUP"

  wrapper="/usr/lib64/libnss_wrapper.so"
  if [ -f "$wrapper" ]; then
    export LD_PRELOAD="${wrapper}${LD_PRELOAD:+:${LD_PRELOAD}}"
  fi
fi

exec "$@"
