#!/usr/bin/env bash
set -euo pipefail

# Builds the macOS .app bundle for the DJ Metadata launcher: frontend -> icon -> PyInstaller.
# arm64 only, no signing, no notarization, no .dmg (by decision). Windows packaging is out
# of scope for this script — see build_exe.bat (not versioned) for that path.
#
# ponytail: no flags, no menu. Override the python interpreter with PYTHON_BIN=... if the
# default lookup below picks the wrong one.

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$ROOT"

SPEC_FILE="DJMetadataLauncher-macos.spec"
APP_NAME="DJMetadataLauncher.app"

if [ -z "${PYTHON_BIN:-}" ]; then
    if [ -x "./.venv/bin/python" ]; then
        PYTHON_BIN="./.venv/bin/python"
    elif command -v python3.14 >/dev/null 2>&1; then
        PYTHON_BIN="python3.14"
    else
        PYTHON_BIN="python3"
    fi
fi

echo "==> Using python: $(command -v "$PYTHON_BIN")"

"$PYTHON_BIN" - <<'PYEOF'
import sys
if sys.platform != "darwin":
    sys.exit("build_app.sh only targets macOS.")
if sys.version_info < (3, 10):
    sys.exit(f"Python 3.10+ required, got {sys.version}.")
PYEOF

for mod in PyInstaller webview; do
    if ! "$PYTHON_BIN" -c "import ${mod}" >/dev/null 2>&1; then
        echo "ERROR: '${mod}' is not importable with $PYTHON_BIN." >&2
        echo "       Create the project venv first (Homebrew python is PEP 668 externally-managed," >&2
        echo "       so a bare 'pip install' fails):" >&2
        echo "         python3.14 -m venv .venv && .venv/bin/pip install -r requirements.txt" >&2
        echo "       Then re-run this script; it picks up ./.venv automatically." >&2
        exit 1
    fi
done

if ! command -v node >/dev/null 2>&1; then
    echo "ERROR: node is required to build the frontend and generate the app icon." >&2
    exit 1
fi

echo "==> [1/3] Building frontend (ui/dist)"
( cd ui && npm install && npm run build )

echo "==> [2/3] Generating app icon (assets/dj_launcher.icns)"
if ( cd ui && node scripts/generate_icon.mjs ); then
    echo "    icon generated."
else
    echo "WARNING: icon generation failed; the app will build without a custom icon." >&2
fi

echo "==> [3/3] Running PyInstaller ($SPEC_FILE, arm64)"
rm -rf "build/DJMetadataLauncher" "dist/$APP_NAME"
"$PYTHON_BIN" -m PyInstaller --noconfirm "$SPEC_FILE"

if [ ! -d "dist/$APP_NAME" ]; then
    echo "ERROR: build finished but dist/$APP_NAME was not produced." >&2
    exit 1
fi

echo "==> Done. App bundle: $ROOT/dist/$APP_NAME"
