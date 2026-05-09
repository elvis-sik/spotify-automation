from __future__ import annotations

import json
import re
import unicodedata
from difflib import SequenceMatcher


NEXT_DATA_PATTERN = re.compile(
    r'<script id="__NEXT_DATA__" type="application/json">(.*?)</script>',
    re.DOTALL,
)


def extract_next_data(html: str) -> dict[str, object]:
    match = NEXT_DATA_PATTERN.search(html)
    if not match:
        raise RuntimeError("Could not find __NEXT_DATA__ JSON on the Buy Music Club page.")
    return json.loads(match.group(1))


def normalize_text(value: str) -> str:
    normalized = unicodedata.normalize("NFKC", value or "").lower()
    cleaned = "".join(character if character.isalnum() else " " for character in normalized)
    return " ".join(cleaned.split())


def similarity(left: str, right: str) -> float:
    left_normalized = normalize_text(left)
    right_normalized = normalize_text(right)
    if not left_normalized or not right_normalized:
        return 0.0
    return SequenceMatcher(None, left_normalized, right_normalized).ratio()


def split_artists(value: str) -> list[str]:
    normalized = (
        value.replace(" feat. ", ",")
        .replace(" feat ", ",")
        .replace(" ft. ", ",")
        .replace(" ft ", ",")
        .replace(" & ", ",")
        .replace(" and ", ",")
        .replace("，", ",")
        .replace("、", ",")
    )
    parts = [part.strip() for part in normalized.split(",")]
    return [part for part in parts if part]


def artist_similarity(source: str, candidate: str) -> float:
    overall = similarity(source, candidate)
    source_parts = split_artists(source)
    candidate_parts = split_artists(candidate)
    if not source_parts or not candidate_parts:
        return overall
    best_part = 0.0
    for source_part in source_parts:
        for candidate_part in candidate_parts:
            best_part = max(best_part, similarity(source_part, candidate_part))
    return max(overall, best_part)


def clamp_confidence(value: float | int | str | None) -> float:
    if value is None:
        return 0.0
    try:
        numeric = float(value)
    except (TypeError, ValueError):
        return 0.0
    return max(0.0, min(1.0, numeric))


def strip_markdown_fences(value: str) -> str:
    text = value.strip()
    if text.startswith("```"):
        text = re.sub(r"^```[a-zA-Z0-9_-]*\n?", "", text)
        text = re.sub(r"\n?```$", "", text)
    return text.strip()


def compact_whitespace(value: str) -> str:
    return " ".join((value or "").split())


def dedupe_strings(values: list[str]) -> list[str]:
    seen: set[str] = set()
    deduped: list[str] = []
    for value in values:
        if not value or value in seen:
            continue
        seen.add(value)
        deduped.append(value)
    return deduped
