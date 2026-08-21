#!/usr/bin/env python3
from __future__ import annotations

import argparse
import os
import re
import sys
import time
from dataclasses import dataclass
from typing import Sequence

from spotipy.exceptions import SpotifyException

from spotify_automation.spotify import get_search_client, get_user_client
from spotify_automation.utils import artist_similarity, compact_whitespace, dedupe_strings, normalize_text, similarity


DEFAULT_PLAYLIST_NAME = "Grace in the Wake of Light"
PLAYLIST_DESCRIPTION = (
    "Sacred minimalism, luminous orchestral elegies, and ambient meditations in the orbit of "
    "Terence Malick's The Tree of Life."
)
DEFAULT_FALLBACK_THRESHOLD = 0.62


@dataclass(frozen=True)
class RequestedTrack:
    artist: str
    title: str

    @property
    def label(self) -> str:
        return f"{self.artist} - {self.title}"


@dataclass(frozen=True)
class TrackCandidate:
    spotify_id: str
    spotify_url: str
    title: str
    artists: str
    album_title: str
    release_date: str
    popularity: int
    score: float
    query_hint: str

    @property
    def label(self) -> str:
        return f"{self.artists} - {self.title}"


REQUESTED_TRACKS: tuple[RequestedTrack, ...] = (
    RequestedTrack("Arvo Pärt", "Te Deum"),
    RequestedTrack("Arvo Pärt", "Adam’s Lament"),
    RequestedTrack("Arvo Pärt", "Kanon Pokajanen: Ode I"),
    RequestedTrack("Arvo Pärt", "Fratres"),
    RequestedTrack("Arvo Pärt", "Tabula Rasa: Silentium"),
    RequestedTrack("Arvo Pärt", "Spiegel im Spiegel"),
    RequestedTrack("Arvo Pärt", "Da pacem Domine"),
    RequestedTrack("Arvo Pärt", "Cantus in Memory of Benjamin Britten"),
    RequestedTrack("Henryk Górecki", "Miserere, Op. 44"),
    RequestedTrack("Henryk Górecki", "Totus Tuus, Op. 60"),
    RequestedTrack("Henryk Górecki", "Beatus Vir, Op. 38"),
    RequestedTrack("Henryk Górecki", "Amen, Op. 35"),
    RequestedTrack("Zbigniew Preisner", "Requiem for My Friend: Dies Irae"),
    RequestedTrack("Zbigniew Preisner", "Requiem for My Friend: Offertorium"),
    RequestedTrack("Zbigniew Preisner", "Requiem for My Friend: Sanctus"),
    RequestedTrack("Zbigniew Preisner", "Requiem for My Friend: Epitaphium"),
    RequestedTrack("Giya Kancheli", "Mourned by the Wind"),
    RequestedTrack("Giya Kancheli", "Styx"),
    RequestedTrack("Giya Kancheli", "Magnum Ignotum"),
    RequestedTrack("Giya Kancheli", "Chiaroscuro"),
    RequestedTrack("Giya Kancheli", "Silent Prayer"),
    RequestedTrack("Olivier Messiaen", "Quartet for the End of Time: Louange à l’Éternité de Jésus"),
    RequestedTrack("Olivier Messiaen", "L’Ascension: Prière du Christ montant vers son Père"),
    RequestedTrack("Olivier Messiaen", "O sacrum convivium!"),
    RequestedTrack("Olivier Messiaen", "Vingt regards sur l’enfant-Jésus: Regard du Père"),
    RequestedTrack("Ralph Vaughan Williams", "Fantasia on a Theme by Thomas Tallis"),
    RequestedTrack("Ralph Vaughan Williams", "The Lark Ascending"),
    RequestedTrack("Ralph Vaughan Williams", "Five Variants of Dives and Lazarus"),
    RequestedTrack("Ralph Vaughan Williams", "Serenade to Music"),
    RequestedTrack("Einojuhani Rautavaara", "Cantus Arcticus: The Bog"),
    RequestedTrack("Einojuhani Rautavaara", "Symphony No. 7 “Angel of Light”: Come un sogno"),
    RequestedTrack("Einojuhani Rautavaara", "Vigilia: Great Doxology"),
    RequestedTrack("Einojuhani Rautavaara", "Missa a cappella: Credo"),
    RequestedTrack("Jean Sibelius", "Symphony No. 5: III. Allegro molto"),
    RequestedTrack("Jean Sibelius", "The Oceanides"),
    RequestedTrack("Jean Sibelius", "Tapiola"),
    RequestedTrack("Jean Sibelius", "Luonnotar"),
    RequestedTrack("Samuel Barber", "Knoxville: Summer of 1915"),
    RequestedTrack("Samuel Barber", "Adagio for Strings"),
    RequestedTrack("Aaron Copland", "Appalachian Spring: Very Slowly"),
    RequestedTrack("Aaron Copland", "Appalachian Spring: Simple Gifts"),
    RequestedTrack("George Butterworth", "The Banks of Green Willow"),
    RequestedTrack("George Butterworth", "A Shropshire Lad: Rhapsody"),
    RequestedTrack("Leoš Janáček", "On an Overgrown Path: Our Evenings"),
    RequestedTrack("Leoš Janáček", "On an Overgrown Path: A Blown-Away Leaf"),
    RequestedTrack("Leoš Janáček", "On an Overgrown Path: The Madonna of Frydek"),
    RequestedTrack("Robert Schumann", "Kinderszenen: Träumerei"),
    RequestedTrack("Robert Schumann", "Waldszenen: Eintritt"),
    RequestedTrack("Robert Schumann", "Waldszenen: Vogel als Prophet"),
    RequestedTrack("J.S. Bach", "Wachet auf, ruft uns die Stimme, BWV 645"),
    RequestedTrack("J.S. Bach", "Gottes Zeit ist die allerbeste Zeit, BWV 106: Sonatina"),
    RequestedTrack("J.S. Bach", "St Matthew Passion: Erbarme dich"),
    RequestedTrack("François Couperin", "Les Ombres errantes"),
    RequestedTrack("François Couperin", "Les Bergeries"),
    RequestedTrack("François Couperin", "Le Tic-Toc-Choc"),
    RequestedTrack("Jean-Philippe Rameau", "Les Sauvages"),
    RequestedTrack("Jean-Philippe Rameau", "L’Enharmonique"),
    RequestedTrack("Jean-Philippe Rameau", "La Livri"),
    RequestedTrack("Anton Bruckner", "Os justi"),
    RequestedTrack("Anton Bruckner", "Locus iste"),
    RequestedTrack("Anton Bruckner", "Christus factus est"),
    RequestedTrack("Anton Bruckner", "Te Deum: Te ergo quaesumus"),
    RequestedTrack("Hector Berlioz", "La mort d’Ophélie"),
    RequestedTrack("Hector Berlioz", "Les nuits d’été: Le spectre de la rose"),
    RequestedTrack("Hector Berlioz", "Symphonie fantastique: Scène aux champs"),
    RequestedTrack("Ottorino Respighi", "Church Windows: The Flight into Egypt"),
    RequestedTrack("Ottorino Respighi", "The Birds: The Dove"),
    RequestedTrack("Ottorino Respighi", "Trittico Botticelliano: La Primavera"),
    RequestedTrack("David Hykes & The Harmonic Choir", "Rainbow Voice"),
    RequestedTrack("David Hykes & The Harmonic Choir", "Harmonic Meetings"),
    RequestedTrack("David Hykes & The Harmonic Choir", "Current Circulation"),
    RequestedTrack("Klaus Wiese", "Qalandar"),
    RequestedTrack("Klaus Wiese", "Baraka"),
    RequestedTrack("Klaus Wiese", "Klangschalen"),
    RequestedTrack("Popol Vuh", "Hosianna Mantra"),
    RequestedTrack("Popol Vuh", "Brüder des Schattens, Söhne des Lichts"),
    RequestedTrack("Popol Vuh", "Aguirre I"),
    RequestedTrack("Brian Eno", "An Ending (Ascent)"),
    RequestedTrack("Brian Eno", "Deep Blue Day"),
    RequestedTrack("Brian Eno", "Under Stars"),
    RequestedTrack("Harold Budd & Brian Eno", "First Light"),
    RequestedTrack("Harold Budd & Brian Eno", "Above Chiangmai"),
    RequestedTrack("Harold Budd & Brian Eno", "The Plateaux of Mirror"),
    RequestedTrack("Hans Zimmer", "The Thin Red Line: Light"),
    RequestedTrack("Hans Zimmer", "The Thin Red Line: The Lagoon"),
    RequestedTrack("Hans Zimmer", "The Thin Red Line: Stone in My Heart"),
    RequestedTrack("Hans Zimmer", "The Thin Red Line: God Yu Tekem Laef Blong Mi"),
    RequestedTrack("Ennio Morricone", "Days of Heaven: Harvest"),
    RequestedTrack("Ennio Morricone", "Days of Heaven: Happiness"),
    RequestedTrack("James Horner", "The New World: Of the Forest"),
    RequestedTrack("James Horner", "The New World: A Flame Within"),
    RequestedTrack("James Horner", "The New World: An Apparition in the Fields"),
    RequestedTrack("Hanan Townshend", "To the Wonder"),
    RequestedTrack("Hanan Townshend", "The Unattainable"),
    RequestedTrack("Hanan Townshend", "Awake"),
    RequestedTrack("James Newton Howard", "A Hidden Life"),
    RequestedTrack("James Newton Howard", "Fani"),
    RequestedTrack("James Newton Howard", "The Fields"),
    RequestedTrack("James Newton Howard", "Hope and Reflection"),
)


def _title_variants(title: str) -> list[str]:
    variants = [title]
    if ":" in title:
        variants.append(title.split(":", 1)[1].strip())
        variants.append(title.rsplit(":", 1)[1].strip())
    stripped_parenthetical = re.sub(r"\s*\([^)]*\)", "", title).strip()
    if stripped_parenthetical and stripped_parenthetical != title:
        variants.append(stripped_parenthetical)
    if title.startswith("The Thin Red Line: "):
        variants.append(title.removeprefix("The Thin Red Line: ").strip())
    if title.startswith("Days of Heaven: "):
        variants.append(title.removeprefix("Days of Heaven: ").strip())
    if title.startswith("The New World: "):
        variants.append(title.removeprefix("The New World: ").strip())
    return dedupe_strings([compact_whitespace(variant) for variant in variants if compact_whitespace(variant)])


def _query_variants(track: RequestedTrack) -> list[str]:
    queries: list[str] = []
    for title in _title_variants(track.title):
        queries.extend(
            [
                f'track:"{title}" artist:"{track.artist}"',
                f'"{title}" "{track.artist}"',
                f"{track.artist} {title}",
                title,
            ]
        )
    normalized_title = normalize_text(track.title)
    if normalized_title:
        queries.append(f"{track.artist} {normalized_title}")
    return dedupe_strings([compact_whitespace(query) for query in queries if compact_whitespace(query)])


def _candidate_artists(raw_artists: list[dict[str, object]]) -> str:
    return ", ".join(str(artist.get("name") or "") for artist in raw_artists if artist.get("name"))


def _score_candidate(track: RequestedTrack, candidate: TrackCandidate) -> float:
    title_variants = _title_variants(track.title)
    title_score = max(similarity(variant, candidate.title) for variant in title_variants)
    album_title_score = max(similarity(variant, candidate.album_title) for variant in title_variants)
    artist_score = max(
        artist_similarity(track.artist, candidate.artists),
        similarity(track.artist, candidate.album_title),
        similarity(track.artist, candidate.title),
    )
    popularity_bonus = min(candidate.popularity, 80) / 80 * 0.03
    score = (0.68 * title_score) + (0.22 * artist_score) + (0.07 * album_title_score) + popularity_bonus
    return round(min(score, 1.0), 4)


def _raw_track_candidate(raw_track: dict[str, object], track: RequestedTrack, query_hint: str) -> TrackCandidate:
    album = raw_track.get("album") or {}
    provisional = TrackCandidate(
        spotify_id=str(raw_track["id"]),
        spotify_url=str(raw_track["external_urls"]["spotify"]),
        title=str(raw_track["name"]),
        artists=_candidate_artists(raw_track.get("artists", [])),
        album_title=str(album.get("name") or ""),
        release_date=str(album.get("release_date") or ""),
        popularity=int(raw_track.get("popularity") or 0),
        score=0.0,
        query_hint=query_hint,
    )
    return TrackCandidate(
        spotify_id=provisional.spotify_id,
        spotify_url=provisional.spotify_url,
        title=provisional.title,
        artists=provisional.artists,
        album_title=provisional.album_title,
        release_date=provisional.release_date,
        popularity=provisional.popularity,
        score=_score_candidate(track, provisional),
        query_hint=query_hint,
    )


def find_spotify_api_fallback(sp, track: RequestedTrack, *, threshold: float) -> TrackCandidate | None:
    candidates: dict[str, TrackCandidate] = {}
    for query in _query_variants(track)[:10]:
        try:
            results = sp.search(q=query, type="track", limit=10)
        except SpotifyException as error:
            if error.http_status == 429:
                raise
            continue
        for raw_track in results["tracks"]["items"]:
            candidate = _raw_track_candidate(raw_track, track, query)
            existing = candidates.get(candidate.spotify_id)
            if existing is None or candidate.score > existing.score:
                candidates[candidate.spotify_id] = candidate
    if not candidates:
        return None
    best = max(candidates.values(), key=lambda candidate: (candidate.score, candidate.popularity))
    if best.score < threshold:
        return None
    return best


def find_or_create_playlist(sp, *, name: str, description: str) -> tuple[str, str]:
    offset = 0
    while True:
        results = sp.current_user_playlists(limit=50, offset=offset)
        for playlist in results["items"]:
            if playlist["name"] == name:
                playlist_id = playlist["id"]
                sp.playlist_change_details(playlist_id, public=False, description=description)
                return playlist_id, playlist["external_urls"]["spotify"]
        if not results["next"]:
            break
        offset += 50

    playlist = sp.current_user_playlist_create(
        name=name,
        public=False,
        description=description,
    )
    return playlist["id"], playlist["external_urls"]["spotify"]


def replace_playlist_tracks(sp, playlist_id: str, track_ids: list[str]) -> None:
    uris = [f"spotify:track:{track_id}" for track_id in dedupe_strings(track_ids)]
    sp.playlist_replace_items(playlist_id, uris[:100])
    for index in range(100, len(uris), 100):
        sp.playlist_add_items(playlist_id, uris[index : index + 100])
        time.sleep(0.1)


def resolve_tracks(
    requested_tracks: Sequence[RequestedTrack],
    *,
    fallback_threshold: float,
) -> tuple[list[str], list[str]]:
    search_client = get_search_client()
    resolved_track_ids: list[str] = []
    unresolved: list[str] = []

    for requested_track in requested_tracks:
        try:
            fallback = find_spotify_api_fallback(search_client, requested_track, threshold=fallback_threshold)
        except SpotifyException as error:
            unresolved.append(f"{requested_track.label} | Spotify API search failed: {error}")
            continue

        if fallback is None:
            unresolved.append(f"{requested_track.label} | No sufficiently confident Spotify API result.")
            continue

        resolved_track_ids.append(fallback.spotify_id)

    print(
        f"Resolved {len(resolved_track_ids)}/{len(requested_tracks)} requested tracks using Spotify API search.",
        flush=True,
    )
    return dedupe_strings(resolved_track_ids), unresolved


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Create the Tree of Life-adjacent Spotify playlist.")
    parser.add_argument("--dry-run", action="store_true", help="Resolve tracks but do not create or update the playlist")
    parser.add_argument("--allow-partial", action="store_true", help="Create the playlist even if some tracks are unresolved")
    parser.add_argument("--playlist-name", default=DEFAULT_PLAYLIST_NAME, help="Spotify playlist name")
    parser.add_argument(
        "--fallback-threshold",
        type=float,
        default=float(os.environ.get("SPOTIFY_AUTOMATION_TREE_FALLBACK_THRESHOLD", DEFAULT_FALLBACK_THRESHOLD)),
        help="Minimum Spotify API fallback confidence score",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    track_ids, unresolved = resolve_tracks(
        REQUESTED_TRACKS,
        fallback_threshold=max(0.0, min(1.0, args.fallback_threshold)),
    )

    if unresolved:
        print("\nUnresolved tracks:")
        for line in unresolved:
            print(f"  {line}")
        if not args.allow_partial:
            print("\nNo playlist changes were made. Re-run with --allow-partial to create it with resolved tracks.")
            return 1

    if args.dry_run:
        print(f"\nDry run only: would replace '{args.playlist_name}' with {len(track_ids)} unique Spotify tracks.")
        return 0

    user_client = get_user_client()
    playlist_id, playlist_url = find_or_create_playlist(
        user_client,
        name=args.playlist_name,
        description=PLAYLIST_DESCRIPTION,
    )
    replace_playlist_tracks(user_client, playlist_id, track_ids)
    print(f"\nPlaylist ready: {args.playlist_name}")
    print(f"Tracks: {len(track_ids)}")
    print(playlist_url)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
