import unittest

from spotify_automation.models import SpotifyEntry
from spotify_automation.spotify import (
    apply_entries_to_spotify,
    get_playlist_track_ids,
    get_preferred_album_ids_for_tracks,
    remove_duplicate_playlist_tracks,
)


class FakeSpotify:
    def playlist_items(self, playlist_id, *, limit, offset):
        self.last_call = (playlist_id, limit, offset)
        return {
            "items": [
                {"track": {"id": "legacy-track"}},
                {"item": {"id": "current-track"}},
                {"item": None},
            ],
            "next": None,
        }


class SpotifyPlaylistTests(unittest.TestCase):
    def test_reads_legacy_and_current_playlist_item_shapes(self):
        spotify = FakeSpotify()

        track_ids = get_playlist_track_ids(spotify, "playlist-id")

        self.assertEqual(track_ids, {"legacy-track", "current-track"})
        self.assertEqual(spotify.last_call, ("playlist-id", 100, 0))

    def test_prefers_album_over_ep_and_single_for_track_match(self):
        class ReleaseSpotify:
            def track(self, track_id, *, market):
                return {
                    "id": track_id,
                    "external_ids": {"isrc": "TEST123"},
                    "album": {
                        "id": "single-id",
                        "name": "Song",
                        "album_type": "single",
                        "total_tracks": 1,
                    },
                }

            def search(self, **_kwargs):
                return {
                    "tracks": {
                        "items": [
                            {
                                "album": {
                                    "id": "ep-id",
                                    "name": "Song EP",
                                    "album_type": "single",
                                    "total_tracks": 4,
                                }
                            },
                            {
                                "album": {
                                    "id": "album-id",
                                    "name": "Full Album",
                                    "album_type": "album",
                                    "total_tracks": 10,
                                }
                            },
                        ]
                    }
                }

        self.assertEqual(
            get_preferred_album_ids_for_tracks(ReleaseSpotify(), ["track-id"]),
            ["album-id"],
        )

    def test_track_match_saves_container_but_only_adds_track_to_playlist(self):
        class ApplySpotify:
            def __init__(self):
                self.saved_albums = []
                self.playlist_additions = []

            def track(self, track_id, *, market):
                return {
                    "id": track_id,
                    "external_ids": {},
                    "album": {
                        "id": "container-id",
                        "name": "Containing Album",
                        "album_type": "album",
                        "total_tracks": 8,
                    },
                }

            def current_user_saved_albums_add(self, album_ids):
                self.saved_albums.extend(album_ids)

            def current_user_playlists(self, *, limit, offset):
                return {"items": [{"id": "playlist-id", "name": "Concrete Avalanche"}], "next": None}

            def playlist_items(self, playlist_id, *, limit, offset):
                return {"items": [], "next": None}

            def playlist_add_items(self, playlist_id, track_ids):
                self.playlist_additions.extend(track_ids)

        spotify = ApplySpotify()
        entry = SpotifyEntry(
            playlist="Issue",
            list_url="https://example.com/issue",
            artist="Artist",
            track="Track",
            link_type="track",
            spotify_url="https://open.spotify.com/track/track-id",
            spotify_title="Track",
            notes="",
        )

        summary = apply_entries_to_spotify(spotify, [entry])

        self.assertEqual(spotify.saved_albums, ["container-id"])
        self.assertEqual(spotify.playlist_additions, ["track-id"])
        self.assertEqual(summary["track_matches_resolved"], 1)

    def test_dedupe_preserves_first_occurrence_and_removes_later_positions(self):
        class DedupeSpotify:
            def __init__(self):
                self.replacement = []
                self.additions = []

            def playlist_items(self, playlist_id, *, limit, offset):
                ids = ["a", "a", "b", "a", "b", "c"]
                return {
                    "items": [
                        {"item": {"id": track_id, "uri": f"spotify:track:{track_id}"}}
                        for track_id in ids
                    ],
                    "next": None,
                }

            def playlist_replace_items(self, playlist_id, items):
                self.replacement.extend(items)

            def playlist_add_items(self, playlist_id, items):
                self.additions.extend(items)

        spotify = DedupeSpotify()

        summary = remove_duplicate_playlist_tracks(spotify, "playlist-id")

        self.assertEqual(
            spotify.replacement + spotify.additions,
            ["spotify:track:a", "spotify:track:b", "spotify:track:c"],
        )
        self.assertEqual(summary["duplicates_removed"], 3)
        self.assertEqual(summary["unique_tracks"], 3)


if __name__ == "__main__":
    unittest.main()
