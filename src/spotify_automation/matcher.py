from __future__ import annotations

import os

from spotify_automation.models import BuyMusicClubItem, MatchDecision, SpotifyCandidate
from spotify_automation.utils import (
    artist_similarity,
    compact_whitespace,
    normalize_text,
    similarity,
)


DEFAULT_CANDIDATE_LIMIT = 8
DEFAULT_SEARCH_MARKETS = ("BR", "")
DEFAULT_MAX_SEARCH_REQUESTS_PER_ITEM = 8
CONFIDENT_CANDIDATE_SCORE = 0.98
DEFAULT_AUTO_MATCH_THRESHOLD = 0.90

def _artist_names(raw_artists: list[dict[str, object]]) -> str:
    return ", ".join(str(artist["name"]) for artist in raw_artists)


def _candidate_from_track(raw_track: dict[str, object], query_hint: str) -> SpotifyCandidate:
    track_id = str(raw_track["id"])
    candidate = SpotifyCandidate(
        candidate_id=f"track:{track_id}",
        link_type="track",
        spotify_id=track_id,
        spotify_url=str(raw_track["external_urls"]["spotify"]),
        title=str(raw_track["name"]),
        artists=_artist_names(raw_track.get("artists", [])),
        album_title=str((raw_track.get("album") or {}).get("name") or ""),
        release_date=str((raw_track.get("album") or {}).get("release_date") or ""),
        popularity=raw_track.get("popularity"),
        total_tracks=(raw_track.get("album") or {}).get("total_tracks"),
        query_hints=[query_hint],
    )
    return candidate


def _candidate_from_album(raw_album: dict[str, object], query_hint: str) -> SpotifyCandidate:
    album_id = str(raw_album["id"])
    candidate = SpotifyCandidate(
        candidate_id=f"album:{album_id}",
        link_type="album",
        spotify_id=album_id,
        spotify_url=str(raw_album["external_urls"]["spotify"]),
        title=str(raw_album["name"]),
        artists=_artist_names(raw_album.get("artists", [])),
        album_title=str(raw_album["name"]),
        release_date=str(raw_album.get("release_date") or ""),
        popularity=raw_album.get("popularity"),
        total_tracks=raw_album.get("total_tracks"),
        query_hints=[query_hint],
    )
    return candidate


def _target_title(item: BuyMusicClubItem, link_type: str) -> str:
    if link_type == "album" and item.release_title:
        return item.release_title
    return item.track


def _search_markets() -> tuple[str, ...]:
    raw_value = os.environ.get("SPOTIFY_AUTOMATION_SEARCH_MARKETS")
    if raw_value is None:
        return DEFAULT_SEARCH_MARKETS
    markets = tuple(part.strip().upper() for part in raw_value.split(","))
    return markets or DEFAULT_SEARCH_MARKETS


def _max_search_requests_per_item() -> int:
    raw_value = os.environ.get("SPOTIFY_AUTOMATION_MAX_SEARCH_REQUESTS_PER_ITEM")
    if raw_value is None:
        return DEFAULT_MAX_SEARCH_REQUESTS_PER_ITEM
    try:
        return max(1, int(raw_value))
    except ValueError:
        return DEFAULT_MAX_SEARCH_REQUESTS_PER_ITEM


def spotify_search_settings_summary() -> str:
    markets = ", ".join(market or "any" for market in _search_markets())
    return (
        f"markets=[{markets}], max_requests_per_item={_max_search_requests_per_item()},"
        f" auto_match_threshold={_auto_match_threshold():.2f}"
    )


def _auto_match_threshold() -> float:
    raw_value = os.environ.get("SPOTIFY_AUTOMATION_AUTO_MATCH_THRESHOLD")
    if raw_value is None:
        return DEFAULT_AUTO_MATCH_THRESHOLD
    try:
        return max(0.0, min(1.0, float(raw_value)))
    except ValueError:
        return DEFAULT_AUTO_MATCH_THRESHOLD


def heuristic_score(item: BuyMusicClubItem, candidate: SpotifyCandidate) -> float:
    title_score = similarity(_target_title(item, candidate.link_type), candidate.title)
    track_score = similarity(item.track, candidate.title)
    release_score = 0.0
    if item.release_title:
        release_score = similarity(item.release_title, candidate.album_title or candidate.title)
    candidate_artist_score = artist_similarity(item.artist, candidate.artists)

    if candidate.link_type == "album":
        score = (0.5 * title_score) + (0.3 * candidate_artist_score) + (0.2 * release_score)
    else:
        score = (0.55 * track_score) + (0.3 * candidate_artist_score) + (0.15 * release_score)
    return round(score, 4)


def collect_candidates(sp, item: BuyMusicClubItem, *, limit: int = DEFAULT_CANDIDATE_LIMIT) -> list[SpotifyCandidate]:
    release_hint = item.release_title or item.track
    raw_search_specs = [
        ("track_exact", "track", f'track:{item.track} artist:{item.artist}'),
        ("track_normalized", "track", f"{item.artist} {normalize_text(item.track)}"),
        ("album_exact", "album", f'album:{release_hint} artist:{item.artist}'),
        ("album_normalized", "album", f"{item.artist} {normalize_text(release_hint)}"),
    ]
    search_specs = []
    seen_queries: set[tuple[str, str, str]] = set()
    for query_hint, search_type, query in raw_search_specs:
        normalized_query = compact_whitespace(query)
        if not normalized_query:
            continue
        for market in _search_markets():
            query_key = (search_type, normalized_query, market)
            if query_key in seen_queries:
                continue
            search_specs.append((query_hint, search_type, normalized_query, market))
            seen_queries.add(query_key)

    candidates: dict[str, SpotifyCandidate] = {}
    for query_hint, search_type, query, market in search_specs[: _max_search_requests_per_item()]:
        results = sp.search(q=query, type=search_type, limit=limit, market=market or None)
        raw_items = results[f"{search_type}s"]["items"]
        for raw_item in raw_items:
            candidate = (
                _candidate_from_track(raw_item, query_hint)
                if search_type == "track"
                else _candidate_from_album(raw_item, query_hint)
            )
            candidate.heuristic_score = heuristic_score(item, candidate)
            existing = candidates.get(candidate.candidate_id)
            if existing:
                existing.heuristic_score = max(existing.heuristic_score, candidate.heuristic_score)
                existing.query_hints = sorted(
                    set(existing.query_hints + candidate.query_hints + [f"market:{market or 'any'}"])
                )
            else:
                candidate.query_hints.append(f"market:{market or 'any'}")
                candidates[candidate.candidate_id] = candidate
        if any(candidate.heuristic_score >= CONFIDENT_CANDIDATE_SCORE for candidate in candidates.values()):
            break

    sorted_candidates = sorted(
        candidates.values(),
        key=lambda candidate: (
            candidate.heuristic_score,
            candidate.popularity or 0,
            candidate.release_date,
        ),
        reverse=True,
    )
    return sorted_candidates[:limit]


def choose_matches_heuristically(items: list[BuyMusicClubItem], candidate_map: dict[str, list[SpotifyCandidate]]) -> dict[str, MatchDecision]:
    decisions: dict[str, MatchDecision] = {}
    for item in items:
        candidates = candidate_map.get(item.source_id, [])
        if not candidates:
            decisions[item.source_id] = MatchDecision(
                source_id=item.source_id,
                decision="no_match",
                selected_candidate_id=None,
                confidence=0.0,
                notes="No Spotify candidates found.",
            )
            continue

        top_candidate = candidates[0]
        if top_candidate.heuristic_score < _auto_match_threshold():
            decisions[item.source_id] = MatchDecision(
                source_id=item.source_id,
                decision="no_match",
                selected_candidate_id=None,
                confidence=top_candidate.heuristic_score,
                notes="Deterministic Spotify search could not find a confident enough match.",
            )
            continue

        decisions[item.source_id] = MatchDecision(
            source_id=item.source_id,
            decision="match",
            selected_candidate_id=top_candidate.candidate_id,
            confidence=top_candidate.heuristic_score,
            notes="Deterministic Spotify search selected the top candidate.",
        )
    return decisions
