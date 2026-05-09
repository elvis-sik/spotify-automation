from __future__ import annotations

import hashlib
import json
import os
import urllib.request
from html.parser import HTMLParser

from openai import OpenAI

from spotify_automation.matcher import DEFAULT_OPENAI_MODEL
from spotify_automation.models import BuyMusicClubItem, BuyMusicClubList
from spotify_automation.utils import compact_whitespace, strip_markdown_fences


USER_AGENT = "spotify-automation/0.1 (+https://openai.com/codex)"
MAX_PAGE_TEXT_CHARS = 60_000

EXTRACTION_SYSTEM_PROMPT = """You extract music recommendations from arbitrary web pages.

Rules:
- The input is plain text extracted from a fetched web page.
- Extract the page's actual list of songs, albums, EPs, or singles.
- Ignore navigation, comments, ads, newsletter text, unrelated links, and boilerplate.
- Each item must have at least an artist and a title.
- Use item_type "album" for albums, EPs, and releases; use "song" for individual songs or tracks; use "unknown" only when the page is ambiguous.
- For song items, release_title may be empty unless the page names the containing release.
- Do not invent entries that are not present in the page text.
- Return only JSON matching the requested schema.
"""

EXTRACTION_RESPONSE_FORMAT = {
    "type": "json_schema",
    "name": "web_page_music_items",
    "strict": True,
    "schema": {
        "type": "object",
        "properties": {
            "page_title": {"type": "string"},
            "items": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "artist": {"type": "string"},
                        "title": {"type": "string"},
                        "item_type": {"type": "string", "enum": ["album", "song", "unknown"]},
                        "release_title": {"type": "string"},
                    },
                    "required": ["artist", "title", "item_type", "release_title"],
                    "additionalProperties": False,
                },
            },
        },
        "required": ["page_title", "items"],
        "additionalProperties": False,
    },
}


class _ReadableTextParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self._skip_depth = 0
        self._chunks: list[str] = []
        self._title_chunks: list[str] = []
        self._in_title = False

    def handle_starttag(self, tag: str, _attrs: list[tuple[str, str | None]]) -> None:
        tag = tag.lower()
        if tag in {"script", "style", "noscript", "svg"}:
            self._skip_depth += 1
            return
        if tag == "title":
            self._in_title = True
        if tag in {"br", "li", "p", "div", "section", "article", "tr", "h1", "h2", "h3", "h4"}:
            self._chunks.append("\n")

    def handle_endtag(self, tag: str) -> None:
        tag = tag.lower()
        if tag in {"script", "style", "noscript", "svg"} and self._skip_depth:
            self._skip_depth -= 1
            return
        if tag == "title":
            self._in_title = False
        if tag in {"li", "p", "div", "section", "article", "tr", "h1", "h2", "h3", "h4"}:
            self._chunks.append("\n")

    def handle_data(self, data: str) -> None:
        if self._skip_depth:
            return
        text = compact_whitespace(data)
        if not text:
            return
        if self._in_title:
            self._title_chunks.append(text)
        self._chunks.append(text)
        self._chunks.append(" ")

    @property
    def title(self) -> str:
        return compact_whitespace(" ".join(self._title_chunks))

    @property
    def text(self) -> str:
        lines = [compact_whitespace(line) for line in "".join(self._chunks).splitlines()]
        return "\n".join(line for line in lines if line)


def fetch_html(url: str) -> str:
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(request, timeout=30) as response:
        charset = response.headers.get_content_charset() or "utf-8"
        return response.read().decode(charset, errors="replace")


def html_to_text(html: str) -> tuple[str, str]:
    parser = _ReadableTextParser()
    parser.feed(html)
    return parser.title, parser.text


def _source_id(url: str, artist: str, title: str, index: int) -> str:
    raw = f"{url}\0{artist}\0{title}\0{index}"
    return hashlib.sha1(raw.encode("utf-8")).hexdigest()[:16]


def fetch_web_page_list(
    url: str,
    *,
    model: str | None = None,
) -> BuyMusicClubList:
    if not os.environ.get("OPENAI_API_KEY"):
        raise RuntimeError("OPENAI_API_KEY is required to extract music items from an arbitrary web page.")

    html = fetch_html(url)
    html_title, page_text = html_to_text(html)
    if len(page_text) > MAX_PAGE_TEXT_CHARS:
        page_text = page_text[:MAX_PAGE_TEXT_CHARS]

    client = OpenAI()
    response = client.responses.create(
        model=model or os.environ.get("OPENAI_MODEL", DEFAULT_OPENAI_MODEL),
        instructions=EXTRACTION_SYSTEM_PROMPT,
        input=json.dumps(
            {
                "url": url,
                "html_title": html_title,
                "page_text": page_text,
            },
            ensure_ascii=False,
        ),
        reasoning={"effort": os.environ.get("OPENAI_REASONING_EFFORT", "medium")},
        text={"format": EXTRACTION_RESPONSE_FORMAT},
    )

    output_text = getattr(response, "output_text", None)
    if not isinstance(output_text, str) or not output_text.strip():
        raise RuntimeError("OpenAI returned an unexpected response shape while extracting page items.")

    parsed = json.loads(strip_markdown_fences(output_text))
    page_title = compact_whitespace(str(parsed.get("page_title") or html_title or url))
    raw_items = parsed.get("items") or []

    items: list[BuyMusicClubItem] = []
    for index, raw_item in enumerate(raw_items, start=1):
        artist = compact_whitespace(str(raw_item.get("artist") or ""))
        title = compact_whitespace(str(raw_item.get("title") or ""))
        if not artist or not title:
            continue

        item_type = compact_whitespace(str(raw_item.get("item_type") or "unknown"))
        release_title = compact_whitespace(str(raw_item.get("release_title") or ""))
        if item_type == "album" and not release_title:
            release_title = title

        items.append(
            BuyMusicClubItem(
                source_id=_source_id(url, artist, title, index),
                list_title=page_title,
                list_url=url,
                list_slug="",
                published_at="",
                artist=artist,
                track=title,
                release_title=release_title,
                bandcamp_type=item_type,
                bandcamp_url="",
                label="",
            )
        )

    return BuyMusicClubList(
        title=page_title,
        slug="",
        url=url,
        published_at="",
        description="",
        source_url=url,
        items=items,
    )
