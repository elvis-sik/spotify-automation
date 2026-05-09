from __future__ import annotations

import csv
from pathlib import Path

from spotify_automation.models import CSV_COLUMNS, BuyMusicClubItem, SpotifyEntry
from spotify_automation.utils import normalize_text


DATA_PATH = Path(__file__).resolve().parents[2] / "data" / "concrete_avalanche_spotify_cumulative.csv"


def entry_key(list_url: str, artist: str, track: str) -> tuple[str, str, str]:
    return (normalize_text(list_url), normalize_text(artist), normalize_text(track))


def item_key(item: BuyMusicClubItem) -> tuple[str, str, str]:
    return entry_key(item.list_url, item.artist, item.track)


def read_catalog(path: Path = DATA_PATH) -> list[SpotifyEntry]:
    if not path.exists():
        return []
    with path.open(newline="", encoding="utf-8") as handle:
        reader = csv.DictReader(handle)
        return [SpotifyEntry.from_csv_row(row) for row in reader]


def entries_for_list(entries: list[SpotifyEntry], list_url: str) -> list[SpotifyEntry]:
    list_key = normalize_text(list_url)
    return [entry for entry in entries if normalize_text(entry.list_url) == list_key]


def existing_index(entries: list[SpotifyEntry]) -> dict[tuple[str, str, str], SpotifyEntry]:
    return {entry_key(entry.list_url, entry.artist, entry.track): entry for entry in entries}


def items_to_process(
    issue_items: list[BuyMusicClubItem],
    entries: list[SpotifyEntry],
    *,
    force_rematch: bool = False,
) -> list[BuyMusicClubItem]:
    if force_rematch:
        return issue_items
    index = existing_index(entries)
    return [item for item in issue_items if item_key(item) not in index]


def upsert_entries(new_entries: list[SpotifyEntry], path: Path = DATA_PATH) -> tuple[int, int]:
    rows: list[dict[str, str]] = []
    if path.exists():
        with path.open(newline="", encoding="utf-8") as handle:
            rows = list(csv.DictReader(handle))

    index: dict[tuple[str, str, str], int] = {}
    for position, row in enumerate(rows):
        index[entry_key(row["list_url"], row["artist"], row["track"])] = position

    added = 0
    updated = 0
    for entry in new_entries:
        row = entry.as_csv_row()
        key = entry_key(entry.list_url, entry.artist, entry.track)
        if key in index:
            rows[index[key]] = row
            updated += 1
        else:
            index[key] = len(rows)
            rows.append(row)
            added += 1

    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=CSV_COLUMNS)
        writer.writeheader()
        writer.writerows(rows)

    return added, updated
