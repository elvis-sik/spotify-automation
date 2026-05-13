## Concrete Avalanche Spotify Automation

This project now supports the full flow for a new Concrete Avalanche issue:

1. Discover the newest Concrete Avalanche list on Buy Music Club.
2. Parse the structured artist/title entries from that list.
3. Ask GPT with web search to find the best Spotify album or track page for each item.
4. Validate the returned Spotify album/track URL format.
5. Upsert the results into the cumulative CSV.
6. Save the matched albums/tracks to your Spotify library and add their tracks to a `Concrete Avalanche` playlist without duplicating tracks already in the playlist.

It also has a separate arbitrary web-page workflow for blog posts or articles that list songs/albums. That flow extracts the music items from the page, finds matching Spotify album pages, and saves those albums to your Spotify library without adding anything to the `Concrete Avalanche` playlist.

The latest list visible during implementation on April 29, 2026 was `April 2026`, published on March 31, 2026:
<https://www.buymusic.club/list/concrete_avalanche-april-2026>

## Setup

1. Copy `.env.example` to `.env`.
2. Fill in:
   - `SPOTIPY_CLIENT_ID`
   - `SPOTIPY_CLIENT_SECRET`
   - `SPOTIPY_REDIRECT_URI`
   - `OPENAI_API_KEY`
3. Install dependencies:

```bash
make setup
```

The intended secrets flow is via 1Password CLI. The checked-in `.env.example` uses `op://...` references, and the `make` targets that need secrets run through `op run --env-file=.env -- ...`.

`OPENAI_MODEL` defaults to `gpt-5.5`, but you can override it in `.env` if you want a cheaper or different model.

OpenAI-backed Spotify matching runs one item at a time with bounded parallelism. For Buy Music Club issues, OpenAI misses are checked again with Spotify's API before the item is left for review. Tune OpenAI matching with:

```bash
SPOTIFY_AUTOMATION_MATCH_CONCURRENCY=3
SPOTIFY_AUTOMATION_MATCH_RETRIES=3
SPOTIFY_AUTOMATION_SEARCH_MARKETS=US,BR,CA,GB,HK,TW,JP,SG,AU
```

## Usage

Quick check:

```bash
make smoke-test
```

Print the latest Buy Music Club URL:

```bash
make latest-url
```

Preview the latest issue without writing the CSV or touching Spotify:

```bash
make sync-latest-dry-run
```

Do the real run:

```bash
make run
```

Run a specific list manually:

```bash
make sync-list LIST_URL=https://www.buymusic.club/list/concrete_avalanche-april-2026
```

Preview an arbitrary web page without writing the CSV or touching Spotify:

```bash
make sync-page-dry-run PAGE_URL=https://example.com/blog/music-list
```

Sync an arbitrary web page for real:

```bash
make sync-page PAGE_URL=https://example.com/blog/music-list
```

The equivalent raw CLI is:

```bash
uv run spotify-automation sync-page --url https://example.com/blog/music-list
```

## Notes on Matching

Spotify sometimes has several believable matches for the same mention: original track, single, EP, album version, live take, remix, compilation appearance, and so on. By default, this tool lets GPT search the web directly for real `open.spotify.com` album and track pages, then stores the chosen URL, confidence score, and a short note in the CSV.

If you ever want to bypass GPT and use the older Spotify API shortlist + heuristic fallback instead:

```bash
uv run spotify-automation sync-latest --skip-openai
```

If you want to re-evaluate items that are already in the CSV:

```bash
uv run spotify-automation sync-latest --force-rematch
```
