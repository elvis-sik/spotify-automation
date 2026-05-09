from __future__ import annotations

from dataclasses import dataclass, field


CSV_COLUMNS = (
    "playlist",
    "list_url",
    "artist",
    "track",
    "spotify_link_type",
    "spotify_url",
    "spotify_title",
    "notes",
)


@dataclass(frozen=True)
class BuyMusicClubItem:
    source_id: str
    list_title: str
    list_url: str
    list_slug: str
    published_at: str
    artist: str
    track: str
    release_title: str
    bandcamp_type: str
    bandcamp_url: str
    label: str


@dataclass(frozen=True)
class BuyMusicClubList:
    title: str
    slug: str
    url: str
    published_at: str
    description: str
    source_url: str
    items: list[BuyMusicClubItem]


@dataclass
class SpotifyCandidate:
    candidate_id: str
    link_type: str
    spotify_id: str
    spotify_url: str
    title: str
    artists: str
    album_title: str
    release_date: str
    popularity: int | None
    total_tracks: int | None
    heuristic_score: float = 0.0
    query_hints: list[str] = field(default_factory=list)

    def llm_payload(self) -> dict[str, object]:
        payload: dict[str, object] = {
            "candidate_id": self.candidate_id,
            "link_type": self.link_type,
            "spotify_url": self.spotify_url,
            "title": self.title,
            "artists": self.artists,
            "heuristic_score": round(self.heuristic_score, 4),
        }
        if self.album_title:
            payload["album_title"] = self.album_title
        if self.release_date:
            payload["release_date"] = self.release_date
        if self.popularity is not None:
            payload["popularity"] = self.popularity
        if self.total_tracks is not None:
            payload["total_tracks"] = self.total_tracks
        if self.query_hints:
            payload["query_hints"] = self.query_hints
        return payload


@dataclass(frozen=True)
class MatchDecision:
    source_id: str
    decision: str
    selected_candidate_id: str | None
    confidence: float
    notes: str


@dataclass(frozen=True)
class SpotifyWebMatch:
    source_id: str
    decision: str
    link_type: str
    spotify_url: str
    spotify_title: str
    confidence: float
    notes: str


@dataclass(frozen=True)
class SpotifyEntry:
    playlist: str
    list_url: str
    artist: str
    track: str
    link_type: str
    spotify_url: str
    spotify_title: str
    notes: str

    @property
    def spotify_id(self) -> str:
        return self.spotify_url.rstrip("/").split("/")[-1].split("?")[0]

    def as_csv_row(self) -> dict[str, str]:
        return {
            "playlist": self.playlist,
            "list_url": self.list_url,
            "artist": self.artist,
            "track": self.track,
            "spotify_link_type": self.link_type,
            "spotify_url": self.spotify_url,
            "spotify_title": self.spotify_title,
            "notes": self.notes,
        }

    @classmethod
    def from_csv_row(cls, row: dict[str, str]) -> "SpotifyEntry":
        return cls(
            playlist=row["playlist"].strip(),
            list_url=row["list_url"].strip(),
            artist=row["artist"].strip(),
            track=row["track"].strip(),
            link_type=row["spotify_link_type"].strip(),
            spotify_url=row["spotify_url"].strip(),
            spotify_title=row["spotify_title"].strip(),
            notes=row["notes"].strip(),
        )
