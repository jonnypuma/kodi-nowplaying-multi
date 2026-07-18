# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

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

