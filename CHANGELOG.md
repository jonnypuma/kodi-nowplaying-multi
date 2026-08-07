# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

<<<<<<< Updated upstream
=======
<<<<<<< HEAD
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

=======
>>>>>>> 827abde8a4ae1cc3ea63ed185bc4ae0a54452049
>>>>>>> Stashed changes
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

