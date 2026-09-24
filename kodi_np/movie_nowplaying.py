"""
Movie-specific HTML generation for Kodi Now Playing application.
Handles movie display with discart spinning animation and movie-specific layout.
"""
import logging

from flask import render_template

from kodi_np.codecs import format_hdr_label
from kodi_np.media_info import (
    aspect_ratio_label,
    codecs_and_channels,
    container_label,
    fanart_pending_json as build_fanart_pending_json,
    fanart_slides_html as build_fanart_slides_html,
    fanart_variant_urls,
    fetch_player_streams,
    format_playback_time,
    html_escape,
    kind_badge_html,
    language_sets,
    resolution_label,
    up_next_html as build_up_next_html,
)
from kodi_np.util import build_cast_html, build_meta_labeled_line, build_meta_labeled_lines

logger = logging.getLogger(__name__)


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
    
    fanart_variants = fanart_variant_urls(downloaded_art)
    logger.debug("Movie fanart variants found: %s", len(fanart_variants))
    
    discart_url = f"/media/{downloaded_art.get('discart')}" if downloaded_art.get("discart") else ""
    banner_url = f"/media/{downloaded_art.get('banner')}" if downloaded_art.get("banner") else ""
    clearlogo_url = f"/media/{downloaded_art.get('clearlogo')}" if downloaded_art.get("clearlogo") else ""
    
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
    
    # Initialize defaults
    director_names = "N/A"
    hdr_type = "SDR"
    
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
    streams = fetch_player_streams(audio_info, subtitle_info)
    enhanced_video_info = streams["enhanced_video_info"]
    audio_info = streams["audio_info"] or audio_info
    subtitle_info = streams["subtitle_info"] or subtitle_info
    langs = language_sets(audio_info, subtitle_info, enhanced_video_info)
    all_audio_languages = langs["all_audio"]
    all_subtitle_languages = langs["all_subtitles"]
    current_audio = langs["current_audio"]
    current_subtitle = langs["current_subtitle"]
    
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
    
    # Cast strip (names immediate; thumbs lazy-loaded after paint)
    cast_list = details.get("cast", [])
    cast_html = build_cast_html(cast_list, limit=8)
    
    # Genre and formatting
    genre_list = details.get("genre", [])
    if not isinstance(genre_list, list):
        genre_list = []
    genres = [g.capitalize() for g in genre_list]
    genre_badges = genres[:3]
    
    height = enhanced_video_info.get("Player.Process(VideoHeight)") or video_info.get("height", 0)
    width = enhanced_video_info.get("Player.Process(VideoWidth)") or video_info.get("width", 0)
    resolution = resolution_label(width, height)
    codec_info = codecs_and_channels(enhanced_video_info, video_info, audio_info)
    video_codec = codec_info["video_codec"]
    audio_codec = codec_info["audio_codec"]
    channels = codec_info["channels"]
    aspect_ratio = aspect_ratio_label(enhanced_video_info)
    container_format = container_label(enhanced_video_info, item)
    
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
    raw_director_names = director_names if director_names and director_names != "N/A" else ""
    raw_release_year = release_year
    director_names = html_escape(director_names)
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
    fanart_slides_html = build_fanart_slides_html(fanart_variants)
    fanart_pending_json = build_fanart_pending_json(details, session_id)
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
        title_banner_html = f"<h2 style='margin-bottom: 4px;'>{title}</h2>"
    tagline_html = (
        f'<p class="show-tagline">{tagline}</p>'
        if tagline
        else ""
    )
    year_director_html = build_meta_labeled_lines(
        build_meta_labeled_line("Year", raw_release_year),
        build_meta_labeled_line("Director", raw_director_names),
    )
    plot_html = (
        f"<div class='meta-plot-block'><div class='meta-heading'>Plot</div><p>{plot}</p></div>"
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
    elapsed_display = format_playback_time(elapsed, duration)
    duration_display = format_playback_time(duration, duration)
    paused_js = str(paused).lower()
    display_kind = (details or {}).get("display_kind") or "movie"
    kind_badge = kind_badge_html(display_kind)
    next_html = build_up_next_html(details)

    return render_template(
        "movie_nowplaying.html",
        percent=percent,
        elapsed=elapsed,
        duration=duration,
        paused_js=paused_js,
        fanart_slides_html=fanart_slides_html,
        fanart_pending_json=fanart_pending_json,
        discart_html=discart_html,
        poster_html=poster_html,
        title_banner_html=title_banner_html,
        tagline_html=tagline_html,
        year_director_html=year_director_html,
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
        kind_badge_html=kind_badge,
        up_next_html=next_html,
        elapsed_display=elapsed_display,
        duration_display=duration_display,
    )
