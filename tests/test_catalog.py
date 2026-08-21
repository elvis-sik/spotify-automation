from __future__ import annotations

import unittest

from spotify_automation.catalog import items_to_process
from spotify_automation.models import BuyMusicClubItem, SpotifyEntry


class CatalogTests(unittest.TestCase):
    def test_manual_match_source_id_resolves_one_to_many_release(self) -> None:
        item = BuyMusicClubItem(
            source_id="source-123",
            list_title="Issue",
            list_url="https://example.com/issue",
            list_slug="issue",
            published_at="",
            artist="Source Artist",
            track="Source Release",
            release_title="Source Release",
            bandcamp_type="album",
            bandcamp_url="https://artist.bandcamp.com/album/source-release",
            label="",
        )
        child_track = SpotifyEntry(
            playlist="Issue",
            list_url="https://example.com/issue",
            artist="Spotify Artist",
            track="Child Track",
            link_type="track",
            spotify_url="https://open.spotify.com/track/abc",
            spotify_title="Child Track",
            notes="source_id=source-123; Agent-verified child track.",
        )

        self.assertEqual(items_to_process([item], [child_track]), [])
