import unittest

from spotify_automation.spotify import get_playlist_track_ids


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


if __name__ == "__main__":
    unittest.main()
