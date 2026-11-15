#!/bin/sh
# Build `dist/Quadraui Files.app` (and, with --dmg, a disk image) from the
# in-tree virtualenv with PyInstaller.
#
#     sh scripts/build-macos-app.sh            # .app only
#     sh scripts/build-macos-app.sh --dmg      # .app + dist/Quadraui-Files-<ver>.dmg
#     open "dist/Quadraui Files.app"
#
# Signing: unset CODESIGN_IDENTITY gives the ad-hoc signature PyInstaller
# applies by default, which runs on this Mac but which Gatekeeper rejects on
# any other. To distribute, set CODESIGN_IDENTITY="Developer ID Application:
# ..." and then notarize the .dmg (`xcrun notarytool submit ... --wait`,
# `xcrun stapler staple ...`).
set -eu

repo_root=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
cd "$repo_root"

PYTHON=${PYTHON:-.venv/bin/python}

if [ "$(uname -s)" != Darwin ]; then
    echo "build-macos-app.sh: macOS only" >&2
    exit 1
fi

backend=$("$PYTHON" -c 'from quadraui._quadraui import _NATIVE_BACKEND; print(_NATIVE_BACKEND)' 2>/dev/null || echo None)
if [ "$backend" != macos ]; then
    echo "build-macos-app.sh: the installed quadraui has no macOS backend (got: $backend)." >&2
    echo "Install the PyPI wheel, or rebuild with MATURIN_PEP517_ARGS=\"--features macos\"." >&2
    exit 1
fi

if ! "$PYTHON" -c 'import PyInstaller' >/dev/null 2>&1; then
    echo "Installing PyInstaller into $PYTHON's environment..." >&2
    "$PYTHON" -m pip install -q 'pyinstaller>=6'
fi

QUADRAUI_FILES_VERSION=$("$PYTHON" -c 'import tomllib; print(tomllib.load(open("pyproject.toml","rb"))["project"]["version"])')
export QUADRAUI_FILES_VERSION

"$PYTHON" -m PyInstaller --noconfirm --clean \
    --distpath dist --workpath build/pyinstaller \
    packaging/macos/quadraui-files.spec

app="dist/Quadraui Files.app"
echo "Built $app (version $QUADRAUI_FILES_VERSION)" >&2

if [ "${1:-}" = --dmg ]; then
    dmg="dist/Quadraui-Files-$QUADRAUI_FILES_VERSION.dmg"
    staging=build/dmg
    rm -rf "$staging" "$dmg"
    mkdir -p "$staging"
    cp -R "$app" "$staging/"
    ln -s /Applications "$staging/Applications"
    hdiutil create -quiet -volname "Quadraui Files" -srcfolder "$staging" -ov -format UDZO "$dmg"
    echo "Built $dmg" >&2
fi
