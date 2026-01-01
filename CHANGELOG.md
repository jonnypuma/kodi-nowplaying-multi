# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

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

