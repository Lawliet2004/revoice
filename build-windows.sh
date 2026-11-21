#!/bin/sh
set -eu
cd "$(dirname -- "$0")"

release=20261110
runtime_version=3.12.16
runtime_hash=e23fe5b16926de1d81661b1a97352e89fb167549c55a6825796ccd0f32ec7f1b
runtime_url="https://github.com/astral-sh/python-build-standalone/releases/download/$release"
runtime_file="cpython-$runtime_version%2B$release-x86_64-pc-windows-msvc-install_only.tar.gz"
runtime_archive=${REVOICE_WINDOWS_RUNTIME:-build/windows-python-$runtime_version.tar.gz}
mkdir -p build dist

stage=$(mktemp -d "$PWD/build/windows.XXXXXX")
trap 'rm -rf "$stage"' EXIT INT TERM
if [ ! -f "$runtime_archive" ]; then
    curl -fsSL --retry 2 --connect-timeout 15 --max-time 240 "$runtime_url/$runtime_file" -o "$stage/python.tar.gz"
    printf '%s  %s\n' "$runtime_hash" "$stage/python.tar.gz" | sha256sum -c
    mv "$stage/python.tar.gz" "$runtime_archive"
fi
printf '%s  %s\n' "$runtime_hash" "$runtime_archive" | sha256sum -c

app="$stage/Revoice"
mkdir -p "$app/revoice_app"
tar -xzf "$runtime_archive" -C "$stage"
mv "$stage/python" "$app/runtime"
find "$app/runtime" -type f -name '*.pdb' -delete
uv pip install --only-binary :all: --python-platform x86_64-pc-windows-msvc \
    --python-version "$runtime_version" --target "$app/runtime/Lib/site-packages" -r windows/requirements.txt
install -m 644 revoice_app/__init__.py revoice_app/config.py revoice_app/speech.py revoice_app/websocket_compat.py \
    revoice_app/windows.py revoice_app/windows_audio.py revoice_app/windows_desktop.py "$app/revoice_app/"
install -m 644 windows/Revoice.cmd windows/start_revoice.pyw "$app/"
install -m 644 windows/README.md "$app/README.md"
install -m 644 THIRD_PARTY_NOTICES.md "$app/"
python3 - "$stage" <<'PY'
import shutil
import sys
from pathlib import Path

stage = Path(sys.argv[1])
shutil.make_archive(str(stage / "revoice-windows-x64"), "zip", root_dir=stage, base_dir="Revoice")
PY
mv "$stage/revoice-windows-x64.zip" dist/revoice-windows-x64.zip
printf '%s\n' "Built dist/revoice-windows-x64.zip."
