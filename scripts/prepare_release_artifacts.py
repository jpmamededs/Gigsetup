from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import re
import shutil
from pathlib import Path


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _safe_version(value: str) -> str:
    cleaned = re.sub(r"[^A-Za-z0-9._-]", "_", value.strip())
    return cleaned or "0.0.0"


def _artifact_entry(path: Path, public_name: str, channel: str) -> dict[str, object]:
    return {
        "channel": channel,
        "fileName": public_name,
        "sizeBytes": path.stat().st_size,
        "sha256": _sha256(path),
    }


def _copy(src: Path, dst: Path) -> None:
    dst.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(src, dst)


def _write_json(path: Path, payload: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def _write_sha_file(path: Path, entries: list[dict[str, object]]) -> None:
    lines = [f"{entry['sha256']} *{entry['fileName']}" for entry in entries]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _write_download_snippet(path: Path, app_name: str) -> None:
    html = f"""<!doctype html>
<html lang=\"pt-br\">
<head>
  <meta charset=\"utf-8\" />
  <meta name=\"viewport\" content=\"width=device-width, initial-scale=1\" />
  <title>Download {app_name}</title>
</head>
<body>
  <a id=\"download-win\" href=\"/releases/latest/{app_name}-Setup-latest.exe\">Baixar para Windows</a>
  <p id=\"download-meta\"></p>

  <script>
    fetch('/releases/latest/release.json')
      .then((r) => r.json())
      .then((data) => {{
        const setup = (data.artifacts || []).find((a) => a.channel === 'setup-latest');
        const exe = (data.artifacts || []).find((a) => a.channel === 'exe-latest');
        const artifact = setup || exe;
        const meta = document.getElementById('download-meta');
        if (!artifact || !meta) return;
        const sizeMb = (artifact.sizeBytes / (1024 * 1024)).toFixed(2);
        meta.textContent = `Versao ${{data.version}} | ${{sizeMb}} MB | SHA-256: ${{artifact.sha256}}`;
      }})
      .catch(() => {{
        const meta = document.getElementById('download-meta');
        if (meta) meta.textContent = 'Metadados de download indisponiveis no momento.';
      }});
  </script>
</body>
</html>
"""
    path.write_text(html, encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(description="Prepara artefatos de release para download em site.")
    parser.add_argument("--app-name", required=True)
    parser.add_argument("--version", required=True)
    parser.add_argument("--exe", required=True)
    parser.add_argument("--installer-dir", required=True)
    parser.add_argument("--out-dir", required=True)
    args = parser.parse_args()

    app_name = args.app_name.strip() or "Gigsetup"
    version = args.version.strip() or "0.0.0"
    safe_version = _safe_version(version)

    exe_src = Path(args.exe)
    if not exe_src.exists():
        raise FileNotFoundError(f"Executavel nao encontrado: {exe_src}")

    installer_src = Path(args.installer_dir) / f"{app_name}-Setup-{version}.exe"
    if not installer_src.exists():
        installer_src = None

    out_root = Path(args.out_dir)
    version_dir = out_root / safe_version
    latest_dir = out_root / "latest"

    versioned_artifacts: list[dict[str, object]] = []
    latest_artifacts: list[dict[str, object]] = []

    exe_version_name = f"{app_name}-{safe_version}.exe"
    exe_latest_name = f"{app_name}-latest.exe"

    exe_version_dst = version_dir / exe_version_name
    exe_latest_dst = latest_dir / exe_latest_name
    _copy(exe_src, exe_version_dst)
    _copy(exe_src, exe_latest_dst)

    versioned_artifacts.append(_artifact_entry(exe_version_dst, exe_version_name, "exe-versioned"))
    latest_artifacts.append(_artifact_entry(exe_latest_dst, exe_latest_name, "exe-latest"))

    if installer_src:
        setup_version_name = f"{app_name}-Setup-{safe_version}.exe"
        setup_latest_name = f"{app_name}-Setup-latest.exe"

        setup_version_dst = version_dir / setup_version_name
        setup_latest_dst = latest_dir / setup_latest_name
        _copy(installer_src, setup_version_dst)
        _copy(installer_src, setup_latest_dst)

        versioned_artifacts.append(_artifact_entry(setup_version_dst, setup_version_name, "setup-versioned"))
        latest_artifacts.append(_artifact_entry(setup_latest_dst, setup_latest_name, "setup-latest"))

    generated_at = dt.datetime.now().isoformat(timespec="seconds")

    version_payload = {
        "app": app_name,
        "version": version,
        "versionSafe": safe_version,
        "generatedAt": generated_at,
        "artifacts": versioned_artifacts,
    }
    latest_payload = {
        "app": app_name,
        "version": version,
        "versionSafe": safe_version,
        "generatedAt": generated_at,
        "artifacts": latest_artifacts,
    }

    _write_json(version_dir / "release.json", version_payload)
    _write_json(latest_dir / "release.json", latest_payload)
    _write_sha_file(version_dir / "SHA256SUMS.txt", versioned_artifacts)
    _write_sha_file(latest_dir / "SHA256SUMS.txt", latest_artifacts)
    _write_download_snippet(latest_dir / "download-button-example.html", app_name)

    print(f"RELEASE_DIR={version_dir}")
    print(f"LATEST_DIR={latest_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
