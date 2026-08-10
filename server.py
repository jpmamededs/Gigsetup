from __future__ import annotations

import asyncio
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


def iter_audio_files(folder_path: Path, recursive: bool) -> list[Path]:
    if recursive:
        return [p for p in folder_path.rglob("*") if p.is_file() and is_audio_file(p)]
    return [p for p in folder_path.glob("*") if p.is_file() and is_audio_file(p)]


@mcp.tool()
def scan_tracks(folderPath: str, recursive: bool = True) -> dict[str, Any]:
    folder = Path(folderPath)
    if not folder.exists() or not folder.is_dir():
        raise ValueError("Invalid or non-existent folder")

    tracks = [read_track_metadata(file_path) for file_path in iter_audio_files(folder, recursive)]
    missing_any = sum(1 for track in tracks if track.get("missingFields"))

    return {
        "folderPath": str(folder),
        "totalFiles": len(tracks),
        "missingAnyCount": missing_any,
        "tracks": tracks,
    }


@mcp.tool()
def suggest_verified_metadata(
    folderPath: str,
    recursive: bool = True,
    minConfidence: float = 0.78,
    onlyMissing: bool = True,
) -> dict[str, Any]:
    folder = Path(folderPath)
    if not folder.exists() or not folder.is_dir():
        raise ValueError("Invalid or non-existent folder")

    tracks = [read_track_metadata(file_path) for file_path in iter_audio_files(folder, recursive)]

    if onlyMissing:
        tracks = [t for t in tracks if t.get("missingFields")]

    async def _run() -> list[dict[str, Any]]:
        tasks = []
        for track in tracks:
            if track.get("error"):
                continue
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
        normalized: list[dict[str, Any]] = []
        for result, track in zip(results, [t for t in tracks if not t.get("error")]):
            if isinstance(result, Exception):
                normalized.append(
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
                normalized.append(result)
        return normalized

    suggestions = asyncio.run(_run())

    return {
        "folderPath": str(folder),
        "minConfidence": minConfidence,
        "totalSuggestions": len(suggestions),
        "verifiedCount": sum(1 for s in suggestions if s.get("verified")),
        "blockedCount": sum(1 for s in suggestions if not s.get("verified")),
        "suggestions": suggestions,
    }


@mcp.tool()
def apply_verified_metadata(
    updates: list[dict[str, Any]],
    dryRun: bool = True,
    strict: bool = True,
    minConfidence: float = 0.78,
) -> dict[str, Any]:
    results: list[dict[str, Any]] = []

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

        metadata = item.get("metadata") or {}
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

        metadata["genre"] = metadata.get("genre") if isinstance(metadata.get("genre"), list) else [metadata.get("genre")]
        metadata["comment"] = (
            metadata.get("comment") if isinstance(metadata.get("comment"), list) else [metadata.get("comment")]
        )

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

        ok, reason = apply_metadata(file_path, metadata)
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
def organize_metadata(
    folderPath: str,
    recursive: bool = True,
    dryRun: bool = True,
    renameFiles: bool = False,
) -> dict[str, Any]:
    folder = Path(folderPath)
    if not folder.exists() or not folder.is_dir():
        raise ValueError("Invalid or non-existent folder")

    tracks = [read_track_metadata(file_path) for file_path in iter_audio_files(folder, recursive)]
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

        ok, reason = apply_metadata(original_path, organized)
        renamed_to = None

        if ok and rename_needed:
            if proposed_path.exists():
                ok = False
                reason = f"Cannot rename: target already exists ({proposed_path.name})"
            else:
                original_path.rename(proposed_path)
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


if __name__ == "__main__":
    print("Server is running. Use Ctrl+C to stop.")
    mcp.run()
