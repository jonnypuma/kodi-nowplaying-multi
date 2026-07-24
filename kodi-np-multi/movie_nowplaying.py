"""
Movie-specific HTML generation for Kodi Now Playing application.
Handles movie display with discart spinning animation and movie-specific layout.
"""
import logging
from html import escape
from flask import render_template

logger = logging.getLogger(__name__)


def html_escape(value):
    return escape(str(value), quote=True) if value is not None else ""


def _format_playback_time(seconds: int, reference_duration: int | None = None) -> str:
    """Format seconds as MM:SS or HH:MM:SS depending on duration."""
    duration = reference_duration if reference_duration is not None else seconds
    if duration < 3600:
        return f"{seconds // 60:02d}:{seconds % 60:02d}"
    return f"{seconds // 3600:02d}:{(seconds // 60) % 60:02d}:{seconds % 60:02d}"

def generate_html(item, session_id, downloaded_art, progress_data, details):
    """
    Generate HTML for movie display.
    
    Args:
        item (dict): Media item from Kodi API
        session_id (str): Session ID for file naming
        downloaded_art (dict): Downloaded artwork files
        progress_data (dict): Playback progress information
        details (dict): Detailed media information
        
    Returns:
        str: HTML content for movie display
    """
    # Extract URLs for artwork
    poster_url = f"/media/{downloaded_art.get('poster')}" if downloaded_art.get("poster") else ""
    
    # Collect all fanart variants for slideshow
    fanart_variants = []
    
    # Check for all possible fanart variants in order of preference
    fanart_keys = ["fanart", "fanart1", "fanart2", "fanart3", "fanart4", "fanart5", "fanart6", "fanart7", "fanart8", "fanart9"]
    for fanart_key in fanart_keys:
        if downloaded_art.get(fanart_key):
            fanart_variants.append(f"/media/{downloaded_art.get(fanart_key)}")
    
    # Also check for extrafanart folder images (dynamic keys like extrafanart_main, extrafanart_fanart2, etc.)
    for key, value in downloaded_art.items():
        if key.startswith("extrafanart"):
            fanart_variants.append(f"/media/{value}")
    
    # Use first fanart as primary, or empty string if none
    fanart_url = fanart_variants[0] if fanart_variants else ""
    
    # Debug logging for fanart variants
    logger.debug(f"Movie fanart variants found: {len(fanart_variants)}")
    logger.debug(f"Movie fanart variants: {fanart_variants}")
    
    discart_url = f"/media/{downloaded_art.get('discart')}" if downloaded_art.get("discart") else ""
    banner_url = f"/media/{downloaded_art.get('banner')}" if downloaded_art.get("banner") else ""
    clearlogo_url = f"/media/{downloaded_art.get('clearlogo')}" if downloaded_art.get("clearlogo") else ""
    clearart_url = f"/media/{downloaded_art.get('clearart')}" if downloaded_art.get("clearart") else ""
    
    # Extract movie information
    title = item.get("title", "Untitled")
    plot = item.get("plot", item.get("description", ""))
    
    # Extract IMDb ID and construct URL - ensure details is a dict
    if not isinstance(details, dict):
        details = {}
    imdb_id = details.get("uniqueid", {}).get("imdb", "")
    imdb_url = f"https://www.imdb.com/title/{imdb_id}" if imdb_id else ""
    
    # Get rating from details or fallback
    rating = round(details.get("rating", 0.0), 1)
    rating_html = f"<strong>⭐ {rating}</strong>" if rating > 0 else ""
    
    def format_hdr_label(value: str) -> str:
        raw = (value or "").strip()
        if not raw:
            return "SDR"
        key = raw.replace(" ", "").replace("_", "").upper()
        mapping = {
            "DOLBYVISION": "Dolby Vision",
            "HDR10PLUS": "HDR10+",
            "HDR10": "HDR10",
            "HLG": "HLG",
            "SDR": "SDR"
        }
        if key in mapping:
            return mapping[key]
        return raw.replace("_", " ").title().replace("Hdr", "HDR").replace("Sdr", "SDR").replace("Hlg", "HLG")

    def format_audio_codec(value: str) -> str:
        raw = (value or "").strip()
        if not raw:
            return "Unknown"
        key = raw.replace(" ", "").replace("_", "").upper()
        mapping = {
            "TRUEHDATMOS": "TrueHD Atmos",
            "TRUEHD": "TrueHD",
            "DTSHDMA": "DTS-HD MA",
            "DTSHD": "DTS-HD",
            "DTSX": "DTS:X",
            "DTS": "DTS",
            "EAC3": "E-AC3",
            "AC3": "AC3",
            "AAC": "AAC",
            "FLAC": "FLAC",
            "PCM": "PCM",
            "LPCM": "LPCM",
            "OPUS": "Opus",
            "VORBIS": "Vorbis",
            "MP3": "MP3",
            "WMA": "WMA",
            "ALAC": "ALAC"
        }
        if key in mapping:
            return mapping[key]
        return raw.replace("_", " ").title()

    # Initialize defaults
    director_names = "N/A"
    cast_names = "N/A"
    hdr_type = "SDR"
    audio_languages = "N/A"
    subtitle_languages = "N/A"
    
    # Extract streamdetails - ensure details is a dict
    if not isinstance(details, dict):
        details = {}
    streamdetails = details.get("streamdetails", {})
    if not isinstance(streamdetails, dict):
        streamdetails = {}
    
    # If streamdetails is empty in details, try to get it from item
    if not streamdetails and item.get("streamdetails"):
        streamdetails = item.get("streamdetails", {})
        logger.debug(f"Using streamdetails from item: {streamdetails}")
    
    video_info = streamdetails.get("video", [{}])[0] if isinstance(streamdetails.get("video"), list) and len(streamdetails.get("video", [])) > 0 else {}
    audio_info = streamdetails.get("audio", []) if isinstance(streamdetails.get("audio"), list) else []
    subtitle_info = streamdetails.get("subtitle", []) if isinstance(streamdetails.get("subtitle"), list) else []
    
    # HDR type
    hdr_type = format_hdr_label(video_info.get("hdrtype", ""))
    
    # Get enhanced video information using XBMC.GetInfoLabels for real-time data
    enhanced_video_info = {}
    player_id = 1  # Default, will be updated if we can get active player
    try:
        from kodi_np.rpc import kodi_rpc

        # Get active player ID
        try:
            active_players_response = kodi_rpc("Player.GetActivePlayers", {})
            if active_players_response and active_players_response.get("result"):
                active_players = active_players_response.get("result", [])
                if active_players:
                    player_id = active_players[0].get("playerid", 1)
                    logger.debug(f"Got active player ID: {player_id}")
        except Exception as e:
            logger.debug(f"Failed to get active player ID, using default 1: {e}")
        
        logger.debug(f"Attempting to get enhanced video info via XBMC.GetInfoLabels")
        
        # Get real-time video information
        infolabels_response = kodi_rpc("XBMC.GetInfoLabels", {
            "labels": [
                "VideoPlayer.VideoAspect",
                "VideoPlayer.VideoAspectLabel", 
                "VideoPlayer.VideoCodec",
                "VideoPlayer.Container",
                "VideoPlayer.AudioCodec",
                "Player.Process(VideoHeight)",
                "Player.Process(VideoWidth)",
                "VideoPlayer.AudioLanguage",
                "VideoPlayer.SubtitlesLanguage",
                "VideoPlayer.Year"
            ]
        })
        
        # Try to get available audio streams using Player.GetProperties
        try:
            audio_streams_response = kodi_rpc("Player.GetProperties", {
                "playerid": player_id,
                "properties": ["audiostreams"]
            })
            logger.debug(f"Player.GetProperties audiostreams response: {audio_streams_response}")
            
            if audio_streams_response and audio_streams_response.get("result"):
                audio_streams = audio_streams_response.get("result", {}).get("audiostreams", [])
                logger.debug(f"Available audio streams: {audio_streams}")
                
                # Convert audio streams to our format
                if audio_streams:
                    audio_info = []
                    for stream in audio_streams:
                        if isinstance(stream, dict) and stream.get("language"):
                            audio_info.append({
                                "language": stream.get("language", ""),
                                "name": stream.get("name", ""),
                                "index": stream.get("index", 0),
                                "codec": stream.get("codec", ""),
                                "channels": stream.get("channels", 0)
                            })
                    logger.debug(f"Converted audio_info from Player.GetProperties: {audio_info}")
        except Exception as e:
            logger.debug(f"Failed to get audio streams: {e}")
        
        # Try to get available subtitle streams using Player.GetProperties
        try:
            subtitle_streams_response = kodi_rpc("Player.GetProperties", {
                "playerid": player_id,
                "properties": ["subtitles"]
            })
            logger.debug(f"Player.GetProperties subtitles response: {subtitle_streams_response}")
            
            if subtitle_streams_response and subtitle_streams_response.get("result"):
                subtitle_streams = subtitle_streams_response.get("result", {}).get("subtitles", [])
                logger.debug(f"Available subtitle streams: {subtitle_streams}")
                
                # Convert subtitle streams to our format
                if subtitle_streams:
                    subtitle_info = []
                    for stream in subtitle_streams:
                        if isinstance(stream, dict) and stream.get("language"):
                            subtitle_info.append({
                                "language": stream.get("language", ""),
                                "name": stream.get("name", ""),
                                "index": stream.get("index", 0)
                            })
                    logger.debug(f"Converted subtitle_info from Player.GetProperties: {subtitle_info}")
        except Exception as e:
            logger.debug(f"Failed to get subtitle streams: {e}")
        
        logger.debug(f"XBMC.GetInfoLabels response: {infolabels_response}")
        
        if infolabels_response and infolabels_response.get("result"):
            enhanced_video_info = infolabels_response.get("result", {})
            logger.debug(f"Enhanced video info extracted: {enhanced_video_info}")
        else:
            logger.debug(f"No result in XBMC.GetInfoLabels response")
    except Exception as e:
        logger.debug(f"Failed to get enhanced video info: {e}")
        import traceback
        logger.debug(f"Traceback: {traceback.format_exc()}")
        enhanced_video_info = {}
    
    # Debug audio and subtitle info
    logger.debug(f"Movie audio_info: {audio_info}")
    logger.debug(f"Movie subtitle_info: {subtitle_info}")
    
    # Get current playing languages from InfoLabels
    audio_language_infolabel = enhanced_video_info.get("VideoPlayer.AudioLanguage", "")
    subtitle_language_infolabel = enhanced_video_info.get("VideoPlayer.SubtitlesLanguage", "")
    
    # Language code normalization mapping
    language_normalization = {
        'GER': 'DEU',  # German: ger -> deu
        'ENG': 'ENG',  # English: eng -> eng
        'FRE': 'FRA',  # French: fre -> fra
        'SPA': 'SPA',  # Spanish: spa -> spa
        'ITA': 'ITA',  # Italian: ita -> ita
        'POR': 'POR',  # Portuguese: por -> por
        'RUS': 'RUS',  # Russian: rus -> rus
        'JPN': 'JPN',  # Japanese: jpn -> jpn
        'KOR': 'KOR',  # Korean: kor -> kor
        'CHI': 'CHI',  # Chinese: chi -> chi
    }
    
    # Get all available languages from streamdetails and normalize them
    all_audio_languages = sorted(set(
        language_normalization.get(a.get("language", "")[:3].upper(), a.get("language", "")[:3].upper()) 
        for a in audio_info if a.get("language")
    ))
    all_subtitle_languages = sorted(set(
        language_normalization.get(s.get("language", "")[:3].upper(), s.get("language", "")[:3].upper()) 
        for s in subtitle_info if s.get("language")
    ))
    
    # Current playing languages (for default display) - normalize immediately
    current_audio = audio_language_infolabel[:3].upper() if audio_language_infolabel else (all_audio_languages[0] if all_audio_languages else "N/A")
    current_subtitle = subtitle_language_infolabel[:3].upper() if subtitle_language_infolabel else (all_subtitle_languages[0] if all_subtitle_languages else "N/A")
    
    # Normalize current language codes to match streamdetails format
    current_audio = language_normalization.get(current_audio, current_audio)
    current_subtitle = language_normalization.get(current_subtitle, current_subtitle)
    
    # Ensure current language is included in the all_languages list for expandable functionality
    if current_audio and current_audio != "N/A" and current_audio not in all_audio_languages:
        all_audio_languages.append(current_audio)
        all_audio_languages = sorted(set(all_audio_languages))
    if current_subtitle and current_subtitle != "N/A" and current_subtitle not in all_subtitle_languages:
        all_subtitle_languages.append(current_subtitle)
        all_subtitle_languages = sorted(set(all_subtitle_languages))
    
    logger.debug(f"Movie current audio: {current_audio}, all audio: {all_audio_languages}, count: {len(all_audio_languages)}")
    logger.debug(f"Movie current subtitle: {current_subtitle}, all subtitle: {all_subtitle_languages}, count: {len(all_subtitle_languages)}")
    logger.debug(f"Movie audio badge will have expandable class: {len(all_audio_languages) > 1}")
    logger.debug(f"Movie subtitle badge will have expandable class: {len(all_subtitle_languages) > 1}")
    
    # Release year - try InfoLabels first, then fallback to item
    release_year = enhanced_video_info.get("VideoPlayer.Year", "")
    if not release_year:
        release_year = item.get("year", "")
    
    # Director - ensure details is a dict
    if not isinstance(details, dict):
        details = {}
    if "director" in details:
        director_list = details.get("director", [])
        if isinstance(director_list, list):
            director_names = ", ".join(director_list) or "N/A"
    
    # Studio and tagline
    studio_list = details.get("studio", [])
    if isinstance(studio_list, list) and studio_list:
        studio_names = ", ".join(studio_list)
    else:
        studio_names = ""
    
    tagline = details.get("tagline", "")
    
    # Cast - limit to top 10 actors
    cast_list = details.get("cast", [])
    if isinstance(cast_list, list) and cast_list:
        cast_names = ", ".join([c.get("name") for c in cast_list[:10] if isinstance(c, dict) and c.get("name")]) or "N/A"
    
    # Genre and formatting
    genre_list = details.get("genre", [])
    if not isinstance(genre_list, list):
        genre_list = []
    genres = [g.capitalize() for g in genre_list]
    genre_badges = genres[:3]
    
    # Format media info - use enhanced video info first, fallback to streamdetails
    resolution = ""
    height = enhanced_video_info.get("Player.Process(VideoHeight)", 0)
    width = enhanced_video_info.get("Player.Process(VideoWidth)", 0)
    
    # Convert to int if they're strings, handle comma formatting
    try:
        if height:
            height = int(str(height).replace(',', ''))
        else:
            height = 0
        if width:
            width = int(str(width).replace(',', ''))
        else:
            width = 0
    except (ValueError, TypeError):
        height = 0
        width = 0
    
    if not height:
        height = video_info.get("height", 0)
    if not width:
        width = video_info.get("width", 0)
    
    # Use width for 4K detection as it's more reliable
    if width >= 3840 or height >= 2160:
        resolution = "4K"
    elif height >= 1080:
        resolution = "1080p"
    elif height >= 720:
        resolution = "720p"
    
    # Enhanced codec information using real-time data
    video_codec = enhanced_video_info.get("VideoPlayer.VideoCodec", video_info.get("codec", "Unknown")).upper()
    audio_codec = format_audio_codec(enhanced_video_info.get("VideoPlayer.AudioCodec", audio_info[0].get("codec", "Unknown") if audio_info else "Unknown"))
    channels = audio_info[0].get("channels", 0) if audio_info else 0
    
    # New enhanced video information
    aspect_ratio = enhanced_video_info.get("VideoPlayer.VideoAspectLabel", "")
    # If VideoAspectLabel is empty, convert numeric aspect ratio to label
    if not aspect_ratio and enhanced_video_info.get("VideoPlayer.VideoAspect"):
        aspect_numeric = float(enhanced_video_info.get("VideoPlayer.VideoAspect", "0"))
        if aspect_numeric > 0:
            # Convert numeric aspect ratio to common labels
            if 1.77 <= aspect_numeric <= 1.78:
                aspect_ratio = "16:9"
            elif 2.35 <= aspect_numeric <= 2.40:
                aspect_ratio = "21:9"
            elif 1.33 <= aspect_numeric <= 1.37:
                aspect_ratio = "4:3"
            elif 1.85 <= aspect_numeric <= 1.90:
                aspect_ratio = "1.85:1"
            elif 2.20 <= aspect_numeric <= 2.25:
                aspect_ratio = "2.20:1"
            else:
                aspect_ratio = f"{aspect_numeric:.2f}:1"
    
    container_format = enhanced_video_info.get("VideoPlayer.Container", "").upper()
    # If container is empty, try to extract from file path
    if not container_format and item.get("file"):
        file_path = item.get("file", "")
        if file_path.lower().endswith('.mkv'):
            container_format = "MKV"
        elif file_path.lower().endswith('.mp4'):
            container_format = "MP4"
        elif file_path.lower().endswith('.avi'):
            container_format = "AVI"
        elif file_path.lower().endswith('.m4v'):
            container_format = "M4V"
        elif file_path.lower().endswith('.mov'):
            container_format = "MOV"
    
    # Playback progress
    elapsed = progress_data.get("elapsed", 0)
    duration = progress_data.get("duration", 0)
    percent = round((elapsed / duration) * 100, 2) if duration else 0
    # Ensure minimum 0.1% width when there's any progress to make it visible
    if elapsed > 0 and percent < 0.1:
        percent = 0.1
    paused = progress_data.get("paused", False)

    title = html_escape(title)
    plot = html_escape(plot)
    imdb_url = html_escape(imdb_url)
    director_names = html_escape(director_names)
    cast_names = html_escape(cast_names)
    studio_names = html_escape(studio_names)
    tagline = html_escape(tagline)
    release_year = html_escape(release_year)
    resolution = html_escape(resolution)
    aspect_ratio = html_escape(aspect_ratio)
    video_codec = html_escape(video_codec)
    container_format = html_escape(container_format)
    audio_codec = html_escape(audio_codec)
    hdr_type = html_escape(hdr_type)
    current_audio = html_escape(current_audio)
    current_subtitle = html_escape(current_subtitle)
    all_audio_languages = [html_escape(lang) for lang in all_audio_languages]
    all_subtitle_languages = [html_escape(lang) for lang in all_subtitle_languages]
    genre_badges = [html_escape(genre) for genre in genre_badges]
    
    # Precomputed HTML fragments for template
    fanart_slides_html = (
        "".join(
            f'<div class="fanart-slide{" active" if i == 0 else ""}" style="background-image: url(\'{fanart}\')"></div>'
            for i, fanart in enumerate(fanart_variants)
        )
        if fanart_variants
        else ""
    )
    discart_html = (
        f"<div class='discart-wrapper'><img class='discart' src='{discart_url}' /></div>"
        if discart_url
        else ""
    )
    poster_html = f"<img class='poster' src='{poster_url}' />" if poster_url else ""
    if clearlogo_url:
        title_banner_html = f"<img class='logo' src='{clearlogo_url}' />"
    elif banner_url:
        title_banner_html = f"<img class='banner' src='{banner_url}' />"
    else:
        title_banner_html = f"<h2 style='margin-bottom: 4px;'>🎬 {title}</h2>"
    tagline_html = (
        f"<p style='font-style: italic; color: #ccc; margin-top: 8px;'>{tagline}</p>"
        if tagline
        else ""
    )
    release_year_html = f"<p><strong>Year:</strong> {release_year}</p>" if release_year else ""
    director_html = (
        f"<p><strong>Director:</strong> {director_names}</p>"
        if director_names and director_names != "N/A"
        else ""
    )
    cast_html = (
        f"<p><strong>Cast:</strong> {cast_names}</p>"
        if cast_names and cast_names != "N/A"
        else ""
    )
    plot_html = (
        f"<h3 style='margin-top:20px;'>Plot</h3><p style='max-width:600px;'>{plot}</p>"
        if plot and plot.strip()
        else ""
    )
    imdb_badge_html = (
        f'<a href="{imdb_url}" target="_blank" class="badge-imdb"><span>IMDb</span></a>'
        if imdb_url
        else ""
    )
    resolution_badge_html = f"<span class='badge'>{resolution}</span>" if resolution else ""
    aspect_ratio_badge_html = f"<span class='badge'>{aspect_ratio}</span>" if aspect_ratio else ""
    container_badge_html = f"<span class='badge'>{container_format}</span>" if container_format else ""
    channels_suffix = f" ({channels}ch)" if channels else ""
    studio_badge_html = f"<span class='badge'>{studio_names}</span>" if studio_names else ""
    audio_badge_extra_class = "expandable-language" if len(all_audio_languages) > 1 else ""
    subtitle_badge_extra_class = "expandable-language" if len(all_subtitle_languages) > 1 else ""
    all_audio_languages_str = ", ".join(all_audio_languages)
    all_subtitle_languages_str = ", ".join(all_subtitle_languages)
    genre_badges_html = "".join(f"<span class='badge'>{g}</span>" for g in genre_badges)
    elapsed_display = _format_playback_time(elapsed, duration)
    duration_display = _format_playback_time(duration, duration)
    paused_js = str(paused).lower()

    return render_template(
        "movie_nowplaying.html",
        percent=percent,
        elapsed=elapsed,
        duration=duration,
        paused_js=paused_js,
        fanart_slides_html=fanart_slides_html,
        discart_html=discart_html,
        poster_html=poster_html,
        title_banner_html=title_banner_html,
        tagline_html=tagline_html,
        release_year_html=release_year_html,
        director_html=director_html,
        cast_html=cast_html,
        plot_html=plot_html,
        rating_html=rating_html,
        imdb_badge_html=imdb_badge_html,
        resolution_badge_html=resolution_badge_html,
        aspect_ratio_badge_html=aspect_ratio_badge_html,
        video_codec=video_codec,
        container_badge_html=container_badge_html,
        audio_codec=audio_codec,
        channels_suffix=channels_suffix,
        hdr_type=hdr_type,
        studio_badge_html=studio_badge_html,
        audio_badge_extra_class=audio_badge_extra_class,
        subtitle_badge_extra_class=subtitle_badge_extra_class,
        current_audio=current_audio,
        all_audio_languages_str=all_audio_languages_str,
        current_subtitle=current_subtitle,
        all_subtitle_languages_str=all_subtitle_languages_str,
        genre_badges_html=genre_badges_html,
        elapsed_display=elapsed_display,
        duration_display=duration_display,
    )
