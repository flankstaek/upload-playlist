# Roadmap

Iterative plan. Ordered roughly by priority and dependency — earlier items unblock later ones.

## Now: verify the live hook

**Status:** pending real-world test.

We need to confirm that `upload_finished_notification` actually fires and writes a valid entry to the playlist when another Soulseek user finishes downloading an audio file. Until we see one real capture we haven't proven the plugin works end to end.

- [ ] Leave plugin enabled, wait for organic upload
- [ ] Confirm entry appears in `~/soulseek_uploads.m3u`
- [ ] Confirm the `real_path` in the entry actually plays in a media player

## Next: own our history (persistent log)

**Why:** `uploads.json(.old)` is rolling state, not a log. Nicotine+ overwrites it on rotation and historical data is lost. To support real dedup, stats, re-exports, or richer playlists, the plugin needs to own its own store.

- [ ] Add a plugin-owned JSON log file (e.g. `upload_playlist_history.json` next to the M3U, or in the plugin's config dir)
- [ ] Write a structured record on every `upload_finished_notification`: timestamp, user, virtual_path, real_path, file size
- [ ] On `init()`, if the M3U is missing but the history JSON exists, rebuild the M3U from the JSON (the JSON becomes the source of truth)
- [ ] Keep the `uploads.json` backfill as a one-time seed for new installs

Once this lands, all subsequent features operate against the owned log rather than Nicotine+'s rolling state.

## Then: dedup

**Why:** repeat uploads of the same file (by the same or different users) currently stack up in the M3U. User wants a clean playlist without duplicate entries.

Open design questions:
- Dedup key: by `real_path` alone? Or `(real_path, user)`? The former gives "one entry per file ever uploaded"; the latter gives "one entry per file per downloader."
- What about re-running backfill? Currently it happily writes duplicates. Should dedup be enforced at write time (in-memory set) or at read time (rebuild M3U from history JSON)?
- Does the user want the most recent upload to "bubble up" in the playlist, or stay in its original position?

Leaning toward: rebuild-from-history-on-dedup. Once the history JSON exists, the M3U becomes a derived artifact that can be regenerated with any dedup strategy the user picks.

## Then: album ordering

**Why:** M3U entries currently land in upload chronological order. User wants tracks grouped by album so the playlist plays as cohesive listens.

Open design questions:
- Group by parent directory of `real_path`? (Usually accurate — Soulseek shares are folder-per-album.)
- Within a group, sort by filename (which usually embeds track number) or by metadata (requires parsing tags — extra dependency)?
- Mix ordering strategies via a setting: `chronological | by-album | by-artist-album`?
- Does grouping break the "live append" model? Yes — a new upload in an old album would need to be inserted, not appended. This means regenerating the whole M3U on each write, which is fine at these file sizes but is a departure from the append-only model.

Depends on: persistent history (so we can regenerate).

## Then: more commands

Candidates, in no particular order:
- `/playlist-clear` — empty the playlist and the underlying history log (with confirmation prompt)
- `/playlist-stats` — counts by user, by file type, by album
- `/playlist-open` — launch the playlist in the default player (platform-dependent)
- `/playlist-reload` — re-generate M3U from the history log (useful after changing ordering/dedup settings)

## Later: nice-to-haves

- **Per-user playlists.** Split into `uploads_by_<username>.m3u` files in addition to the master.
- **Duration in `#EXTINF`.** Currently `-1` (unknown). Parsing duration requires reading file headers — could use stdlib `wave`, `aifc` for limited formats, or punt.
- **Richer display names.** Parse metadata tags for `Artist - Title`. Needs stdlib-only parser (no mutagen, since we can't install packages into Nicotine+).
- **Playlist rotation.** Cap the M3U at N entries or bytes, archive older entries. Probably not needed at typical usage.
- **Multiple output formats.** Alongside `.m3u`, optionally write `.m3u8` (UTF-8 explicit) or `.pls`.

## Not doing

- **Parsing `.dbn` share databases** — binary format, fragile, no upside over our own log.
- **Watching `uploads.json` in real time** — the live hook already gives us the event cleanly; no reason to scrape state.
- **Third-party deps** (mutagen, etc.) — Nicotine+ can't install packages, stdlib only.
- **GUI settings beyond what Nicotine+ supports** — we get bool/int/float/string/list/radio/dropdown and chat commands. No custom widgets, no action buttons.
