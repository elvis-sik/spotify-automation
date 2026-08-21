from __future__ import annotations

import hashlib
import html
import json
import re
import time
import urllib.parse
import urllib.request
from urllib.error import HTTPError
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from html.parser import HTMLParser

from spotify_automation.models import BuyMusicClubItem, BuyMusicClubList
from spotify_automation.utils import compact_whitespace


SUBSTACK_BASE_URL = "https://jakenewby.substack.com"
SUBSTACK_ARCHIVE_URL = f"{SUBSTACK_BASE_URL}/api/v1/archive"
SUBSTACK_POST_API_PREFIX = f"{SUBSTACK_BASE_URL}/api/v1/posts"
USER_AGENT = "spotify-automation/0.1 (+https://jakenewby.substack.com)"
DEFAULT_ARCHIVE_CONCURRENCY = 2
DEFAULT_FETCH_RETRIES = 7
_BYLINE_PATTERN = re.compile(r"^(?P<title>.+?),\s+by\s+(?P<artist>.+)$", re.IGNORECASE)
_MUSIC_HOSTS = (
    "bandcamp.com",
    "open.spotify.com",
    "music.apple.com",
    "youtube.com",
    "youtu.be",
    "soundcloud.com",
    "music.163.com",
    "y.qq.com",
)


@dataclass(frozen=True)
class SubstackPostSummary:
    post_id: int
    title: str
    slug: str
    url: str
    published_at: str
    description: str


def _fetch_json(url: str) -> dict[str, object] | list[dict[str, object]]:
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    for attempt in range(DEFAULT_FETCH_RETRIES + 1):
        try:
            with urllib.request.urlopen(request, timeout=30) as response:
                return json.loads(response.read().decode("utf-8"))
        except HTTPError as error:
            if error.code != 429 or attempt >= DEFAULT_FETCH_RETRIES:
                raise
            retry_after = error.headers.get("Retry-After")
            try:
                delay = float(retry_after) if retry_after else 2.0**attempt
            except ValueError:
                delay = 2.0**attempt
            time.sleep(min(30.0, delay + 0.25))
    raise RuntimeError(f"Unable to fetch Substack JSON: {url}")


def _summary_from_raw(raw_post: dict[str, object]) -> SubstackPostSummary:
    slug = compact_whitespace(str(raw_post.get("slug") or ""))
    canonical_url = compact_whitespace(str(raw_post.get("canonical_url") or ""))
    return SubstackPostSummary(
        post_id=int(raw_post["id"]),
        title=compact_whitespace(str(raw_post.get("title") or slug)),
        slug=slug,
        url=canonical_url or f"{SUBSTACK_BASE_URL}/p/{slug}",
        published_at=compact_whitespace(str(raw_post.get("post_date") or "")),
        description=compact_whitespace(
            str(raw_post.get("subtitle") or raw_post.get("description") or "")
        ),
    )


def fetch_archive(*, max_posts: int | None = None) -> list[SubstackPostSummary]:
    posts: list[SubstackPostSummary] = []
    seen_ids: set[int] = set()
    offset = 0

    while max_posts is None or len(posts) < max_posts:
        query = urllib.parse.urlencode(
            {"sort": "new", "search": "", "offset": offset, "limit": 50}
        )
        raw_page = _fetch_json(f"{SUBSTACK_ARCHIVE_URL}?{query}")
        if not isinstance(raw_page, list) or not raw_page:
            break

        new_count = 0
        for raw_post in raw_page:
            summary = _summary_from_raw(raw_post)
            if summary.post_id in seen_ids:
                continue
            seen_ids.add(summary.post_id)
            posts.append(summary)
            new_count += 1
            if max_posts is not None and len(posts) >= max_posts:
                break

        if new_count == 0:
            break
        offset += len(raw_page)

    return posts


class _BandcampEmbedParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.embeds: list[dict[str, object]] = []
        self.music_urls: list[str] = []

    def _collect_url(self, value: object) -> None:
        if isinstance(value, dict):
            for nested in value.values():
                self._collect_url(nested)
            return
        if isinstance(value, list):
            for nested in value:
                self._collect_url(nested)
            return
        if not isinstance(value, str):
            return
        raw_url = compact_whitespace(html.unescape(value))
        if not raw_url.startswith(("https://", "http://")):
            return
        hostname = (urllib.parse.urlsplit(raw_url).hostname or "").lower()
        if any(hostname == host or hostname.endswith(f".{host}") for host in _MUSIC_HOSTS):
            self.music_urls.append(raw_url)

    def handle_starttag(self, _tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attributes = dict(attrs)
        self._collect_url(attributes.get("href"))
        self._collect_url(attributes.get("src"))
        raw_data = attributes.get("data-attrs")
        if raw_data:
            try:
                parsed_data = json.loads(html.unescape(raw_data))
            except (json.JSONDecodeError, TypeError):
                parsed_data = None
            self._collect_url(parsed_data)

        if attributes.get("data-component-name") != "BandcampToDOM":
            return
        if not raw_data:
            return
        try:
            parsed = json.loads(html.unescape(raw_data))
        except (json.JSONDecodeError, TypeError):
            return
        if isinstance(parsed, dict):
            self.embeds.append(parsed)


def extract_bandcamp_embeds(body_html: str) -> list[dict[str, object]]:
    parser = _BandcampEmbedParser()
    parser.feed(body_html)
    return parser.embeds


def extract_music_urls(body_html: str) -> list[str]:
    parser = _BandcampEmbedParser()
    parser.feed(body_html)
    return list(dict.fromkeys(parser.music_urls))


def _artist_and_title(raw_title: str, raw_author: str) -> tuple[str, str]:
    title = compact_whitespace(raw_title)
    author = compact_whitespace(raw_author)
    match = _BYLINE_PATTERN.match(title)
    if match:
        return (
            compact_whitespace(match.group("artist")),
            compact_whitespace(match.group("title")),
        )
    return author, title


def _source_id(post_id: int, bandcamp_url: str) -> str:
    raw = f"substack:{post_id}\0{bandcamp_url}"
    return hashlib.sha1(raw.encode("utf-8")).hexdigest()[:16]


def issue_from_post(raw_post: dict[str, object]) -> BuyMusicClubList:
    summary = _summary_from_raw(raw_post)
    body_html = str(raw_post.get("body_html") or "")
    items: list[BuyMusicClubItem] = []
    seen_urls: set[str] = set()

    for embed in extract_bandcamp_embeds(body_html):
        bandcamp_url = compact_whitespace(str(embed.get("url") or ""))
        if not bandcamp_url or bandcamp_url in seen_urls:
            continue
        seen_urls.add(bandcamp_url)

        artist, title = _artist_and_title(
            str(embed.get("title") or ""),
            str(embed.get("author") or ""),
        )
        if not artist or not title:
            continue

        is_album = bool(embed.get("is_album"))
        items.append(
            BuyMusicClubItem(
                source_id=_source_id(summary.post_id, bandcamp_url),
                list_title=summary.title,
                list_url=summary.url,
                list_slug=summary.slug,
                published_at=summary.published_at,
                artist=artist,
                track=title,
                release_title=title if is_album else "",
                bandcamp_type="album" if is_album else "track",
                bandcamp_url=bandcamp_url,
                label="",
            )
        )

    return BuyMusicClubList(
        title=summary.title,
        slug=summary.slug,
        url=summary.url,
        published_at=summary.published_at,
        description=summary.description,
        source_url=summary.url,
        items=items,
        music_urls=extract_music_urls(body_html),
    )


def fetch_issue(url_or_slug: str) -> BuyMusicClubList:
    slug = url_or_slug.rstrip("/").rsplit("/", 1)[-1]
    raw_post = _fetch_json(f"{SUBSTACK_POST_API_PREFIX}/{slug}")
    if not isinstance(raw_post, dict):
        raise RuntimeError(f"Unexpected Substack response for {url_or_slug}")
    return issue_from_post(raw_post)


def fetch_latest_issue() -> BuyMusicClubList:
    posts = fetch_archive(max_posts=1)
    if not posts:
        raise RuntimeError("Concrete Avalanche's Substack archive is empty.")
    return fetch_issue(posts[0].slug)


def fetch_all_issues(*, concurrency: int = DEFAULT_ARCHIVE_CONCURRENCY) -> list[BuyMusicClubList]:
    summaries = fetch_archive()
    issues_by_id: dict[int, BuyMusicClubList] = {}
    with ThreadPoolExecutor(max_workers=max(1, concurrency)) as executor:
        futures = {executor.submit(fetch_issue, summary.slug): summary for summary in summaries}
        for future in as_completed(futures):
            summary = futures[future]
            issues_by_id[summary.post_id] = future.result()
    return [issues_by_id[summary.post_id] for summary in summaries]
