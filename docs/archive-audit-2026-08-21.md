# Concrete Avalanche archive audit — 2026-08-21

This is a read-only audit checkpoint. It records what is known, what has been manually
reviewed against article context, and what still needs Spotify matching. No Spotify
library, playlist, or CSV writes were made during this audit.

## Full archive inventory

The audit covered all 109 published issues and all 59 archived Buy Music Club lists.
The source union contains:

- 714 Bandcamp occurrences representing 661 unique releases.
- 192 non-Bandcamp music-link occurrences representing 179 unique links.
- 184 Bandcamp occurrences already matched through the cumulative Spotify catalog.
- 1 article source item previously resolved directly by an agent.
- 503 unique Bandcamp gaps: 246 represented in Buy Music Club but unmatched in the
  Spotify catalog, and 257 found only in Substack articles.

The 503 gaps are candidates, not 503 confirmed omissions from the Spotify account.
The Buy Music Club subset is editorially in scope but still needs exact Spotify
matching. The Substack-only subset additionally needs article-context review because
older releases are sometimes embedded as history or comparison.

## Direct Spotify links

The articles contain 49 Spotify-link occurrences. After treating Spotify's `/embed/`
and public URLs as the same entity, they resolve to 29 unique Spotify entities:

- 24 albums or tracks.
- 3 artist pages.
- 1 playlist.
- 1 podcast episode.

Artist, playlist, and podcast links are navigation/context and are not library-save
candidates. The 24 albums and tracks were reviewed against their surrounding article
text and classified below.

### Verified recommendations (17)

| Issue | Spotify item | Type | Why it belongs |
| --- | --- | --- | --- |
| 2023-08-02 | [Pocari Sweet波卡利甜 — Tears in Rain（就像泪水消逝在雨中）](https://open.spotify.com/album/6nlLIph5HfbYSJ9UquhqVM) | album | Featured current EP. |
| 2023-07-05 | [也是福 — 疯了 (Crazy)](https://open.spotify.com/album/6anPhnFd80AX3n9vQbKC38) | album | Current solo album; explicitly recommended. |
| 2023-06-21 | [動物園釘子戶 — 動物園釘子戶Ⅱ](https://open.spotify.com/album/4rTW8Y7cZyDgzLV9xsNbrM) | album | Featured new album. |
| 2023-05-24 | [THE BOOTLEGS — 星加坡](https://open.spotify.com/album/7klFP8pzgzrOFnptn6ijYE) | album | Featured new LP. |
| 2023-05-24 | [夏之禹 — Young Fresh Chin II](https://open.spotify.com/album/6mtaqW1aC1xz4jecXxBM5X) | album | Explicitly identified as a new album. |
| 2023-04-26 | [mafmadmaf — 猫登天空 Vol.2 伸个懒腰](https://open.spotify.com/album/0txmUJLqVzktKUIUL6Ggg0) | album | New compilation; explicitly linked on Spotify. |
| 2023-03-01 | [The Shanghai Restoration Project — The Artist](https://open.spotify.com/track/12hN2JCgTf2oSP9XccNPbo) | track | New soundtrack song. |
| 2023-02-01 | [重塑雕像的权利 — THREE-BODY](https://open.spotify.com/track/4CwvnIh1vXtyjKdLYYiZtI) | track | New television theme. |
| 2023-02-01 | [Li Daiguo — Pilgrimage to the Realm of Deep Baby Sleep](https://open.spotify.com/album/4CUge5KVfy7UzG19kicngi) | album | Current album and explicit exit-music recommendation. |
| 2023-01-20 | [波激小丝 — 兔菌](https://open.spotify.com/track/26Y9112utDDp8SMIGtrR71) | track | Explicitly praised and embedded. |
| 2023-01-11 | [孤独的利里 — 最後的四重奏](https://open.spotify.com/album/4AbAZeq2zWgYUPHRqe6JTE) | album | New live album; described as worth a spin. |
| 2023-01-11 | [彭喜悦TingTing — 彭喜悦的待办事项](https://open.spotify.com/album/5NCQqhyYrNg6YCwM3AffO1) | album | Featured new album. |
| 2023-01-11 | [Various Artists — Mintone Records Autumn Special Mini Album: Whoa!](https://open.spotify.com/album/1yRUAmBGkJs0TwAD7foMkb) | album | Recommended recent compilation. |
| 2022-12-13 | [Frankfurt Helmet, AtomTM — Patch (AtomTM Remix)](https://open.spotify.com/track/4J2cHOPDzI5BPbflbbdpGK) | track | One of the issue's two explicit exit-music choices. |
| 2022-11-15 | [Various Artists — 去爱去哭去疑惑](https://open.spotify.com/album/2VJDxvrruFoiTGhrPRF6Gs) | album | Called a favourite recent release. |
| 2022-10-04 | [肖骏, Leah Dou — Somberton](https://open.spotify.com/track/2X9XKRfa3YDKk0fjQZ9XJn) | track | Track singled out while recommending its new album. |
| 2022-09-21 | [Lava Ox Sea — Concrete Avalanche](https://open.spotify.com/track/5ahfjdqG5KN5r37aHTlLSe) | track | Deliberate namesake exit-music recommendation. |

These are high-confidence historical repair candidates. Account state still needs to be
checked before calling them missing from the user's saved library: the existing OAuth
grant has library-write but not library-read permission. All 17 are, however, confirmed
absent from the `Concrete Avalanche` playlist, so they did not flow through this
automation.

### Context only (6)

| Issue | Spotify item | Reason to exclude |
| --- | --- | --- |
| 2023-07-05 | [也是福 — 也是蓝 (Also Blue)](https://open.spotify.com/album/2DRM74Pi43nASjSjiC4dNL) | Older collaboration offered as background for a new solo album. |
| 2023-06-07 | [Booji — Reserved](https://open.spotify.com/album/2VToJuAYwBvUGi3QJCCRWp) | 2009 release in a career retrospective. |
| 2023-03-29 | [P.K.14 — Whoever and Whoever](https://open.spotify.com/album/43cIRs15bo8m79frJfGZnk) | Older comparison for the featured Lygort release. |
| 2023-03-29 | [P.K.14 — White Paper](https://open.spotify.com/album/7jIllMzewzN0c9LV2PSBYy) | Older comparison for the featured Lygort release. |
| 2023-02-01 | [Re-TROS — Cut Off!](https://open.spotify.com/album/5kb3V5mtR3kap1KGvGnvxi) | Early record used as career history before the new THREE-BODY theme. |
| 2022-12-13 | [万能青年旅店 — 河北墨麒麟](https://open.spotify.com/track/4pKD4Yqa6TOC4kSw4APe8M) | Illustrates another band's influence; not presented as the issue's recommendation. |

### Judgment call (1)

| Issue | Spotify item | Why it remains a review item |
| --- | --- | --- |
| 2023-01-20 | [Li Daiguo — 李姝睿](https://open.spotify.com/album/4j9srVQSQqHBPbl2NE3wtc) | Included in a 2022 best-albums roundup inside the issue, rather than as a current featured release. It is editorially recommended, but whether retrospectives should backfill every listed album is a policy choice. |

## Audit behavior repaired

Spotify embed URLs such as `https://open.spotify.com/embed/album/…` and their public
`https://open.spotify.com/album/…` counterparts are now canonicalized as one entity.
This removes false duplicates from future archive counts.

Spotify also changed playlist rows from a `track` field to an `item` field. The old
parser therefore treated the existing playlist as empty. It now accepts both response
shapes, preventing future syncs from blindly re-adding every selected track. At audit
time, the playlist contained 1,980 entries representing 1,633 unique tracks: 347 entries
were duplicates. This audit did not remove or reorder any playlist entries. The three
tracks from the latest issue, including both YEHAIYAHAN/Tulipa Ruiz collaborations, are
present in the corrected playlist view.

## Remaining audit queue

The next bounded pass should resolve the 246 Buy Music Club releases against Spotify,
newest first. Those are already editorially in scope under the union policy. The 257
Substack-only Bandcamp releases then require section-by-section context classification,
followed by Spotify matching only for items classified as recommendations. The other
non-Bandcamp providers (Apple Music, YouTube, SoundCloud, NetEase, and QQ Music) remain a
separate context-review queue.
