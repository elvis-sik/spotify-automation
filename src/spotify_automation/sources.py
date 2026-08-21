from __future__ import annotations

import urllib.parse

from spotify_automation.models import BuyMusicClubItem, BuyMusicClubList
from spotify_automation.utils import artist_similarity, normalize_text, similarity


def _canonical_source_url(url: str) -> str:
    parsed = urllib.parse.urlsplit(url.strip())
    return f"{(parsed.hostname or '').lower()}{urllib.parse.unquote(parsed.path).rstrip('/')}"


def _same_release(left: BuyMusicClubItem, right: BuyMusicClubItem) -> bool:
    left_url = _canonical_source_url(left.bandcamp_url)
    right_url = _canonical_source_url(right.bandcamp_url)
    if left_url and left_url == right_url:
        return True

    left_titles = [left.track, left.release_title]
    right_titles = [right.track, right.release_title]
    title_score = max(
        similarity(left_title, right_title)
        for left_title in left_titles
        for right_title in right_titles
    )
    artists_are_exact = normalize_text(left.artist) == normalize_text(right.artist)
    artists_are_equivalent = artist_similarity(left.artist, right.artist) >= 0.95
    return title_score >= 0.95 and (artists_are_exact or artists_are_equivalent)


def merge_issue_sources(
    substack_issue: BuyMusicClubList,
    buy_music_club_list: BuyMusicClubList,
) -> BuyMusicClubList:
    """Return the conservative union of Substack and Buy Music Club releases."""
    items = list(substack_issue.items)
    for candidate in buy_music_club_list.items:
        if any(_same_release(candidate, existing) for existing in items):
            continue
        items.append(candidate)

    return BuyMusicClubList(
        title=substack_issue.title,
        slug=substack_issue.slug,
        url=substack_issue.url,
        published_at=substack_issue.published_at,
        description=substack_issue.description,
        source_url=substack_issue.source_url,
        items=items,
        music_urls=list(dict.fromkeys(substack_issue.music_urls + buy_music_club_list.music_urls)),
    )
