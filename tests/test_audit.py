from __future__ import annotations

import unittest

from spotify_automation.audit import audit_issues, canonical_music_url
from spotify_automation.models import BuyMusicClubItem, BuyMusicClubList, SpotifyEntry


def item(*, source: str, list_url: str, artist: str, title: str, bandcamp_url: str) -> BuyMusicClubItem:
    return BuyMusicClubItem(
        source_id=source,
        list_title="Issue",
        list_url=list_url,
        list_slug="issue",
        published_at="2026-08-19",
        artist=artist,
        track=title,
        release_title=title,
        bandcamp_type="album",
        bandcamp_url=bandcamp_url,
        label="",
    )


def music_list(url: str, items: list[BuyMusicClubItem]) -> BuyMusicClubList:
    return BuyMusicClubList("Issue", "issue", url, "2026-08-19", "", url, items)


class ArchiveAuditTests(unittest.TestCase):
    def test_canonical_music_url_discards_query_and_fragment(self) -> None:
        self.assertEqual(
            canonical_music_url("https://Artist.Bandcamp.com/album/test/?from=embed#x"),
            "artist.bandcamp.com/album/test",
        )

    def test_canonical_music_url_preserves_youtube_identity(self) -> None:
        self.assertEqual(
            canonical_music_url("https://music.youtube.com/playlist?si=tracking&list=OLAK123"),
            "music.youtube.com/playlist?list=OLAK123",
        )

    def test_canonical_music_url_unifies_spotify_embed_and_public_urls(self) -> None:
        self.assertEqual(
            canonical_music_url("https://open.spotify.com/embed/album/abc?utm_source=generator"),
            canonical_music_url("https://open.spotify.com/album/abc?si=tracking"),
        )

    def test_classifies_catalogued_unmatched_and_article_only_items(self) -> None:
        article_url = "https://jakenewby.substack.com/p/issue"
        bmc_url = "https://www.buymusic.club/list/issue"
        article_items = [
            item(source="a", list_url=article_url, artist="Artist A", title="One", bandcamp_url="https://a.bandcamp.com/album/one"),
            item(source="b", list_url=article_url, artist="Artist B", title="Two", bandcamp_url="https://b.bandcamp.com/album/two"),
            item(source="c", list_url=article_url, artist="Artist C", title="Three", bandcamp_url="https://c.bandcamp.com/album/three"),
        ]
        bmc_items = [
            item(source="d", list_url=bmc_url, artist="Artist A", title="One", bandcamp_url="https://a.bandcamp.com/album/one?from=embed"),
            item(source="e", list_url=bmc_url, artist="Artist B", title="Two", bandcamp_url="https://b.bandcamp.com/album/two"),
        ]
        catalog = [
            SpotifyEntry(
                playlist="Issue",
                list_url=bmc_url,
                artist="Artist A",
                track="One",
                link_type="album",
                spotify_url="https://open.spotify.com/album/abc",
                spotify_title="One",
                notes="",
            )
        ]

        records = audit_issues(
            [music_list(article_url, article_items)],
            [music_list(bmc_url, bmc_items)],
            catalog,
        )

        self.assertEqual(
            [record.status for record in records],
            ["matched_catalog", "unmatched_catalog", "absent_from_buy_music_club"],
        )

    def test_classifies_source_id_manual_resolution(self) -> None:
        article_url = "https://example.com/article"
        article_item = item(
            source="source-123",
            list_url=article_url,
            artist="Source Artist",
            title="Source Album",
            bandcamp_url="https://artist.bandcamp.com/album/source-album",
        )
        catalog_entry = SpotifyEntry(
            playlist="Issue",
            list_url=article_url,
            artist="Spotify Artist",
            track="Child Track",
            link_type="track",
            spotify_url="https://open.spotify.com/track/abc",
            spotify_title="Child Track",
            notes="source_id=source-123; Agent-verified child track.",
        )

        records = audit_issues([music_list(article_url, [article_item])], [], [catalog_entry])

        self.assertEqual(records[0].status, "agent_resolved")
        self.assertEqual(records[0].spotify_url, catalog_entry.spotify_url)


if __name__ == "__main__":
    unittest.main()
