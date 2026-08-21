---
name: concrete-avalanche-spotify
description: Operate and audit this repository's Concrete Avalanche Substack-to-Spotify workflow. Use when the user asks to process a new Concrete Avalanche issue, repair missing recommendations, audit the archive, sync the Spotify playlist/library, or verify a Spotify match.
---

# Concrete Avalanche Spotify

Use the union of the latest Substack article and latest Buy Music Club list. If a release
appears in either source, include it for matching and review. Use the Substack prose as
the authoritative source for editorial context, such as whether an embed is a current
recommendation or historical background.

## Latest issue workflow

1. From the repository root, run `uv run spotify-automation inspect-latest --json`. It
   reports the Substack count, Buy Music Club count, and deduplicated union count.
2. Open and read the full issue. The parser reliably extracts Bandcamp embeds, but the
   article may also contain Spotify, Apple Music, YouTube, SoundCloud, or plain-text
   recommendations.
3. Distinguish featured recommendations from older releases embedded only as context.
   Do not add every embed blindly.
4. Preview automatic matches with
   `op run --env-file=.env -- uv run spotify-automation sync-latest --dry-run`.
5. Verify each proposed Spotify result against the article. Prefer the exact release and
   artist. Reject remixes, live versions, covers, and compilations unless the article
   identifies that version.
6. When the user has asked for the real sync, run the same command without `--dry-run`.
7. Resolve remaining items by finding a canonical `open.spotify.com/album/...` or
   `open.spotify.com/track/...` URL. Use `search --artist "ARTIST" --title "TITLE"`
   for a Spotify API shortlist, then use `record-match`. Quote every argument.
8. Review the CSV diff and the command's Spotify summary before reporting completion.

Use `op run --env-file=.env --` at the process boundary for commands requiring Spotify
credentials. Never print or inspect `.env` values.

## Archive repair

Run `uv run spotify-automation audit-archive --format summary` first. Use JSON or CSV for
structured investigation. Review newest issues first and group work into bounded batches.

The audit statuses mean:

- `matched_catalog`: the article embed maps to a Buy Music Club row already recorded.
- `agent_resolved`: an agent recorded one or more Spotify tracks for this exact article
  source item.
- `unmatched_catalog`: Buy Music Club contains it, but the CSV has no Spotify match.
- `absent_from_buy_music_club`: the article has an embed omitted from Buy Music Club.

An embed can be historical context rather than a current recommendation, and fuzzy source
matching can be wrong. Read its article context before changing Spotify. Deduplicate the
same release across issues. Do not bulk-add an entire archive merely because the audit
reports a gap; make only verified repairs authorized by the user.

For an exact past issue use `sync-issue --url URL --dry-run`, then perform the real run
only after review. For a verified manual match, use:

```bash
op run --env-file=.env -- uv run spotify-automation record-match \
  --source-url "ISSUE_URL" \
  --source-id "SOURCE_ID_FROM_INSPECT" \
  --source-title "ISSUE_TITLE" \
  --artist "ARTIST" \
  --title "RELEASE" \
  --spotify-url "SPOTIFY_URL" \
  --notes "Agent-verified from the Substack article."
```

Reuse the same source ID for multiple Spotify tracks belonging to one source release. This
marks the source release resolved while preserving every verified track in the CSV.

## Safety

Spotify writes and CSV updates are external/material changes. Run them only when the user
has requested a sync or repair. Dry runs and audits are safe defaults for inspection.
