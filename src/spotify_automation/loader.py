"""Load and filter the Concrete Avalanche CSV data."""

import csv
from dataclasses import dataclass
from pathlib import Path

DATA_PATH = Path(__file__).resolve().parents[2] / "data" / "concrete_avalanche_spotify_cumulative.csv"

# Row 115 in 1-indexed CSV (including header) = index 114 in the reader output.
# Header is row 1, data starts at row 2, so row 115 = data index 113 (0-based).
START_ROW = 115  # 1-indexed row number (including header)


@dataclass
class SpotifyEntry:
    playlist: str
    artist: str
    track: str
    link_type: str  # "track" or "album"
    spotify_url: str
    spotify_id: str

    @property
    def uri(self) -> str:
        return f"spotify:{self.link_type}:{self.spotify_id}"


def extract_spotify_id(url: str) -> str:
    """Extract the Spotify ID from a URL like https://open.spotify.com/track/ABC123."""
    return url.rstrip("/").split("/")[-1].split("?")[0]


def load_entries(start_row: int = START_ROW) -> list[SpotifyEntry]:
    """Load CSV entries starting from the given 1-indexed row number."""
    entries: list[SpotifyEntry] = []
    with DATA_PATH.open(newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for i, row in enumerate(reader, start=2):  # row 1 is header, data starts at 2
            if i < start_row:
                continue
            url = row["spotify_url"].strip()
            if not url:
                continue
            entries.append(
                SpotifyEntry(
                    playlist=row["playlist"].strip(),
                    artist=row["artist"].strip(),
                    track=row["track"].strip(),
                    link_type=row["spotify_link_type"].strip(),
                    spotify_url=url,
                    spotify_id=extract_spotify_id(url),
                )
            )
    return entries
