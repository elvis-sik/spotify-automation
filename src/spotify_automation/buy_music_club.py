from __future__ import annotations

import urllib.request

from spotify_automation.models import BuyMusicClubItem, BuyMusicClubList
from spotify_automation.utils import extract_next_data


BUY_MUSIC_CLUB_USER_URL = "https://www.buymusic.club/user/concrete_avalanche"
BUY_MUSIC_CLUB_LIST_PREFIX = "https://www.buymusic.club/list"
USER_AGENT = "spotify-automation/0.1 (+https://www.buymusic.club)"


def _fetch_html(url: str) -> str:
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(request, timeout=30) as response:
        return response.read().decode("utf-8")


def _list_url_for_slug(slug: str) -> str:
    return f"{BUY_MUSIC_CLUB_LIST_PREFIX}/{slug}"


def _item_from_raw(raw_list: dict[str, object], raw_item: dict[str, object]) -> BuyMusicClubItem:
    return BuyMusicClubItem(
        source_id=str(raw_item["id"]),
        list_title=str(raw_list["title"] or "").strip(),
        list_url=_list_url_for_slug(str(raw_list["slug"])),
        list_slug=str(raw_list["slug"] or "").strip(),
        published_at=str(raw_list["published_at"] or "").strip(),
        artist=str(raw_item.get("artist") or "").strip(),
        track=str(raw_item.get("title") or "").strip(),
        release_title=str(raw_item.get("releaseTitle") or "").strip(),
        bandcamp_type=str(raw_item.get("type") or "").strip(),
        bandcamp_url=str(raw_item.get("url") or "").strip(),
        label=str(raw_item.get("label") or "").strip(),
    )


def _list_from_raw(raw_list: dict[str, object]) -> BuyMusicClubList:
    raw_items = sorted(
        raw_list.get("ListItems", []),
        key=lambda raw_item: (raw_item.get("order", 0), raw_item.get("id", 0)),
    )
    items = [_item_from_raw(raw_list, raw_item) for raw_item in raw_items]
    return BuyMusicClubList(
        title=str(raw_list["title"] or "").strip(),
        slug=str(raw_list["slug"] or "").strip(),
        url=_list_url_for_slug(str(raw_list["slug"])),
        published_at=str(raw_list["published_at"] or "").strip(),
        description=str(raw_list.get("description") or "").strip(),
        source_url=str(raw_list.get("url") or "").strip(),
        items=items,
    )


def fetch_latest_list() -> BuyMusicClubList:
    data = extract_next_data(_fetch_html(BUY_MUSIC_CLUB_USER_URL))
    raw_lists = data["props"]["pageProps"]["lists"]
    latest = max(raw_lists, key=lambda raw_list: raw_list["published_at"])
    return _list_from_raw(latest)


def fetch_list(list_url_or_slug: str) -> BuyMusicClubList:
    if list_url_or_slug.startswith("http://") or list_url_or_slug.startswith("https://"):
        url = list_url_or_slug
    else:
        url = _list_url_for_slug(list_url_or_slug)
    data = extract_next_data(_fetch_html(url))
    raw_list = data["props"]["pageProps"]["list"]
    return _list_from_raw(raw_list)
