"""
Music-specific HTML generation for Kodi Now Playing application.
Handles music display with album poster, discart/cdart spinning animation, and music-specific layout.
"""
import json
import logging

from flask import render_template

from kodi_np.codecs import format_audio_codec
from kodi_np.media_info import (
    fanart_pending_json as build_fanart_pending_json,
    fanart_slides_html as build_fanart_slides_html,
    format_playback_time,
    html_escape,
    up_next_html as build_up_next_html,
)

logger = logging.getLogger(__name__)


def generate_html(item, session_id, downloaded_art, progress_data, details):
    """
    Generate HTML for music display.
    
    Args:
        item (dict): Media item from Kodi API
        session_id (str): Session ID for file naming
        downloaded_art (dict): Downloaded artwork files
        progress_data (dict): Playback progress information
        details (dict): Detailed media information
        
    Returns:
        str: HTML content for music display
    """
    # Extract additional details from the enhanced API calls (define early to avoid variable scope issues)
    # Use safe fallbacks to prevent crashes
    if isinstance(details, dict):
        album_details = details.get("album", {})
        artist_details = details.get("artist", {})
    else:
        logger.warning(f"Details is not a dict: {type(details)}, value: {details}")
        album_details = {}
        artist_details = {}
        # If details is not a dict, create a safe fallback
        if not isinstance(details, dict):
            details = {}
    
    # Extract URLs for artwork - use safe fallbacks
    try:
        # Ensure downloaded_art is a dict
        if not isinstance(downloaded_art, dict):
            logger.warning(f"Downloaded_art is not a dict: {type(downloaded_art)}")
            downloaded_art = {}
        
        # For music, check for front cover, then thumbnail, then poster
        # Priority: front (from album.front), thumbnail, poster
        front_cover_path = ""
        if isinstance(downloaded_art, dict):
            priority_front_keys = ["front", "frontcover", "cover", "thumbnail", "poster"]
            for front_key in priority_front_keys:
                if downloaded_art.get(front_key):
                    front_cover_path = downloaded_art.get(front_key)
                    break
        album_poster_url = f"/media/{front_cover_path}" if front_cover_path else ""
        # Collect all fanart variants for slideshow
        fanart_variants = []
        
        # First, check for extrafanart folder images (dynamic keys like extrafanart_main, extrafanart_fanart2, etc.)
        # Note: Files in extrafanart folder are named fanart.jpg, fanart2.jpg, etc.
        for key, value in downloaded_art.items():
            if key.startswith("extrafanart"):
                fanart_variants.append(f"/media/{value}")
        
        # If no extrafanart found, fall back to numbered fanart variants
        if not fanart_variants:
            fanart_keys = ["fanart", "fanart1", "fanart2", "fanart3", "fanart4", "fanart5", "fanart6", "fanart7", "fanart8", "fanart9"]
            for fanart_key in fanart_keys:
                if downloaded_art.get(fanart_key):
                    fanart_variants.append(f"/media/{downloaded_art.get(fanart_key)}")
        
        # If no downloaded fanarts, try to get from various sources
        if not fanart_variants:
            fallback_fanart = ""
            if isinstance(album_details, dict) and album_details.get("fanart"):
                fallback_fanart = album_details.get("fanart")
                logger.debug(f"Using album fanart: {fallback_fanart}")
            elif isinstance(artist_details, dict) and artist_details.get("fanart"):
                fallback_fanart = artist_details.get("fanart")
                logger.debug(f"Using artist fanart: {fallback_fanart}")
            elif item.get("art", {}).get("fanart"):
                fallback_fanart = item.get("art", {}).get("fanart")
                logger.debug(f"Using item fanart: {fallback_fanart}")
            elif item.get("art", {}).get("albumartist.fanart"):
                fallback_fanart = item.get("art", {}).get("albumartist.fanart")
                logger.debug(f"Using albumartist.fanart: {fallback_fanart}")
            elif item.get("art", {}).get("artist.fanart"):
                fallback_fanart = item.get("art", {}).get("artist.fanart")
                logger.debug(f"Using artist.fanart: {fallback_fanart}")
            
            if fallback_fanart:
                fanart_variants.append(fallback_fanart)
        
        logger.debug(f"Fanart variants found: {len(fanart_variants)}")
        logger.debug(f"Fanart variants content: {fanart_variants}")
        # For music, don't use fanart as primary background - only for slideshow
        # The slideshow will handle all fanart variants
        fanart_url = ""
    except Exception as e:
        logger.warning(f"Artwork URL generation failed: {e}")
        logger.warning(f"Exception type: {type(e)}")
        import traceback
        logger.warning(f"Traceback: {traceback.format_exc()}")
        album_poster_url = ""
        fanart_url = ""
        fanart_variants = []
    # Look for both discart and cdart for music
    discart_url = f"/media/{downloaded_art.get('discart')}" if downloaded_art.get("discart") else ""
    cdart_url = f"/media/{downloaded_art.get('cdart')}" if downloaded_art.get("cdart") else ""
    # Use discart if available, otherwise use cdart
    discart_display_url = discart_url if discart_url else cdart_url
    back_cover_path = ""
    if isinstance(downloaded_art, dict):
        priority_back_keys = ["back", "backcover", "rear", "rearcover"]
        for back_key in priority_back_keys:
            if downloaded_art.get(back_key):
                back_cover_path = downloaded_art.get(back_key)
                break
        if not back_cover_path:
            for key, value in downloaded_art.items():
                if not value or not isinstance(value, str):
                    continue
                key_lower = str(key).lower()
                value_lower = value.lower()
                if "background" in key_lower or "background" in value_lower:
                    continue
                if "back" in key_lower or "backcover" in key_lower or "rear" in key_lower:
                    back_cover_path = value
                    break
                if "back" in value_lower or "rear" in value_lower:
                    back_cover_path = value
                    break
    back_cover_url = f"/media/{back_cover_path}" if back_cover_path else ""
    if back_cover_path:
        logger.debug(f"Back cover detected: {back_cover_path}")
    # Only use banner if it's not actually a fanart image
    banner_url = ""
    if downloaded_art.get("banner"):
        # Check if the banner is actually a fanart by looking at the filename
        banner_filename = downloaded_art.get("banner", "")
        logger.debug(f"Banner filename: {banner_filename}")
        if not any(fanart_name in banner_filename.lower() for fanart_name in ["fanart", "fanart1", "fanart2", "fanart3", "fanart4"]):
            banner_url = f"/media/{downloaded_art.get('banner')}"
            logger.debug(f"Using banner: {banner_url}")
        else:
            logger.debug("Skipping banner as it appears to be a fanart image")
    clearlogo_url = f"/media/{downloaded_art.get('clearlogo')}" if downloaded_art.get("clearlogo") else ""
    # Logo fallback: some libraries only have clearart.png in the artist folder
    if not clearlogo_url and downloaded_art.get("clearart"):
        clearlogo_url = f"/media/{downloaded_art.get('clearart')}"
    # For music, do not render clearart under the album cover (often mistaken for fanart)
    clearart_url = ""
    if downloaded_art.get("clearart"):
        clearart_filename = downloaded_art.get("clearart", "")
        logger.debug(f"Clearart filename: {clearart_filename}")
        logger.debug("Skipping clearart for music to prevent fanart display underneath album cover")
    
    # Extract music information
    title = item.get("title", "Untitled Track")
    album = item.get("album", "")
    artist = item.get("artist", [])
    artist_names = ", ".join(artist) if artist else "Unknown Artist"

    # Get additional album info (fallback to item data if API failed)
    album_year = album_details.get("year", item.get("year", "")) if isinstance(album_details, dict) else item.get("year", "")
    album_rating = album_details.get("rating", item.get("rating", 0)) if isinstance(album_details, dict) else item.get("rating", 0)
    
    # Get additional song info - ensure details is a dict
    if not isinstance(details, dict):
        details = {}
    song_lyrics = details.get("lyrics", "")
    song_disc = details.get("disc", 0)
    song_samplerate = details.get("samplerate", 0)
    song_bitrate = details.get("bitrate", 0)
    song_channels = details.get("channels", 0)
    song_track = details.get("track", 0)
    record_label = album_details.get("albumlabel", "") if isinstance(album_details, dict) else ""
    
    # Get album details for totaldiscs
    album_details = details.get("album", {}) if isinstance(details, dict) else {}
    total_discs = album_details.get("totaldiscs", 1)
    
    # Create music badge components
    # Only show disc badge if album has 2 or more discs
    disc_badge = f"Disc {song_disc}" if song_disc > 0 and total_discs >= 2 else ""
    track_badge = f"Track {song_track:02d}" if song_track > 0 else ""
    title_badge = title if title else ""
    
    
    # Get additional artist info - ensure artist_details is a dict
    if not isinstance(artist_details, dict):
        artist_details = {}
    artist_born = artist_details.get("born", "")
    artist_genre = artist_details.get("genre", [])
    artist_style = artist_details.get("style", [])
    
    # If API calls failed, use basic item data
    if not isinstance(album_details, dict) and album:
        album_details = {"title": album, "year": item.get("year", "")}
    if not isinstance(artist_details, dict) and artist_names:
        artist_details = {"name": artist_names}
    
    # Debug logging
    logger.debug(f"Album details: {album_details}")
    logger.debug(f"Artist details: {artist_details}")
    logger.debug(f"Fanart URL: {fanart_url}")
    logger.debug(f"Album year: {album_year}, Album rating: {album_rating}")
    
    # Get rating from details or fallback - ensure details is a dict
    if not isinstance(details, dict):
        details = {}
    rating = round(details.get("rating", 0.0), 1)
    rating_html = f"<strong>⭐ {rating}</strong>" if rating > 0 else ""
    
    
    # Extract streamdetails - ensure details is a dict
    if not isinstance(details, dict):
        details = {}
    streamdetails = details.get("streamdetails", {})
    if not isinstance(streamdetails, dict):
        streamdetails = {}
    audio_info = streamdetails.get("audio", []) if isinstance(streamdetails.get("audio"), list) else []
    
    # Get enhanced audio information using XBMC.GetInfoLabels for real-time data
    enhanced_audio_info = {}
    try:
        from kodi_np.rpc import kodi_rpc

        logger.debug("Attempting to get enhanced audio info via XBMC.GetInfoLabels")
        
        # Get real-time audio information
        infolabels_response = kodi_rpc("XBMC.GetInfoLabels", {
            "labels": [
                "VideoPlayer.AudioCodec",
                "VideoPlayer.Container",
                "MusicPlayer.BitsPerSample",
                "Player.Process(AudioSamplerate)",
                "Player.Process(AudioChannels)"
            ]
        })
        
        logger.debug(f"XBMC.GetInfoLabels response: {infolabels_response}")
        
        if infolabels_response and infolabels_response.get("result"):
            enhanced_audio_info = infolabels_response.get("result", {})
            logger.debug(f"Enhanced audio info extracted: {enhanced_audio_info}")
        else:
            logger.debug("No result in XBMC.GetInfoLabels response")
    except Exception as e:
        logger.debug(f"Failed to get enhanced audio info: {e}")
        import traceback
        logger.debug(f"Traceback: {traceback.format_exc()}")
        enhanced_audio_info = {}
    
    # Genre and formatting - ensure details is a dict
    if not isinstance(details, dict):
        details = {}
    genre_list = details.get("genre", [])
    if not isinstance(genre_list, list):
        genre_list = []
    genres = [g.capitalize() for g in genre_list]
    genre_badges = genres[:3]
    
    # Enhanced audio codec information using real-time data
    audio_codec = format_audio_codec(enhanced_audio_info.get("VideoPlayer.AudioCodec", audio_info[0].get("codec", "Unknown") if audio_info else "Unknown"))
    
    # Get audio bits per sample from enhanced audio info
    audio_bits_per_sample = enhanced_audio_info.get("MusicPlayer.BitsPerSample", 0)
    try:
        audio_bits_per_sample = int(audio_bits_per_sample) if audio_bits_per_sample else 0
    except (ValueError, TypeError):
        audio_bits_per_sample = 0
    
    # If MusicPlayer.BitsPerSample doesn't work, try to get from streamdetails
    if audio_bits_per_sample == 0 and audio_info:
        # Try to estimate from bitrate and sample rate
        audio_samplerate = enhanced_audio_info.get("Player.Process(AudioSamplerate)", 0)
        audio_channels = enhanced_audio_info.get("Player.Process(AudioChannels)", 0)
        try:
            audio_samplerate = int(audio_samplerate) if audio_samplerate else 0
            audio_channels = int(audio_channels) if audio_channels else 0
            if audio_samplerate > 0 and audio_channels > 0:
                # Rough estimation: if sample rate is 96kHz or higher, likely 24-bit
                audio_bits_per_sample = 24 if audio_samplerate >= 96000 else 16
        except (ValueError, TypeError):
            pass
    
    # New enhanced audio information - use real-time data first, fallback to filename extension
    container_format = enhanced_audio_info.get("VideoPlayer.Container", "").upper()
    # Only use filename extension as fallback if container is empty from JSON
    if not container_format and item.get("file"):
        file_path = item.get("file", "")
        if file_path.lower().endswith('.flac'):
            container_format = "FLAC"
        elif file_path.lower().endswith('.mp3'):
            container_format = "MP3"
        elif file_path.lower().endswith('.m4a'):
            container_format = "M4A"
        elif file_path.lower().endswith('.wav'):
            container_format = "WAV"
        elif file_path.lower().endswith('.ogg'):
            container_format = "OGG"
        elif file_path.lower().endswith('.aac'):
            container_format = "AAC"
    
    # Playback progress
    elapsed = progress_data.get("elapsed", 0)
    duration = progress_data.get("duration", 0)
    percent = int((elapsed / duration) * 100) if duration else 0
    paused = progress_data.get("paused", False)
    
    # Debug: Check fanart_variants before HTML generation
    logger.debug(f"Before HTML generation - fanart_variants length: {len(fanart_variants)}")
    logger.debug(f"Before HTML generation - fanart_variants content: {fanart_variants}")

    lyrics_bootstrap = {
        "artist": artist_names or "",
        "title": title or "",
        "album": album or "",
        "duration": duration,
        "kodi_lyrics": song_lyrics or "",
    }
    lyrics_bootstrap_json = json.dumps(lyrics_bootstrap).replace("<", "\\u003c")
    music_meta_bootstrap = {
        "artist": artist_names or "",
        "album": album or "",
        "album_id": details.get("albumid") if isinstance(details, dict) else None,
        "artist_id": None,
        "need_album": not bool(
            ((album_details.get("description") if isinstance(album_details, dict) else "") or "").strip()
        ),
        "need_artist": not bool(
            ((artist_details.get("description") if isinstance(artist_details, dict) else "") or "").strip()
        ),
    }
    if isinstance(details, dict):
        raw_artist = details.get("artistid")
        if isinstance(raw_artist, list) and raw_artist:
            music_meta_bootstrap["artist_id"] = raw_artist[0]
        elif raw_artist is not None and not isinstance(raw_artist, list):
            music_meta_bootstrap["artist_id"] = raw_artist
    music_meta_bootstrap_json = json.dumps(music_meta_bootstrap).replace("<", "\\u003c")

    artist_names = html_escape(artist_names)
    album = html_escape(album)
    album_year = html_escape(album_year)
    disc_badge = html_escape(disc_badge)
    track_badge = html_escape(track_badge)
    title_badge = html_escape(title_badge)
    audio_codec = html_escape(audio_codec)
    container_format = html_escape(container_format)
    record_label = html_escape(record_label)
    genre_badges = [html_escape(genre) for genre in genre_badges]
    album_description = html_escape(album_details.get("description", "")) if isinstance(album_details, dict) else ""
    artist_description = html_escape(artist_details.get("description", "")) if isinstance(artist_details, dict) else ""
    artist_born = html_escape(artist_born)
    artist_genre = [html_escape(genre) for genre in artist_genre] if isinstance(artist_genre, list) else ([html_escape(artist_genre)] if artist_genre else [])
    artist_style = [html_escape(style) for style in artist_style] if isinstance(artist_style, list) else ([html_escape(artist_style)] if artist_style else [])
    
    # Precomputed HTML fragments for template
    fanart_debug_html = (
        f"<!-- DEBUG: fanart_variants length: {len(fanart_variants)}, content: {fanart_variants} -->"
    )
    fanart_slides_html = build_fanart_slides_html(
        fanart_variants, empty="<!-- No fanart variants available -->"
    )
    fanart_pending_json = build_fanart_pending_json(details, session_id)
    poster_container_extra_class = " flip-enabled" if back_cover_url else ""
    discart_html = (
        f"<div class='discart-wrapper'><img class='discart' src='{discart_display_url}' /></div>"
        if discart_display_url
        else ""
    )
    if album_poster_url and back_cover_url:
        album_poster_html = (
            "<div class='album-flip' role='button' tabindex='0' aria-pressed='false' aria-label='Flip album cover'>"
            f"<img class='poster front-face' src='{album_poster_url}' alt='Album front cover' />"
            f"<img class='poster back-face' src='{back_cover_url}' alt='Album back cover' />"
            "</div>"
            "<button type='button' class='flip-indicator' aria-label='Show album back cover'>Show Back</button>"
        )
    elif album_poster_url:
        album_poster_html = f"<img class='poster' src='{album_poster_url}' alt='Album front cover' />"
    else:
        album_poster_html = ""
    clearart_html = f"<img class='clearart' src='{clearart_url}' />" if clearart_url else ""
    if clearlogo_url:
        title_banner_html = f"<img class='logo' src='{clearlogo_url}' />"
    elif banner_url:
        title_banner_html = f"<img class='banner' src='{banner_url}' />"
    else:
        title_banner_html = f"<h2 style='margin-bottom: 4px;'>🎵 {artist_names}</h2>"
    album_badge_html = (
        f"<span class='music-badge' id='soft-badge-album'>{album}" + (f" ({album_year})" if album_year else "") + "</span>"
        if album
        else "<span class='music-badge' id='soft-badge-album' style='display:none'></span>"
    )
    disc_badge_html = f"<span class='music-badge' id='soft-badge-disc'>{disc_badge}</span>" if disc_badge else "<span class='music-badge' id='soft-badge-disc' style='display:none'></span>"
    track_badge_html = f"<span class='music-badge' id='soft-badge-track'>{track_badge}</span>" if track_badge else "<span class='music-badge' id='soft-badge-track' style='display:none'></span>"
    title_badge_html = f"<span class='music-badge' id='soft-badge-title'>{title_badge}</span>" if title_badge else "<span class='music-badge' id='soft-badge-title' style='display:none'></span>"
    album_rating_html = (
        f"<div class='album-title'>Album Rating: ⭐ {album_rating:.1f}</div>"
        if album_rating > 0
        else ""
    )
    container_badge_html = (
        f"<span class='badge'>{container_format}</span>"
        if container_format and container_format != audio_codec
        else ""
    )
    total_discs_badge_html = f"<span class='badge'>Discs: {total_discs}</span>" if total_discs > 0 else ""
    channels_badge_html = f"<span class='badge'>{song_channels}ch</span>" if song_channels > 0 else ""
    bitrate_badge_html = f"<span class='badge'>{song_bitrate} kbps</span>" if song_bitrate > 0 else ""
    samplerate_badge_html = (
        f"<span class='badge'>{song_samplerate / 1000:.1f} kHz</span>" if song_samplerate > 0 else ""
    )
    bitdepth_badge_html = (
        f"<span class='badge'>{audio_bits_per_sample}-bit</span>" if audio_bits_per_sample > 0 else ""
    )
    record_label_badge_html = f"<span class='badge'>{record_label}</span>" if record_label else ""
    genre_badges_html = "".join(f"<span class='badge'>{g}</span>" for g in genre_badges)
    elapsed_display = format_playback_time(elapsed, duration)
    duration_display = format_playback_time(duration, duration)
    paused_js = str(paused).lower()
    album_description_html = (
        f"<div class='album-description' id='soft-album-description'><p id='soft-album-description-text'>{album_description}</p></div>"
        if album_description
        else "<div class='album-description' id='soft-album-description' style='display:none'><p id='soft-album-description-text'></p></div>"
    )
    artist_bio_parts = []
    if artist_description:
        artist_bio_parts.append("<div class='album-description' id='soft-artist-bio'>")
        if artist_born:
            artist_bio_parts.append(f"<p id='soft-artist-born'><strong>Born:</strong> {artist_born}</p>")
        if artist_genre:
            artist_bio_parts.append(f"<p><strong>Genre:</strong> {', '.join(artist_genre)}</p>")
        if artist_style:
            artist_bio_parts.append(f"<p><strong>Style:</strong> {', '.join(artist_style)}</p>")
        artist_bio_parts.append(f"<p id='soft-artist-bio-text'>{artist_description}</p></div>")
    artist_bio_html = (
        "".join(artist_bio_parts)
        if artist_bio_parts
        else "<div class='album-description' id='soft-artist-bio' style='display:none'><p id='soft-artist-bio-text'></p></div>"
    )

    music_info_panel_html = f"""
            <div class="info-panel" id="music-info-panel">
              <div class="info-panel-tabs" role="tablist" aria-label="Music details">
                <button type="button" class="info-panel-tab" role="tab" data-panel="lyrics" aria-selected="false">Lyrics</button>
                <button type="button" class="info-panel-tab" role="tab" data-panel="album" aria-selected="false">Album</button>
                <button type="button" class="info-panel-tab" role="tab" data-panel="artist" aria-selected="false">Artist</button>
              </div>
              <div class="info-panel-pane" id="panel-lyrics" role="tabpanel" hidden>
                <div class="lyrics-panel" id="lyrics-panel">
                  <div class="lyrics-inner" id="lyrics-inner"></div>
                  <div class="lyrics-empty" id="lyrics-empty">Loading lyrics…</div>
                </div>
              </div>
              <div class="info-panel-pane" id="panel-album" role="tabpanel" hidden>
                {album_description_html if album_description else '<div class="album-description" id="soft-album-description"><p id="soft-album-description-text" class="info-panel-empty">No album description available.</p></div>'}
              </div>
              <div class="info-panel-pane" id="panel-artist" role="tabpanel" hidden>
                {artist_bio_html if artist_description else '<div class="album-description" id="soft-artist-bio"><p id="soft-artist-bio-text" class="info-panel-empty">No artist biography available.</p></div>'}
              </div>
            </div>
            <script type="application/json" id="lyrics-bootstrap">{lyrics_bootstrap_json}</script>
            <script type="application/json" id="music-meta-bootstrap">{music_meta_bootstrap_json}</script>
    """

    # Wrap album art region for soft updates
    album_poster_html = f"<div id='soft-album-art'>{album_poster_html}</div>"
    discart_html = f"<div id='soft-discart'>{discart_html}</div>" if discart_html else "<div id='soft-discart'></div>"

    soft_identity = {
        "media_type": "song",
        "item_id": f"song_{item.get('id')}" if item.get("id") is not None else "",
        "tvshow_id": None,
        "season": None,
        "album_id": details.get("albumid") if isinstance(details, dict) else None,
        "artist_id": None,
    }
    if isinstance(details, dict):
        raw_artist = details.get("artistid")
        if isinstance(raw_artist, list) and raw_artist:
            soft_identity["artist_id"] = raw_artist[0]
        elif raw_artist is not None and not isinstance(raw_artist, list):
            soft_identity["artist_id"] = raw_artist
        # album details object shouldn't overwrite albumid — GetSongDetails merges albumid onto details
        if soft_identity["album_id"] is None and isinstance(album_details, dict):
            soft_identity["album_id"] = album_details.get("albumid")
    soft_identity_json = json.dumps(soft_identity)

    return render_template(
        "music_nowplaying.html",
        percent=percent,
        elapsed=elapsed,
        duration=duration,
        paused_js=paused_js,
        fanart_debug_html=fanart_debug_html,
        fanart_slides_html=fanart_slides_html,
        fanart_pending_json=fanart_pending_json,
        poster_container_extra_class=poster_container_extra_class,
        discart_html=discart_html,
        album_poster_html=album_poster_html,
        clearart_html=clearart_html,
        title_banner_html=title_banner_html,
        album_badge_html=album_badge_html,
        disc_badge_html=disc_badge_html,
        track_badge_html=track_badge_html,
        title_badge_html=title_badge_html,
        album_rating_html=album_rating_html,
        rating_html=rating_html,
        audio_codec=audio_codec,
        container_badge_html=container_badge_html,
        total_discs_badge_html=total_discs_badge_html,
        channels_badge_html=channels_badge_html,
        bitrate_badge_html=bitrate_badge_html,
        samplerate_badge_html=samplerate_badge_html,
        bitdepth_badge_html=bitdepth_badge_html,
        record_label_badge_html=record_label_badge_html,
        genre_badges_html=genre_badges_html,
        elapsed_display=elapsed_display,
        duration_display=duration_display,
        music_info_panel_html=music_info_panel_html,
        soft_identity_json=soft_identity_json,
        up_next_html=build_up_next_html(details),
    )
