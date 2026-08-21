from __future__ import annotations

import unittest

from spotify_automation.models import BuyMusicClubItem, BuyMusicClubList
from spotify_automation.sources import merge_issue_sources


def item(source_id: str, list_url: str, artist: str, title: str, bandcamp_url: str) -> BuyMusicClubItem:
    return BuyMusicClubItem(
        source_id=source_id,
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


def issue(url: str, items: list[BuyMusicClubItem]) -> BuyMusicClubList:
    return BuyMusicClubList("Issue", "issue", url, "2026-08-19", "", url, items)


class SourceUnionTests(unittest.TestCase):
    def test_keeps_unique_items_from_both_sources(self) -> None:
        substack_url = "https://example.substack.com/p/issue"
        club_url = "https://www.buymusic.club/list/issue"
        shared_substack = item(
            "substack-shared",
            substack_url,
            "Shared Artist",
            "Shared Release",
            "https://shared.bandcamp.com/album/release",
        )
        shared_club = item(
            "club-shared",
            club_url,
            "Shared Artist",
            "Shared Release",
            "https://shared.bandcamp.com/album/release?from=embed",
        )
        article_only = item(
            "article-only",
            substack_url,
            "Article Artist",
            "Article Release",
            "https://article.bandcamp.com/album/release",
        )
        club_only = item(
            "club-only",
            club_url,
            "Club Artist",
            "Club Release",
            "https://club.bandcamp.com/album/release",
        )

        merged = merge_issue_sources(
            issue(substack_url, [shared_substack, article_only]),
            issue(club_url, [shared_club, club_only]),
        )

        self.assertEqual(
            [entry.source_id for entry in merged.items],
            ["substack-shared", "article-only", "club-only"],
        )
        self.assertEqual(merged.items[-1].list_url, club_url)

    def test_deduplicates_equivalent_artist_and_title_when_urls_differ(self) -> None:
        left = item(
            "left",
            "https://example.com/article",
            "Artist & Friend",
            "Release Name",
            "https://label.bandcamp.com/album/release-name",
        )
        right = item(
            "right",
            "https://example.com/list",
            "Artist, Friend",
            "Release Name",
            "https://artist.bandcamp.com/album/release-name",
        )

        merged = merge_issue_sources(
            issue("https://example.com/article", [left]),
            issue("https://example.com/list", [right]),
        )

        self.assertEqual([entry.source_id for entry in merged.items], ["left"])


if __name__ == "__main__":
    unittest.main()
