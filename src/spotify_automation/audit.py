from __future__ import annotations

import urllib.parse
from dataclasses import asdict, dataclass

from spotify_automation.buy_music_club import fetch_all_lists
from spotify_automation.catalog import entry_key, read_catalog, source_id_from_entry
from spotify_automation.models import BuyMusicClubItem, BuyMusicClubList, SpotifyEntry
from spotify_automation.substack import fetch_all_issues
from spotify_automation.utils import artist_similarity, similarity


MIN_SOURCE_MATCH_SCORE = 0.82


@dataclass(frozen=True)
class ArchiveAuditRecord:
    issue_title: str
    issue_url: str
    published_at: str
    artist: str
    title: str
    item_type: str
    bandcamp_url: str
    status: str
    buy_music_club_list_url: str
    buy_music_club_artist: str
    buy_music_club_title: str
    spotify_url: str
    match_score: float

    def as_dict(self) -> dict[str, object]:
        return asdict(self)


@dataclass(frozen=True)
class ArchiveMusicLinkRecord:
    issue_title: str
    issue_url: str
    published_at: str
    music_url: str
    provider: str

    def as_dict(self) -> dict[str, str]:
        return asdict(self)


def canonical_music_url(url: str) -> str:
    parsed = urllib.parse.urlsplit(url.strip())
    hostname = (parsed.hostname or "").lower()
    path = urllib.parse.unquote(parsed.path).rstrip("/")
    if hostname == "open.spotify.com" and path.startswith("/embed/"):
        path = path.removeprefix("/embed")
    identity_keys: tuple[str, ...] = ()
    if hostname.endswith("youtube.com") or hostname == "youtu.be":
        identity_keys = ("list", "v")
    elif hostname.endswith("music.163.com"):
        identity_keys = ("id",)
    query = urllib.parse.parse_qs(parsed.query)
    identity = urllib.parse.urlencode(
        [(key, value) for key in identity_keys for value in query.get(key, [])]
    )
    return f"{hostname}{path}{f'?{identity}' if identity else ''}"


def music_provider(url: str) -> str:
    hostname = (urllib.parse.urlsplit(url).hostname or "").lower()
    if hostname.endswith("bandcamp.com"):
        return "bandcamp"
    if hostname == "open.spotify.com":
        return "spotify"
    if hostname == "music.apple.com":
        return "apple_music"
    if hostname.endswith("youtube.com") or hostname == "youtu.be":
        return "youtube"
    if hostname.endswith("soundcloud.com"):
        return "soundcloud"
    if hostname.endswith("music.163.com"):
        return "netease_music"
    if hostname == "y.qq.com":
        return "qq_music"
    return "other"


def _source_match_score(article_item: BuyMusicClubItem, list_item: BuyMusicClubItem) -> float:
    article_url = canonical_music_url(article_item.bandcamp_url)
    list_url = canonical_music_url(list_item.bandcamp_url)
    if article_url and article_url == list_url:
        return 1.0

    artist_score = artist_similarity(article_item.artist, list_item.artist)
    title_score = max(
        similarity(article_item.track, list_item.track),
        similarity(article_item.track, list_item.release_title),
        similarity(article_item.release_title, list_item.track),
        similarity(article_item.release_title, list_item.release_title),
    )
    return round((0.55 * artist_score) + (0.45 * title_score), 4)


def _best_source_match(
    article_item: BuyMusicClubItem,
    list_items: list[BuyMusicClubItem],
) -> tuple[BuyMusicClubItem | None, float]:
    if not list_items:
        return None, 0.0
    scored = [(_source_match_score(article_item, item), item) for item in list_items]
    score, item = max(scored, key=lambda pair: pair[0])
    if score < MIN_SOURCE_MATCH_SCORE:
        return None, score
    return item, score


def _catalog_index(entries: list[SpotifyEntry]) -> dict[tuple[str, str, str], SpotifyEntry]:
    return {entry_key(entry.list_url, entry.artist, entry.track): entry for entry in entries}


def audit_issues(
    issues: list[BuyMusicClubList],
    buy_music_lists: list[BuyMusicClubList],
    catalog_entries: list[SpotifyEntry],
) -> list[ArchiveAuditRecord]:
    buy_music_items = [item for playlist in buy_music_lists for item in playlist.items]
    catalog = _catalog_index(catalog_entries)
    direct_catalog = {
        source_id: entry
        for entry in catalog_entries
        if (source_id := source_id_from_entry(entry))
    }
    records: list[ArchiveAuditRecord] = []

    for issue in issues:
        for article_item in issue.items:
            list_item, score = _best_source_match(article_item, buy_music_items)
            catalog_entry = None
            status = "absent_from_buy_music_club"
            if article_item.source_id in direct_catalog:
                catalog_entry = direct_catalog[article_item.source_id]
                status = "agent_resolved"
            elif list_item is not None:
                catalog_entry = catalog.get(
                    entry_key(list_item.list_url, list_item.artist, list_item.track)
                )
                status = "matched_catalog" if catalog_entry else "unmatched_catalog"

            records.append(
                ArchiveAuditRecord(
                    issue_title=issue.title,
                    issue_url=issue.url,
                    published_at=issue.published_at,
                    artist=article_item.artist,
                    title=article_item.track,
                    item_type=article_item.bandcamp_type,
                    bandcamp_url=article_item.bandcamp_url,
                    status=status,
                    buy_music_club_list_url=list_item.list_url if list_item else "",
                    buy_music_club_artist=list_item.artist if list_item else "",
                    buy_music_club_title=list_item.track if list_item else "",
                    spotify_url=catalog_entry.spotify_url if catalog_entry else "",
                    match_score=score,
                )
            )

    return records


def run_archive_audit() -> tuple[list[ArchiveAuditRecord], list[ArchiveMusicLinkRecord], dict[str, int]]:
    issues = fetch_all_issues()
    buy_music_lists = fetch_all_lists()
    records = audit_issues(issues, buy_music_lists, read_catalog())
    music_links = [
        ArchiveMusicLinkRecord(
            issue_title=issue.title,
            issue_url=issue.url,
            published_at=issue.published_at,
            music_url=url,
            provider=music_provider(url),
        )
        for issue in issues
        for url in issue.music_urls
        if music_provider(url) != "bandcamp"
    ]
    status_counts: dict[str, int] = {}
    for record in records:
        status_counts[record.status] = status_counts.get(record.status, 0) + 1
    unique_release_urls = {canonical_music_url(record.bandcamp_url) for record in records}
    summary: dict[str, int] = {
        "substack_issues": len(issues),
        "buy_music_club_lists": len(buy_music_lists),
        "bandcamp_embed_occurrences": len(records),
        "unique_bandcamp_releases": len(unique_release_urls),
        "non_bandcamp_music_link_occurrences": len(music_links),
        "unique_non_bandcamp_music_links": len({canonical_music_url(link.music_url) for link in music_links}),
        **status_counts,
    }
    for provider in sorted({link.provider for link in music_links}):
        summary[f"{provider}_link_occurrences"] = sum(
            1 for link in music_links if link.provider == provider
        )
        summary[f"unique_{provider}_links"] = len(
            {
                canonical_music_url(link.music_url)
                for link in music_links
                if link.provider == provider
            }
        )
    for status in ("unmatched_catalog", "absent_from_buy_music_club"):
        summary[f"unique_{status}"] = len(
            {
                canonical_music_url(record.bandcamp_url)
                for record in records
                if record.status == status
            }
        )
    return records, music_links, summary
