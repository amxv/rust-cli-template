#!/bin/sh
# Website-hosted installer. cargo-dist publishes and verifies release archives.
set -eu
cli='__CLI__'
repo='https://github.com/__OWNER__/__REPO__'
mode=${1:-install}
case "$mode" in install|upgrade|--check) ;; *) echo 'Usage: install.sh [upgrade|--check]' >&2; exit 2;; esac
for command in curl sh; do command -v "$command" >/dev/null 2>&1 || { echo "$command is required" >&2; exit 1; }; done
if [ "$mode" = --check ]; then
  printf 'Installed: '
  if command -v "$cli" >/dev/null 2>&1; then "$cli" --version; else echo '(not installed)'; fi
  curl --proto '=https' --tlsv1.2 -fsSIL -o /dev/null -w 'Latest release: %{url_effective}\n' "$repo/releases/latest"
  exit 0
fi

if [ "$mode" = upgrade ] && [ -n "${CLI_UPGRADE_TARGET:-}" ]; then
  case "$CLI_UPGRADE_TARGET" in /*) ;; *) echo 'Upgrade target must be absolute' >&2; exit 1;; esac
  if [ ! -f "$CLI_UPGRADE_TARGET" ] || [ -L "$CLI_UPGRADE_TARGET" ]; then
    echo 'Upgrade requires a regular installed executable' >&2; exit 1
  fi
  __CLI_ENV___INSTALL_DIR=$(dirname "$CLI_UPGRADE_TARGET")
  export __CLI_ENV___INSTALL_DIR
fi
umask 077
stage=$(mktemp -d "${TMPDIR:-/tmp}/${cli}-install.XXXXXXXX")
trap 'rm -rf "$stage"' EXIT HUP INT TERM
# cargo-dist uses sha256sum for release verification. Make its verifier
# available on macOS, where shasum is installed instead.
if ! command -v sha256sum >/dev/null 2>&1; then
  command -v shasum >/dev/null 2>&1 || { echo 'shasum or sha256sum is required' >&2; exit 1; }
  printf '#!/bin/sh\nexec shasum -a 256 "$@"\n' > "$stage/sha256sum"
  chmod 755 "$stage/sha256sum"
  PATH="$stage:$PATH"
  export PATH
fi
curl --proto '=https' --tlsv1.2 -fsSL --retry 3 \
  "$repo/releases/latest/download/${cli}-installer.sh" -o "$stage/installer.sh"
sh "$stage/installer.sh"
