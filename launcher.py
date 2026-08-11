from __future__ import annotations

import json
import os
import platform
import subprocess
import sys
import threading
from pathlib import Path
from typing import Any

import webview

BASE_DIR = Path(__file__).resolve().parent


class MCPDesktopApi:
    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._server_process: subprocess.Popen[str] | None = None
        self._config: dict[str, str] = {
            "serverName": "dj-music-metadata",
            "serverMode": "stdio",
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

            validation_error = self._validate_config(self._config)
            if validation_error:
                return {"ok": False, "running": False, "message": validation_error, "config": dict(self._config)}
        return self.get_state()

    def start_server(self) -> dict[str, Any]:
        with self._lock:
            if self._server_process and self._server_process.poll() is None:
                return {"ok": False, "message": "Server is already running."}

            validation_error = self._validate_config(self._config)
            if validation_error:
                return {"ok": False, "message": validation_error}

            command = self._server_command()
            try:
                self._server_process = subprocess.Popen(
                    command,
                    cwd=BASE_DIR,
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

        with self._lock:
            validation_error = self._validate_config(self._config)
            mode = self._config["serverMode"].strip().lower() or "stdio"
        if validation_error:
            return {"ok": False, "message": validation_error}

        # HTTP mode needs a running local server; stdio is started by the MCP client itself.
        if mode == "streamable-http":
            with self._lock:
                running = self._server_process is not None and self._server_process.poll() is None
            if not running:
                started = self.start_server()
                if not started.get("ok"):
                    return {"ok": False, "message": started.get("message", "Could not start local HTTP server.")}

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

        mode = (cfg["serverMode"].strip() or "stdio").lower()
        if mode == "stdio":
            command, args = self._stdio_command_for_client()
            return {
                "type": "stdio",
                "command": command,
                "args": args,
                "env": {
                    "MCP_TRANSPORT": "stdio",
                },
            }

        host = cfg["host"].strip() or "127.0.0.1"
        port = cfg["port"].strip() or "8000"
        payload: dict[str, Any] = {"type": "http", "url": f"http://{host}:{port}/mcp"}
        key = cfg["apiKey"].strip()
        if key:
            payload["headers"] = {"Authorization": f"Bearer {key}"}
        return payload

    def _stdio_command_for_client(self) -> tuple[str, list[str]]:
        if getattr(sys, "frozen", False):
            command = str(Path(sys.executable).resolve())
            if not Path(command).exists():
                raise RuntimeError("Executable path does not exist for stdio MCP server.")
            return command, ["--server"]

        command = str(Path(sys.executable).resolve())
        script = str((BASE_DIR / "server.py").resolve())
        if not Path(script).exists():
            raise RuntimeError("server.py not found.")
        return command, [script]

    def _validate_config(self, cfg: dict[str, str]) -> str | None:
        server_name = (cfg.get("serverName") or "").strip()
        if not server_name:
            return "Server name is required."

        mode = (cfg.get("serverMode") or "").strip().lower()
        if mode not in {"stdio", "streamable-http"}:
            return "Invalid mode. Use 'stdio' or 'streamable-http'."

        if mode == "streamable-http":
            host = (cfg.get("host") or "").strip()
            if not host:
                return "Host is required in streamable-http mode."

            port_raw = (cfg.get("port") or "").strip()
            try:
                port = int(port_raw)
            except ValueError:
                return "Port must be a number in streamable-http mode."

            if port < 1 or port > 65535:
                return "Port must be between 1 and 65535 in streamable-http mode."

        return None

    def _write_json(self, path: Path, payload: dict[str, Any]) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    def _connect_vscode(self) -> str:
        file_path = self._resolve_vscode_user_mcp_path()
        payload: dict[str, Any] = {"servers": {}, "inputs": []}
        if file_path.exists():
            payload = json.loads(file_path.read_text(encoding="utf-8"))
            payload.setdefault("servers", {})
            payload.setdefault("inputs", [])

        with self._lock:
            server_name = self._config["serverName"].strip()

        payload["servers"][server_name] = self._selected_config()
        self._write_json(file_path, payload)
        return str(file_path)

    def _resolve_vscode_user_mcp_path(self) -> Path:
        system = platform.system().lower()

        if system == "windows":
            appdata_raw = (os.getenv("APPDATA", "") or "").strip()
            if not appdata_raw:
                raise RuntimeError("APPDATA was not found. Could not locate VS Code user settings.")
            return Path(appdata_raw).expanduser() / "Code" / "User" / "mcp.json"

        home = Path.home()
        if system == "darwin":
            return home / "Library" / "Application Support" / "Code" / "User" / "mcp.json"

        # Linux and other Unix-like platforms.
        xdg_config_home = (os.getenv("XDG_CONFIG_HOME", "") or "").strip()
        config_root = Path(xdg_config_home).expanduser() if xdg_config_home else (home / ".config")
        return config_root / "Code" / "User" / "mcp.json"

    def _connect_cursor(self) -> str:
        file_path = self._resolve_cursor_user_mcp_path()
        payload: dict[str, Any] = {"mcpServers": {}}
        if file_path.exists():
            payload = json.loads(file_path.read_text(encoding="utf-8"))
            payload.setdefault("mcpServers", {})

        with self._lock:
            server_name = self._config["serverName"].strip()

        payload["mcpServers"][server_name] = self._selected_config()
        self._write_json(file_path, payload)
        return str(file_path)

    def _resolve_cursor_user_mcp_path(self) -> Path:
        system = platform.system().lower()
        home = Path.home()

        if system == "windows":
            return home / ".cursor" / "mcp.json"
        if system == "darwin":
            return home / ".cursor" / "mcp.json"
        return home / ".cursor" / "mcp.json"

    def _connect_claude(self) -> str:
        with self._lock:
            server_name = self._config["serverName"].strip()

        cfg = self._selected_config()
        if cfg.get("type") == "stdio":
            command = ["claude", "mcp", "add", "--transport", "stdio", server_name, cfg["command"]]
            for arg in cfg.get("args", []):
                command.append(arg)
        else:
            command = ["claude", "mcp", "add", "--transport", "http", server_name, cfg["url"]]

            headers = cfg.get("headers") or {}
            auth_header = headers.get("Authorization")
            if auth_header:
                command.extend(["--header", f"Authorization: {auth_header}"])

        process = subprocess.run(command, cwd=BASE_DIR, capture_output=True, text=True, check=False)

        self._append_log(f"$ {' '.join(command)}")
        if process.stdout:
            self._append_log(process.stdout.strip())
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
