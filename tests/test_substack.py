from __future__ import annotations

import html
import json
import unittest

from spotify_automation.substack import extract_bandcamp_embeds, extract_music_urls, issue_from_post


class SubstackParserTests(unittest.TestCase):
    def test_extracts_bandcamp_embed_attributes(self) -> None:
        attributes = {
            "url": "https://artist.bandcamp.com/album/china-sessions",
            "title": "China Sessions, by Tulipa Ruiz & YEHAIYAHAN",
            "author": "Tulipa Ruiz & YEHAIYAHAN",
            "is_album": True,
        }
        body = (
            '<div data-component-name="BandcampToDOM" data-attrs="'
            + html.escape(json.dumps(attributes), quote=True)
            + '"></div>'
        )

        self.assertEqual(extract_bandcamp_embeds(body), [attributes])

    def test_builds_issue_items_and_deduplicates_urls(self) -> None:
        attributes = {
            "url": "https://artist.bandcamp.com/album/china-sessions",
            "title": "China Sessions, by Tulipa Ruiz & YEHAIYAHAN",
            "author": "Tulipa Ruiz & YEHAIYAHAN",
            "is_album": True,
        }
        embed = (
            '<div data-component-name="BandcampToDOM" data-attrs="'
            + html.escape(json.dumps(attributes), quote=True)
            + '"></div>'
        )
        issue = issue_from_post(
            {
                "id": 42,
                "title": "Summer issue",
                "slug": "summer-issue",
                "canonical_url": "https://jakenewby.substack.com/p/summer-issue",
                "post_date": "2026-08-19T00:00:00Z",
                "body_html": embed + embed,
            }
        )

        self.assertEqual(len(issue.items), 1)
        item = issue.items[0]
        self.assertEqual(item.artist, "Tulipa Ruiz & YEHAIYAHAN")
        self.assertEqual(item.track, "China Sessions")
        self.assertEqual(item.release_title, "China Sessions")
        self.assertEqual(item.bandcamp_type, "album")

    def test_extracts_known_music_links_from_anchors_and_embed_json(self) -> None:
        embed_data = html.escape(
            json.dumps({"url": "https://open.spotify.com/track/abc?si=123"}),
            quote=True,
        )
        body = (
            '<a href="https://music.apple.com/us/album/example/123">Apple</a>'
            f'<div data-attrs="{embed_data}"></div>'
            '<a href="https://example.com/not-music">Ignore</a>'
        )
        self.assertEqual(
            extract_music_urls(body),
            [
                "https://music.apple.com/us/album/example/123",
                "https://open.spotify.com/track/abc?si=123",
            ],
        )


if __name__ == "__main__":
    unittest.main()
