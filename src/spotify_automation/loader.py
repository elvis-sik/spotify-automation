"""Backwards-compatible CSV loading helpers."""

from spotify_automation.catalog import DATA_PATH, read_catalog
from spotify_automation.models import SpotifyEntry

START_ROW = 2


def extract_spotify_id(url: str) -> str:
    return url.rstrip("/").split("/")[-1].split("?")[0]


def load_entries(start_row: int = START_ROW) -> list[SpotifyEntry]:
    entries = read_catalog(DATA_PATH)
    if start_row <= 2:
        return entries
    data_offset = max(0, start_row - 2)
    return entries[data_offset:]
