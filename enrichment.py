from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from difflib import SequenceMatcher
import os
from pathlib import Path
from typing import Any
from urllib.parse import quote_plus

import httpx
import asyncio

logging.getLogger("httpx").setLevel(logging.WARNING)


@dataclass
class Candidate:
    source: str
    title: str | None
    artist: str | None
    album: str | None
    genres: list[str]
    confidence: float
    evidence: dict[str, Any]


@dataclass
class ConsensusResult:
    title: str | None
    artist: str | None
    album: str | None
    genres: list[str]
    confidence: float
    evidence: list[dict[str, Any]]


def normalize_text(text: str) -> str:
    return " ".join(text.lower().strip().split())


def similarity(a: str | None, b: str | None) -> float:
    if not a or not b:
        return 0.0
    return SequenceMatcher(None, normalize_text(a), normalize_text(b)).ratio()


def token_overlap(a: str | None, b: str | None) -> float:
    if not a or not b:
        return 0.0
    a_tokens = {t for t in normalize_text(a).split() if t}
    b_tokens = {t for t in normalize_text(b).split() if t}
    if not a_tokens or not b_tokens:
        return 0.0
    inter = len(a_tokens.intersection(b_tokens))
    union = len(a_tokens.union(b_tokens))
    return inter / union if union else 0.0


def infer_from_filename(file_path: Path) -> tuple[str | None, str | None]:
    best = infer_variants_from_filename(file_path)[0]
    return best[0], best[1]


def clean_track_text(text: str | None) -> str | None:
    if not text:
        return None

    cleaned = text
    cleaned = re.sub(r"[\[\]【】]", " ", cleaned)
    parts = re.findall(r"\(([^)]*)\)", cleaned)
    keep_parts = []
    for p in parts:
        lower = p.lower()
        if any(token in lower for token in ["extended", "radio edit", "instrumental", "mix", "remix", "vip", "bootleg", "edit"]):
            keep_parts.append(p.strip())
    cleaned = re.sub(r"\([^)]*\)", " ", cleaned)
    cleaned = re.sub(r"\b(320|karaoke|no\s+guide\s+melody|official|lyrics?)\b", " ", cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r"\s+", " ", cleaned).strip(" -_")
    if keep_parts:
        cleaned = f"{cleaned} " + " ".join([f"({p})" for p in keep_parts])
        cleaned = re.sub(r"\s+", " ", cleaned).strip()
    return cleaned or None


def infer_variants_from_filename(file_path: Path) -> list[tuple[str | None, str | None]]:
    base = file_path.stem.strip()
    variants: list[tuple[str | None, str | None]] = []

    for separator in [" - ", " – ", " — ", "_"]:
        if separator in base:
            left, right = base.split(separator, 1)
            left = clean_track_text(left.strip())
            right = clean_track_text(right.strip())
            if left and right:
                # Common format: Artist - Title
                variants.append((right, left))
                # Alternate interpretation for mislabeled files.
                variants.append((left, right))

    cleaned_base = clean_track_text(base)
    if cleaned_base:
        variants.append((cleaned_base, None))

    deduped: list[tuple[str | None, str | None]] = []
    seen = set()
    for title, artist in variants:
        key = (normalize_text(title or ""), normalize_text(artist or ""))
        if key not in seen:
            deduped.append((title, artist))
            seen.add(key)

    if not deduped:
        return [(base or None, None)]
    return deduped


def _candidate_key(title: str | None, artist: str | None) -> tuple[str, str]:
    return (normalize_text(clean_track_text(title) or ""), normalize_text(clean_track_text(artist) or ""))


def _consensus_from_candidates(
    candidates: list[Candidate],
    search_title: str | None,
    search_artist: str | None,
) -> ConsensusResult | None:
    if not candidates:
        return None

    clusters: dict[tuple[str, str], list[Candidate]] = {}
    for cand in candidates:
        key = _candidate_key(cand.title, cand.artist)
        clusters.setdefault(key, []).append(cand)

    best_score = -1.0
    best_key: tuple[str, str] | None = None
    best_cluster: list[Candidate] = []

    for key, cluster in clusters.items():
        sources = {c.source for c in cluster}
        source_bonus = 0.08 * len(sources)
        avg_conf = sum(c.confidence for c in cluster) / len(cluster)
        title_anchor = max(token_overlap(search_title, c.title) for c in cluster)
        artist_anchor = max(token_overlap(search_artist, c.artist) for c in cluster)
        anchor = (title_anchor * 0.6) + (artist_anchor * 0.4)
        score = (avg_conf * 0.72) + (anchor * 0.20) + source_bonus
        if score > best_score:
            best_score = score
            best_key = key
            best_cluster = cluster

    if not best_key:
        return None

    best_title = None
    best_artist = None
    best_album = None
    for cand in best_cluster:
        if not best_title and cand.title:
            best_title = clean_track_text(cand.title)
        if not best_artist and cand.artist:
            best_artist = clean_track_text(cand.artist)
        if not best_album and cand.album:
            best_album = clean_track_text(cand.album)

    merged_genres = _merge_genres(*[c.genres for c in best_cluster])
    evidences = [{"source": c.source, **c.evidence} for c in best_cluster]

    return ConsensusResult(
        title=best_title,
        artist=best_artist,
        album=best_album,
        genres=merged_genres,
        confidence=round(max(0.0, min(1.0, best_score)), 4),
        evidence=evidences,
    )


async def query_musicbrainz(title: str | None, artist: str | None) -> list[Candidate]:
    if not title and not artist:
        return []

    query_parts = []
    if title:
        query_parts.append(f'recording:"{title}"')
    if artist:
        query_parts.append(f'artist:"{artist}"')

    url = "https://musicbrainz.org/ws/2/recording"
    params = {
        "query": " AND ".join(query_parts),
        "fmt": "json",
        "limit": 5,
    }

    headers = {
        "User-Agent": "dj-metadata-mcp/0.2.0 (contato: local)",
        "Accept": "application/json",
    }

    data = await _safe_get_json(url=url, params=params, headers=headers)
    if data is None:
        return []

    candidates: list[Candidate] = []
    for item in data.get("recordings", []):
        mb_title = item.get("title")
        artist_credits = item.get("artist-credit", [])
        mb_artist = None
        if artist_credits:
            names = [a.get("name") for a in artist_credits if isinstance(a, dict) and a.get("name")]
            if names:
                mb_artist = ", ".join(names)

        tag_list = item.get("tags", [])
        genres = [tag.get("name") for tag in tag_list if isinstance(tag, dict) and tag.get("name")]

        title_match = similarity(title, mb_title)
        artist_match = similarity(artist, mb_artist)
        score = (title_match * 0.65) + (artist_match * 0.35)

        candidates.append(
            Candidate(
                source="musicbrainz",
                title=mb_title,
                artist=mb_artist,
                album=((item.get("releases") or [{}])[0] or {}).get("title"),
                genres=genres,
                confidence=score,
                evidence={
                    "recordingId": item.get("id"),
                    "titleMatch": round(title_match, 4),
                    "artistMatch": round(artist_match, 4),
                    "query": params["query"],
                },
            )
        )

    return candidates


async def query_itunes(title: str | None, artist: str | None) -> list[Candidate]:
    if not title and not artist:
        return []

    search_term = " ".join([x for x in [artist, title] if x])
    url = f"https://itunes.apple.com/search?term={quote_plus(search_term)}&entity=song&limit=5"

    data = await _safe_get_json(url=url)
    if data is None:
        return []

    candidates: list[Candidate] = []
    for item in data.get("results", []):
        it_title = item.get("trackName")
        it_artist = item.get("artistName")
        it_genre = item.get("primaryGenreName")

        title_match = similarity(title, it_title)
        artist_match = similarity(artist, it_artist)
        score = (title_match * 0.6) + (artist_match * 0.4)

        genres = [it_genre] if it_genre else []
        candidates.append(
            Candidate(
                source="itunes",
                title=it_title,
                artist=it_artist,
                album=item.get("collectionName"),
                genres=genres,
                confidence=score,
                evidence={
                    "trackId": item.get("trackId"),
                    "collectionName": item.get("collectionName"),
                    "titleMatch": round(title_match, 4),
                    "artistMatch": round(artist_match, 4),
                    "searchTerm": search_term,
                },
            )
        )

    return candidates


async def query_spotify(title: str | None, artist: str | None) -> list[Candidate]:
    client_id = os.getenv("SPOTIFY_CLIENT_ID")
    client_secret = os.getenv("SPOTIFY_CLIENT_SECRET")
    if not client_id or not client_secret or (not title and not artist):
        return []

    token = await _get_spotify_access_token(client_id, client_secret)
    if not token:
        return []

    search_term = " ".join([x for x in [artist, title] if x])
    headers = {"Authorization": f"Bearer {token}"}
    params = {"q": search_term, "type": "track", "limit": 5}

    data = await _safe_get_json(
        url="https://api.spotify.com/v1/search",
        params=params,
        headers=headers,
    )
    if data is None:
        return []

    items = (((data.get("tracks") or {}).get("items")) or [])
    artist_ids = []
    for item in items:
        for a in item.get("artists", []):
            artist_id = a.get("id")
            if artist_id:
                artist_ids.append(artist_id)

    artist_genres_map = await _spotify_artist_genres_map(token, artist_ids)

    candidates: list[Candidate] = []
    for item in items:
        sp_title = item.get("name")
        sp_artists = [a.get("name") for a in item.get("artists", []) if a.get("name")]
        sp_artist = ", ".join(sp_artists) if sp_artists else None

        genres: list[str] = []
        for a in item.get("artists", []):
            artist_id = a.get("id")
            if artist_id and artist_id in artist_genres_map:
                genres.extend(artist_genres_map[artist_id])
        genres = _merge_genres(genres)

        title_match = similarity(title, sp_title)
        artist_match = similarity(artist, sp_artist)
        score = (title_match * 0.6) + (artist_match * 0.4)

        candidates.append(
            Candidate(
                source="spotify",
                title=sp_title,
                artist=sp_artist,
                album=((item.get("album") or {}).get("name") or None),
                genres=genres,
                confidence=score,
                evidence={
                    "trackId": item.get("id"),
                    "externalUrl": (((item.get("external_urls") or {}).get("spotify")) or None),
                    "titleMatch": round(title_match, 4),
                    "artistMatch": round(artist_match, 4),
                    "searchTerm": search_term,
                },
            )
        )

    return candidates


async def query_soundcloud(title: str | None, artist: str | None) -> list[Candidate]:
    client_id = os.getenv("SOUNDCLOUD_CLIENT_ID")
    if not client_id or (not title and not artist):
        return []

    query = " ".join([x for x in [artist, title] if x])
    params = {"q": query, "limit": 5, "client_id": client_id}
    data = await _safe_get_json(url="https://api-v2.soundcloud.com/search/tracks", params=params)
    if data is None:
        return []

    candidates: list[Candidate] = []
    for item in data.get("collection", []):
        if not isinstance(item, dict):
            continue

        sc_title = item.get("title")
        user = item.get("user") or {}
        sc_artist = user.get("username") if isinstance(user, dict) else None
        sc_genre = item.get("genre")

        title_match = similarity(title, sc_title)
        artist_match = similarity(artist, sc_artist)
        score = (title_match * 0.55) + (artist_match * 0.45)

        candidates.append(
            Candidate(
                source="soundcloud",
                title=sc_title,
                artist=sc_artist,
                album=None,
                genres=[sc_genre] if sc_genre else [],
                confidence=score,
                evidence={
                    "trackId": item.get("id"),
                    "permalinkUrl": item.get("permalink_url"),
                    "titleMatch": round(title_match, 4),
                    "artistMatch": round(artist_match, 4),
                    "query": query,
                },
            )
        )

    return candidates


async def _get_spotify_access_token(client_id: str, client_secret: str) -> str | None:
    data = await _safe_post_json(
        url="https://accounts.spotify.com/api/token",
        auth=(client_id, client_secret),
        form_data={"grant_type": "client_credentials"},
    )
    if not data:
        return None
    token = data.get("access_token")
    return str(token) if token else None


async def _spotify_artist_genres_map(token: str, artist_ids: list[str]) -> dict[str, list[str]]:
    unique_ids = []
    seen = set()
    for artist_id in artist_ids:
        if artist_id and artist_id not in seen:
            unique_ids.append(artist_id)
            seen.add(artist_id)

    if not unique_ids:
        return {}

    params = {"ids": ",".join(unique_ids[:50])}
    headers = {"Authorization": f"Bearer {token}"}
    data = await _safe_get_json(url="https://api.spotify.com/v1/artists", params=params, headers=headers)
    if data is None:
        return {}

    result: dict[str, list[str]] = {}
    for artist in data.get("artists", []):
        artist_id = artist.get("id")
        if artist_id:
            result[artist_id] = [g for g in artist.get("genres", []) if isinstance(g, str) and g.strip()]
    return result


def _merge_genres(*genre_lists: list[str]) -> list[str]:
    merged: list[str] = []
    seen = set()
    for source in genre_lists:
        for genre in source:
            g = genre.strip()
            key = g.lower()
            if g and key not in seen:
                merged.append(g)
                seen.add(key)
    return merged


def _normalize_artist_text(artist: str | None) -> str | None:
    if not artist:
        return None

    work = artist
    work = re.sub(r"\b(feat\.?|ft\.?|featuring)\b", ",", work, flags=re.IGNORECASE)
    work = work.replace("&", ",")
    work = re.sub(r"\b(and|x|with)\b", ",", work, flags=re.IGNORECASE)
    tokens = [" ".join(part.split()) for part in work.split(",") if " ".join(part.split())]

    deduped: list[str] = []
    seen = set()
    for token in tokens:
        key = token.lower()
        if key not in seen:
            deduped.append(token)
            seen.add(key)

    if not deduped:
        return None
    return ", ".join(deduped)


def _split_artist_tokens(artist: str | None) -> list[str]:
    normalized = _normalize_artist_text(artist)
    if not normalized:
        return []
    return [part.strip() for part in normalized.split(",") if part.strip()]


def _remove_artist_from_title(title: str | None, artist: str | None) -> str | None:
    if not title:
        return title

    cleaned = title
    for token in _split_artist_tokens(artist):
        pattern = rf"^\s*{re.escape(token)}\s*[-–—:]\s*"
        cleaned = re.sub(pattern, "", cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r"\s+", " ", cleaned).strip()
    return cleaned or None


def _extract_featured_from_title(title: str | None) -> tuple[str | None, list[str]]:
    if not title:
        return title, []

    def _has_version_qualifier(text: str) -> bool:
        lower = text.lower()
        return any(
            token in lower
            for token in ["remix", "mix", "edit", "version", "vip", "bootleg", "rework", "instrumental", "extended"]
        )

    parenthetical = re.search(r"\((feat\.?|ft\.?|featuring)\s+([^)]+)\)", title, flags=re.IGNORECASE)
    if parenthetical:
        featured_raw = " ".join(parenthetical.group(2).split())
        if _has_version_qualifier(featured_raw):
            return title, []
        base = re.sub(r"\s+", " ", title[: parenthetical.start()] + " " + title[parenthetical.end() :]).strip()
        featured_raw = featured_raw.replace("&", ",")
        featured_raw = re.sub(r"\b(and|x|with)\b", ",", featured_raw, flags=re.IGNORECASE)
        featured = [" ".join(part.split()) for part in featured_raw.split(",") if " ".join(part.split())]
        return base or None, featured

    match = re.search(r"\s+(feat\.?|ft\.?|featuring)\s+(.+)$", title, flags=re.IGNORECASE)
    if not match:
        return title, []

    featured_raw = match.group(2)
    if _has_version_qualifier(featured_raw):
        return title, []

    base = re.sub(r"\s+", " ", title[: match.start()]).strip()
    featured_raw = re.split(r"\s*[-–—]\s*", featured_raw, maxsplit=1)[0]
    featured_raw = featured_raw.replace("&", ",")
    featured_raw = re.sub(r"\b(and|x|with)\b", ",", featured_raw, flags=re.IGNORECASE)
    featured = [" ".join(part.split()) for part in featured_raw.split(",") if " ".join(part.split())]
    return base or None, featured


def _finalize_title_artist(title: str | None, artist: str | None, fallback_artist: str | None) -> tuple[str | None, str | None]:
    normalized_artist = _normalize_artist_text(artist) or _normalize_artist_text(fallback_artist)
    cleaned_title = clean_track_text(title)
    cleaned_title = _remove_artist_from_title(cleaned_title, normalized_artist)
    cleaned_title, featured = _extract_featured_from_title(cleaned_title)

    if featured:
        merged = _split_artist_tokens(normalized_artist)
        seen = {m.lower() for m in merged}
        for feat_artist in featured:
            if feat_artist.lower() not in seen:
                merged.append(feat_artist)
                seen.add(feat_artist.lower())
        normalized_artist = _normalize_artist_text(", ".join(merged))

    return cleaned_title, normalized_artist


async def _safe_get_json(
    *,
    url: str,
    params: dict[str, Any] | None = None,
    headers: dict[str, str] | None = None,
    attempts: int = 3,
) -> dict[str, Any] | None:
    last_error: Exception | None = None

    for attempt in range(attempts):
        try:
            async with httpx.AsyncClient(timeout=12.0) as client:
                response = await client.get(url, params=params, headers=headers)

            if 500 <= response.status_code <= 599:
                raise httpx.HTTPStatusError(
                    f"Server error status: {response.status_code}",
                    request=response.request,
                    response=response,
                )

            response.raise_for_status()
            return response.json()
        except (httpx.HTTPError, httpx.TimeoutException, ValueError) as exc:
            last_error = exc
            if attempt < attempts - 1:
                await asyncio.sleep(0.6 * (attempt + 1))

    return None


async def _safe_post_json(
    *,
    url: str,
    auth: tuple[str, str] | None = None,
    form_data: dict[str, Any] | None = None,
    attempts: int = 3,
) -> dict[str, Any] | None:
    for attempt in range(attempts):
        try:
            async with httpx.AsyncClient(timeout=12.0) as client:
                response = await client.post(url, auth=auth, data=form_data)

            if 500 <= response.status_code <= 599:
                raise httpx.HTTPStatusError(
                    f"Server error status: {response.status_code}",
                    request=response.request,
                    response=response,
                )

            response.raise_for_status()
            return response.json()
        except (httpx.HTTPError, httpx.TimeoutException, ValueError):
            if attempt < attempts - 1:
                await asyncio.sleep(0.6 * (attempt + 1))

    return None


async def build_verified_suggestion(
    *,
    file_path: Path,
    current_title: str | None,
    current_artist: str | None,
    current_album: str | None,
    current_album_artist: str | None,
    current_genres: list[str],
    current_comments: list[str],
    min_confidence: float,
) -> dict[str, Any]:
    inferred_title, inferred_artist = infer_from_filename(file_path)

    base_title = clean_track_text(current_title) or inferred_title
    base_artist = clean_track_text(current_artist) or clean_track_text(current_album_artist) or inferred_artist
    base_album = clean_track_text(current_album)

    query_variants = [(base_title, base_artist)]

    # If tags already have reliable fields, prioritize them as primary lookups.
    if base_title and base_artist:
        query_variants.insert(0, (base_title, base_artist))
    if base_title and not base_artist and base_album:
        query_variants.insert(0, (f"{base_title} {base_album}", None))
    for v_title, v_artist in infer_variants_from_filename(file_path):
        query_variants.append((v_title, v_artist))

    normalized_variants: list[tuple[str | None, str | None]] = []
    seen_query = set()
    for v_title, v_artist in query_variants:
        key = (normalize_text(v_title or ""), normalize_text(v_artist or ""))
        if key not in seen_query:
            normalized_variants.append((v_title, v_artist))
            seen_query.add(key)

    mb_candidates: list[Candidate] = []
    it_candidates: list[Candidate] = []
    sp_candidates: list[Candidate] = []
    sc_candidates: list[Candidate] = []

    for v_title, v_artist in normalized_variants[:4]:
        mb_candidates.extend(await query_musicbrainz(v_title, v_artist))
        it_candidates.extend(await query_itunes(v_title, v_artist))
        sp_candidates.extend(await query_spotify(v_title, v_artist))
        sc_candidates.extend(await query_soundcloud(v_title, v_artist))

    best_mb = max(mb_candidates, key=lambda c: c.confidence, default=None)
    best_it = max(it_candidates, key=lambda c: c.confidence, default=None)
    best_sp = max(sp_candidates, key=lambda c: c.confidence, default=None)
    best_sc = max(sc_candidates, key=lambda c: c.confidence, default=None)

    title = clean_track_text(current_title)
    artist = clean_track_text(current_artist)
    album = clean_track_text(current_album)
    genres: list[str] = []

    evidences: list[dict[str, Any]] = []
    confidences = []

    if best_mb:
        confidences.append(best_mb.confidence * 1.05)
        evidences.append({"source": best_mb.source, **best_mb.evidence})
        title = title or clean_track_text(best_mb.title) or inferred_title
        artist = artist or clean_track_text(best_mb.artist) or inferred_artist
        album = album or clean_track_text(best_mb.album)

    if best_it:
        confidences.append(best_it.confidence * 0.95)
        evidences.append({"source": best_it.source, **best_it.evidence})
        title = title or clean_track_text(best_it.title) or inferred_title
        artist = artist or clean_track_text(best_it.artist) or inferred_artist
        album = album or clean_track_text(best_it.album)

    if best_sp:
        confidences.append(best_sp.confidence * 1.0)
        evidences.append({"source": best_sp.source, **best_sp.evidence})
        title = title or clean_track_text(best_sp.title) or inferred_title
        artist = artist or clean_track_text(best_sp.artist) or inferred_artist
        album = album or clean_track_text(best_sp.album)

    if best_sc:
        confidences.append(best_sc.confidence * 0.9)
        evidences.append({"source": best_sc.source, **best_sc.evidence})
        title = title or clean_track_text(best_sc.title) or inferred_title
        artist = artist or clean_track_text(best_sc.artist) or inferred_artist
        album = album or clean_track_text(best_sc.album)

    all_candidates = mb_candidates + it_candidates + sp_candidates + sc_candidates
    consensus = _consensus_from_candidates(all_candidates, base_title, base_artist)
    if consensus:
        title = title or consensus.title or inferred_title
        artist = artist or consensus.artist or inferred_artist
        album = album or consensus.album
        genres = _merge_genres(genres, consensus.genres)
        confidences.append(consensus.confidence)
        evidences.extend(consensus.evidence)

    # Bonus confidence when external result agrees with existing local tags.
    if base_title and title:
        confidences.append(similarity(base_title, title) * 0.15)
    if base_artist and artist:
        confidences.append(similarity(base_artist, artist) * 0.12)
    if base_album and album:
        confidences.append(similarity(base_album, album) * 0.08)

    if not title:
        title = inferred_title
    if not artist:
        artist = inferred_artist

    external_genres = _merge_genres(
        best_mb.genres if best_mb else [],
        best_it.genres if best_it else [],
        best_sp.genres if best_sp else [],
        best_sc.genres if best_sc else [],
    )
    genres = external_genres or _merge_genres(current_genres)

    title, artist = _finalize_title_artist(title, artist, inferred_artist)

    final_confidence = max(confidences) if confidences else 0.0
    verified = final_confidence >= min_confidence

    if current_comments:
        comments = current_comments
    else:
        comments = [
            f"Suggestion validated by APIs (confidence={final_confidence:.2f})" if verified
            else f"Suggestion NOT validated (confidence={final_confidence:.2f})"
        ]

    return {
        "filePath": str(file_path),
        "searchBasis": {
            "title": base_title,
            "artist": base_artist,
            "album": base_album,
            "derivedFromFilename": {
                "title": inferred_title,
                "artist": inferred_artist,
            },
            "queryVariants": [
                {"title": t, "artist": a} for t, a in normalized_variants[:4]
            ],
        },
        "verified": verified,
        "confidence": round(final_confidence, 4),
        "apiStatus": {
            "musicbrainz": "ok" if mb_candidates else "unavailable_or_no_match",
            "itunes": "ok" if it_candidates else "unavailable_or_no_match",
            "spotify": "ok" if sp_candidates else "unavailable_or_no_match_or_not_configured",
            "soundcloud": "ok" if sc_candidates else "unavailable_or_no_match_or_not_configured",
        },
        "suggested": {
            "title": title,
            "artist": artist,
            "album": album,
            "genre": genres,
            "comment": comments,
        },
        "evidence": evidences,
    }
