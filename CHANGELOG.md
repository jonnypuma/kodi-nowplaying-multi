# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [3.4.1] - 2026-08-16

### Fixed
- Every server showed as offline on the overview page after a cold start, and
  only the per-tile Retry button brought them back. The cache poller makes its
  first pass two seconds after Flask starts, so if a Kodi box was still booting
  it answered with a hard-down error such as `Connection refused`. Those errors
  jumped straight to the maximum backoff, meaning one badly timed attempt
  silenced the server for the full `SERVER_FAIL_BACKOFF_SECONDS` (5 minutes by
  default).
- Unreachable backoff now starts at `SERVER_FAIL_BACKOFF_INITIAL_SECONDS`
  (15s) and doubles per failed round up to `SERVER_FAIL_BACKOFF_SECONDS`,
  resetting on the first success. A host that is slow to boot is retried in
  seconds; a host that is genuinely gone still settles into long, quiet
  intervals, so the log noise this backoff was added to stop does not return.
- The overview page could not recover on its own even after the host came
  back. Its initial load skipped any server in backoff, and neither the 12s
  refresh nor the SSE stream performs a live probe, so nothing re-checked the
  server until the backoff expired. Opening the page now probes a server that
  has never been reached, since an "offline" we never confirmed is a guess.
  Servers with a warm cache keep their backoff and answer from cache, and an
  authentication failure is treated as a definite answer rather than a cold
  server.

### Added
- `SERVER_FAIL_BACKOFF_INITIAL_SECONDS` (default 15), documented in
  `.env.example`.

## [3.4.0] - 2026-08-16

### Changed
- The inline JavaScript duplicated across the three nowplaying templates moves
  into `templates/partials/`: `_save_preference.js.html`,
  `_playback_button.js.html`, `_server_management.js.html`,
  `_playback_polling.js.html`, `_server_switch.js.html`, and
  `_playback_config.js.html`. Preference saving, the play/pause button, server
  switching, and playback polling existed as three separate copies that had to
  be kept in step by hand.
- As with the CSS, each include sits where its copy used to, so execution order
  is unchanged. Only runs at statement level that reference no template context
  were extracted; anything touching a Jinja variable stayed inline.
- Combined with 3.3.0 the templates are ~700 lines lighter each: movie
  2256 → 1556, episode 2562 → 1862, music 2446 → 1746.

## [3.3.0] - 2026-08-16

### Changed
- The marquee and side-panel CSS was copied verbatim into all three nowplaying
  templates. It now lives in `templates/partials/` as `_marquee.css.html`,
  `_side_panel_controls.css.html`, `_side_panel_dropdown.css.html`, and
  `_side_panel_sections.css.html`, pulled in with `{% include %}`. The
  templates shrink by 478 lines each (movie 2256 → 1778, episode 2562 → 2084,
  music 2446 → 1968).
- Each include sits exactly where the copied rules used to, so the cascade is
  unchanged. This matters because the templates link `nowplaying-common.css`
  *before* their inline `<style>`: rules moved into that file would quietly
  lose ties they currently win, which is why only whole rule blocks that could
  keep their position were extracted.

### Added
- `tests/test_template_partials.py` renders each page through Jinja and asserts
  every shared partial is included and its rules reach the output, so a
  renamed or dropped partial fails the suite instead of shipping an unstyled
  page.

## [3.2.1] - 2026-08-16

### Changed
- `episode_nowplaying.py` drops from 583 to 353 lines. The InfoLabels fetch,
  audio/subtitle stream collection, language normalisation, resolution, codec,
  aspect ratio, and container derivation were a hand-copied fork of the movie
  builder; they now call the `media_info` helpers the movie builder already
  used, so a fix to stream handling no longer has to be made twice.
- The fanart slideshow markup and the deferred-fanart JSON payload were
  duplicated across all three builders and are now
  `media_info.fanart_slides_html()` and `media_info.fanart_pending_json()`.
  Music keeps its own variant ordering and empty-state comment.
- `media_info.fetch_player_streams()` takes an optional `server_id` so the
  episode builder can keep pinning its RPCs to the server that owns the
  playback rather than whichever server is currently active.
- Application version is now `3.2.1`.

### Fixed
- Resolution could read as blank for episodes and movies when Kodi returned a
  literal `"0"` for `Player.Process(VideoWidth/Height)`. The new
  `media_info.video_dimensions()` parses the InfoLabel before deciding whether
  to fall back to the library's streamdetails, which the movie builder's
  truthiness check did not do.

## [3.2.0] - 2026-08-16

### Changed
- `art.py` (1792 lines) is split into focused modules. Path parsing, download
  URL building, and filesystem path safety move to `art_paths.py`; share-file
  identity, scoping, and reuse to `art_share.py`; first-artwork selection to
  `art_select.py`; artist-folder discovery for music to `art_music.py`; and
  HTTP fetching, per-server locks, deferred downloads, and cache trimming to
  `art_download.py`. `art.py` keeps the metadata-to-artwork orchestration and
  re-exports the moved names, so existing `from kodi_np.art import ...` call
  sites are unaffected.
- Application version is now `3.2.0`.

### Fixed
- `tests/conftest.py` patched `kodi_rpc` and `get_active_server` only on
  `kodi_np.art`. The split modules bind their own references, so RPC stubs
  would have leaked to the real network from `art_paths`, `art_music`, and
  `art_download`; all three are now patched too.

## [3.1.9] - 2026-08-16

### Added
- Tests for the previously uncovered surface: SSE streaming (`/api/events`),
  server CRUD and preference mutation routes, the login gate (page redirect vs
  API 401, logout, rate limiting, redirect hardening), static asset and
  artwork routes including image-type sniffing, `/api/diagnostics`,
  `/api/cast-thumb`, the load-job lifecycle, and Flask secret key persistence.
  The suite grows from 141 to 253 tests.
- CI now runs `ruff` as its own job, collects coverage with `pytest-cov`, and
  asserts the built image does not run as uid 0.

### Changed
- Application version is now `3.1.9`.

## [3.1.8] - 2026-08-16

### Changed
- `load_preferences()` caches the parsed file and re-reads only when
  `preferences.json` changes on disk. It previously reopened and reparsed the
  file on every call, which happens per deferred fanart download and on every
  poller tick. Writes through `save_preferences()` / `update_preferences()`
  invalidate the cache, and an external edit is picked up via the file's
  size and mtime.
- `ensure_preferences_dir()` no longer performs an `exists()` syscall building
  a debug message that was discarded at the default log level.
- The three identical copies of `to_secs()` in `nowplaying.py` and
  `routes/playback.py` are now one `kodi_time_to_seconds()` in `util.py`,
  which also tolerates missing, null, and non-numeric fields instead of
  raising.
- Application version is now `3.1.8`.

## [3.1.7] - 2026-08-16

### Added
- Application-wide error handlers in `kodi_np/errors.py`. Requests under
  `/api/` (or with an explicit JSON `Accept`) now get a JSON body with
  `success`, `error`, and `status`, so front-end `response.json()` calls no
  longer fail on Werkzeug's HTML error page. Everything else gets a styled
  `error.html` matching the sign-in page.
- Unhandled exceptions are logged with a traceback and return a generic 500
  that does not expose the exception message.

### Changed
- Application version is now `3.1.7`.

## [3.1.6] - 2026-08-16

### Removed
- `generate_fallback_html()`, an unreachable 80-line HTML page in
  `nowplaying.py` that nothing had called since the modular renderers landed.
- `startMarqueeShimmer()` from `nowplaying-common.js`. All three now-playing
  templates ship their own shimmer loop and none referenced the shared one.
- Roughly 30 dead local variables across the movie, episode, and music page
  builders — metadata pulled out of Kodi responses and then discarded
  (`artist_bio`, `song_bpm`, `audio_languages`, `resolution`, and similar).
- Unused imports in `cache.py`, `nowplaying.py`, `routes/playback.py`, and
  `routes/servers_prefs.py`.

### Added
- `ruff.toml` and `ruff` in `requirements-dev.txt`. The config exempts the
  compat shim modules, whose re-exports are deliberate. `ruff check` is clean.

### Changed
- Application version is now `3.1.6`.

## [3.1.5] - 2026-08-16

### Security
- The container runs as an unprivileged user (`1000:1000` by default, override
  with `PUID` / `PGID`) instead of root, with `no-new-privileges` and all
  capabilities dropped.
- Added `kodi-np-multi/.dockerignore`. The build context is `./kodi-np-multi`,
  so the repo-root ignore file never applied and every build uploaded the
  artwork cache plus `preferences/` (Flask secret key and plaintext Kodi
  passwords) to the Docker daemon.

### Upgrading
- Existing installs must hand the bind mounts to the new user once:
  `sudo chown -R 1000:1000 ./kodi-np-multi/tmp ./kodi-np-multi/preferences`.
  Without this, artwork and preference writes fail. See the README.

### Changed
- Application version is now `3.1.5`.

## [3.1.4] - 2026-08-16

### Security
- `POST /api/fanart` no longer fetches arbitrary URLs. Deferred artwork paths
  always come from Kodi, so a raw `http(s)` path is now only accepted when it
  resolves to the configured Kodi host. Previously any caller could make the
  container issue a request to a host of their choosing.
- Sign-in honours only same-origin relative `next` targets. `//evil.example`
  passed the old `startswith("/")` check and redirected off-site.
- New optional `KODI_HOST_ALLOWLIST` restricts which hosts custom Kodi servers
  may point at. Unset (default) keeps existing behaviour.

### Changed
- Application version is now `3.1.4`.

## [3.1.3] - 2026-08-16

### Fixed
- Extrafanart scanning no longer misreads directory listings. A misindented
  branch ran the filename check for every entry, so a non-image entry
  (subfolder, `.nfo`) either raised a swallowed `NameError` that aborted the
  whole scan, or reused the previous file's name and registered a fanart
  variant under the wrong key.
- Artwork fallback downloads no longer reuse the previous candidate's URL when
  Kodi returns neither a token nor a path, which could store an image under the
  wrong source path and poison share reuse.

### Changed
- Extrafanart listing is parsed by `collect_extrafanart_variants()` instead of
  a loop nested ten levels deep inside the art builder.
- Application version is now `3.1.3`.

## [3.1.2] - 2026-08-14

### Fixed
- Cast thumbnails layout horizontally again. A broken CSS block after
  `.badge.live-badge` was discarded by the parser and took `.cast-row`
  `{ display: flex }` with it, so cards stacked as a single column.

### Changed
- Application version is now `3.1.2`.

## [3.1.1] - 2026-08-14

### Fixed
- Unreachable Kodi hosts (connection refused, no route, connect timeout) enter
  poll backoff on the first failure instead of being retried every 12s.
- Overview auto-refresh reads the cache snapshot (`/api/overview`) instead of
  live-probing every server. Retry still probes that one host.
- Background cache probes and overview live status honor unreachable backoff
  (`/poll_playback` on an open now-playing page still bypasses it).
- Connection attempts use a 2s connect timeout (`KODI_CONNECT_TIMEOUT`) so
  powered-off boxes fail fast.

### Changed
- Application version is now `3.1.1`.

## [3.1.0] - 2026-08-14

### Added
- Overview **Auto-switch to playing** slide toggle (off by default). Idle stays a
  server picker; enabling the toggle jumps to the first playing Kodi box.
- Add custom Kodi hosts from the overview page without a container restart
  (saved in `preferences.json`; env hosts remain read-only).
- Playlist **Up next** line on movie, episode, and music pages.
- Live TV / music video / plugin streams use the movie layout with a Live or
  Video badge instead of a dead-end unknown page.
- `/api/events` SSE feed for overview and playback (pages still poll as fallback).
- `TZ` environment variable for container timezone (IANA name; default `UTC`).
- Login rate limit, HttpOnly/SameSite session cookies, and a persisted Flask
  secret key in `/app/preferences/flask_secret_key` when `FLASK_SECRET_KEY` is unset.

### Changed
- Parser, movie/episode/music HTML generators, and shared stream helpers now live
  in the `kodi_np` package. Mutable cache/backoff state moved to `kodi_np.state`.
- Shared clock, playback monitor, and marquee shimmer live in `nowplaying-common.js`.
- Compose defaults `LOG_LEVEL` to `INFO` and no longer hardcodes `BASIC_AUTH`.
- JSON logs use the process timezone.
- Application version is now `3.1.0`.
- GitHub Actions builds the Docker image in addition to pytest.

### Fixed
- TV show tagline and season plot now read `tvshow.nfo` / `season.nfo` via plain Kodi
  VFS (`nfs://…`) instead of the image download path, which returned HTTP 500 for NFO
  files. Kodi's JSON API does not expose `tagline` on `GetTVShowDetails`; season plot
  now resolves `seasonid` correctly for `GetSeasonDetails`.
- Overview page no longer wipes and rebuilds all tiles every refresh (fixes flashing
  “Checking…” on offline servers); tiles update in place every 12s instead.
- Now-playing no longer redirects to the idle screen after prolonged Kodi connection
  blips (`error_idle` holds the current page instead of reporting stopped).
- Overview tiles and now-playing correctly detect when playback has stopped (stale
  cached "playing" state no longer persists after Kodi reports idle players).

## [3.0.5] - 2026-08-02

### Added
- Episode page shows TV show **tagline** from `tvshow.nfo` / Kodi library (toggle in
  settings sidebar; default on).
- **Season plot** from `season.nfo` (season folder first, then show-root
  `seasonNN.nfo`) or Kodi `GetSeasonDetails`, with optional named-season labels
  from `<namedseason>` in `tvshow.nfo` (toggle + label style in sidebar).
- Year, Director, Episode Plot, and Season Plot headings now match Cast styling
  (uppercase, off-white).

### Changed
- Episode metadata order: Cast → Season plot → Episode plot.
- Application version is now `3.0.5`.

## [3.0.4] - 2026-08-02

### Changed
- Overview page paints server tiles immediately from cache/config, then probes each
  Kodi box in parallel via `/api/overview-server/<id>` and updates cards as
  responses arrive (no more multi-minute wait on one slow/offline host).
- Application version is now `3.0.4`.

## [3.0.3] - 2026-08-02

### Fixed
- Overview no longer shows **Auth failed** for powered-off / unreachable Kodi
  boxes; unreachable connection errors clear stale auth backoff and the overview
  re-probes live status each refresh instead of trusting old cache flags.

### Changed
- Application version is now `3.0.3`.

## [3.0.2] - 2026-08-02

### Added
- Progressive fanart loading: page paints with the primary fanart; remaining
  variants download after load via `POST /api/fanart` and append to the slideshow.
- `ART_DOWNLOAD_WORKERS` (default `2`, max `4`) for parallel HTTP artwork GETs
  after serial Kodi `PrepareDownload` (still one Gunicorn worker).

### Changed
- Application version is now `3.0.2`.
- Music soft-update on artist change refreshes fanart slides and re-hydrates any
  pending variants.

## [3.0.1] - 2026-08-02

### Fixed
- Opaque JPG discarts are cropped to a circle (`border-radius` + `object-fit`) so
  spinning square backgrounds no longer show on music and movie pages.
- Cast strip stays left-aligned when fewer than a full row of actors; cards no
  longer stretch to fill the width with large gaps.
- Cast HTML deduplicates the same actor listed multiple times with alternate
  role strings from Kodi/NFO scrapers.
- Soft track changes reload lyrics (and guard against stale responses) so the
  first song’s lines no longer stick after autoplay.
- Interactive `/poll_playback` always resolves `Player.GetItem`, so song/artist
  changes are detected on the normal 4s poll instead of waiting on a slower
  item-check interval.
- Idle / hard-reload navigation clears tracked item id and stops further poll
  redirects, avoiding a stale previous track after stop → new playback.
- Default idle confirmation is two empty-player polls (`POLL_IDLE_CONFIRMATIONS=2`);
  now-playing pages confirm stop after two consecutive `playing: false` responses.

### Changed
- Application version is now `3.0.1`.
- Movie discart peek / poster drop positioning shows more of the disc under the
  content overlay without clipping into the marquee.

## [3.0.0] - 2026-08-02

### Added
- Synced karaoke-style lyrics on the music page (Kodi `lyrics` field first, then
  free [LRCLib](https://lrclib.net) lookup) with a Lyrics / Album / Artist tab panel.
- `/api/lyrics` and `/api/cast-thumb` endpoints for async lyrics resolution and
  post-load cast thumbnail downloads.
- Cast strip with actor names immediately, thumbnails fading in after page load.
- Overview tiles distinguish **Auth failed** from generic **Offline**, with clearer
  status copy and continued 5-second auto-refresh.
- Shared Jinja partial `templates/partials/side_panel.html` for now-playing settings.

### Changed
- Application version is now `3.0.0`.
- README documents Gunicorn (single worker), `FLASK_SECRET_KEY` session behavior,
  and production runtime details.
- Shared `nowplaying-common.css` / `.js` expanded for cast, lyrics, and info tabs.
- Now-playing layout: larger cast thumbs that grow with column width, tighter
  spacing under the marquee, full-width plot/progress, and even side-panel
  vertical rhythm.
- Music info panel (Lyrics / Album / Artist) is wider; Album and Artist text
  boxes match the Lyrics panel height. Lyrics resolution logs `source=kodi|lrclib`
  and uses stricter LRCLib matching (album + duration scoring).
- Album/artist text falls back to TheAudioDB (then Wikipedia) when Kodi fields
  are empty; fetched asynchronously after page load and share-cached per album /
  artist across soft track changes.

### Tests
- Coverage for LRC parsing, lyrics preference enum, overview `auth_failed`, and
  cast HTML builder. Full suite passes with 99 tests.

## [2.0.0] - 2026-08-01

### Added
- Production WSGI container runtime using Gunicorn with one worker and threaded
  request handling.
- Optional session-based web authentication via `BASIC_AUTH=username:password`;
  leaving it empty keeps authentication disabled.
- Sleek dark login screen with gradient branding, validation feedback, and safe
  post-login return handling.
- `/health/live` and `/health/ready` endpoints alongside the existing liveness
  endpoint, including the application version.
- `/api/diagnostics` with artwork-cache usage, configured cache limits, build
  counts, and per-server connection state.
- Configurable artwork cache limits through `CACHE_MAX_ART_FILES` and
  `CACHE_MAX_ART_MB`.
- Shared `nowplaying-common.css` and `nowplaying-common.js` assets for common
  dashboard behavior.
- Manual **Reduce motion** toggle in the right-hand settings panel, persisted
  with the other preferences and defaulting to off.
- GitHub Actions test workflow and root `pytest.ini` so the nested package is
  tested consistently in local and CI runs.

### Changed
- Application version is now exposed as `2.0.0`.
- Cache cleanup removes old unprotected artwork when file-count or size limits
  are exceeded, while retaining files referenced by active cache entries.
- JSON-RPC authentication failures are identified separately from network
  failures and temporarily pause polling with a clear diagnostic.
- Cache rebuild logs now describe the old and new now-playing titles when a
  playback fingerprint changes.
- Docker health monitoring remains unauthenticated so container orchestration
  can continue to inspect the service when web login is enabled.

### Accessibility
- Artwork receives meaningful fallback alternative text where the UI creates
  image elements without one.
- Keyboard focus is visibly outlined with `:focus-visible`.
- Marquee and icon-only controls expose button semantics, labels, and keyboard
  activation with Enter or Space.
- `prefers-reduced-motion: reduce` disables or minimizes marquee, discart,
  fade, and other animated transitions for users who request less motion.

### Tests
- Added authentication, health, cache diagnostics, artwork-priority, codec,
  and overview regression coverage.
- Full suite passes with 92 tests.

## [1.2.3] - 2026-07-18

### Added
- Optional friendly host labels via `KODI_HOST_LABEL_1`…`N` (and legacy `KODI_HOST_LABEL`), shown in the server dropdown, idle page, and multi-server overview.

## [1.2.2] - 2026-07-18

### Added
- Pytest suite under `tests/` covering server env parsing, preference validation, load-job pruning, overview helpers, health/path safety, logging config, and movie/episode/music template smoke renders.
- `requirements-dev.txt` for local test dependencies (`pytest`).

## [1.2.1] - 2026-07-18

### Changed
- Replaced print-based `[DEBUG]` / `[INFO]` / `[WARNING]` / `[ERROR]` output with structured Python logging controlled by the `LOG_LEVEL` environment variable (default `INFO`).
- Added `logging_config.py` with optional `LOG_FORMAT=json` for one-line JSON logs.

## [1.2.0] - 2026-07-18

### Changed
- Moved movie, episode, and music now-playing HTML into Jinja2 templates under `templates/` while keeping media-specific Python logic in each `*_nowplaying.py` module.
- Flask app loads templates from the local `templates/` directory; Docker image copies that folder into `/app/templates`.

## [1.1.1] - 2026-07-18

### Fixed
- Prune in-memory now-playing load jobs by TTL (default 10 minutes finished / 30 minutes stale) and hard cap (50).
- Drop rendered HTML from a load job after the first successful `/nowplaying-content` fetch to limit memory growth.

## [1.1.0] - 2026-07-18

### Added
- Multi-Kodi overview wall at `/overview` with playing / paused / idle / offline tiles for every configured server.
- `/api/overview` JSON endpoint that polls all servers in parallel.
- Idle page link to the multi-server overview; click a tile to switch server and open now playing when media is active.

## [1.0.4] - 2026-07-18

### Changed
- Artwork cache directory is now `/app/tmp` (configurable via `ART_TMP_DIR`) instead of overwriting container `/tmp`.
- Docker Compose mounts `./kodi-np-multi/tmp` to `/app/tmp` and passes `FLASK_SECRET_KEY` / `LOG_LEVEL`.
- Dockerfile installs pinned dependencies from `requirements.txt`.

### Added
- `/health` liveness endpoint for Docker healthchecks and uptime monitors.
- Compose and Dockerfile `HEALTHCHECK` against `/health`.
- `.dockerignore` and `.gitignore` (ignores `.env`, artwork cache, caches).

### Fixed
- Documented that `.env` keys must not have leading spaces (can prevent servers 2+ from loading).

## [1.0.3] - 2026-07-18

### Documentation
- Rewrote Setup to match multi-server Docker Compose (`KODI_HOST_1`…`N`, port 6001).
- Removed obsolete zip / single-host code-edit instructions.
- Added `.env.example` with numbered hosts, optional `FLASK_SECRET_KEY`, and legacy env notes.
- Clarified Homarr iframe URLs and reverse-proxy guidance for remote access.

## [1.0.2] - 2026-04-26

### Security
- Hardened media and static file serving to reject path traversal and unexpected filenames.
- Escaped Kodi metadata before rendering it into HTML pages.
- Restricted preference updates to known UI settings and valid slider ranges.
- Reduced preference logging so full preference payloads are not written to logs.

### Documentation
- Documented that the dashboard is intended for trusted LAN/VPN use and should not be exposed directly to the internet without an external access-control layer.
- Corrected Docker Compose service examples to use `kodi-np-multi`.

## [1.0.0] - 2024-12-19

### Added
- Multi-server support: Switch between multiple Kodi devices from the web interface
- Side panel settings menu with server selection dropdown
- Server connection status indicator with real-time connection testing
- Interactive blur toggle control moved to settings panel
- Configurable blur amount slider (0-100%)
- Overlay opacity control slider (0-100%)
- Marquee shimmer effect interval control (5-60 seconds)
- Fanart slideshow interval control (5-120 seconds)
- Session-based server selection and persistence
- API endpoints for server management (`/api/servers`, `/api/switch-server`, `/api/test-connection`)
- CSS toggle component for settings (styled to match existing green theme)
- Support for numbered environment variables (KODI_HOST_1, KODI_HOST_2, KODI_HOST_3, etc.)

### Changed
- Port changed from 5001 to 6001
- Docker Compose configuration updated for multi-server support
- Environment variable format updated to support multiple servers
- Blur toggle moved from top-right corner to settings panel
- Settings panel slides in from the right side of the screen

### Technical Details
- Flask session management for active server tracking
- Backend server parsing from environment variables
- Real-time connection testing with visual feedback
- LocalStorage persistence for all user preferences
- Dynamic interval updates for marquee and fanart animations

