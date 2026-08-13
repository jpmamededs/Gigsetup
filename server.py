from __future__ import annotations

import asyncio
import io
import os
import re
import sys
import warnings
from pathlib import Path
from typing import Any

# Known third-party warning from pydantic_settings/mcp on some versions.
warnings.filterwarnings(
    "ignore",
    message=r"Field 'lifespan' has an incomplete definition.*",
)

from mcp.server.fastmcp import FastMCP

from enrichment import build_verified_suggestion
from metadata_store import apply_metadata, is_audio_file, read_track_metadata
from organizer import build_organized_metadata, build_proposed_filename, diff_metadata

mcp = FastMCP(name="dj-metadata-mcp-python")


def _ensure_windows_stdio_streams() -> bool:
    if os.name != "nt":
        return bool(sys.stdin is not None and sys.stdout is not None)

    stdin_ok = sys.stdin is not None and getattr(sys.stdin, "buffer", None) is not None
    stdout_ok = sys.stdout is not None and getattr(sys.stdout, "buffer", None) is not None
    if stdin_ok and stdout_ok:
        return True

    try:
        import ctypes
        import msvcrt

        kernel32 = ctypes.windll.kernel32
        STD_INPUT_HANDLE = -10
        STD_OUTPUT_HANDLE = -11
        STD_ERROR_HANDLE = -12

        stdin_handle = kernel32.GetStdHandle(STD_INPUT_HANDLE)
        stdout_handle = kernel32.GetStdHandle(STD_OUTPUT_HANDLE)
        stderr_handle = kernel32.GetStdHandle(STD_ERROR_HANDLE)

        if stdin_handle in (0, -1) or stdout_handle in (0, -1):
            return False

        stdin_fd = msvcrt.open_osfhandle(stdin_handle, os.O_RDONLY)
        stdout_fd = msvcrt.open_osfhandle(stdout_handle, os.O_WRONLY)
        stderr_fd = msvcrt.open_osfhandle(stderr_handle, os.O_WRONLY) if stderr_handle not in (0, -1) else None

        stdin_bin = os.fdopen(stdin_fd, "rb", buffering=0)
        stdout_bin = os.fdopen(stdout_fd, "wb", buffering=0)

        sys.stdin = io.TextIOWrapper(stdin_bin, encoding="utf-8", newline="\n")
        sys.stdout = io.TextIOWrapper(stdout_bin, encoding="utf-8", newline="\n", write_through=True)

        if stderr_fd is not None:
            stderr_bin = os.fdopen(stderr_fd, "wb", buffering=0)
            sys.stderr = io.TextIOWrapper(stderr_bin, encoding="utf-8", newline="\n", write_through=True)

        return True
    except Exception:
        return False


def iter_audio_files(folder_path: Path, recursive: bool) -> list[Path]:
    if recursive:
        return [p for p in folder_path.rglob("*") if p.is_file() and is_audio_file(p)]
    return [p for p in folder_path.glob("*") if p.is_file() and is_audio_file(p)]


@mcp.tool()
async def scan_tracks(folderPath: str, recursive: bool = True) -> dict[str, Any]:
    folder = Path(folderPath)
    if not folder.exists() or not folder.is_dir():
        raise ValueError("Invalid or non-existent folder")

    audio_files = iter_audio_files(folder, recursive)
    tracks = await asyncio.gather(*[asyncio.to_thread(read_track_metadata, file_path) for file_path in audio_files])
    missing_any = sum(1 for track in tracks if track.get("missingFields"))

    return {
        "folderPath": str(folder),
        "totalFiles": len(tracks),
        "missingAnyCount": missing_any,
        "tracks": tracks,
    }


@mcp.tool()
async def suggest_verified_metadata(
    folderPath: str,
    recursive: bool = True,
    minConfidence: float = 0.78,
    onlyMissing: bool = True,
    fixExistingMetadata: bool = True,
) -> dict[str, Any]:
    folder = Path(folderPath)
    if not folder.exists() or not folder.is_dir():
        raise ValueError("Invalid or non-existent folder")

    audio_files = iter_audio_files(folder, recursive)
    tracks = await asyncio.gather(*[asyncio.to_thread(read_track_metadata, file_path) for file_path in audio_files])

    if onlyMissing and not fixExistingMetadata:
        tracks = [t for t in tracks if t.get("missingFields")]

    candidate_tracks = [t for t in tracks if not t.get("error")]
    tasks = []
    for track in candidate_tracks:
        tasks.append(
            build_verified_suggestion(
                file_path=Path(track["filePath"]),
                current_title=track.get("title"),
                current_artist=track.get("artist"),
                current_album=track.get("album"),
                current_album_artist=track.get("albumArtist"),
                current_genres=track.get("genre") or [],
                current_comments=track.get("comment") or [],
                min_confidence=minConfidence,
            )
        )

    results = await asyncio.gather(*tasks, return_exceptions=True)
    suggestions: list[dict[str, Any]] = []
    for result, track in zip(results, candidate_tracks):
        if isinstance(result, Exception):
            suggestions.append(
                {
                    "filePath": track.get("filePath"),
                    "verified": False,
                    "confidence": 0.0,
                    "apiStatus": {
                        "musicbrainz": "error",
                        "itunes": "error",
                    },
                    "suggested": {
                        "title": track.get("title"),
                        "artist": track.get("artist"),
                        "genre": track.get("genre") or [],
                        "comment": ["Suggestion failed due to API/network error"],
                    },
                    "evidence": [],
                    "error": str(result),
                }
            )
        else:
            suggestions.append(result)

    return {
        "folderPath": str(folder),
        "minConfidence": minConfidence,
        "onlyMissing": onlyMissing,
        "fixExistingMetadata": fixExistingMetadata,
        "totalSuggestions": len(suggestions),
        "verifiedCount": sum(1 for s in suggestions if s.get("verified")),
        "blockedCount": sum(1 for s in suggestions if not s.get("verified")),
        "suggestions": suggestions,
    }


@mcp.tool()
async def apply_verified_metadata(
    updates: list[dict[str, Any]],
    dryRun: bool = True,
    strict: bool = True,
    minConfidence: float = 0.78,
) -> dict[str, Any]:
    results: list[dict[str, Any]] = []

    def _extract_metadata_payload(item: dict[str, Any]) -> dict[str, Any]:
        # Backward/forward compatibility: accept payload in metadata, suggested,
        # or top-level fields used by some MCP clients.
        candidate = item.get("metadata")
        if not isinstance(candidate, dict) or not candidate:
            candidate = item.get("suggested")
        if not isinstance(candidate, dict) or not candidate:
            candidate = {}

        title = candidate.get("title", item.get("title"))
        artist = candidate.get("artist", item.get("artist"))
        album = candidate.get("album", item.get("album"))
        album_artist = candidate.get("albumArtist", item.get("albumArtist"))
        genre = candidate.get("genre", item.get("genre"))
        comment = candidate.get("comment", item.get("comment"))

        if isinstance(genre, list):
            normalized_genre = [str(g).strip() for g in genre if g is not None and str(g).strip()]
        elif genre is None:
            normalized_genre = []
        else:
            text = str(genre).strip()
            normalized_genre = [text] if text else []

        if isinstance(comment, list):
            normalized_comment = [str(c).strip() for c in comment if c is not None and str(c).strip()]
        elif comment is None:
            normalized_comment = []
        else:
            text = str(comment).strip()
            normalized_comment = [text] if text else []

        def _split_artist_tokens(value: str | None) -> list[str]:
            if not value:
                return []
            normalized = re.sub(r"\b(feat\.?|ft\.?|featuring)\b", ",", value, flags=re.IGNORECASE)
            normalized = normalized.replace("&", ",")
            normalized = re.sub(r"\b(and|x|with)\b", ",", normalized, flags=re.IGNORECASE)
            result = []
            seen = set()
            for token in normalized.split(","):
                clean = str(token).strip()
                if not clean:
                    continue
                key = clean.lower()
                if key not in seen:
                    result.append(clean)
                    seen.add(key)
            return result

        def _split_featured_from_title(value: str | None) -> tuple[str | None, list[str]]:
            if not value:
                return value, []

            def _has_version_qualifier(text: str) -> bool:
                lower = text.lower()
                return any(
                    marker in lower
                    for marker in ["remix", "mix", "edit", "version", "vip", "bootleg", "rework", "instrumental", "extended"]
                )

            parenthetical = re.search(r"\((feat\.?|ft\.?|featuring)\s+([^)]+)\)", value, flags=re.IGNORECASE)
            if parenthetical:
                featured_raw = " ".join(parenthetical.group(2).split())
                if _has_version_qualifier(featured_raw):
                    return value, []
                clean_title = " ".join((value[: parenthetical.start()] + " " + value[parenthetical.end() :]).split())
                return clean_title or None, _split_artist_tokens(featured_raw)

            inline = re.search(r"\s+(feat\.?|ft\.?|featuring)\s+(.+)$", value, flags=re.IGNORECASE)
            if not inline:
                return value, []

            featured_raw = " ".join(inline.group(2).split())
            if _has_version_qualifier(featured_raw):
                return value, []
            clean_title = " ".join(value[: inline.start()].split())
            featured_raw = re.split(r"\s*[-–—]\s*", featured_raw, maxsplit=1)[0]
            return clean_title or None, _split_artist_tokens(featured_raw)

        normalized_artists = _split_artist_tokens(str(artist) if artist else None)
        cleaned_title, featured_artists = _split_featured_from_title(str(title) if title else None)
        for feat_artist in featured_artists:
            if feat_artist.lower() not in {a.lower() for a in normalized_artists}:
                normalized_artists.append(feat_artist)

        normalized_artist = ", ".join(normalized_artists) if normalized_artists else artist

        return {
            "title": cleaned_title,
            "artist": normalized_artist,
            "album": album,
            "albumArtist": normalized_artist or album_artist,
            "genre": normalized_genre,
            "comment": normalized_comment,
        }

    for item in updates:
        file_path = Path(item.get("filePath", ""))
        if not file_path.exists() or not file_path.is_file():
            results.append(
                {
                    "filePath": str(file_path),
                    "ok": False,
                    "blocked": True,
                    "reason": "File does not exist",
                }
            )
            continue

        metadata = _extract_metadata_payload(item)
        confidence = float(item.get("confidence", 0.0))
        evidence = item.get("evidence") or []

        if strict:
            if confidence < minConfidence:
                results.append(
                    {
                        "filePath": str(file_path),
                        "ok": False,
                        "blocked": True,
                        "reason": f"Confidence below minimum ({confidence:.2f} < {minConfidence:.2f})",
                    }
                )
                continue
            if not evidence:
                results.append(
                    {
                        "filePath": str(file_path),
                        "ok": False,
                        "blocked": True,
                        "reason": "Missing API evidence for strict validation",
                    }
                )
                continue

        if dryRun:
            results.append(
                {
                    "filePath": str(file_path),
                    "ok": True,
                    "dryRun": True,
                    "blocked": False,
                    "metadata": metadata,
                    "confidence": confidence,
                    "evidence": evidence,
                }
            )
            continue

        ok, reason = await asyncio.to_thread(apply_metadata, file_path, metadata)
        results.append(
            {
                "filePath": str(file_path),
                "ok": ok,
                "dryRun": False,
                "blocked": False,
                "confidence": confidence,
                "evidence": evidence,
                "reason": reason,
            }
        )

    return {
        "total": len(updates),
        "dryRun": dryRun,
        "strict": strict,
        "written": sum(1 for r in results if r.get("ok") and not r.get("dryRun")),
        "blocked": sum(1 for r in results if r.get("blocked")),
        "failed": sum(1 for r in results if not r.get("ok") and not r.get("blocked")),
        "results": results,
    }


@mcp.tool()
async def organize_metadata(
    folderPath: str,
    recursive: bool = True,
    dryRun: bool = True,
    renameFiles: bool = False,
) -> dict[str, Any]:
    folder = Path(folderPath)
    if not folder.exists() or not folder.is_dir():
        raise ValueError("Invalid or non-existent folder")

    audio_files = iter_audio_files(folder, recursive)
    tracks = await asyncio.gather(*[asyncio.to_thread(read_track_metadata, file_path) for file_path in audio_files])
    results: list[dict[str, Any]] = []

    for track in tracks:
        if track.get("error"):
            results.append(
                {
                    "filePath": track.get("filePath"),
                    "ok": False,
                    "reason": track.get("error"),
                }
            )
            continue

        organized = build_organized_metadata(track)
        changed_fields = diff_metadata(track, organized)
        original_path = Path(track["filePath"])
        proposed_name = build_proposed_filename(track, organized)
        proposed_path = original_path.with_name(proposed_name)

        rename_needed = renameFiles and proposed_path != original_path
        if rename_needed:
            changed_fields = list(changed_fields)
            if "fileName" not in changed_fields:
                changed_fields.append("fileName")
        if not changed_fields:
            results.append(
                {
                    "filePath": track.get("filePath"),
                    "ok": True,
                    "dryRun": dryRun,
                    "changed": False,
                    "changedFields": [],
                    "proposedFilePath": str(proposed_path),
                }
            )
            continue

        if dryRun:
            results.append(
                {
                    "filePath": track.get("filePath"),
                    "ok": True,
                    "dryRun": True,
                    "changed": True,
                    "changedFields": changed_fields,
                    "metadata": organized,
                    "proposedFilePath": str(proposed_path),
                }
            )
            continue

        ok, reason = await asyncio.to_thread(apply_metadata, original_path, organized)
        renamed_to = None

        if ok and rename_needed:
            if proposed_path.exists():
                ok = False
                reason = f"Cannot rename: target already exists ({proposed_path.name})"
            else:
                await asyncio.to_thread(original_path.rename, proposed_path)
                renamed_to = str(proposed_path)

        results.append(
            {
                "filePath": track.get("filePath"),
                "ok": ok,
                "dryRun": False,
                "changed": True,
                "changedFields": changed_fields,
                "proposedFilePath": str(proposed_path),
                "renamedTo": renamed_to,
                "reason": reason,
            }
        )

    return {
        "folderPath": str(folder),
        "total": len(results),
        "dryRun": dryRun,
        "changed": sum(1 for r in results if r.get("changed")),
        "written": sum(1 for r in results if r.get("ok") and not r.get("dryRun") and r.get("changed")),
        "failed": sum(1 for r in results if not r.get("ok")),
        "results": results,
    }


def _sanitize_folder_name(value: str) -> str:
    cleaned = " ".join(value.split())
    cleaned = "".join(ch for ch in cleaned if ch not in '<>:"/\\|?*')
    return cleaned.strip().strip(".")


def _target_genre_folder(track: dict[str, Any], fallback_folder: str) -> str:
    genres = track.get("genre") or []
    if not genres:
        return fallback_folder
    first_genre = str(genres[0]).strip()
    if not first_genre:
        return fallback_folder
    return _sanitize_folder_name(first_genre) or fallback_folder


@mcp.tool()
async def organize_directory_by_genre(
    folderPath: str,
    recursive: bool = True,
    dryRun: bool = True,
    fallbackFolder: str = "Sem Genero",
) -> dict[str, Any]:
    folder = Path(folderPath)
    if not folder.exists() or not folder.is_dir():
        raise ValueError("Invalid or non-existent folder")

    fallback_folder = _sanitize_folder_name(fallbackFolder) or "Sem Genero"
    audio_files = iter_audio_files(folder, recursive)

    tracks = await asyncio.gather(*[asyncio.to_thread(read_track_metadata, file_path) for file_path in audio_files])
    results: list[dict[str, Any]] = []

    for track in tracks:
        file_path_raw = track.get("filePath")
        if not file_path_raw:
            continue

        source_path = Path(file_path_raw)
        if track.get("error"):
            results.append(
                {
                    "filePath": str(source_path),
                    "ok": False,
                    "reason": track.get("error"),
                }
            )
            continue

        genre_folder = _target_genre_folder(track, fallback_folder)
        destination_dir = folder / genre_folder
        destination_path = destination_dir / source_path.name
        will_move = source_path.parent != destination_dir

        if not will_move:
            results.append(
                {
                    "filePath": str(source_path),
                    "ok": True,
                    "dryRun": dryRun,
                    "moved": False,
                    "targetFolder": genre_folder,
                    "targetPath": str(destination_path),
                }
            )
            continue

        if destination_path.exists():
            results.append(
                {
                    "filePath": str(source_path),
                    "ok": False,
                    "dryRun": dryRun,
                    "moved": False,
                    "targetFolder": genre_folder,
                    "targetPath": str(destination_path),
                    "reason": "Target file already exists",
                }
            )
            continue

        if dryRun:
            results.append(
                {
                    "filePath": str(source_path),
                    "ok": True,
                    "dryRun": True,
                    "moved": True,
                    "targetFolder": genre_folder,
                    "targetPath": str(destination_path),
                }
            )
            continue

        await asyncio.to_thread(destination_dir.mkdir, parents=True, exist_ok=True)
        await asyncio.to_thread(source_path.rename, destination_path)
        results.append(
            {
                "filePath": str(source_path),
                "ok": True,
                "dryRun": False,
                "moved": True,
                "targetFolder": genre_folder,
                "targetPath": str(destination_path),
            }
        )

    return {
        "folderPath": str(folder),
        "dryRun": dryRun,
        "fallbackFolder": fallback_folder,
        "total": len(results),
        "moved": sum(1 for r in results if r.get("ok") and r.get("moved")),
        "failed": sum(1 for r in results if not r.get("ok")),
        "results": results,
    }


def run_server_from_env() -> None:
    transport = os.getenv("MCP_TRANSPORT", "stdio").strip().lower()

    if transport == "stdio":
        if not _ensure_windows_stdio_streams():
            raise RuntimeError(
                "stdio transport requires valid stdin/stdout streams. "
                "If this machine does not provide them for windowed executables, "
                "switch to streamable-http mode in the launcher."
            )
        print("MCP server running in local stdio mode.")
        mcp.run(transport="stdio")
    elif transport == "streamable-http":
        from starlette.applications import Starlette
        from starlette.middleware.base import BaseHTTPMiddleware
        from starlette.responses import JSONResponse
        import uvicorn

        class ApiKeyAuthMiddleware(BaseHTTPMiddleware):
            async def dispatch(self, request, call_next):
                api_key = os.getenv("MCP_API_KEY", "").strip()
                # In local mode, allow unauthenticated access when key is not configured.
                if not api_key:
                    return await call_next(request)

                auth = request.headers.get("Authorization", "")
                expected = f"Bearer {api_key}"
                if auth != expected:
                    return JSONResponse(
                        {"error": "Unauthorized"},
                        status_code=401,
                    )

                return await call_next(request)

        host = os.getenv("MCP_HOST", "0.0.0.0")
        port = int(os.getenv("MCP_PORT", "8000"))

        mcp.settings.host = host
        mcp.settings.port = port
        mcp.settings.streamable_http_path = "/mcp"

        mcp_app = mcp.streamable_http_app()
        app = Starlette()
        app.add_middleware(ApiKeyAuthMiddleware)
        app.mount("/", mcp_app)

        print(f"MCP server running in remote mode at http://{host}:{port}/mcp")
        uvicorn.run(app, host=host, port=port)
    else:
        raise ValueError("Invalid MCP_TRANSPORT. Use 'stdio' or 'streamable-http'.")


if __name__ == "__main__":
    run_server_from_env()
