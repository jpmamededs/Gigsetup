# -*- mode: python ; coding: utf-8 -*-
#
# PyInstaller spec for the macOS build of the DJ Metadata launcher.
# Produces a windowed, arm64-only .app bundle (no code signing, no notarization,
# no .dmg — those are out of scope by decision).
#
# Build with: pyinstaller --noconfirm DJMetadataLauncher-macos.spec
# (build_app.sh does this after building ui/dist and generating the icon.)

import os

ROOT = os.path.abspath(SPECPATH)

APP_NAME = "DJMetadataLauncher"

# ponytail: icon is a nice-to-have generated asset (see ui/scripts/generate_icon.mjs).
# If it hasn't been generated yet, build without one instead of failing the whole app.
ICON_PATH = os.path.join(ROOT, "assets", "dj_launcher.icns")
if not os.path.isfile(ICON_PATH):
    print(f"WARNING: icon not found at {ICON_PATH}; building {APP_NAME}.app without a custom icon.")
    ICON_PATH = None

# launcher.py:187-195 resolve_frontend_entry() looks for ui/dist/index.html under
# BASE_DIR or sys._MEIPASS — either way it expects the whole built frontend tree
# at "ui/dist" relative to the app resources, so ship it verbatim.
UI_DIST = os.path.join(ROOT, "ui", "dist")
if not os.path.isdir(UI_DIST):
    raise SystemExit(
        "ui/dist not found. Run `cd ui && npm install && npm run build` before packaging "
        "(build_app.sh does this for you)."
    )

a = Analysis(
    [os.path.join(ROOT, "launcher.py")],
    pathex=[ROOT],
    binaries=[],
    datas=[(UI_DIST, os.path.join("ui", "dist"))],
    hiddenimports=[],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
    optimize=0,
)

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name=APP_NAME,
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,
    target_arch="arm64",
    codesign_identity=None,
    entitlements_file=None,
    icon=ICON_PATH,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name=APP_NAME,
)

app = BUNDLE(
    coll,
    name=f"{APP_NAME}.app",
    icon=ICON_PATH,
    bundle_identifier="com.gigsetup.djmetadatalauncher",
    info_plist={
        "CFBundleShortVersionString": "1.0.0",
        "NSHighResolutionCapable": True,
        "LSMinimumSystemVersion": "11.0",
    },
)
