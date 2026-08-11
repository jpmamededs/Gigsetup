from __future__ import annotations

import json
import os
import subprocess
import sys
import threading
from pathlib import Path
from typing import Any

import webview

BASE_DIR = Path(__file__).resolve().parent


def _app_data_dir() -> Path:
    # ponytail: frozen builds must not write inside the bundle/_MEIPASS — macOS replaces
    # Contents/ on reinstall and writing there breaks the code signature; the Windows
    # onefile build unpacks to a temp dir that is deleted on exit.
    if not getattr(sys, "frozen", False):
        return BASE_DIR
    if sys.platform == "darwin":
        return Path.home() / "Library" / "Application Support" / "DJMetadataLauncher"
    if sys.platform == "win32":
        return Path(os.environ.get("APPDATA") or Path.home()) / "DJMetadataLauncher"
    return Path.home() / ".local" / "share" / "DJMetadataLauncher"


def _vscode_user_config() -> Path:
    if sys.platform == "darwin":
        base = Path.home() / "Library" / "Application Support" / "Code" / "User"
    elif sys.platform == "win32":
        base = Path(os.environ.get("APPDATA") or Path.home()) / "Code" / "User"
    else:
        base = Path.home() / ".config" / "Code" / "User"
    return base / "mcp.json"


DATA_DIR = _app_data_dir()
DATA_DIR.mkdir(parents=True, exist_ok=True)


class MCPDesktopApi:
    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._server_process: subprocess.Popen[str] | None = None
        self._config: dict[str, str] = {
            "serverName": "dj-music-metadata",
            "serverMode": "streamable-http",
            "host": "127.0.0.1",
            "port": "8000",
            "apiKey": "",
        }

    def get_state(self) -> dict[str, Any]:
        with self._lock:
            running = self._server_process is not None and self._server_process.poll() is None
            return {"ok": True, "running": running, "config": dict(self._config)}

    def update_config(self, payload: dict[str, Any]) -> dict[str, Any]:
        with self._lock:
            for key in self._config:
                value = payload.get(key)
                if value is not None:
                    self._config[key] = str(value)
        return self.get_state()

    def start_server(self) -> dict[str, Any]:
        with self._lock:
            if self._server_process and self._server_process.poll() is None:
                return {"ok": False, "message": "Server is already running."}

            command = self._server_command()
            try:
                self._server_process = subprocess.Popen(
                    command,
                    cwd=DATA_DIR,
                    env=self._server_env(),
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                )
            except Exception as exc:
                return {"ok": False, "message": str(exc)}

        return {"ok": True, "message": "Server started successfully."}

    def stop_server(self) -> dict[str, Any]:
        with self._lock:
            if not self._server_process or self._server_process.poll() is not None:
                return {"ok": False, "message": "No running server found."}
            self._server_process.terminate()
        return {"ok": True, "message": "Stop signal sent to server."}

    def connect_client(self, client_name: str) -> dict[str, Any]:
        normalized = (client_name or "").strip().lower()

        # Keep client connection config aligned with local HTTP mode.
        self.update_config(
            {
                "serverMode": "streamable-http",
                "host": "127.0.0.1",
                "port": "8000",
                "apiKey": "",
            }
        )

        try:
            if normalized in {"vscode", "vs code", "visual studio code"}:
                path = self._connect_vscode()
                return {"ok": True, "message": f"VS Code connected. File updated: {path}"}
            if normalized in {"cursor"}:
                path = self._connect_cursor()
                return {"ok": True, "message": f"Cursor connected. File updated: {path}"}
            if normalized in {"claude", "claude code"}:
                message = self._connect_claude()
                return {"ok": True, "message": message}
            return {"ok": False, "message": "Client not recognized."}
        except Exception as exc:
            return {"ok": False, "message": str(exc)}

    def shutdown(self) -> dict[str, Any]:
        with self._lock:
            if self._server_process and self._server_process.poll() is None:
                self._server_process.terminate()
        return {"ok": True}

    def _server_command(self) -> list[str]:
        if getattr(sys, "frozen", False):
            return [sys.executable, "--server"]
        return [sys.executable, str(BASE_DIR / "server.py")]

    def _server_env(self) -> dict[str, str]:
        with self._lock:
            cfg = dict(self._config)

        env = os.environ.copy()
        env["MCP_TRANSPORT"] = cfg["serverMode"].strip() or "streamable-http"
        env["MCP_HOST"] = cfg["host"].strip() or "127.0.0.1"
        env["MCP_PORT"] = cfg["port"].strip() or "8000"

        api_key = cfg["apiKey"].strip()
        if api_key:
            env["MCP_API_KEY"] = api_key
        return env

    def _selected_config(self) -> dict[str, Any]:
        with self._lock:
            cfg = dict(self._config)

        host = cfg["host"].strip() or "127.0.0.1"
        port = cfg["port"].strip() or "8000"
        payload: dict[str, Any] = {"url": f"http://{host}:{port}/mcp"}
        key = cfg["apiKey"].strip()
        if key:
            payload["headers"] = {"Authorization": f"Bearer {key}"}
        return payload

    def _write_json(self, path: Path, payload: dict[str, Any]) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    def _connect_vscode(self) -> str:
        # VS Code reads user-level servers from mcp.json with "servers" at the top level;
        # the nested {"mcp": {"servers": ...}} shape belongs to settings.json instead.
        file_path = _vscode_user_config()
        payload: dict[str, Any] = {"servers": {}}
        if file_path.exists():
            payload = json.loads(file_path.read_text(encoding="utf-8"))
            payload.setdefault("servers", {})

        with self._lock:
            server_name = self._config["serverName"].strip()

        payload["servers"][server_name] = {**self._selected_config(), "type": "http"}
        self._write_json(file_path, payload)
        return str(file_path)

    def _connect_cursor(self) -> str:
        file_path = Path.home() / ".cursor" / "mcp.json"
        payload: dict[str, Any] = {"mcpServers": {}}
        if file_path.exists():
            payload = json.loads(file_path.read_text(encoding="utf-8"))
            payload.setdefault("mcpServers", {})

        with self._lock:
            server_name = self._config["serverName"].strip()

        payload["mcpServers"][server_name] = self._selected_config()
        self._write_json(file_path, payload)
        return str(file_path)

    def _connect_claude(self) -> str:
        with self._lock:
            server_name = self._config["serverName"].strip()

        cfg = self._selected_config()
        # --scope user: the CLI defaults to "local", which scopes the server to the current
        # working directory — inside a frozen bundle that directory is thrown away.
        command = [
            "claude", "mcp", "add", "--scope", "user",
            "--transport", "http", server_name, cfg["url"],
        ]

        headers = cfg.get("headers") or {}
        auth_header = headers.get("Authorization")
        if auth_header:
            command.extend(["--header", f"Authorization: {auth_header}"])

        process = subprocess.run(command, cwd=DATA_DIR, capture_output=True, text=True, check=False)

        if process.returncode != 0:
            stderr = process.stderr.strip() if process.stderr else "Claude CLI not found or invalid command."
            raise RuntimeError(stderr)

        return "Claude Code connected successfully."


def resolve_frontend_entry() -> Path:
    candidates = [
        BASE_DIR / "ui" / "dist" / "index.html",
        Path(getattr(sys, "_MEIPASS", "")) / "ui" / "dist" / "index.html",
    ]
    for candidate in candidates:
        if candidate.exists():
            return candidate
    raise FileNotFoundError("Frontend not found. Run npm install and npm run build in ui/.")


def main() -> None:
    api = MCPDesktopApi()
    entry = resolve_frontend_entry()

    window = webview.create_window(
        title="DJ Metadata MCP Control Center",
        url=entry.as_uri(),
        js_api=api,
        width=1280,
        height=860,
        min_size=(980, 680),
        background_color="#0b1020",
    )

    def on_close() -> bool:
        api.shutdown()
        return True

    window.events.closing += on_close
    webview.start(debug=not getattr(sys, "frozen", False))


if __name__ == "__main__":
    if "--server" in sys.argv:
        from server import run_server_from_env

        run_server_from_env()
    else:
        main()
