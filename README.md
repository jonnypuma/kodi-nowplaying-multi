This is a Docker container application whcihc provides a html page showing what a Kodi device is playing and displays artwork, progress bar, media information, plot etc with background slideshow if more than one fanart is found.

<img width="2553" height="1371" alt="image" src="https://github.com/user-attachments/assets/ccccf224-4ba6-4922-98a7-737c16b230cc" />

<img width="2559" height="1372" alt="image" src="https://github.com/user-attachments/assets/d1e25039-1f32-4e7d-8fe5-b61efd3d7951" />

<img width="2559" height="1377" alt="image" src="https://github.com/user-attachments/assets/c384628c-f1bd-47b0-8be9-5719ff2eb8ad" />


## Package layout

The Flask app lives in the `kodi_np/` package. Docker starts Gunicorn against
`kodi_np.app:app` (see `Dockerfile`). The shim `kodi-nowplaying.py` remains useful
for local non-Docker runs.

| Module | Responsibility |
|--------|----------------|
| `kodi_np/config.py` | Env knobs, locks, shared process state |
| `kodi_np/rpc.py` | JSON-RPC client + unreachable backoff |
| `kodi_np/servers.py` / `preferences.py` | Multi-server registry and prefs file |
| `kodi_np/art.py` | Artwork download + identity-scoped share reuse |
| `kodi_np/cache.py` | Per-server now-playing cache + poller |
| `kodi_np/lyrics.py` | LRC parsing + LRCLib lyrics lookup |
| `kodi_np/music_meta.py` | Album/artist text fallbacks (TheAudioDB, Wikipedia) |
| `kodi_np/nowplaying.py` | HTML build, load jobs, soft-update payloads |
| `kodi_np/routes/` | Blueprints (pages, playback, overview, extras, static) |
| `kodi_np/app.py` | `create_app()` factory |
| `templates/` | Jinja pages (`index`, `overview`, `loading`, media layouts, `partials/`) |
| `episode_nowplaying.py` / `music_nowplaying.py` / `movie_nowplaying.py` | Media HTML generators (import `kodi_np.rpc`) |

## Features

- **Multi-Kodi Overview**: `/overview` wall showing playing / paused / idle / offline / auth-failed status for every configured server (auto-refreshes every 5s)
- **Jinja Templates**: Movie, episode, and music layouts live in `templates/` with shared side-panel partials
- **Real-time Playback Detection**: Automatically detects when Kodi starts/stops playing media
- **Playback State Monitoring**: Shows current play/pause state with visual indicators (status icon; not a remote control)
- **Smart Timer Management**: Timer stops when paused and resyncs on resume
- **Comprehensive Media Support**: Episodes, movies, and music with appropriate artwork
- **Synced Lyrics (music)**: Karaoke-style highlighting from Kodi tags or LRCLib, with Album/Artist tab toggle
- **Album/Artist metadata fallback**: When Kodi has no album/artist text, probes TheAudioDB (free key) then Wikipedia asynchronously after page load; cached per album/artist across soft track changes
- **Lazy Cast Thumbnails**: Cast names render immediately; actor photos fade in after load
- **Background Slideshow**: Multiple fanart images for enhanced visual experience
- **Responsive Design**: Clean, modern interface that works on various screen sizes
- **Blur Toggle Control**: Discreet button to switch between blurred and non-blurred overlay modes
- **Cross-Browser Scrollbar Styling**: Custom scrollbars with green hover effects
- **Smart Episode Title Detection**: Automatically hides generic episode titles to prevent duplication
- **Enhanced HDR Badge Display**: Clean HDR type indicators (SDR, HDR, HDR10, HDR10+, HLG, Dolby Vision)
- **Enhanced Video/Audio Information**: Real-time aspect ratio, container format, and accurate codec detection
- **Studio/Tagline Display**: Production studio badges and movie/episode taglines
- **Music Sample Rate/Record Label**: Enhanced audio information with kHz formatting and record label display
- **Album Back Cover Flip**: Smooth front/back cover toggle for music albums
- **Expandable Language Badges**: Interactive audio/subtitle language display with smart highlighting

## Playback Indicators

The HTML webpage includes:
- **Play/Pause Icon**: Visual indicator that changes based on playback state in real-time
- **Smooth Transitions**: 500ms fade in/out effects when switching between play/pause states
- **Timer Integration**: Icon positioned to the left of the playback timer
- **Interactive Discart Animation**: Discart (CD/DVD/Bluray artwork) spins during playback and pauses when media is paused

## Theater-Style Marquee Banner

The interface features a hideable marquee banner that displays the current media title in a theater sign style:
- **Auto-hide Toggle**: Click the half-circle arrow tab to hide/show the marquee banner
- **Dynamic Color Shifting**: Smooth color transitions that cycle through different hues
- **Smooth Animations**: Fade in/out effects when toggling visibility
- **Responsive Design**: Banner adapts to different screen sizes
- **Clean Integration**: Seamlessly integrated with the overall design

### Text Shimmer Effect

The marquee banner includes an elegant text shimmer effect that adds visual interest:
- **Automatic Triggering**: Effect runs every 10 seconds when media is playing
- **Letter-by-Letter Animation**: Each letter of "NOW PLAYING" animates individually
- **Two-Stage Effect**: 
  1. **Dark Wave**: Letters fade to dark gray in sequence (80ms stagger between letters)
  2. **Shimmer Wave**: Bright orange glow sweeps across, leading the white fade
- **Perfect Timing**: Shimmer arrives first, then letters fade back to white with proper delay
- **Consistent Spacing**: Letter spacing remains identical whether effect is active or not
- **Smooth Transitions**: All animations use CSS transitions for fluid motion
- **Non-Intrusive**: Effect is subtle enough to not distract from content viewing

## Blur Toggle Control
A sleek, discreet toggle button that allows you to switch between blurred and non-blurred overlay modes:
- **Top-Right Placement**: Small circular button positioned in the top-right corner of the content overlay
- **Custom SVG Icon**: Inline SVG icon representing the blur effect with layered rectangles
- **Smooth Animations**: Subtle pulsing glow animation and hover effects
- **Persistent Preferences**: Your blur preference is saved in localStorage and restored across sessions
- **Smart Defaults**: 
  - Movies: Default to non-blurred (shows more fanart detail)
  - Episodes & Music: Default to blurred (better text readability)
- **Instant Toggle**: Pure CSS/JavaScript implementation with no page reload required

## Enhanced Scrollbar Styling
Custom scrollbars during music playback for artist and album info sections with improved visual design and cross-browser support:
- **WebKit Browsers** (Chrome, Safari, Edge, Brave): Full custom styling with sleek appearance
- **Firefox**: Thin scrollbars with color changes on hover
- **Green Hover Effect**: Scrollbars turn the same green color used throughout the UI when hovered
- **Smooth Transitions**: CSS transitions for polished interactions
- **Consistent Design**: Maintains sleek appearance across all browsers

## Smart Episode Title Detection
Intelligent detection of generic episode titles to prevent visual duplication:
- **Pattern Recognition**: Automatically detects titles like "Episode 6", "Episode #6", "episode 6"
- **Case Insensitive**: Works with any capitalization
- **Flexible Matching**: Handles variations with spaces, hash symbols, and extra whitespace
- **Real Title Preservation**: Keeps meaningful episode titles like "The Pilot" or "Winter is Coming"
- **Clean Display**: Eliminates duplicate badges when episode title matches episode number

## HDR Badge Display
HDR type indicators for better clarity:
- **Clean Format**: Shows just the HDR type (SDR, HDR, HDR10, HDR10+, HLG, Dolby Vision)
- **Automatic Detection**: Uses Kodi's stream information to determine the correct HDR type
- **Consistent Styling**: Matches the design of other media information badges

## Enhanced Video/Audio Information
Real-time media format detection with comprehensive badge system:
- **Aspect Ratio Detection**: Real-time aspect ratio from Kodi's video player (16:9, 21:9, etc.)
- **Container Format**: Video/audio container detection (MKV, MP4, AVI, FLAC, MP3, etc.)
- **Accurate Codec Detection**: Enhanced video/audio codec information from active playback
- **Smart Fallbacks**: Filename extension fallback when API data is unavailable
- **Numeric Conversion**: Automatic conversion of aspect ratios (1.78 → 16:9, 2.35 → 21:9)
- **Duplicate Prevention**: Container format only shows when different from codec

## Studio/Tagline Display
Enhanced movie and episode information:
- **Studio Badges**: Production studio information displayed as badges
- **Tagline Display**: Movie/episode taglines shown in italic text under clearlogo
- **API Integration**: Uses Kodi's VideoLibrary API with proper field requests
- **Conditional Display**: Only shows when information is available
- **Clean Formatting**: Studio names joined with commas, taglines without prefixes

## Music Sample Rate/Record Label
Enhanced audio information with improved formatting:
- **Sample Rate Display**: Clean kHz formatting (44.1 kHz, 48.0 kHz, 22.5 kHz)
- **Record Label Badges**: Album record label information from Kodi's database
- **Precision Formatting**: Proper decimal handling for common sample rates
- **Clean Badge Design**: Removed unnecessary prefixes for streamlined display
- **Smart Extraction**: Properly extracts from album details API response

## Album Back Cover Flip
Interactive album artwork that reveals additional details when back cover art is available:
- **Back Cover Detection**: Automatically loads back cover assets supplied by Kodi (e.g., `back`, `backcover`, `rear`)
- **3D Flip Animation**: Smooth 180° horizontal flip between front and back covers
- **Double-Click Trigger**: Toggle between front and back covers by double-clicking the album artwork
- **Keyboard Accessible**: Toggle with Enter or Space when focused; focus outlines help when navigating via keyboard
- **Contextual Indicator**: Subtle overlay text updates to show whether the front or back cover is currently displayed
- **Zoom Compatibility**: Single-click zooms the cover; double-click flips between front/back without triggering zoom

## Poster/Cover Zoom Functionality
Interactive zoom feature for all media artwork that provides a detailed view:
- **Universal Support**: Works with movie posters, TV show posters, TV season posters, and album covers
- **Single-Click Zoom**: Click any poster or cover to view it in a larger, centered overlay
- **Smooth Animation**: Elegant scale-up animation with fade effects when opening/closing
- **Responsive Sizing**: Zoomed images scale up to ~4× original size (up to 80% of viewport) depending on screen size
- **Visual Feedback**: Magnifying glass cursor (zoom-in) appears when hovering over clickable artwork
- **Easy Dismissal**: Click anywhere on the dark overlay or press Escape to close the zoom view
- **Album Cover Integration**: Single-click zooms album covers; double-click flips between front/back (when back cover available)
- **Non-Image Exclusion**: Fallback icons (`.no-image`) are excluded from zoom functionality

## Expandable Language Badges
Interactive audio and subtitle language display with intelligent highlighting and real-time updates:
- **Smart Clickability**: Only clickable when multiple languages are available
- **Default View**: Shows currently playing language (e.g., "Audio: ENG")
- **Expanded View**: Reveals all available languages with active language highlighted
- **Visual Highlighting**: Green highlight box around the currently playing language
- **Real-Time Updates**: Language badges automatically update when you switch audio/subtitle tracks in Kodi
- **No Page Reload**: Seamless updates without refreshing the page
- **Persistent Preferences**: Remembers your expansion preferences across sessions
- **Smooth Animations**: Hover effects and transition animations
- **Clean Readability**: Dark badge background with white text for optimal contrast
- **Dual Source Detection**: Uses both InfoLabels (current) and streamdetails (all available)
- **Smart Fallbacks**: Graceful handling when language data is incomplete
- **Language Normalization**: Consistent language codes across different data sources

## Media Type Display Features

The application provides specialized displays and artwork for different media types, each optimized for the unique characteristics of TV shows, movies, and music:

### TV Shows
**Artwork Display:**
- **Show Poster**: Main TV show poster displayed prominently
- **Season Artwork**: Season-specific poster when available (shows season number and artwork)
- **ClearArt**: High-quality transparent show artwork (preferred for overlay)
- **Banner**: Wide banner artwork for show identification
- **Fanart Slideshow**: Multiple background images including show fanart and extrafanart

**Information Displayed:**
- Show title and episode title
- Season and episode numbers
- Episode plot/synopsis
- Show genre and rating
- Cast information (when available)
- Video quality (resolution, codec, HDR type, aspect ratio, container format)
- Audio information (channels, codec, container format)
- Interactive language badges (audio/subtitle with expandable view)
- Studio information and tagline
- Release year and director information
- Playback progress and time remaining

### Movies
**Artwork Display:**
- **Movie Poster**: Primary movie poster with cinematic styling
- **Discart**: Spinning disc/DVD/Blu-ray artwork that rotates during playback
- **ClearArt**: Transparent movie artwork for clean overlay
- **Banner**: Movie banner artwork for identification
- **Fanart Slideshow**: Cinematic background images from movie fanart and extrafanart

**Information Displayed:**
- Movie title and year
- Director and cast information
- Genre and rating
- Plot summary
- Video quality (resolution, codec, HDR type, aspect ratio, container format)
- Audio information (channels, codec, container format)
- Interactive language badges (audio/subtitle with expandable view)
- Studio information and tagline
- Release year and director information
- Playback progress and total runtime

### Music
**Artwork Display:**
- **Album Artwork**: Album cover displayed prominently (thumbnail or poster)
- **Artist ClearArt**: High-quality transparent artist artwork
- **Artist Banner**: Wide banner artwork for artist identification
- **Fanart Slideshow**: Artist fanart and concert/live performance images

**Information Displayed:**
- Artist name and song title
- Album name and release year
- Genre and music quality information
- Audio codec and container format
- Sample rate (kHz) and bitrate information
- Record label and channel information
- Artist biography (when available from metadata)
- Album information and track details
- Playback progress and song duration

### Artwork Fallback System
Each media type follows a sophisticated fallback hierarchy to ensure optimal visual presentation:

**TV Shows:**
1. **ClearArt** → **Banner** → **Text Fallback**
2. **Season Poster** (when available) → **Show Poster** → **Default**
3. **Fanart Collection**: Main fanart + extrafanart folder images

**Movies:**
1. **ClearArt** → **Banner** → **Text Fallback**  
2. **Discart** (spinning disc artwork) for visual appeal
3. **Fanart Collection**: Movie fanart + extrafanart folder images

**Music:**
1. **ClearArt** → **Banner** → **Text Fallback**
2. **Album Artwork** (thumbnail/poster) as primary display
3. **Fanart Collection**: Artist fanart + concert/performance images

### Artwork Sources
- **Kodi's Artwork Database**: Primary source for all artwork types
- **Local Media Folders**: Scans movie/TV/music directories for additional artwork
- **Extrafanart Folders**: Automatically discovers fanart in `extrafanart/` subdirectories
- **Automatic Detection**: Script automatically detects available artwork types
- **Seamless Fallbacks**: Transitions between artwork types are smooth and automatic
- **Quality Priority**: Always displays the highest quality artwork available
- **Responsive Scaling**: All artwork types scale appropriately for different screen sizes

### Background Slideshow
When multiple fanart images are available:
- **Automatic Rotation**: Cycles through all available fanart images
- **20-Second Intervals**: Each image displays for 20 seconds
- **Smooth Transitions**: Fade effects between background changes
- **Dynamic Detection**: Automatically detects and uses all available fanart images
- **Extrafanart Support**: Scans `extrafanart/` subdirectories to find additional background images
- **Comprehensive Collection**: Includes fanart from both main directory and extrafanart folders for maximum variety

## Setup

### Prerequisites

1. On each Kodi device, enable **Settings → Services → Control → Allow remote control via HTTP**.
2. Note the HTTP port and (if set) the username/password for web access.

### Configure servers

Copy the example env file and edit it with your Kodi hosts:

```bash
cp .env.example .env
```

Use numbered variables for one or more servers (`KODI_HOST_1`, `KODI_HOST_2`, …). Do not put spaces before variable names.

```env
# Server 1 (required)
KODI_HOST_1=http://192.168.0.10:8080
KODI_HOST_LABEL_1=Living Room
KODI_USERNAME_1=kodi
KODI_PASSWORD_1=secret

# Server 2 (optional)
KODI_HOST_2=http://192.168.0.11:8080
KODI_HOST_LABEL_2=Bedroom
KODI_USERNAME_2=kodi
KODI_PASSWORD_2=secret
```

Optional `KODI_HOST_LABEL_N` values appear in the server dropdown, idle message, and `/overview` tiles (falls back to IP if unset).

### Flask secret key (`FLASK_SECRET_KEY`)

Used to sign Flask session cookies (selected server, and web login when
`BASIC_AUTH` is enabled). **The app works without setting one** — if unset, a
random key is generated at startup. That is intentional for easy LAN use: you
do not need a secret to get started.

Trade-off: the random key changes on every container restart, so browser session
cookies become invalid (you may need to pick the server again, and you will need
to sign in again if `BASIC_AUTH` is set). The last selected server is still
restored from `preferences.json` when possible.

For a stable key across restarts (recommended when using `BASIC_AUTH`), generate
one and put it in `.env`:

**PowerShell**

```powershell
# Works on Windows PowerShell 5.1 and PowerShell 7+
$bytes = New-Object byte[] 32
[System.Security.Cryptography.RandomNumberGenerator]::Create().GetBytes($bytes)
($bytes | ForEach-Object { $_.ToString('x2') }) -join ''

# Alternatives (if available):
openssl rand -hex 32
python -c "import secrets; print(secrets.token_hex(32))"
```

**Linux / macOS**

```bash
openssl rand -hex 32
# or:
python3 -c "import secrets; print(secrets.token_hex(32))"
# or:
head -c 32 /dev/urandom | xxd -p -c 32
```

Then add it to `.env`:

```env
FLASK_SECRET_KEY=paste-the-generated-value-here
```

Optional: `LOG_LEVEL` (`DEBUG`, `INFO`, `WARNING`, `ERROR`; default `INFO`) controls log verbosity. Set `LOG_FORMAT=json` for one-line JSON logs.

### Production runtime (Gunicorn)

The Docker image runs **Gunicorn** with **one worker** and multiple threads:

```text
gunicorn --bind 0.0.0.0:6001 --workers 1 --threads 8 --timeout 180 kodi_np.app:app
```

Keep `--workers 1`. The now-playing cache, artwork state, and server backoff live
in process memory. Multiple workers would not share that state and would cause
inconsistent overview / now-playing results. Scale with threads (or a future
shared store), not additional Gunicorn workers.

Artwork HTTP downloads after Kodi `PrepareDownload` can run in a small thread
pool. Set `ART_DOWNLOAD_WORKERS` to `1`–`4` (default `2`). RPC discovery stays
serialized per Kodi host. Extra fanart variants load progressively after first
paint via `/api/fanart` so the loading screen only waits on one primary fanart
plus posters/logos.

### Optional web login

Set `BASIC_AUTH` to `username:password` to enable the sleek sign-in page. Leave it
empty to keep the dashboard open on a trusted LAN/VPN:

```env
BASIC_AUTH=admin:choose-a-long-password
```

The health endpoints remain unauthenticated for Docker monitoring:
`/health`, `/health/live`, and `/health/ready`.

Artwork cache limits can be adjusted with `CACHE_MAX_ART_FILES` and
`CACHE_MAX_ART_MB`. `/api/diagnostics` reports cache usage and per-server
connection status after login.

Legacy single-server names (`KODI_HOST`, `KODI_USER` / `KODI_USERNAME`, `KODI_PASS` / `KODI_PASSWORD`) still work if no numbered hosts are defined.

Health check URL (for Docker / Uptime Kuma): `http://<host>:6001/health`

### Build and run

```bash
docker compose build --no-cache kodi-np-multi
docker compose up -d kodi-np-multi
```

### Tests

From the repository root (Python 3.12+):

```bash
pip install -r requirements-dev.txt
python -m pytest -q
```

Start playing media on a configured Kodi device, then open:

- Idle / picker page: `http://<host>:6001/`
- Multi-server overview: `http://<host>:6001/overview`
- Now playing: `http://<host>:6001/nowplaying`

Use the settings side panel to switch between configured Kodi servers.

### Homarr iframe

Add a custom Homarr iframe tile pointing to:

```text
http://<host>:6001/nowplaying
```

Replace `<host>` with the IP or hostname of the machine running Docker. For a wall that always shows the idle page until something plays, use `http://<host>:6001/`.

## Network Exposure

This dashboard is intended for a trusted local network or VPN. It does not include built-in user authentication, and it exposes now-playing data plus preference/server-management endpoints. Do not publish port `6001` directly to the internet. If remote access is needed, place it behind a reverse proxy or another access-control layer (for example Traefik, Caddy, or nginx basic auth / Authelia).

