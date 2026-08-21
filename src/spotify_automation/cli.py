from __future__ import annotations

import argparse
import csv
import json
import os
import re
import sys
from dataclasses import asdict
from pathlib import Path
from typing import Sequence

from spotipy.exceptions import SpotifyException

from spotify_automation.audit import run_archive_audit
from spotify_automation.buy_music_club import fetch_latest_list, fetch_list
from spotify_automation.catalog import entries_for_list, items_to_process, read_catalog, upsert_entries
from spotify_automation.matcher import (
    choose_matches_heuristically,
    collect_candidates,
    spotify_search_settings_summary,
)
from spotify_automation.models import BuyMusicClubItem, MatchDecision, SpotifyCandidate, SpotifyEntry
from spotify_automation.spotify import (
    DEFAULT_PLAYLIST_NAME,
    apply_entries_to_spotify,
    apply_entries_to_spotify_library,
    get_search_client,
    get_user_client,
)
from spotify_automation.substack import fetch_issue, fetch_latest_issue
from spotify_automation.web_page import fetch_web_page_list


ENV_PATH = Path(".env")
SPOTIFY_URL_PATTERN = re.compile(
    r"^https://open\.spotify\.com/(?:intl-[a-z]{2}/)?(?P<link_type>album|track)/"
    r"(?P<spotify_id>[A-Za-z0-9]+)(?:[/?#].*)?$"
)


def load_env_file(path: Path = ENV_PATH) -> None:
    if not path.exists():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            continue
        key, value = stripped.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


def _entry_from_decision(
    item: BuyMusicClubItem,
    decision: MatchDecision,
    candidate_lookup: dict[str, SpotifyCandidate],
) -> SpotifyEntry | None:
    if decision.decision != "match" or not decision.selected_candidate_id:
        return None
    candidate = candidate_lookup[decision.selected_candidate_id]
    return SpotifyEntry(
        playlist=item.list_title,
        list_url=item.list_url,
        artist=item.artist,
        track=item.track,
        link_type=candidate.link_type,
        spotify_url=candidate.spotify_url,
        spotify_title=candidate.title,
        notes=f"confidence={decision.confidence:.2f}; {decision.notes}",
    )


def _print_issue_summary(issue) -> None:
    print(f"Issue: {issue.title}")
    print(f"Published at: {issue.published_at}")
    print(f"Issue URL: {issue.url}")
    print(f"Extracted Bandcamp embeds: {len(issue.items)}")


def _print_match_preview(
    entries: list[SpotifyEntry],
    unmatched: list[tuple[BuyMusicClubItem, MatchDecision, list[SpotifyCandidate]]],
) -> None:
    if entries:
        print("\nMatched entries:")
        for entry in entries:
            print(f"  {entry.link_type:5} | {entry.artist} - {entry.track} -> {entry.spotify_url}")
    if unmatched:
        print("\nNeeds agent review / no confident match:")
        for item, decision, candidates in unmatched:
            print(f"  {item.artist} - {item.track} | {decision.notes}")
            print(f"    source: {item.bandcamp_url or item.list_url}")
            for candidate in candidates[:3]:
                print(
                    f"    candidate {candidate.heuristic_score:.3f} | {candidate.link_type:5} |"
                    f" {candidate.artists} - {candidate.title} -> {candidate.spotify_url}"
                )


def _candidate_subset(item: BuyMusicClubItem, candidates: list[SpotifyCandidate]) -> list[SpotifyCandidate]:
    if item.bandcamp_type != "album":
        return candidates
    album_candidates = [candidate for candidate in candidates if candidate.link_type == "album"]
    return album_candidates or candidates


def _match_with_spotify_api(
    items: list[BuyMusicClubItem],
) -> tuple[list[SpotifyEntry], list[tuple[BuyMusicClubItem, MatchDecision, list[SpotifyCandidate]]]]:
    print(f"Matching {len(items)} item(s) with Spotify API search; {spotify_search_settings_summary()}.")
    search_client = get_search_client()
    candidate_map: dict[str, list[SpotifyCandidate]] = {}
    rate_limit_note = ""

    for item in items:
        try:
            candidates = _candidate_subset(item, collect_candidates(search_client, item))
        except SpotifyException as error:
            if error.http_status == 429:
                retry_after = (error.headers or {}).get("Retry-After")
                rate_limit_note = "Spotify rate limit stopped candidate collection."
                if retry_after:
                    rate_limit_note += f" Retry-After={retry_after}s."
                print(f"  {rate_limit_note}")
                break
            print(f"  Spotify search failed for {item.artist} - {item.track}: {error}")
            candidates = []
        candidate_map[item.source_id] = candidates
        print(f"  Collected {len(candidates)} candidates for {item.artist} - {item.track}")

    decisions = choose_matches_heuristically(items, candidate_map)
    matched: list[SpotifyEntry] = []
    unmatched: list[tuple[BuyMusicClubItem, MatchDecision, list[SpotifyCandidate]]] = []
    for item in items:
        candidates = candidate_map.get(item.source_id, [])
        decision = decisions[item.source_id]
        if rate_limit_note and not candidates:
            decision = MatchDecision(item.source_id, "no_match", None, 0.0, rate_limit_note)
        lookup = {candidate.candidate_id: candidate for candidate in candidates}
        entry = _entry_from_decision(item, decision, lookup) if lookup else None
        if entry is None:
            unmatched.append((item, decision, candidates))
        else:
            matched.append(entry)
    return matched, unmatched


def _sync_issue(
    issue,
    *,
    dry_run: bool,
    force_rematch: bool,
    skip_spotify: bool,
    playlist_name: str,
    library_only: bool = False,
) -> int:
    catalog_entries = read_catalog()
    existing_for_issue = entries_for_list(catalog_entries, issue.url)
    pending_items = items_to_process(issue.items, catalog_entries, force_rematch=force_rematch)

    _print_issue_summary(issue)
    print(f"Already matched in CSV: {len(existing_for_issue)}")
    print(f"Items to process now: {len(pending_items)}")
    if not pending_items:
        print("Nothing new to do for this issue.")
        return 0

    matched_entries, unmatched = _match_with_spotify_api(pending_items)
    print(f"Matched successfully: {len(matched_entries)}")
    print(f"Unmatched / review needed: {len(unmatched)}")
    _print_match_preview(matched_entries, unmatched)

    if dry_run:
        print("\nDry run only: no CSV or Spotify changes were made.")
        return 0

    if matched_entries:
        added, updated = upsert_entries(matched_entries)
        print(f"\nCSV updated: {added} added, {updated} updated.")
    else:
        print("\nNo matched entries to write into the CSV.")

    if skip_spotify or not matched_entries:
        print("Skipping Spotify account sync.")
        return 0

    user_client = get_user_client()
    if library_only:
        summary = apply_entries_to_spotify_library(user_client, matched_entries)
        print(
            "\nSpotify library sync complete:"
            f" saved {summary['albums_saved']} albums,"
            f" added {summary['playlist_tracks_added']} playlist tracks."
        )
    else:
        summary = apply_entries_to_spotify(user_client, matched_entries, playlist_name=playlist_name)
        print(
            "\nSpotify sync complete:"
            f" saved {summary['albums_saved']} albums,"
            f" saved {summary['tracks_saved']} tracks,"
            f" added {summary['playlist_tracks_added']} new playlist tracks."
        )
    return 0


def command_latest_url(_args: argparse.Namespace) -> int:
    print(fetch_latest_issue().url)
    return 0


def command_latest_buy_music_url(_args: argparse.Namespace) -> int:
    print(fetch_latest_list().url)
    return 0


def command_smoke_test(_args: argparse.Namespace | None = None) -> int:
    issue = fetch_latest_issue()
    _print_issue_summary(issue)
    print("\nFirst three extracted releases:")
    for item in issue.items[:3]:
        print(f"  {item.artist} - {item.track}")
    return 0


def command_inspect_latest(args: argparse.Namespace) -> int:
    issue = fetch_latest_issue()
    if args.json:
        print(
            json.dumps(
                {
                    "issue": {
                        "title": issue.title,
                        "url": issue.url,
                        "published_at": issue.published_at,
                    },
                    "items": [asdict(item) for item in issue.items],
                    "music_urls": issue.music_urls,
                },
                ensure_ascii=False,
                indent=2,
            )
        )
    else:
        _print_issue_summary(issue)
        for item in issue.items:
            print(f"  {item.bandcamp_type:5} | {item.artist} - {item.track} | {item.bandcamp_url}")
        non_bandcamp_urls = [url for url in issue.music_urls if "bandcamp.com" not in url]
        if non_bandcamp_urls:
            print("\nOther music links requiring article-context review:")
            for url in non_bandcamp_urls:
                print(f"  {url}")
    return 0


def command_sync_latest(args: argparse.Namespace) -> int:
    return _sync_issue(
        fetch_latest_issue(),
        dry_run=args.dry_run,
        force_rematch=args.force_rematch,
        skip_spotify=args.skip_spotify,
        playlist_name=args.playlist_name or os.environ.get("SPOTIFY_PLAYLIST_NAME", DEFAULT_PLAYLIST_NAME),
    )


def command_sync_issue(args: argparse.Namespace) -> int:
    return _sync_issue(
        fetch_issue(args.url),
        dry_run=args.dry_run,
        force_rematch=args.force_rematch,
        skip_spotify=args.skip_spotify,
        playlist_name=args.playlist_name or os.environ.get("SPOTIFY_PLAYLIST_NAME", DEFAULT_PLAYLIST_NAME),
    )


def command_sync_list(args: argparse.Namespace) -> int:
    return _sync_issue(
        fetch_list(args.list_url),
        dry_run=args.dry_run,
        force_rematch=args.force_rematch,
        skip_spotify=args.skip_spotify,
        playlist_name=args.playlist_name or os.environ.get("SPOTIFY_PLAYLIST_NAME", DEFAULT_PLAYLIST_NAME),
    )


def command_sync_page(args: argparse.Namespace) -> int:
    return _sync_issue(
        fetch_web_page_list(args.url),
        dry_run=args.dry_run,
        force_rematch=args.force_rematch,
        skip_spotify=args.skip_spotify,
        playlist_name=args.playlist_name or os.environ.get("SPOTIFY_PLAYLIST_NAME", DEFAULT_PLAYLIST_NAME),
        library_only=args.library_only,
    )


def command_audit_archive(args: argparse.Namespace) -> int:
    records, music_links, summary = run_archive_audit()
    if args.format == "json":
        print(
            json.dumps(
                {
                    "summary": summary,
                    "records": [record.as_dict() for record in records],
                    "non_bandcamp_music_links": [link.as_dict() for link in music_links],
                },
                ensure_ascii=False,
                indent=2,
            )
        )
        return 0
    if args.format == "csv":
        writer = csv.DictWriter(sys.stdout, fieldnames=list(records[0].as_dict()) if records else [])
        if records:
            writer.writeheader()
            writer.writerows(record.as_dict() for record in records)
        return 0

    print(json.dumps(summary, ensure_ascii=False, indent=2))
    print("\nGaps by newest issue:")
    shown = 0
    for record in records:
        if record.status in {"matched_catalog", "agent_resolved"}:
            continue
        print(
            f"  {record.published_at[:10]} | {record.status:27} |"
            f" {record.artist} - {record.title}"
        )
        shown += 1
        if shown >= args.limit:
            break
    if music_links:
        print("\nNewest non-Bandcamp music links requiring article-context review:")
        for link in music_links[: args.limit]:
            print(f"  {link.published_at[:10]} | {link.provider:13} | {link.music_url}")
    return 0


def _canonical_spotify_url(value: str) -> tuple[str, str]:
    match = SPOTIFY_URL_PATTERN.match(value.strip())
    if not match:
        raise ValueError("--spotify-url must be an open.spotify.com album or track URL")
    link_type = match.group("link_type")
    return link_type, f"https://open.spotify.com/{link_type}/{match.group('spotify_id')}"


def command_record_match(args: argparse.Namespace) -> int:
    link_type, spotify_url = _canonical_spotify_url(args.spotify_url)
    notes = args.notes or "Agent-verified Spotify match."
    if args.source_id:
        notes = f"source_id={args.source_id}; {notes}"
    entry = SpotifyEntry(
        playlist=args.source_title,
        list_url=args.source_url,
        artist=args.artist,
        track=args.title,
        link_type=link_type,
        spotify_url=spotify_url,
        spotify_title=args.spotify_title or args.title,
        notes=notes,
    )
    added, updated = upsert_entries([entry])
    print(f"CSV updated: {added} added, {updated} updated.")
    if args.skip_spotify:
        return 0
    user_client = get_user_client()
    if args.library_only:
        summary = apply_entries_to_spotify_library(user_client, [entry])
    else:
        summary = apply_entries_to_spotify(
            user_client,
            [entry],
            playlist_name=args.playlist_name or os.environ.get("SPOTIFY_PLAYLIST_NAME", DEFAULT_PLAYLIST_NAME),
        )
    print(json.dumps(summary, sort_keys=True))
    return 0


def command_search(args: argparse.Namespace) -> int:
    limit = max(1, min(50, args.limit))
    item = BuyMusicClubItem(
        source_id="manual-search",
        list_title="Manual search",
        list_url="manual:search",
        list_slug="manual-search",
        published_at="",
        artist=args.artist,
        track=args.title,
        release_title=args.title if args.type in {"album", "any"} else "",
        bandcamp_type=args.type,
        bandcamp_url="",
        label="",
    )
    candidates = collect_candidates(get_search_client(), item, limit=limit)
    if args.type != "any":
        candidates = [candidate for candidate in candidates if candidate.link_type == args.type]
    for candidate in candidates[:limit]:
        print(
            f"{candidate.heuristic_score:.3f}\t{candidate.link_type}\t{candidate.artists}\t"
            f"{candidate.title}\t{candidate.spotify_url}"
        )
    return 0


def _add_sync_options(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--dry-run", action="store_true", help="Do not write the CSV or touch Spotify")
    parser.add_argument("--force-rematch", action="store_true", help="Reprocess catalogued items")
    parser.add_argument("--skip-spotify", action="store_true", help="Update the CSV without touching Spotify")
    parser.add_argument("--playlist-name", default=None, help="Spotify playlist to create/update")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Concrete Avalanche Spotify automation")
    subparsers = parser.add_subparsers(dest="command", required=True)

    latest_url = subparsers.add_parser("latest-url", help="Print the newest Concrete Avalanche Substack URL")
    latest_url.set_defaults(func=command_latest_url)

    latest_bmc = subparsers.add_parser("latest-buy-music-url", help="Print the newest Buy Music Club list URL")
    latest_bmc.set_defaults(func=command_latest_buy_music_url)

    smoke_test_parser = subparsers.add_parser("smoke-test", help="Fetch and parse the latest Substack issue")
    smoke_test_parser.set_defaults(func=command_smoke_test)

    inspect_latest = subparsers.add_parser(
        "inspect-latest",
        help="List releases extracted from the latest Substack issue",
    )
    inspect_latest.add_argument("--json", action="store_true", help="Emit structured JSON")
    inspect_latest.set_defaults(func=command_inspect_latest)

    sync_latest = subparsers.add_parser("sync-latest", help="Sync the newest Substack issue")
    _add_sync_options(sync_latest)
    sync_latest.set_defaults(func=command_sync_latest)

    sync_issue = subparsers.add_parser("sync-issue", help="Sync a specific Concrete Avalanche Substack issue")
    sync_issue.add_argument("--url", required=True, help="Substack issue URL or slug")
    _add_sync_options(sync_issue)
    sync_issue.set_defaults(func=command_sync_issue)

    sync_list = subparsers.add_parser("sync-list", help="Sync a legacy Buy Music Club list")
    sync_list.add_argument("--list-url", required=True, help="Buy Music Club list URL or slug")
    _add_sync_options(sync_list)
    sync_list.set_defaults(func=command_sync_list)

    sync_page = subparsers.add_parser("sync-page", help="Sync Bandcamp embeds from a web page")
    sync_page.add_argument("--url", required=True, help="Web page URL")
    sync_page.add_argument(
        "--library-only",
        action="store_true",
        help="Save releases without updating a playlist",
    )
    _add_sync_options(sync_page)
    sync_page.set_defaults(func=command_sync_page)

    audit_archive = subparsers.add_parser(
        "audit-archive",
        help="Compare every Substack issue with Buy Music Club and the catalog",
    )
    audit_archive.add_argument("--format", choices=("summary", "json", "csv"), default="summary")
    audit_archive.add_argument("--limit", type=int, default=30, help="Maximum gap rows in summary output")
    audit_archive.set_defaults(func=command_audit_archive)

    record_match = subparsers.add_parser(
        "record-match",
        help="Record an agent-verified Spotify match and sync it",
    )
    record_match.add_argument("--source-url", required=True)
    record_match.add_argument("--source-id", default="", help="Source item ID from inspect-latest")
    record_match.add_argument("--source-title", required=True)
    record_match.add_argument("--artist", required=True)
    record_match.add_argument("--title", required=True)
    record_match.add_argument("--spotify-url", required=True)
    record_match.add_argument("--spotify-title", default="")
    record_match.add_argument("--notes", default="")
    record_match.add_argument("--library-only", action="store_true")
    record_match.add_argument("--skip-spotify", action="store_true")
    record_match.add_argument("--playlist-name", default=None)
    record_match.set_defaults(func=command_record_match)

    search = subparsers.add_parser(
        "search",
        help="Show deterministic Spotify candidates for agent review",
    )
    search.add_argument("--artist", required=True)
    search.add_argument("--title", required=True)
    search.add_argument("--type", choices=("album", "track", "any"), default="any")
    search.add_argument("--limit", type=int, default=8)
    search.set_defaults(func=command_search)

    return parser


def main(argv: Sequence[str] | None = None) -> int:
    load_env_file()
    args = build_parser().parse_args(argv)
    return args.func(args)


def smoke_test() -> None:
    raise SystemExit(command_smoke_test())


if __name__ == "__main__":
    raise SystemExit(main())
