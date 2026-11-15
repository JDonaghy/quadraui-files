# PyInstaller spec for `Quadraui Files.app`. Build it with
# `scripts/build-macos-app.sh`, not by calling pyinstaller directly: that
# script sets the version and checks that quadraui was built with the macOS
# backend.
#
# Why a bundle at all: an unbundled `python -m quadraui_files --native` gets
# its name from Homebrew's `Python.app` (so the app menu says "Python"), and
# since macOS 14 it can't take focus from a terminal that won't hand it over
# (Ghostty). Inside a real bundle with its own executable in
# Contents/MacOS, `CFBundleName` names the app menu, and LaunchServices
# activates the app on launch.

import os

from PyInstaller.utils.hooks import collect_data_files

repo_root = os.path.abspath(os.path.join(SPECPATH, "..", ".."))

APP_NAME = "Quadraui Files"
BUNDLE_ID = "io.github.jdonaghy.quadraui-files"
VERSION = os.environ.get("QUADRAUI_FILES_VERSION", "0.0.0")

a = Analysis(
    [os.path.join(SPECPATH, "launcher.py")],
    pathex=[os.path.join(repo_root, "src")],
    # `app.py` reads `_NATIVE_BACKEND` straight from the compiled extension,
    # and the extension's own `.pyi`/data files ship beside it.
    hiddenimports=["quadraui._quadraui"],
    datas=collect_data_files("quadraui"),
    # The pytest plugin and the hot-reloader are dev-only.
    excludes=["quadraui.testing", "pytest", "_pytest", "tkinter"],
    noarchive=False,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="quadraui-files",
    console=False,
    argv_emulation=False,
    target_arch=None,  # the quadraui wheel is arm64-only today
    codesign_identity=os.environ.get("CODESIGN_IDENTITY") or None,
    entitlements_file=None,
)
coll = COLLECT(exe, a.binaries, a.datas, name="quadraui-files")

app = BUNDLE(
    coll,
    name=f"{APP_NAME}.app",
    icon=None,  # no .icns yet: the Dock shows the generic app icon
    bundle_identifier=BUNDLE_ID,
    version=VERSION,
    info_plist={
        "CFBundleName": APP_NAME,
        "CFBundleDisplayName": APP_NAME,
        "CFBundleShortVersionString": VERSION,
        "CFBundleVersion": VERSION,
        "LSMinimumSystemVersion": "11.0",
        "LSApplicationCategoryType": "public.app-category.utilities",
        "NSHighResolutionCapable": True,
        "NSHumanReadableCopyright": "MIT License",
        # A bundled app gets its own privacy (TCC) grants rather than
        # inheriting the terminal's, so the first listing of ~/Desktop,
        # ~/Documents, etc. blocks on a consent prompt. These strings are
        # the reason that prompt shows.
        "NSDesktopFolderUsageDescription": "Quadraui Files shows the contents of your Desktop folder.",
        "NSDocumentsFolderUsageDescription": "Quadraui Files shows the contents of your Documents folder.",
        "NSDownloadsFolderUsageDescription": "Quadraui Files shows the contents of your Downloads folder.",
        "NSRemovableVolumesUsageDescription": "Quadraui Files shows the contents of removable drives.",
        "NSNetworkVolumesUsageDescription": "Quadraui Files shows the contents of network volumes.",
    },
)
