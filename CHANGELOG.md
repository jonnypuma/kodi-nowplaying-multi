# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [1.0.3] - 2025-01-01

### Added
- Server-side preferences storage in JSON file (`preferences.json`) for persistence across container restarts
- Preferences API endpoints (`/api/preferences` GET/POST) for saving and loading user settings
- Preferences volume mount (`./kodi-np-multi/preferences:/app/preferences`) in Docker Compose
- Atomic file writing for preferences to prevent corruption during concurrent writes
- Automatic fallback to localStorage if server-side storage is unavailable

### Changed
- User preferences (blur toggle, blur amount, overlay toggle, overlay opacity, marquee interval, fanart interval) now persist across container restarts
- Preferences are stored server-side and shared across all browsers/devices accessing the application
- Preferences are saved to both localStorage (immediate) and server (persistent) for reliability

### Technical Details
- Preferences stored in `/app/preferences/preferences.json` inside container
- Preferences file is created automatically if it doesn't exist
- All preference changes are merged with existing preferences (no data loss)
- Atomic save operation (write to temp file, then replace) prevents file corruption

## [1.0.2] - 2025-01-01

### Added
- Loading screen with animated "LOADING" text during page transitions
- Smooth fade-out/fade-in transitions when switching servers or when media playback changes
- New `/loading` route that displays animated loading animation before content loads
- AJAX-based content loading to replace loading screen with nowplaying content seamlessly

### Changed
- Updated h1 header styling (font-size: 35px, padding: 15px 15px) for better visual balance
- Server dropdown highlighting now correctly shows green text for selected server across all media types
- Page transitions now use loading screen instead of blank page during content generation

### Technical Details
- Loading screen appears when:
  - Media is detected and nowplaying HTML is being generated
  - Server is switched via dropdown menu
  - New item starts playing (episode, movie, or song change)
- Uses DOMParser to parse and inject fetched HTML content
- Fade-out animation (800ms) before loading screen, fade-in animation (500ms) for loading screen appearance

### Known Issues
- After server switch, page will reload again due to improper detection and handling of item id change 

## [1.0.1] - 2025-01-01

### Added
- Retro shadow CSS style for side panel heading ("Now Playing On")
- New checkbox-based dropdown menu CSS styling with improved visual design

### Fixed
- Fixed server dropdown menu not populating for movies
- Removed duplicate server management functions in movie_nowplaying.py that were overriding correct implementations
- Resolved undefined variable reference (`currentServerIdParam`) in movie dropdown population
- Fixed incorrect CSS class name (`current` instead of `current-server`) in movie dropdown highlighting

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

