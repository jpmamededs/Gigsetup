from __future__ import annotations

import re
from pathlib import Path
from typing import Any

QUALIFIER_KEYWORDS = {
    "instrumental",
    "extended",
    "radio edit",
    "radio",
    "edit",
    "mix",
    "remix",
    "vip",
    "bootleg",
    "rework",
    "version",
    "club mix",
}

NOISE_TOKENS = {
    "320",
    "128",
    "kbps",
    "no guide melody",
    "official",
    "lyrics",
}

WINDOWS_FORBIDDEN_CHARS = r'[<>:"/\\|?*]'


def _normalize_spaces(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()


def _clean_noise(text: str) -> str:
    cleaned = text
    cleaned = re.sub(r"\b\d{2,4}\s?kbps\b", " ", cleaned, flags=re.IGNORECASE)
    for token in NOISE_TOKENS:
        cleaned = re.sub(rf"\b{re.escape(token)}\b", " ", cleaned, flags=re.IGNORECASE)
    return _normalize_spaces(cleaned)


def _contains_qualifier(text: str) -> bool:
    lower = text.lower()
    return any(keyword in lower for keyword in QUALIFIER_KEYWORDS)


def _extract_parenthetical_parts(text: str) -> tuple[str, list[str]]:
    parts = re.findall(r"\(([^)]*)\)", text)
    base = re.sub(r"\([^)]*\)", " ", text)
    keep = [_normalize_spaces(p) for p in parts if _contains_qualifier(p)]
    return _normalize_spaces(base), keep


def _split_artist_title(stem: str) -> tuple[str | None, str | None]:
    for separator in [" - ", " – ", " — ", "_"]:
        if separator in stem:
            left, right = stem.split(separator, 1)
            left = _normalize_spaces(left)
            right = _normalize_spaces(right)
            if left and right:
                return left, right
    return None, _normalize_spaces(stem)


def _normalize_artist(artist: str | None) -> str | None:
    if not artist:
        return None

    work = artist
    work = re.sub(r"\b(feat\.?|ft\.?|featuring)\b", ",", work, flags=re.IGNORECASE)
    work = work.replace(".", " ")
    work = work.replace("&", ",")
    tokens = [_normalize_spaces(t) for t in work.split(",")]
    deduped: list[str] = []
    seen = set()
    for token in tokens:
        if not token:
            continue
        key = token.lower()
        if key not in seen:
            deduped.append(token)
            seen.add(key)

    if not deduped:
        return None
    return ", ".join(deduped)


def _split_artist_tokens(artist: str | None) -> list[str]:
    normalized = _normalize_artist(artist)
    if not normalized:
        return []
    return [_normalize_spaces(token) for token in normalized.split(",") if _normalize_spaces(token)]


def _remove_artist_from_title_prefix(title: str, artist: str | None) -> str:
    if not title or not artist:
        return title

    work = title
    artist_tokens = _split_artist_tokens(artist)
    if not artist_tokens:
        return work

    for token in artist_tokens:
        pattern = rf"^\s*{re.escape(token)}\s*[-–—:]\s*"
        work = re.sub(pattern, "", work, flags=re.IGNORECASE)

    return _normalize_spaces(work)


def _extract_featured_artists_from_title(title: str) -> tuple[str, list[str]]:
    if not title:
        return title, []

    # Parenthetical form: Title (feat. Artist)
    parenthetical = re.search(r"\((feat\.?|ft\.?|featuring)\s+([^)]+)\)", title, flags=re.IGNORECASE)
    if parenthetical:
        featured_raw = _normalize_spaces(parenthetical.group(2))
        if _contains_qualifier(featured_raw):
            return title, []
        cleaned_title = _normalize_spaces((title[: parenthetical.start()] + " " + title[parenthetical.end() :]))
        featured_raw = featured_raw.replace("&", ",")
        featured_raw = re.sub(r"\b(and|x|with)\b", ",", featured_raw, flags=re.IGNORECASE)
        featured = [_normalize_spaces(p) for p in featured_raw.split(",") if _normalize_spaces(p)]
        return cleaned_title, featured

    # Inline form: Title feat. Artist
    inline = re.search(r"\s+(feat\.?|ft\.?|featuring)\s+(.+)$", title, flags=re.IGNORECASE)
    if not inline:
        return title, []

    featured_raw = _normalize_spaces(inline.group(2))
    if _contains_qualifier(featured_raw):
        return title, []

    cleaned_title = _normalize_spaces(title[: inline.start()])
    featured_raw = re.split(r"\s*[-–—]\s*", featured_raw, maxsplit=1)[0]
    featured_raw = featured_raw.replace("&", ",")
    featured_raw = re.sub(r"\b(and|x|with)\b", ",", featured_raw, flags=re.IGNORECASE)
    featured = [_normalize_spaces(p) for p in featured_raw.split(",") if _normalize_spaces(p)]
    return cleaned_title, featured


def _normalize_title(title: str | None, fallback_stem: str) -> str | None:
    source = title or fallback_stem
    if not source:
        return None

    source = source.replace("【", "(").replace("】", ")")
    source = _clean_noise(source)
    base, qualifiers = _extract_parenthetical_parts(source)
    base = _clean_noise(base)

    if not base and qualifiers:
        base = fallback_stem

    if qualifiers:
        suffix = " ".join([f"({q})" for q in qualifiers])
        return _normalize_spaces(f"{base} {suffix}")

    return base or None


def _normalize_genres(genres: list[str]) -> list[str]:
    deduped: list[str] = []
    seen = set()
    for genre in genres:
        g = _normalize_spaces(str(genre))
        if not g:
            continue
        key = g.lower()
        if key not in seen:
            deduped.append(g)
            seen.add(key)
    return deduped


def _normalize_album(album: str | None, fallback: str | None = None) -> str | None:
    source = album or fallback
    if not source:
        return None
    source = source.replace("【", "(").replace("】", ")")
    source = _clean_noise(source)
    return source or None


def _sanitize_filename_part(text: str) -> str:
    sanitized = re.sub(WINDOWS_FORBIDDEN_CHARS, " ", text)
    sanitized = _normalize_spaces(sanitized).strip(".")
    return sanitized


def build_proposed_filename(track: dict[str, Any], organized: dict[str, Any]) -> str:
    file_path = Path(track["filePath"])
    ext = file_path.suffix

    title = _sanitize_filename_part((organized.get("title") or file_path.stem))
    stem = title

    stem = _normalize_spaces(stem)
    if not stem:
        stem = file_path.stem

    return f"{stem}{ext}"


def build_organized_metadata(track: dict[str, Any]) -> dict[str, Any]:
    file_path = Path(track["filePath"])
    stem = file_path.stem

    inferred_artist, inferred_title = _split_artist_title(stem)

    raw_artist = track.get("artist") or inferred_artist
    raw_title = track.get("title") or inferred_title or stem

    artist = _normalize_artist(raw_artist)
    raw_title = _remove_artist_from_title_prefix(raw_title, artist)
    raw_title, featured_artists = _extract_featured_artists_from_title(raw_title)

    if featured_artists:
        merged_artists = _split_artist_tokens(artist)
        for feat_artist in featured_artists:
            key = feat_artist.lower()
            if key not in {a.lower() for a in merged_artists}:
                merged_artists.append(feat_artist)
        artist = _normalize_artist(", ".join(merged_artists))

    title = _normalize_title(raw_title, inferred_title or stem)
    title = _remove_artist_from_title_prefix(title or "", artist) or title
    album = _normalize_album(track.get("album"), file_path.parent.name if file_path.parent else None)

    genres = _normalize_genres(track.get("genre") or [])
    comments = [c for c in (track.get("comment") or []) if str(c).strip()]

    metadata = {
        "title": title,
        "artist": artist,
        "album": album,
        "albumArtist": artist,
        "genre": genres,
        "comment": comments,
    }

    if not metadata["comment"]:
        metadata["comment"] = ["Organized by MCP metadata normalizer"]

    return metadata


def diff_metadata(track: dict[str, Any], organized: dict[str, Any]) -> list[str]:
    changed: list[str] = []

    current_title = track.get("title")
    current_artist = track.get("artist")
    current_album = track.get("album")
    current_genre = track.get("genre") or []
    current_comment = track.get("comment") or []

    if (current_title or None) != (organized.get("title") or None):
        changed.append("title")
    if (current_artist or None) != (organized.get("artist") or None):
        changed.append("artist")
    if (current_album or None) != (organized.get("album") or None):
        changed.append("album")
    if list(current_genre) != list(organized.get("genre") or []):
        changed.append("genre")
    if list(current_comment) != list(organized.get("comment") or []):
        changed.append("comment")

    if organized.get("albumArtist") and organized.get("albumArtist") != current_artist:
        changed.append("albumArtist")

    return changed
