from __future__ import annotations

from pathlib import Path
from typing import Any

from mutagen import File as MutagenFile
from mutagen.easyid3 import EasyID3
from mutagen.flac import FLAC
from mutagen.id3 import COMM, ID3
from mutagen.mp4 import MP4, MP4FreeForm
import re

SUPPORTED_EXTENSIONS = {".mp3", ".flac", ".m4a", ".mp4", ".wav", ".aiff"}


def is_audio_file(path: Path) -> bool:
    return path.suffix.lower() in SUPPORTED_EXTENSIONS


def _coalesce(value: Any, default: Any) -> Any:
    return value if value not in (None, "", [], {}) else default


def read_track_metadata(file_path: Path) -> dict[str, Any]:
    audio = MutagenFile(file_path)
    if audio is None:
        return {
            "filePath": str(file_path),
            "error": "Unable to read audio file",
            "missingFields": ["title", "artist", "genre", "comment"],
        }

    tags = getattr(audio, "tags", None) or {}

    title = _first_non_empty(tags, ["title", "TIT2", "\xa9nam"])
    artist = _first_non_empty(tags, ["artist", "TPE1", "\xa9ART"])
    album = _first_non_empty(tags, ["album", "TALB", "\xa9alb"])
    album_artist = _first_non_empty(tags, ["albumartist", "TPE2", "aART"])
    year = _extract_year(_first_non_empty(tags, ["date", "year", "TDRC", "TYER", "\xa9day"]))
    genre = _as_list(_first_non_empty(tags, ["genre", "TCON", "\xa9gen"]))
    comment = _extract_comments(audio)

    missing = []
    if not title:
        missing.append("title")
    if not artist:
        missing.append("artist")
    if not genre:
        missing.append("genre")
    if not comment:
        missing.append("comment")

    return {
        "filePath": str(file_path),
        "format": file_path.suffix.lower(),
        "title": title,
        "artist": artist,
        "album": album,
        "albumArtist": album_artist,
        "year": year,
        "genre": genre,
        "comment": comment,
        "missingFields": missing,
    }


def _extract_year(value: str | None) -> str | None:
    if not value:
        return None
    match = re.search(r"\b(19\d{2}|20\d{2}|21\d{2})\b", str(value))
    return match.group(1) if match else None


def _first_non_empty(tags: Any, keys: list[str]) -> str | None:
    for key in keys:
        if key in tags:
            value = tags[key]
            if isinstance(value, list):
                if value and str(value[0]).strip():
                    return str(value[0]).strip()
            elif str(value).strip():
                return str(value).strip()
    return None


def _as_list(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, list):
        return [str(v).strip() for v in value if str(v).strip()]
    text = str(value).strip()
    if not text:
        return []
    if ";" in text:
        return [part.strip() for part in text.split(";") if part.strip()]
    return [text]


def _extract_comments(audio: Any) -> list[str]:
    try:
        if hasattr(audio, "tags") and audio.tags is not None:
            if isinstance(audio.tags, ID3):
                comments = [frame.text[0] for frame in audio.tags.getall("COMM") if frame.text]
                return [c.strip() for c in comments if c and c.strip()]
            raw = audio.tags.get("comment") or audio.tags.get("\xa9cmt")
            if isinstance(raw, list):
                return [str(x).strip() for x in raw if str(x).strip()]
            if raw:
                return [str(raw).strip()]
    except Exception:
        return []
    return []


def apply_metadata(file_path: Path, metadata: dict[str, Any]) -> tuple[bool, str | None]:
    ext = file_path.suffix.lower()

    try:
        if ext == ".mp3":
            _write_mp3(file_path, metadata)
            return True, None
        if ext == ".flac":
            _write_flac(file_path, metadata)
            return True, None
        if ext in {".m4a", ".mp4"}:
            _write_m4a(file_path, metadata)
            return True, None
        return False, "Format not supported for writing yet"
    except Exception as exc:
        return False, f"Failed to write metadata: {exc}"


def _write_mp3(file_path: Path, metadata: dict[str, Any]) -> None:
    try:
        tags = EasyID3(str(file_path))
    except Exception:
        tags = EasyID3()

    if metadata.get("title"):
        tags["title"] = [str(metadata["title"])]
    if metadata.get("artist"):
        tags["artist"] = [str(metadata["artist"])]
    if metadata.get("album"):
        tags["album"] = [str(metadata["album"])]
    if metadata.get("albumArtist"):
        tags["albumartist"] = [str(metadata["albumArtist"])]
    if metadata.get("year"):
        tags["date"] = [str(metadata["year"])]
    if metadata.get("genre"):
        genres = metadata["genre"] if isinstance(metadata["genre"], list) else [metadata["genre"]]
        tags["genre"] = [str(g) for g in genres if str(g).strip()]

    tags.save(str(file_path))

    if metadata.get("comment"):
        id3 = ID3(str(file_path))
        id3.delall("COMM")
        comment_text = " | ".join(_as_list(metadata.get("comment")))
        if comment_text:
            id3.add(COMM(encoding=3, lang="eng", desc="", text=comment_text))
        id3.save(v2_version=3)


def _write_flac(file_path: Path, metadata: dict[str, Any]) -> None:
    audio = FLAC(str(file_path))
    if metadata.get("title"):
        audio["title"] = [str(metadata["title"])]
    if metadata.get("artist"):
        audio["artist"] = [str(metadata["artist"])]
    if metadata.get("album"):
        audio["album"] = [str(metadata["album"])]
    if metadata.get("albumArtist"):
        audio["albumartist"] = [str(metadata["albumArtist"])]
    if metadata.get("year"):
        audio["date"] = [str(metadata["year"])]
    if metadata.get("genre"):
        audio["genre"] = _as_list(metadata["genre"])
    if metadata.get("comment"):
        audio["comment"] = _as_list(metadata["comment"])
    audio.save()


def _write_m4a(file_path: Path, metadata: dict[str, Any]) -> None:
    audio = MP4(str(file_path))
    if metadata.get("title"):
        audio["\xa9nam"] = [str(metadata["title"])]
    if metadata.get("artist"):
        audio["\xa9ART"] = [str(metadata["artist"])]
    if metadata.get("album"):
        audio["\xa9alb"] = [str(metadata["album"])]
    if metadata.get("albumArtist"):
        audio["aART"] = [str(metadata["albumArtist"])]
    if metadata.get("year"):
        audio["\xa9day"] = [str(metadata["year"])]
    if metadata.get("genre"):
        genres = _as_list(metadata["genre"])
        if genres:
            audio["\xa9gen"] = ["; ".join(genres)]
    if metadata.get("comment"):
        comments = _as_list(metadata["comment"])
        if comments:
            audio["----:com.apple.iTunes:COMMENT"] = [
                MP4FreeForm(" | ".join(comments).encode("utf-8"), dataformat=1)
            ]
    audio.save()
