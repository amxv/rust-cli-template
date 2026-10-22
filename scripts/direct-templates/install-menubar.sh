#!/bin/sh
# Installs the CLI; on macOS also installs and relaunches its signed Swift .app.
# curl/tar creates no Finder quarantine metadata. This is NOT notarization.
set -eu
cli='__CLI__'
binary='__BINARY__'
app='__APP_NAME__.app'
app_exec='__APP_EXEC__'
repo='https://github.com/__OWNER__/__REPO__'
action=${1:-install}
case "$action" in install|upgrade|--check) ;; *) echo "Usage: install.sh [upgrade|--check]" >&2; exit 2 ;; esac
case "$(uname -s)" in
  Darwin) os=darwin; mac=1 ;;
  Linux) os=linux; mac=0 ;;
  *) echo 'On Windows use __SITE__/install.ps1' >&2; exit 1 ;;
esac
case "$(uname -m)" in
  arm64|aarch64) arch=arm64 ;;
  x86_64|amd64) arch=amd64 ;;
  *) echo 'Unsupported CPU architecture' >&2; exit 1 ;;
esac
install_dir=${CLI_INSTALL_DIR:-"$HOME/.local/bin"}
case "$install_dir" in /*) ;; *) echo 'CLI_INSTALL_DIR must be absolute' >&2; exit 1 ;; esac
target=${CLI_UPGRADE_TARGET:-"$install_dir/$cli"}
case "$target" in /*) ;; *) echo 'CLI_UPGRADE_TARGET must be absolute' >&2; exit 1 ;; esac
install_dir=$(dirname "$target")
app_dest="$install_dir/$app"
if [ -L "$target" ] || [ -L "$app_dest" ]; then
  echo 'Refusing to replace a symlink installation' >&2; exit 1
fi
if [ "$action" = install ] && { [ -e "$target" ] || [ -e "$app_dest" ]; }; then
  echo "$cli is installed. Use '$cli upgrade' rather than reinstalling." >&2; exit 1
fi
if [ "$action" = upgrade ] && [ ! -f "$target" ]; then
  echo "No installed CLI at $target" >&2; exit 1
fi
if [ "$action" = --check ]; then
  printf 'Installed: '
  if [ -x "$target" ]; then "$target" --version; else echo '(not installed)'; fi
  curl --proto '=https' --tlsv1.2 -fsSIL --max-time 20 -o /dev/null \
    -w 'Latest release: %{url_effective}\n' "$repo/releases/latest"
  exit 0
fi

version=${CLI_VERSION:-}
if [ -n "$version" ]; then
  version=${version#v}
  printf '%s\n' "$version" | grep -Eq '^[0-9]+\.[0-9]+\.[0-9]+$' || { echo 'Invalid CLI_VERSION' >&2; exit 1; }
  base="$repo/releases/download/v$version"
else
  base="$repo/releases/latest/download"
fi
# Linux uses the regular checksum-verifying cargo-dist shell installer.
# The macOS path below installs the paired CLI + signed .app archive.
if [ "$mac" = 0 ]; then
  umask 077
  stage=$(mktemp -d "${TMPDIR:-/tmp}/$cli-install.XXXXXXXX")
  trap 'rm -rf "$stage"' EXIT HUP INT TERM
  curl --proto '=https' --tlsv1.2 -fsSL --retry 3 \
    "$base/$cli-installer.sh" -o "$stage/installer.sh"
  __CLI_ENV___INSTALL_DIR="$install_dir"
  export __CLI_ENV___INSTALL_DIR
  if ! command -v sha256sum >/dev/null 2>&1; then
    command -v shasum >/dev/null 2>&1 || { echo 'sha256sum or shasum is required' >&2; exit 1; }
    printf '#!/bin/sh\nexec shasum -a 256 "$@"\n' > "$stage/sha256sum"
    chmod 755 "$stage/sha256sum"
    PATH="$stage:$PATH"
    export PATH
  fi
  sh "$stage/installer.sh"
  exit 0
fi
for tool in curl awk tar; do
  command -v "$tool" >/dev/null 2>&1 || { echo "$tool is required" >&2; exit 1; }
done
umask 077
stage=$(mktemp -d "${TMPDIR:-/tmp}/$cli-install.XXXXXXXX")
trap 'rm -rf "$stage"' EXIT HUP INT TERM
if [ "$mac" = 1 ]; then
  asset="${binary}_darwin_${arch}.tar.gz"
  curl --proto '=https' --tlsv1.2 -fsSL --retry 3 "$base/$asset.sha256" -o "$stage/sums"
else
  asset="${binary}_linux_${arch}"
  curl --proto '=https' --tlsv1.2 -fsSL --retry 3 "$base/SHA256SUMS" -o "$stage/sums"
fi
curl --proto '=https' --tlsv1.2 -fsSL --retry 3 "$base/$asset" -o "$stage/$asset"
if [ "$mac" = 1 ]; then
  expected=$(awk 'NF { n++; value=$1 } END { if (n == 1) print value }' "$stage/sums")
else
  expected=$(awk -v name="$asset" '$2 == name { n++; value=$1 } END { if (n == 1) print value }' "$stage/sums")
fi
printf '%s' "$expected" | grep -Eq '^[[:xdigit:]]{64}$' || { echo 'Missing or ambiguous release checksum' >&2; exit 1; }
if command -v shasum >/dev/null 2>&1; then
  actual=$(shasum -a 256 "$stage/$asset" | awk '{print $1}')
else
  actual=$(sha256sum "$stage/$asset" | awk '{print $1}')
fi
[ "$actual" = "$expected" ] || { echo 'Checksum mismatch; installation unchanged' >&2; exit 1; }

if [ "$mac" = 1 ]; then
  mkdir "$stage/unpacked"
  tar -tzf "$stage/$asset" | while IFS= read -r entry; do
    case "$entry" in
      "$cli"|"$app"|"$app/"|"$app/"*|LICENSE) ;;
      *) echo "Unexpected or unsafe archive member: $entry" >&2; exit 1 ;;
    esac
  done
  tar -xzf "$stage/$asset" -C "$stage/unpacked"
  [ -x "$stage/unpacked/$cli" ] || { echo 'Archive is missing the CLI' >&2; exit 1; }
  [ -x "$stage/unpacked/$app/Contents/MacOS/$app_exec" ] || { echo 'Archive is missing the menu bar app' >&2; exit 1; }
  codesign --verify --deep --strict "$stage/unpacked/$app"
  "$stage/unpacked/$app/Contents/MacOS/$app_exec" --check
  source_cli="$stage/unpacked/$cli"
else
  source_cli="$stage/$asset"
  chmod 755 "$source_cli"
fi
"$source_cli" --version
mkdir -p "$install_dir"

if [ "$mac" != 1 ]; then
  pending=$(mktemp "$install_dir/.$cli-next.XXXXXXXX")
  trap 'rm -rf "$stage"; rm -f "$pending"' EXIT HUP INT TERM
  cp "$source_cli" "$pending"
  chmod 755 "$pending"
  mv -f "$pending" "$target"
  "$target" --version
  printf 'Installed %s at %s\n' "$cli" "$target"
  exit 0
fi

# Stage BOTH replacements before stopping the menu bar process. If any move
# fails, recover the old CLI/app from the sibling backup directory.
staged=$(mktemp -d "$install_dir/.$cli-stage.XXXXXXXX")
backup=$(mktemp -d "$install_dir/.$cli-backup.XXXXXXXX")
trap 'rm -rf "$stage" "$staged" "$backup"' EXIT HUP INT TERM
cp "$source_cli" "$staged/$cli"
chmod 755 "$staged/$cli"
cp -R "$stage/unpacked/$app" "$staged/$app"
codesign --verify --deep --strict "$staged/$app"
app_program="$app_dest/Contents/MacOS/$app_exec"
app_pids() {
  /bin/ps -axww -o uid= -o pid= -o command= 2>/dev/null |
    /usr/bin/awk -v uid="$(id -u)" -v executable="$app_program" '
      $1 == uid {
        pid=$2; $1=""; $2=""; sub(/^[[:space:]]+/, "")
        if ($0 == executable || $0 == executable " --after-upgrade") print pid
      }'
}
was_running=0
if [ -n "$(app_pids)" ]; then
  was_running=1
  for pid in $(app_pids); do kill -TERM "$pid" 2>/dev/null || true; done
  for attempt in 1 2 3 4 5 6 7 8 9 10 11 12 13 14 15 16 17 18 19 20 21 22 23 24 25 26 27 28 29 30; do
    [ -z "$(app_pids)" ] && break
    sleep 0.1
  done
  [ -z "$(app_pids)" ] || { echo 'Menu bar app did not exit; nothing was replaced' >&2; exit 1; }
fi
if [ -d "$app_dest" ]; then mv "$app_dest" "$backup/old-app"; fi
if [ -f "$target" ]; then mv "$target" "$backup/old-cli"; fi
restore() {
  rm -rf "$app_dest"
  rm -f "$target"
  [ ! -d "$backup/old-app" ] || mv "$backup/old-app" "$app_dest"
  [ ! -f "$backup/old-cli" ] || mv "$backup/old-cli" "$target"
  if [ "$was_running" = 1 ] && [ -d "$app_dest" ]; then
    /usr/bin/open -n -g "$app_dest" --args --after-upgrade >/dev/null 2>&1 || true
  fi
}
if ! mv "$staged/$app" "$app_dest" || ! mv "$staged/$cli" "$target"; then
  restore; echo 'Install failed; restored previous CLI and app' >&2; exit 1
fi
if ! codesign --verify --deep --strict "$app_dest" || ! "$target" --version; then
  restore; echo 'Installed app or CLI failed verification; restored previous release' >&2; exit 1
fi
rm -rf "$backup/old-app"
rm -f "$backup/old-cli"
printf 'Installed %s and %s at %s\n' "$cli" "$app" "$install_dir"
if [ "${CLI_NO_LAUNCH:-0}" != 1 ] && { [ "$action" = install ] || [ "$was_running" = 1 ]; }; then
  /usr/bin/open -n -g "$app_dest" --args --after-upgrade ||
    echo "Installed successfully, but could not launch $app; open it manually." >&2
fi
