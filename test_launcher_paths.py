"""Guards the path rules the frozen .app/.exe depends on. Run: python test_launcher_paths.py"""

from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import patch

import launcher


def _frozen_data_dir(platform: str) -> Path:
    with patch.object(sys, "frozen", True, create=True), patch.object(sys, "platform", platform):
        return launcher._app_data_dir()


def test_dev_writes_next_to_the_source() -> None:
    with patch.object(launcher.sys, "frozen", False, create=True):
        assert launcher._app_data_dir() == launcher.BASE_DIR


def test_frozen_never_writes_inside_the_bundle() -> None:
    # The whole point: _MEIPASS/Contents is read-only-by-contract, replaced on reinstall,
    # and writing there invalidates the code signature.
    for platform in ("darwin", "win32", "linux"):
        data_dir = _frozen_data_dir(platform)
        assert data_dir != launcher.BASE_DIR, platform
        assert data_dir.is_absolute(), platform
        assert "Contents" not in data_dir.parts, platform


def test_editor_configs_land_where_the_editor_reads() -> None:
    home = Path.home()
    for platform in ("darwin", "win32", "linux"):
        with patch.object(sys, "platform", platform):
            vscode = launcher._vscode_user_config()
        assert vscode.name == "mcp.json", platform
        assert launcher.BASE_DIR not in vscode.parents, platform

    # Cursor reads a single global file regardless of platform.
    assert (home / ".cursor" / "mcp.json").is_absolute()


def test_claude_cli_is_added_at_user_scope() -> None:
    # `claude mcp add` defaults to --scope local, which pins the server to the cwd.
    source = Path(launcher.__file__).read_text(encoding="utf-8")
    assert '"--scope", "user",' in source


if __name__ == "__main__":
    for name, case in sorted(globals().items()):
        if name.startswith("test_"):
            case()
            print(f"ok  {name}")
    print("\nall path guards passed")
