from __future__ import annotations

import hashlib
import urllib.parse
import urllib.request
from html.parser import HTMLParser

from spotify_automation.models import BuyMusicClubList
from spotify_automation.substack import SUBSTACK_BASE_URL, fetch_issue, issue_from_post
from spotify_automation.utils import compact_whitespace


USER_AGENT = "spotify-automation/0.1 (+https://openai.com/codex)"


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


def fetch_web_page_list(url: str) -> BuyMusicClubList:
    parsed_url = urllib.parse.urlsplit(url)
    if parsed_url.hostname == urllib.parse.urlsplit(SUBSTACK_BASE_URL).hostname and "/p/" in parsed_url.path:
        return fetch_issue(url)

    page_html = fetch_html(url)
    html_title, _page_text = html_to_text(page_html)
    synthetic_id = int(hashlib.sha1(url.encode("utf-8")).hexdigest()[:12], 16)
    return issue_from_post(
        {
            "id": synthetic_id,
            "title": html_title or url,
            "slug": "",
            "canonical_url": url,
            "post_date": "",
            "subtitle": "",
            "body_html": page_html,
        }
    )
