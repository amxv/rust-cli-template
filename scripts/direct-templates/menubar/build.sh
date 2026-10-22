#!/usr/bin/env bash
set -euo pipefail

# Build and ad-hoc sign a standalone Swift menu bar application.
# The companion CLI is installed beside the .app bundle, not inside it.
root="$(cd "$(dirname "$0")/../.." && pwd)"
source_dir="$root/apps/menubar"
output="$1"
architecture="$2"
version="$3"
case "$architecture" in
  arm64|aarch64) swift_arch=arm64 ;;
  amd64|x86_64) swift_arch=x86_64 ;;
  *) echo "Unsupported macOS architecture: $architecture" >&2; exit 2 ;;
esac
[[ "$version" =~ ^[0-9]+\.[0-9]+\.[0-9]+$ ]] || { echo "Expected X.Y.Z release version" >&2; exit 2; }
[[ "$output" = /* ]] || { echo "App output must be an absolute path" >&2; exit 2; }
[[ "$output" != "/" && "$output" != "$root" && "$output" != "$HOME" ]] || { echo "Unsafe app output" >&2; exit 2; }

rm -rf "$output"
mkdir -p "$output/Contents/MacOS"
cp "$source_dir/Info.plist" "$output/Contents/Info.plist"
for key in CFBundleShortVersionString CFBundleVersion AppReleaseVersion; do
  /usr/libexec/PlistBuddy -c "Set :$key $version" "$output/Contents/Info.plist"
done
/usr/bin/swiftc -O -target "$swift_arch-apple-macos13.0" \
  "$source_dir/Sources/main.swift" \
  -o "$output/Contents/MacOS/__APP_EXEC__"

# Ad-hoc signing does NOT notarize. Browser downloads can remain quarantined.
codesign --force --sign "${MACOS_CODESIGN_IDENTITY:--}" "$output"
codesign --verify --deep --strict "$output"
printf 'Built and signed %s (%s, v%s)\n' "$output" "$swift_arch" "$version"
