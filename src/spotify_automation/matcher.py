from __future__ import annotations

import json
import os
import re

from openai import OpenAI

from spotify_automation.models import BuyMusicClubItem, MatchDecision, SpotifyCandidate, SpotifyWebMatch
from spotify_automation.utils import (
    artist_similarity,
    clamp_confidence,
    compact_whitespace,
    normalize_text,
    similarity,
    strip_markdown_fences,
)


DEFAULT_OPENAI_MODEL = "gpt-5.5"
DEFAULT_CANDIDATE_LIMIT = 8
DEFAULT_SEARCH_MARKETS = ("", "US", "BR", "CA", "GB", "HK", "TW", "JP", "SG", "AU")
SPOTIFY_URL_PATTERN = re.compile(
    r"^https://open\.spotify\.com/(?:intl-[a-z]{2}/)?(?P<link_type>album|track)/(?P<spotify_id>[A-Za-z0-9]+)(?:[/?#].*)?$"
)

WEB_SEARCH_SYSTEM_PROMPT = """You match Buy Music Club song mentions to Spotify albums or tracks by searching the live web.

Rules:
- Search the web for each item, focused on real open.spotify.com album and track pages.
- Do not invent Spotify URLs. Return a match only when you found an actual Spotify album or track URL.
- Prefer an album when it clearly corresponds to the source release and contains the mentioned song, or is the obvious single/EP carrying it.
- Prefer a track when it is the clearest exact song match and the album/release evidence is weaker.
- Reject remixes, live versions, demos, edits, instrumentals, and alternate versions unless the source title explicitly asks for them.
- Minor punctuation, transliteration, and multilingual title differences are acceptable when the artist and release context line up.
- If nothing is good enough, return no_match with an empty spotify_url.
- Return only JSON matching the requested schema.
"""

ALBUM_WEB_SEARCH_SYSTEM_PROMPT = """You match arbitrary blog music recommendations to Spotify album pages by searching the live web.

Rules:
- Search the web for each item, focused on real open.spotify.com album pages.
- Do not invent Spotify URLs. Return a match only when you found an actual Spotify album URL.
- For albums, EPs, singles, and releases, return the matching Spotify album page.
- For individual songs or tracks, return the best Spotify album/single/EP page that contains that song.
- Prefer the original release or obvious single/EP over compilations, remixes, live versions, demos, edits, instrumentals, and alternate versions unless the source explicitly asks for them.
- Minor punctuation, transliteration, and multilingual title differences are acceptable when the artist and release context line up.
- If you cannot find a suitable album page, return no_match with an empty spotify_url.
- Return only JSON matching the requested schema.
"""

WEB_SEARCH_RESPONSE_FORMAT = {
    "type": "json_schema",
    "name": "spotify_web_matches",
    "strict": True,
    "schema": {
        "type": "object",
        "properties": {
            "matches": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "source_id": {"type": "string"},
                        "decision": {"type": "string", "enum": ["match", "no_match"]},
                        "spotify_link_type": {"type": "string", "enum": ["album", "track", ""]},
                        "spotify_url": {"type": "string"},
                        "spotify_title": {"type": "string"},
                        "confidence": {"type": "number"},
                        "notes": {"type": "string"},
                    },
                    "required": [
                        "source_id",
                        "decision",
                        "spotify_link_type",
                        "spotify_url",
                        "spotify_title",
                        "confidence",
                        "notes",
                    ],
                    "additionalProperties": False,
                },
            },
        },
        "required": ["matches"],
        "additionalProperties": False,
    },
}


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
        ("track_broad", "track", f"{item.artist} {item.track}"),
        ("track_normalized", "track", f"{item.artist} {normalize_text(item.track)}"),
        ("album_exact", "album", f'album:{release_hint} artist:{item.artist}'),
        ("album_broad", "album", f"{item.artist} {release_hint}"),
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
    for query_hint, search_type, query, market in search_specs:
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
        if top_candidate.heuristic_score < 0.78:
            decisions[item.source_id] = MatchDecision(
                source_id=item.source_id,
                decision="no_match",
                selected_candidate_id=None,
                confidence=top_candidate.heuristic_score,
                notes="Heuristic fallback could not find a confident enough match.",
            )
            continue

        decisions[item.source_id] = MatchDecision(
            source_id=item.source_id,
            decision="match",
            selected_candidate_id=top_candidate.candidate_id,
            confidence=top_candidate.heuristic_score,
            notes="Heuristic fallback selected the top Spotify candidate.",
        )
    return decisions


def _build_web_search_payload(items: list[BuyMusicClubItem]) -> dict[str, object]:
    issue = items[0]
    return {
        "issue": {
            "title": issue.list_title,
            "list_url": issue.list_url,
            "published_at": issue.published_at,
        },
        "items": [
            {
                "source_id": item.source_id,
                "artist": item.artist,
                "track": item.track,
                "release_title": item.release_title,
                "source_item_type": item.bandcamp_type,
                "bandcamp_type": item.bandcamp_type,
                "bandcamp_url": item.bandcamp_url,
                "label": item.label,
            }
            for item in items
        ],
    }


def _response_output_text(response) -> str:
    output_text = getattr(response, "output_text", None)
    if isinstance(output_text, str) and output_text.strip():
        return output_text
    raise RuntimeError("OpenAI returned an unexpected response shape.")


def _canonical_spotify_url(value: str) -> tuple[str, str] | None:
    match = SPOTIFY_URL_PATTERN.match((value or "").strip())
    if not match:
        return None
    link_type = match.group("link_type")
    spotify_id = match.group("spotify_id")
    return link_type, f"https://open.spotify.com/{link_type}/{spotify_id}"


def _choose_matches_with_openai(
    items: list[BuyMusicClubItem],
    *,
    model: str | None = None,
    instructions: str,
    required_link_type: str | None = None,
) -> dict[str, SpotifyWebMatch]:
    if not os.environ.get("OPENAI_API_KEY"):
        raise RuntimeError("OPENAI_API_KEY is required to use GPT web-search matching.")

    payload = _build_web_search_payload(items)
    client = OpenAI()
    response = client.responses.create(
        model=model or os.environ.get("OPENAI_MODEL", DEFAULT_OPENAI_MODEL),
        instructions=instructions,
        input=json.dumps(payload, ensure_ascii=False),
        reasoning={"effort": os.environ.get("OPENAI_REASONING_EFFORT", "medium")},
        tools=[
            {
                "type": "web_search",
                "search_context_size": os.environ.get("OPENAI_WEB_SEARCH_CONTEXT_SIZE", "medium"),
                "filters": {"allowed_domains": ["open.spotify.com"]},
            }
        ],
        tool_choice="required",
        max_tool_calls=max(4, min(50, len(items) * 6)),
        text={"format": WEB_SEARCH_RESPONSE_FORMAT},
    )
    parsed = json.loads(strip_markdown_fences(_response_output_text(response)))
    raw_matches = parsed.get("matches", [])

    item_lookup = {item.source_id: item for item in items}
    response_lookup = {str(match.get("source_id")): match for match in raw_matches}

    decisions: dict[str, SpotifyWebMatch] = {}
    for source_id in item_lookup:
        raw_match = response_lookup.get(source_id)
        if not raw_match:
            decisions[source_id] = SpotifyWebMatch(
                source_id=source_id,
                decision="no_match",
                link_type="",
                spotify_url="",
                spotify_title="",
                confidence=0.0,
                notes="GPT web search did not include a decision for this item.",
            )
            continue

        decision = str(raw_match.get("decision") or "no_match").strip().lower()
        notes = compact_whitespace(str(raw_match.get("notes") or "")) or "No notes provided."
        confidence = clamp_confidence(raw_match.get("confidence"))
        spotify_url = str(raw_match.get("spotify_url") or "").strip()
        spotify_title = compact_whitespace(str(raw_match.get("spotify_title") or ""))

        if decision != "match" or not spotify_url:
            decisions[source_id] = SpotifyWebMatch(
                source_id=source_id,
                decision="no_match",
                link_type="",
                spotify_url="",
                spotify_title="",
                confidence=confidence,
                notes=notes,
            )
            continue

        canonical = _canonical_spotify_url(spotify_url)
        if canonical is None:
            decisions[source_id] = SpotifyWebMatch(
                source_id=source_id,
                decision="no_match",
                link_type="",
                spotify_url="",
                spotify_title="",
                confidence=0.0,
                notes="GPT web search did not return a valid open.spotify.com album or track URL.",
            )
            continue

        link_type, canonical_url = canonical
        if required_link_type and link_type != required_link_type:
            decisions[source_id] = SpotifyWebMatch(
                source_id=source_id,
                decision="no_match",
                link_type="",
                spotify_url="",
                spotify_title="",
                confidence=0.0,
                notes=f"GPT web search returned a Spotify {link_type} URL, but this workflow requires {required_link_type} URLs.",
            )
            continue

        decisions[source_id] = SpotifyWebMatch(
            source_id=source_id,
            decision="match",
            link_type=link_type,
            spotify_url=canonical_url,
            spotify_title=spotify_title,
            confidence=confidence,
            notes=notes,
        )

    return decisions


def choose_matches_with_openai(
    items: list[BuyMusicClubItem],
    *,
    model: str | None = None,
) -> dict[str, SpotifyWebMatch]:
    return _choose_matches_with_openai(
        items,
        model=model,
        instructions=WEB_SEARCH_SYSTEM_PROMPT,
    )


def choose_album_matches_with_openai(
    items: list[BuyMusicClubItem],
    *,
    model: str | None = None,
) -> dict[str, SpotifyWebMatch]:
    return _choose_matches_with_openai(
        items,
        model=model,
        instructions=ALBUM_WEB_SEARCH_SYSTEM_PROMPT,
        required_link_type="album",
    )
