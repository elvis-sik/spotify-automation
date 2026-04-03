"""Spotify automation - add tracks to library and playlist from CSV data."""

import os
import sys
import time

import spotipy
from spotipy.oauth2 import SpotifyOAuth

from spotify_automation.loader import load_entries

SCOPES = "user-library-modify playlist-modify-private playlist-modify-public"
PLAYLIST_NAME = "Concrete Avalanche"


def get_spotify_client() -> spotipy.Spotify:
    """Create an authenticated Spotify client using env vars."""
    for var in ("SPOTIPY_CLIENT_ID", "SPOTIPY_CLIENT_SECRET", "SPOTIPY_REDIRECT_URI"):
        if not os.environ.get(var):
            print(f"Error: {var} environment variable is not set.")
            sys.exit(1)
    return spotipy.Spotify(auth_manager=SpotifyOAuth(scope=SCOPES))


def find_playlist(sp: spotipy.Spotify, name: str) -> str | None:
    """Find a playlist by name in the current user's playlists. Returns playlist ID."""
    offset = 0
    while True:
        results = sp.current_user_playlists(limit=50, offset=offset)
        for pl in results["items"]:
            if pl["name"] == name:
                return pl["id"]
        if results["next"] is None:
            break
        offset += 50
    return None


def get_track_ids_for_albums(sp: spotipy.Spotify, album_ids: list[str]) -> list[str]:
    """Get all track IDs from a list of album IDs (batched by 20)."""
    track_ids = []
    for i in range(0, len(album_ids), 20):
        batch = album_ids[i : i + 20]
        albums = sp.albums(batch)
        for album in albums["albums"]:
            if album is None:
                continue
            for track in album["tracks"]["items"]:
                track_ids.append(track["id"])
    return track_ids


def save_tracks_to_library(sp: spotipy.Spotify, track_ids: list[str]) -> None:
    """Save tracks to the user's library in batches of 50."""
    for i in range(0, len(track_ids), 50):
        batch = track_ids[i : i + 50]
        sp.current_user_saved_tracks_add(batch)
        print(f"  Saved {min(i + 50, len(track_ids))}/{len(track_ids)} tracks to library")
        time.sleep(0.1)


def save_albums_to_library(sp: spotipy.Spotify, album_ids: list[str]) -> None:
    """Save albums to the user's library in batches of 50."""
    for i in range(0, len(album_ids), 50):
        batch = album_ids[i : i + 50]
        sp.current_user_saved_albums_add(batch)
        print(f"  Saved {min(i + 50, len(album_ids))}/{len(album_ids)} albums to library")
        time.sleep(0.1)


def add_tracks_to_playlist(sp: spotipy.Spotify, playlist_id: str, track_ids: list[str]) -> None:
    """Add tracks to a playlist in batches of 100."""
    for i in range(0, len(track_ids), 100):
        batch = track_ids[i : i + 100]
        sp.playlist_add_items(playlist_id, batch)
        print(f"  Added {min(i + 100, len(track_ids))}/{len(track_ids)} tracks to playlist")
        time.sleep(0.1)


def main() -> None:
    entries = load_entries()
    print(f"Loaded {len(entries)} entries from CSV (row 115 onward)")

    track_entries = [e for e in entries if e.link_type == "track"]
    album_entries = [e for e in entries if e.link_type == "album"]
    print(f"  {len(track_entries)} direct tracks, {len(album_entries)} albums")

    sp = get_spotify_client()
    user = sp.current_user()
    print(f"Authenticated as: {user['display_name']} ({user['id']})")

    # Find the target playlist
    playlist_id = find_playlist(sp, PLAYLIST_NAME)
    if playlist_id is None:
        print(f"Error: playlist '{PLAYLIST_NAME}' not found in your account.")
        sys.exit(1)
    print(f"Found playlist '{PLAYLIST_NAME}' (ID: {playlist_id})")

    # Step 1: Save albums to library
    album_ids = [e.spotify_id for e in album_entries]
    if album_ids:
        print(f"\nSaving {len(album_ids)} albums to library...")
        save_albums_to_library(sp, album_ids)

    # Step 2: Save individual tracks to library
    direct_track_ids = [e.spotify_id for e in track_entries]
    if direct_track_ids:
        print(f"\nSaving {len(direct_track_ids)} individual tracks to library...")
        save_tracks_to_library(sp, direct_track_ids)

    # Step 3: Resolve album entries to track IDs for playlist addition
    print(f"\nResolving album entries to tracks for playlist...")
    album_track_ids = get_track_ids_for_albums(sp, album_ids)
    print(f"  Resolved {len(album_ids)} albums to {len(album_track_ids)} tracks")

    # Step 4: Add all tracks to playlist
    all_track_ids = direct_track_ids + album_track_ids
    print(f"\nAdding {len(all_track_ids)} total tracks to playlist '{PLAYLIST_NAME}'...")
    add_tracks_to_playlist(sp, playlist_id, all_track_ids)

    print(f"\nDone! Added {len(all_track_ids)} tracks to library and playlist.")
