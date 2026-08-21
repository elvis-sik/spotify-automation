from __future__ import annotations

import os
import time

import spotipy
from spotipy.exceptions import SpotifyException
from spotipy.oauth2 import SpotifyClientCredentials, SpotifyOAuth

from spotify_automation.models import SpotifyEntry
from spotify_automation.utils import dedupe_strings


WRITE_SCOPES = "playlist-modify-private playlist-modify-public playlist-read-private playlist-read-collaborative user-library-modify"
DEFAULT_PLAYLIST_NAME = "Concrete Avalanche"
PLAYLIST_MUTATION_BATCH_SIZE = 100


def _require_env(*names: str) -> dict[str, str]:
    values: dict[str, str] = {}
    missing = [name for name in names if not os.environ.get(name)]
    if missing:
        raise RuntimeError(f"Missing required environment variables: {', '.join(missing)}")
    for name in names:
        values[name] = os.environ[name]
    return values


def get_search_client() -> spotipy.Spotify:
    values = _require_env("SPOTIPY_CLIENT_ID", "SPOTIPY_CLIENT_SECRET")
    auth_manager = SpotifyClientCredentials(
        client_id=values["SPOTIPY_CLIENT_ID"],
        client_secret=values["SPOTIPY_CLIENT_SECRET"],
    )
    return spotipy.Spotify(
        auth_manager=auth_manager,
        retries=0,
        status_retries=0,
    )


def get_user_client() -> spotipy.Spotify:
    values = _require_env("SPOTIPY_CLIENT_ID", "SPOTIPY_CLIENT_SECRET", "SPOTIPY_REDIRECT_URI")
    auth_manager = SpotifyOAuth(
        client_id=values["SPOTIPY_CLIENT_ID"],
        client_secret=values["SPOTIPY_CLIENT_SECRET"],
        redirect_uri=values["SPOTIPY_REDIRECT_URI"],
        scope=WRITE_SCOPES,
        cache_path=os.environ.get("SPOTIPY_CACHE_PATH", ".spotify_cache"),
    )
    return spotipy.Spotify(auth_manager=auth_manager)


def find_playlist(sp: spotipy.Spotify, name: str) -> str | None:
    offset = 0
    while True:
        results = sp.current_user_playlists(limit=50, offset=offset)
        for playlist in results["items"]:
            if playlist["name"] == name:
                return playlist["id"]
        if not results["next"]:
            break
        offset += 50
    return None


def find_or_create_playlist(sp: spotipy.Spotify, name: str) -> str:
    if playlist_id := find_playlist(sp, name):
        return playlist_id

    playlist = sp.current_user_playlist_create(
        name=name,
        public=False,
        description="Tracks gathered from Concrete Avalanche issues.",
    )
    return playlist["id"]


def get_track_ids_for_albums(sp: spotipy.Spotify, album_ids: list[str]) -> list[str]:
    track_ids: list[str] = []
    for album_id in album_ids:
        offset = 0
        while True:
            page = sp.album_tracks(album_id, limit=50, offset=offset)
            for track in page["items"]:
                track_id = track.get("id")
                if track_id:
                    track_ids.append(track_id)
            if not page["next"]:
                break
            offset += 50
    return dedupe_strings(track_ids)


def remove_tracks_from_library(sp: spotipy.Spotify, track_ids: list[str]) -> None:
    unique_track_ids = dedupe_strings(track_ids)
    for index in range(0, len(unique_track_ids), 50):
        batch = unique_track_ids[index : index + 50]
        sp.current_user_saved_tracks_delete(batch)
        print(
            f"  Removed {min(index + 50, len(unique_track_ids))}/{len(unique_track_ids)}"
            " direct track saves from Liked Songs"
        )
        time.sleep(0.1)


def save_albums_to_library(sp: spotipy.Spotify, album_ids: list[str]) -> None:
    unique_album_ids = dedupe_strings(album_ids)
    for index in range(0, len(unique_album_ids), 50):
        batch = unique_album_ids[index : index + 50]
        sp.current_user_saved_albums_add(batch)
        print(f"  Saved {min(index + 50, len(unique_album_ids))}/{len(unique_album_ids)} albums to library")
        time.sleep(0.1)


def _release_preference(album: dict[str, object]) -> int:
    album_type = str(album.get("album_type") or "")
    total_tracks = int(album.get("total_tracks") or 0)
    if album_type == "album":
        return 3
    if album_type == "single" and total_tracks > 1:
        return 2
    if album_type == "single":
        return 1
    return 0


def _preferred_album_for_track(sp: spotipy.Spotify, track_id: str) -> dict[str, object] | None:
    track = sp.track(track_id, market="BR")
    original_album = (track or {}).get("album") or {}
    candidates = [original_album] if original_album.get("id") else []
    isrc = ((track or {}).get("external_ids") or {}).get("isrc")

    if isrc:
        try:
            results = sp.search(q=f"isrc:{isrc}", type="track", limit=10, market="BR")
        except SpotifyException as error:
            print(f"  Spotify ISRC lookup failed for track {track_id}: {error}")
        else:
            candidates.extend(
                candidate.get("album") or {}
                for candidate in results.get("tracks", {}).get("items", [])
            )

    unique_candidates: dict[str, dict[str, object]] = {}
    for album in candidates:
        album_id = str(album.get("id") or "")
        if album_id:
            unique_candidates.setdefault(album_id, album)
    if not unique_candidates:
        return None

    original_album_id = str(original_album.get("id") or "")
    return max(
        unique_candidates.values(),
        key=lambda album: (
            _release_preference(album),
            str(album.get("id") or "") == original_album_id,
        ),
    )


def get_preferred_album_ids_for_tracks(sp: spotipy.Spotify, track_ids: list[str]) -> list[str]:
    album_ids: list[str] = []
    for track_id in dedupe_strings(track_ids):
        album = _preferred_album_for_track(sp, track_id)
        if album:
            album_id = str(album["id"])
            album_ids.append(album_id)
            total_tracks = int(album.get("total_tracks") or 0)
            release_kind = "album"
            if album.get("album_type") == "single":
                release_kind = "EP" if total_tracks > 1 else "single"
            print(
                f"  Track {track_id} -> {release_kind} {album.get('name') or album_id}"
                f" ({album_id})"
            )
        time.sleep(0.1)
    return dedupe_strings(album_ids)


def get_playlist_track_ids(sp: spotipy.Spotify, playlist_id: str) -> set[str]:
    track_ids: set[str] = set()
    offset = 0
    while True:
        page = sp.playlist_items(playlist_id, limit=100, offset=offset)
        for item in page["items"]:
            # Spotify's current Web API names this field `item`; older responses and
            # Spotipy fixtures use `track`. Accept both shapes during the migration.
            track = item.get("track") or item.get("item") or {}
            track_id = track.get("id")
            if track_id:
                track_ids.add(track_id)
        if not page["next"]:
            break
        offset += 100
    return track_ids


def remove_duplicate_playlist_tracks(sp: spotipy.Spotify, playlist_id: str) -> dict[str, int]:
    seen_track_ids: set[str] = set()
    unique_uris: list[str] = []
    duplicate_count = 0
    position = 0
    offset = 0
    while True:
        page = sp.playlist_items(playlist_id, limit=100, offset=offset)
        for row in page["items"]:
            item = row.get("track") or row.get("item") or {}
            track_id = item.get("id")
            uri = item.get("uri")
            if track_id and uri:
                if track_id in seen_track_ids:
                    duplicate_count += 1
                else:
                    seen_track_ids.add(track_id)
                    unique_uris.append(uri)
            position += 1
        if not page["next"]:
            break
        offset += 100

    if duplicate_count:
        # Spotify's current delete endpoint removes every occurrence even when
        # positions are supplied. Rebuild from the first-occurrence order instead.
        sp.playlist_replace_items(playlist_id, unique_uris[:PLAYLIST_MUTATION_BATCH_SIZE])
        for index in range(PLAYLIST_MUTATION_BATCH_SIZE, len(unique_uris), 100):
            sp.playlist_add_items(playlist_id, unique_uris[index : index + 100])
        print(
            f"  Rebuilt playlist with {len(unique_uris)} unique tracks;"
            f" removed {duplicate_count} duplicate entries"
        )

    return {
        "playlist_entries_before": position,
        "unique_tracks": len(seen_track_ids),
        "duplicates_removed": duplicate_count,
    }


def add_tracks_to_playlist(sp: spotipy.Spotify, playlist_id: str, track_ids: list[str]) -> int:
    existing_track_ids = get_playlist_track_ids(sp, playlist_id)
    pending_track_ids = [track_id for track_id in dedupe_strings(track_ids) if track_id not in existing_track_ids]
    if not pending_track_ids:
        return 0

    for index in range(0, len(pending_track_ids), 100):
        batch = pending_track_ids[index : index + 100]
        sp.playlist_add_items(playlist_id, batch)
        print(f"  Added {min(index + 100, len(pending_track_ids))}/{len(pending_track_ids)} tracks to playlist")
        time.sleep(0.1)

    return len(pending_track_ids)


def apply_entries_to_spotify(
    sp: spotipy.Spotify,
    entries: list[SpotifyEntry],
    playlist_name: str = DEFAULT_PLAYLIST_NAME,
) -> dict[str, int]:
    track_ids = [entry.spotify_id for entry in entries if entry.link_type == "track"]
    album_ids = [entry.spotify_id for entry in entries if entry.link_type == "album"]

    if track_ids:
        print(f"Resolving {len(dedupe_strings(track_ids))} track match(es) to preferred releases...")
        album_ids.extend(get_preferred_album_ids_for_tracks(sp, track_ids))

    unique_album_ids = dedupe_strings(album_ids)
    if unique_album_ids:
        print(f"Saving {len(unique_album_ids)} releases to your library...")
        save_albums_to_library(sp, unique_album_ids)

    explicit_album_ids = [entry.spotify_id for entry in entries if entry.link_type == "album"]
    album_track_ids = get_track_ids_for_albums(sp, explicit_album_ids)
    all_track_ids = dedupe_strings(track_ids + album_track_ids)

    playlist_id = find_or_create_playlist(sp, playlist_name)
    print(f"Syncing {len(all_track_ids)} tracks into playlist '{playlist_name}'...")
    added_to_playlist = add_tracks_to_playlist(sp, playlist_id, all_track_ids)

    return {
        "albums_saved": len(unique_album_ids),
        "track_matches_resolved": len(dedupe_strings(track_ids)),
        "playlist_tracks_added": added_to_playlist,
    }


def apply_entries_to_spotify_library(sp: spotipy.Spotify, entries: list[SpotifyEntry]) -> dict[str, int]:
    track_ids = [entry.spotify_id for entry in entries if entry.link_type == "track"]
    album_ids = [entry.spotify_id for entry in entries if entry.link_type == "album"]

    if track_ids:
        print(f"Resolving {len(dedupe_strings(track_ids))} track match(es) to preferred releases...")
        album_ids.extend(get_preferred_album_ids_for_tracks(sp, track_ids))

    unique_album_ids = dedupe_strings(album_ids)
    if unique_album_ids:
        print(f"Saving {len(unique_album_ids)} albums to your library...")
        save_albums_to_library(sp, unique_album_ids)

    return {
        "albums_saved": len(unique_album_ids),
        "track_matches_resolved": len(dedupe_strings(track_ids)),
        "playlist_tracks_added": 0,
    }
