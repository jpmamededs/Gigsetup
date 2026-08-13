from __future__ import annotations

import argparse
import datetime as dt
import os
import re
import subprocess
from pathlib import Path


def _safe_int(value: str, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _git_tag() -> str | None:
    try:
        value = subprocess.check_output(
            ["git", "describe", "--tags", "--abbrev=0"],
            stderr=subprocess.DEVNULL,
            text=True,
        ).strip()
        return value or None
    except Exception:
        return None


def _resolve_versions() -> tuple[str, tuple[int, int, int, int]]:
    override = os.getenv("APP_VERSION_OVERRIDE", "").strip()
    now = dt.datetime.now()

    raw_version = override or _git_tag() or now.strftime("%Y.%m.%d.%H%M")
    display = raw_version.lstrip("vV")

    numeric_parts = [_safe_int(part) for part in re.findall(r"\d+", display)]

    if len(numeric_parts) >= 3:
        major = numeric_parts[0]
        minor = numeric_parts[1]
        patch = numeric_parts[2]
        build = numeric_parts[3] if len(numeric_parts) >= 4 else now.hour * 100 + now.minute
    else:
        major = now.year
        minor = now.month
        patch = now.day
        build = now.hour * 100 + now.minute

    file_tuple = (major, minor, patch, build)
    normalized_display = display if display else now.strftime("%Y.%m.%d.%H%M")
    return normalized_display, file_tuple


def _version_info_content(app_name: str, display_version: str, file_tuple: tuple[int, int, int, int]) -> str:
    file_version = ".".join(str(x) for x in file_tuple)
    major, minor, patch, build = file_tuple
    return f"""# UTF-8
# Arquivo gerado automaticamente por scripts/generate_version_info.py
VSVersionInfo(
  ffi=FixedFileInfo(
    filevers=({major}, {minor}, {patch}, {build}),
    prodvers=({major}, {minor}, {patch}, {build}),
    mask=0x3F,
    flags=0x0,
    OS=0x40004,
    fileType=0x1,
    subtype=0x0,
    date=(0, 0)
  ),
  kids=[
    StringFileInfo([
      StringTable(
        '040904B0',
        [
          StringStruct('CompanyName', 'DJ Music Metadata MCP'),
          StringStruct('FileDescription', 'Launcher desktop para servidor MCP de metadata musical'),
          StringStruct('FileVersion', '{file_version}'),
          StringStruct('InternalName', '{app_name}'),
          StringStruct('LegalCopyright', 'Copyright (c) 2026'),
          StringStruct('OriginalFilename', '{app_name}.exe'),
          StringStruct('ProductName', '{app_name}'),
          StringStruct('ProductVersion', '{display_version}')
        ]
      )
    ]),
    VarFileInfo([
      VarStruct('Translation', [1033, 1200])
    ])
  ]
)
"""


def main() -> int:
    parser = argparse.ArgumentParser(description="Gera arquivo de version info para PyInstaller.")
    parser.add_argument("--app-name", required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()

    display_version, file_tuple = _resolve_versions()
    output_path = Path(args.output)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        _version_info_content(args.app_name, display_version, file_tuple),
        encoding="utf-8",
        newline="\n",
    )

    print(f"APP_VERSION={display_version}")
    print(f"FILE_VERSION={'.'.join(str(x) for x in file_tuple)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
