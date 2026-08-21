# Concrete Avalanche Spotify Automation

This project keeps a Spotify library and playlist in sync with Jake Newby's
[Concrete Avalanche](https://jakenewby.substack.com/) newsletter.

The program uses the deduplicated union of the newest Substack article and newest Buy
Music Club list: a release present in either source is included. The Substack prose is
the source of editorial context, while Buy Music Club may contribute releases absent
from the article. The program searches Spotify deterministically, records confident
matches in the cumulative CSV, saves them to the Spotify library, and adds their tracks
to the `Concrete Avalanche` playlist.

The library policy is container-only: album matches save the album, while track matches
resolve to the best available containing release in the order album, EP, then single.
The automation never adds individual tracks to Liked Songs. A track recommendation still
adds only that track to the playlist; resolving its library container does not add the
whole album to the playlist.

Ambiguous matches and recommendations linked through something other than Bandcamp need
agent review. The bundled repo skill at
`.agents/skills/concrete-avalanche-spotify/SKILL.md` describes that workflow. The program
does not call an LLM or require an OpenAI API key.

## Setup

1. Copy `.env.example` to `.env`.
2. Fill in `SPOTIPY_CLIENT_ID`, `SPOTIPY_CLIENT_SECRET`, and
   `SPOTIPY_REDIRECT_URI`.
3. Install dependencies:

```bash
make setup
```

The intended secrets flow is through the 1Password CLI. The checked-in example uses
placeholder `op://` references, and commands that need Spotify credentials run through
`op run --env-file=.env -- ...`.

## Routine workflow

Inspect the latest article first:

```bash
make latest-url
make inspect-latest
```

Preview deterministic Spotify matches without changing the CSV or Spotify:

```bash
make sync-latest-dry-run
```

After reviewing the article and the proposed matches, sync it:

```bash
make run
```

For a specific Substack article:

```bash
make sync-issue ISSUE_URL=https://jakenewby.substack.com/p/example-slug
```

For an older Buy Music Club list:

```bash
make sync-list LIST_URL=https://www.buymusic.club/list/concrete_avalanche-example
```

To compare every archived Substack issue against Buy Music Club and the cumulative
Spotify catalog:

```bash
make audit-archive
uv run spotify-automation audit-archive --format csv > archive-audit.csv
```

To remove repeated playlist occurrences while keeping the first occurrence and its
position:

```bash
op run --env-file=.env -- uv run spotify-automation dedupe-playlist
```

## Matching and agent review

Spotify can contain several plausible versions of a release: the original, a remix, a
live take, a compilation appearance, or a reissue. The automatic matcher deliberately
accepts only high-scoring artist/title results. Tune its behavior with:

```bash
SPOTIFY_AUTOMATION_SEARCH_MARKETS=BR
SPOTIFY_AUTOMATION_MAX_SEARCH_REQUESTS_PER_ITEM=8
SPOTIFY_AUTOMATION_AUTO_MATCH_THRESHOLD=0.90
```

Use `record-match` after an agent has verified an ambiguous Spotify URL:

```bash
op run --env-file=.env -- uv run spotify-automation search \
  --artist "Artist" --title "Release"
```

Then record the verified result:

```bash
op run --env-file=.env -- uv run spotify-automation record-match \
  --source-url https://jakenewby.substack.com/p/example-slug \
  --source-id SOURCE_ID_FROM_INSPECT \
  --source-title "Issue title" \
  --artist "Artist" \
  --title "Release" \
  --spotify-url https://open.spotify.com/album/EXAMPLE
```

The command records the match and performs the normal Spotify sync. Add
`--skip-spotify` to update only the CSV.

## Other workflows

`sync-page` deterministically extracts Bandcamp embeds from another web page:

```bash
make sync-page-dry-run PAGE_URL=https://example.com/music-article
make sync-page PAGE_URL=https://example.com/music-article
```

The separate Tree of Life playlist script also uses Spotify API search only:

```bash
make tree-of-life-playlist-dry-run
make tree-of-life-playlist
```
