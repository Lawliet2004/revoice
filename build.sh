#!/bin/sh
set -eu
cd "$(dirname -- "$0")"

mkdir -p build dist
wayland-scanner client-header native/ext-data-control-v1.xml build/data-control.h
wayland-scanner private-code native/ext-data-control-v1.xml build/data-control.c
# pkg-config emits the compiler arguments as separate words.
# shellcheck disable=SC2046
"${CC:-cc}" -O2 -Wall -Wextra -Werror -Ibuild native/clipboard.c build/data-control.c \
    $(pkg-config --cflags --libs wayland-client) -o build/revoice-clipboard
wayland-scanner client-header native/keystate.xml build/keystate.h
wayland-scanner private-code native/keystate.xml build/keystate.c
# shellcheck disable=SC2046
"${CC:-cc}" -O2 -Wall -Wextra -Werror -Ibuild native/modifiers.c build/keystate.c \
    $(pkg-config --cflags --libs wayland-client) -o build/revoice-modifiers

if [ "${1:-}" != "--package" ]; then
    printf '%s\n' "Built the native Wayland helpers. Run ./revoice to open Revoice."
    exit 0
fi

revoice_stage=$(mktemp -d "$PWD/build/package.XXXXXX")
trap 'rm -rf "$revoice_stage"' EXIT INT TERM
chmod 755 "$revoice_stage"
revoice_arch=$(dpkg --print-architecture)
revoice_version=$(sed -n 's/^VERSION = "\(.*\)"$/\1/p' revoice_app/__main__.py)
mkdir -p "$revoice_stage/DEBIAN" "$revoice_stage/opt/revoice/revoice_app" \
    "$revoice_stage/opt/revoice/build" "$revoice_stage/usr/bin" \
    "$revoice_stage/usr/share/applications" "$revoice_stage/usr/share/icons/hicolor/scalable/apps" \
    "$revoice_stage/usr/share/doc/revoice"
install -m 755 revoice "$revoice_stage/usr/bin/revoice"
install -m 755 build/revoice-clipboard "$revoice_stage/opt/revoice/build/"
install -m 755 build/revoice-modifiers "$revoice_stage/opt/revoice/build/"
install -m 644 revoice_app/*.py revoice_app/*.js revoice_app/*.css revoice_app/*.svg "$revoice_stage/opt/revoice/revoice_app/"
install -d "$revoice_stage/opt/revoice/revoice_app/web"
install -m 644 revoice_app/web/* "$revoice_stage/opt/revoice/revoice_app/web/"
install -m 644 io.github.revoice.Revoice.desktop "$revoice_stage/usr/share/applications/"
install -m 644 revoice_app/icon.svg "$revoice_stage/usr/share/icons/hicolor/scalable/apps/io.github.revoice.Revoice.svg"
install -m 644 README.md THIRD_PARTY_NOTICES.md "$revoice_stage/usr/share/doc/revoice/"
install -m 644 native/ext-data-control-v1.xml native/keystate.xml LICENSES/LGPL-2.1-or-later.txt "$revoice_stage/usr/share/doc/revoice/"
cat > "$revoice_stage/DEBIAN/control" <<CONTROL
Package: revoice
Version: $revoice_version
Section: utils
Priority: optional
Architecture: $revoice_arch
Maintainer: Revoice Project
Depends: python3 (>= 3.11), python3-gi, python3-gi-cairo, python3-dbus, python3-evdev, python3-websockets (>= 10.4), gir1.2-gtk-3.0, gir1.2-webkit2-4.1, gir1.2-gtklayershell-0.1, libwayland-client0, pipewire-bin, pulseaudio-utils, wl-clipboard, xclip
Recommends: gir1.2-ayatanaappindicator3-0.1, libsecret-tools
Description: Global voice typing for Linux
 Revoice provides configurable desktop shortcuts, a floating dictation pill,
 text insertion, and transcript history. It supports Codex sign-in and the
 separately billed OpenAI transcription API.
CONTROL
dpkg-deb --root-owner-group --build "$revoice_stage" "dist/revoice_${revoice_version}_${revoice_arch}.deb"
