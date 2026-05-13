from __future__ import annotations

import argparse
import os
import re
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from threading import Lock
from typing import Sequence

from openai import RateLimitError

from spotify_automation.buy_music_club import BUY_MUSIC_CLUB_USER_URL, fetch_latest_list, fetch_list
from spotify_automation.catalog import entries_for_list, items_to_process, read_catalog, upsert_entries
from spotify_automation.matcher import (
    DEFAULT_OPENAI_MODEL,
    choose_album_matches_with_openai,
    choose_matches_heuristically,
    choose_matches_with_openai,
    collect_candidates,
)
from spotify_automation.models import (
    BuyMusicClubItem,
    MatchDecision,
    SpotifyCandidate,
    SpotifyEntry,
    SpotifyWebMatch,
)
from spotify_automation.spotify import (
    DEFAULT_PLAYLIST_NAME,
    apply_entries_to_spotify,
    apply_entries_to_spotify_library,
    get_search_client,
    get_user_client,
)
from spotify_automation.web_page import fetch_web_page_list


ENV_PATH = Path(".env")
DEFAULT_MATCH_CONCURRENCY = 3
DEFAULT_MATCH_RETRIES = 3
RETRY_AFTER_PATTERN = re.compile(r"try again in ([0-9.]+)s", re.IGNORECASE)


def load_env_file(path: Path = ENV_PATH) -> None:
    if not path.exists():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            continue
        key, value = stripped.split("=", 1)
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        os.environ.setdefault(key, value)


def _env_int(name: str, default: int, *, minimum: int = 1, maximum: int | None = None) -> int:
    raw_value = os.environ.get(name)
    if raw_value is None:
        return default
    try:
        value = int(raw_value)
    except ValueError:
        print(f"Ignoring invalid {name}={raw_value!r}; using {default}.")
        return default
    value = max(minimum, value)
    if maximum is not None:
        value = min(maximum, value)
    return value


def _entry_from_decision(
    item: BuyMusicClubItem,
    decision: MatchDecision,
    candidate_lookup: dict[str, SpotifyCandidate],
) -> SpotifyEntry | None:
    if decision.decision != "match" or not decision.selected_candidate_id:
        return None
    candidate = candidate_lookup[decision.selected_candidate_id]
    notes = f"confidence={decision.confidence:.2f}; {decision.notes}"
    return SpotifyEntry(
        playlist=item.list_title,
        list_url=item.list_url,
        artist=item.artist,
        track=item.track,
        link_type=candidate.link_type,
        spotify_url=candidate.spotify_url,
        spotify_title=candidate.title,
        notes=notes,
    )


def _entry_from_web_match(item: BuyMusicClubItem, decision: SpotifyWebMatch) -> SpotifyEntry | None:
    if decision.decision != "match" or not decision.spotify_url:
        return None
    notes = f"confidence={decision.confidence:.2f}; {decision.notes}"
    return SpotifyEntry(
        playlist=item.list_title,
        list_url=item.list_url,
        artist=item.artist,
        track=item.track,
        link_type=decision.link_type,
        spotify_url=decision.spotify_url,
        spotify_title=decision.spotify_title,
        notes=notes,
    )


def _print_issue_summary(issue) -> None:
    print(f"Issue: {issue.title}")
    print(f"Published at: {issue.published_at}")
    print(f"List URL: {issue.url}")
    print(f"Source profile: {BUY_MUSIC_CLUB_USER_URL}")
    print(f"Items in issue: {len(issue.items)}")


def _print_page_summary(page) -> None:
    print(f"Page: {page.title}")
    print(f"URL: {page.url}")
    print(f"Extracted music items: {len(page.items)}")


def _print_match_preview(
    entries: list[SpotifyEntry],
    unmatched: list[tuple[BuyMusicClubItem, MatchDecision | SpotifyWebMatch]],
) -> None:
    if entries:
        print("\nMatched entries:")
        for entry in entries:
            print(f"  {entry.link_type:5} | {entry.artist} - {entry.track} -> {entry.spotify_url}")
    if unmatched:
        print("\nNeeds review / no match:")
        for item, decision in unmatched:
            print(f"  {item.artist} - {item.track} | {decision.notes}")


def _rate_limit_delay(error: RateLimitError, attempt_index: int) -> float:
    match = RETRY_AFTER_PATTERN.search(str(error))
    if match:
        return float(match.group(1)) + 1.0
    return min(60.0, 2.0 ** attempt_index)


def _no_match_decision(item: BuyMusicClubItem, notes: str) -> SpotifyWebMatch:
    return SpotifyWebMatch(
        source_id=item.source_id,
        decision="no_match",
        link_type="",
        spotify_url="",
        spotify_title="",
        confidence=0.0,
        notes=notes,
    )


def _match_item_with_retries(
    item: BuyMusicClubItem,
    *,
    model: str,
    retries: int,
    print_lock: Lock,
    album_only: bool,
) -> tuple[SpotifyWebMatch, int]:
    match_label = "Spotify album" if album_only else "Spotify"
    match_function = choose_album_matches_with_openai if album_only else choose_matches_with_openai
    total_attempts = retries + 1
    for attempt_index in range(total_attempts):
        try:
            decisions = match_function([item], model=model)
            return decisions[item.source_id], attempt_index + 1
        except RateLimitError as error:
            if attempt_index >= retries:
                return (
                    _no_match_decision(
                        item,
                        f"OpenAI rate limit persisted after {total_attempts} attempts: {error}",
                    ),
                    attempt_index + 1,
                )
            delay = _rate_limit_delay(error, attempt_index)
            with print_lock:
                print(
                    f"  rate limited | retry {attempt_index + 1}/{retries}"
                    f" in {delay:.1f}s | {item.artist} - {item.track}",
                    flush=True,
                )
            time.sleep(delay)
        except Exception as error:
            return (
                _no_match_decision(item, f"{match_label} matching failed for this item: {error}"),
                attempt_index + 1,
            )

    return _no_match_decision(item, f"{match_label} matching failed unexpectedly."), total_attempts


def _match_items_with_openai(
    items: list[BuyMusicClubItem],
    *,
    model: str,
    album_only: bool,
) -> dict[str, SpotifyWebMatch]:
    concurrency = _env_int(
        "SPOTIFY_AUTOMATION_MATCH_CONCURRENCY",
        DEFAULT_MATCH_CONCURRENCY,
        minimum=1,
        maximum=len(items),
    )
    retries = _env_int("SPOTIFY_AUTOMATION_MATCH_RETRIES", DEFAULT_MATCH_RETRIES, minimum=0)
    target = "Spotify album pages" if album_only else "Spotify album/track pages"
    print(
        f"Matching {len(items)} item(s) against {target} with {model};"
        f" concurrency={concurrency}, retries={retries}.",
        flush=True,
    )

    print_lock = Lock()
    decisions: dict[str, SpotifyWebMatch] = {}
    completed = 0

    with ThreadPoolExecutor(max_workers=concurrency) as executor:
        future_map = {
            executor.submit(
                _match_item_with_retries,
                item,
                model=model,
                retries=retries,
                print_lock=print_lock,
                album_only=album_only,
            ): item
            for item in items
        }

        for future in as_completed(future_map):
            item = future_map[future]
            completed += 1
            try:
                decision, attempts = future.result()
            except Exception as error:
                decision = _no_match_decision(item, f"Spotify album matching crashed for this item: {error}")
                attempts = 1

            decisions[item.source_id] = decision
            retry_note = f" after {attempts} attempts" if attempts > 1 else ""
            with print_lock:
                if decision.decision == "match":
                    print(
                        f"[{completed:>2}/{len(items)}] matched{retry_note} |"
                        f" {item.artist} - {item.track} -> {decision.spotify_url}",
                        flush=True,
                    )
                else:
                    print(
                        f"[{completed:>2}/{len(items)}] no match{retry_note} |"
                        f" {item.artist} - {item.track} | {decision.notes}",
                        flush=True,
                    )

    return decisions


def _match_issue_items_to_spotify(
    items: list[BuyMusicClubItem],
    *,
    model: str,
) -> dict[str, SpotifyWebMatch]:
    return _match_items_with_openai(items, model=model, album_only=False)


def _match_page_items_to_albums(
    items: list[BuyMusicClubItem],
    *,
    model: str,
) -> dict[str, SpotifyWebMatch]:
    return _match_items_with_openai(items, model=model, album_only=True)


def _sync_issue(
    issue,
    *,
    dry_run: bool,
    force_rematch: bool,
    skip_openai: bool,
    skip_spotify: bool,
    playlist_name: str,
    model: str,
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

    matched_entries: list[SpotifyEntry] = []
    unmatched: list[tuple[BuyMusicClubItem, MatchDecision | SpotifyWebMatch]] = []

    if skip_openai:
        search_client = get_search_client()
        candidate_map: dict[str, list[SpotifyCandidate]] = {}
        for item in pending_items:
            candidates = collect_candidates(search_client, item)
            candidate_map[item.source_id] = candidates
            print(f"  Collected {len(candidates)} Spotify candidates for {item.artist} - {item.track}")

        decisions = choose_matches_heuristically(pending_items, candidate_map)
        for item in pending_items:
            candidates = {candidate.candidate_id: candidate for candidate in candidate_map.get(item.source_id, [])}
            decision = decisions[item.source_id]
            entry = _entry_from_decision(item, decision, candidates) if candidates else None
            if entry is None:
                unmatched.append((item, decision))
                continue
            matched_entries.append(entry)
    else:
        web_decisions = _match_issue_items_to_spotify(pending_items, model=model)
        for item in pending_items:
            decision = web_decisions[item.source_id]
            entry = _entry_from_web_match(item, decision)
            if entry is None:
                unmatched.append((item, decision))
                continue
            matched_entries.append(entry)

    print(f"Matched successfully: {len(matched_entries)}")
    print(f"Unmatched / review needed: {len(unmatched)}")
    _print_match_preview(matched_entries, unmatched)

    if dry_run:
        print("\nDry run only: no CSV changes and no Spotify library/playlist changes were made.")
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
    summary = apply_entries_to_spotify(user_client, matched_entries, playlist_name=playlist_name)
    print(
        "\nSpotify sync complete:"
        f" saved {summary['albums_saved']} albums,"
        f" saved {summary['tracks_saved']} tracks,"
        f" added {summary['playlist_tracks_added']} new playlist tracks."
    )
    return 0


def _sync_web_page(
    page,
    *,
    dry_run: bool,
    force_rematch: bool,
    skip_spotify: bool,
    model: str,
) -> int:
    catalog_entries = read_catalog()
    existing_for_page = entries_for_list(catalog_entries, page.url)
    pending_items = items_to_process(page.items, catalog_entries, force_rematch=force_rematch)

    _print_page_summary(page)
    print(f"Already matched in CSV: {len(existing_for_page)}")
    print(f"Items to process now: {len(pending_items)}")

    if not pending_items:
        print("Nothing new to do for this page.")
        return 0

    matched_entries: list[SpotifyEntry] = []
    unmatched: list[tuple[BuyMusicClubItem, SpotifyWebMatch]] = []

    web_decisions = _match_page_items_to_albums(pending_items, model=model)
    for item in pending_items:
        decision = web_decisions[item.source_id]
        entry = _entry_from_web_match(item, decision)
        if entry is None:
            unmatched.append((item, decision))
            continue
        matched_entries.append(entry)

    print(f"Matched successfully: {len(matched_entries)}")
    print(f"Unmatched / review needed: {len(unmatched)}")
    _print_match_preview(matched_entries, unmatched)

    if dry_run:
        print("\nDry run only: no CSV changes and no Spotify library changes were made.")
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
    summary = apply_entries_to_spotify_library(user_client, matched_entries)
    print(
        "\nSpotify library sync complete:"
        f" saved {summary['albums_saved']} albums,"
        f" added {summary['playlist_tracks_added']} playlist tracks."
    )
    return 0


def command_latest_url(_args: argparse.Namespace) -> int:
    load_env_file()
    issue = fetch_latest_list()
    print(issue.url)
    return 0


def command_smoke_test(_args: argparse.Namespace | None = None) -> int:
    load_env_file()
    issue = fetch_latest_list()
    _print_issue_summary(issue)
    print("\nFirst three items:")
    for item in issue.items[:3]:
        print(f"  {item.artist} - {item.track}")
    return 0


def command_sync_latest(args: argparse.Namespace) -> int:
    load_env_file()
    issue = fetch_latest_list()
    return _sync_issue(
        issue,
        dry_run=args.dry_run,
        force_rematch=args.force_rematch,
        skip_openai=args.skip_openai,
        skip_spotify=args.skip_spotify,
        playlist_name=args.playlist_name or os.environ.get("SPOTIFY_PLAYLIST_NAME", DEFAULT_PLAYLIST_NAME),
        model=args.model or os.environ.get("OPENAI_MODEL", DEFAULT_OPENAI_MODEL),
    )


def command_sync_list(args: argparse.Namespace) -> int:
    load_env_file()
    issue = fetch_list(args.list_url)
    return _sync_issue(
        issue,
        dry_run=args.dry_run,
        force_rematch=args.force_rematch,
        skip_openai=args.skip_openai,
        skip_spotify=args.skip_spotify,
        playlist_name=args.playlist_name or os.environ.get("SPOTIFY_PLAYLIST_NAME", DEFAULT_PLAYLIST_NAME),
        model=args.model or os.environ.get("OPENAI_MODEL", DEFAULT_OPENAI_MODEL),
    )


def command_sync_page(args: argparse.Namespace) -> int:
    load_env_file()
    model = args.model or os.environ.get("OPENAI_MODEL", DEFAULT_OPENAI_MODEL)
    page = fetch_web_page_list(args.url, model=model)
    return _sync_web_page(
        page,
        dry_run=args.dry_run,
        force_rematch=args.force_rematch,
        skip_spotify=args.skip_spotify,
        model=model,
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Concrete Avalanche Spotify automation")
    subparsers = parser.add_subparsers(dest="command", required=True)

    latest_url_parser = subparsers.add_parser("latest-url", help="Print the newest Concrete Avalanche Buy Music Club URL")
    latest_url_parser.set_defaults(func=command_latest_url)

    smoke_test_parser = subparsers.add_parser("smoke-test", help="Fetch the latest issue and print a quick summary")
    smoke_test_parser.set_defaults(func=command_smoke_test)

    for command_name, help_text in (
        ("sync-latest", "Match the newest Buy Music Club list and sync it to Spotify"),
        ("sync-list", "Match a specific Buy Music Club list URL and sync it to Spotify"),
    ):
        subparser = subparsers.add_parser(command_name, help=help_text)
        if command_name == "sync-list":
            subparser.add_argument("--list-url", required=True, help="Buy Music Club list URL or slug")
        subparser.add_argument("--dry-run", action="store_true", help="Do not write the CSV or touch your Spotify account")
        subparser.add_argument("--force-rematch", action="store_true", help="Reprocess items even if they already exist in the CSV")
        subparser.add_argument(
            "--skip-openai",
            action="store_true",
            help="Use the old Spotify API shortlist + heuristic fallback instead of GPT web search",
        )
        subparser.add_argument("--skip-spotify", action="store_true", help="Update the CSV but do not save anything to Spotify")
        subparser.add_argument(
            "--playlist-name",
            default=None,
            help="Spotify playlist name to create/update",
        )
        subparser.add_argument(
            "--model",
            default=None,
            help="OpenAI model for Spotify matching",
        )
        subparser.set_defaults(func=command_sync_latest if command_name == "sync-latest" else command_sync_list)

    sync_page_parser = subparsers.add_parser(
        "sync-page",
        help="Extract music from an arbitrary web page and save matched albums to your Spotify library",
    )
    sync_page_parser.add_argument("--url", required=True, help="Web page URL containing songs or albums")
    sync_page_parser.add_argument("--dry-run", action="store_true", help="Do not write the CSV or touch your Spotify account")
    sync_page_parser.add_argument("--force-rematch", action="store_true", help="Reprocess items even if they already exist in the CSV")
    sync_page_parser.add_argument("--skip-spotify", action="store_true", help="Update the CSV but do not save anything to Spotify")
    sync_page_parser.add_argument(
        "--model",
        default=None,
        help="OpenAI model for page extraction and Spotify matching",
    )
    sync_page_parser.set_defaults(func=command_sync_page)

    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    return args.func(args)


def smoke_test() -> None:
    raise SystemExit(command_smoke_test())


if __name__ == "__main__":
    raise SystemExit(main())
