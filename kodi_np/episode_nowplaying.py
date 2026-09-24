"""
TV Episode-specific HTML generation for Kodi Now Playing application.
Handles TV episode display with show poster, season poster, and episode information.
"""
import json
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
    language_sets,
    resolution_label,
    up_next_html as build_up_next_html,
    video_dimensions,
)
from kodi_np.tv_nfo import format_season_plot_heading
from kodi_np.util import build_cast_html, build_meta_labeled_line, build_meta_labeled_lines

logger = logging.getLogger(__name__)


def generate_html(item, session_id, downloaded_art, progress_data, details):
    """
    Generate HTML for TV episode display.
    
    Args:
        item (dict): Media item from Kodi API
        session_id (str): Session ID for file naming
        downloaded_art (dict): Downloaded artwork files
        progress_data (dict): Playback progress information
        details (dict): Detailed media information
        
    Returns:
        str: HTML content for TV episode display
    """
    logger.debug(f"Episode handler called for: {item.get('title', 'Unknown')}")
    # Extract URLs for artwork
    # For TV episodes, 'poster' is typically the show poster, and we need to get season poster separately
    show_poster_url = f"/media/{downloaded_art.get('poster')}" if downloaded_art.get("poster") else ""
    season_poster_url = f"/media/{downloaded_art.get('season.poster')}" if downloaded_art.get("season.poster") else ""
    
    fanart_variants = fanart_variant_urls(downloaded_art)
    logger.debug("Episode fanart variants found: %s", len(fanart_variants))
    
    banner_url = f"/media/{downloaded_art.get('banner')}" if downloaded_art.get("banner") else ""
    clearlogo_url = f"/media/{downloaded_art.get('clearlogo')}" if downloaded_art.get("clearlogo") else ""
    
    # Extract TV episode information
    title = item.get("title", "Untitled Episode")
    show = item.get("showtitle", "")
    season = item.get("season", 0)
    episode = item.get("episode", 0)
    plot = item.get("plot", item.get("description", ""))
    
    # Create episode subtitle components for badges
    season_badge = f"Season {season}" if season > 0 else ""
    episode_badge = f"Episode {episode}" if episode > 0 else ""
    
    # Check if title is generic (like "Episode 6" or "Episode #6") to avoid duplication
    title_badge = ""
    if title:
        import re
        # Pattern to match "Episode X" or "Episode #X" where X is a number
        generic_pattern = r'^Episode\s*#?\s*\d+\s*$'
        if not re.match(generic_pattern, title, re.IGNORECASE):
            title_badge = title
    
    # Extract IMDb ID and construct URL - ensure details is a dict
    if not isinstance(details, dict):
        details = {}
    active_server_id = details.get("active_server_id")
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
    streams = fetch_player_streams(audio_info, subtitle_info, server_id=active_server_id)
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
    
    # Studio and tagline - for episodes, prefer TV show extras from details
    studio_names = ""
    show_tagline = (details.get("show_tagline") or details.get("tagline") or "").strip()
    season_plot = (details.get("season_plot") or "").strip()
    named_seasons = details.get("named_seasons") or {}
    if not isinstance(named_seasons, dict):
        named_seasons = {}
    
    # Try to get studio from episode details first
    studio_list = details.get("studio", [])
    if isinstance(studio_list, list) and studio_list:
        studio_names = ", ".join(studio_list)
    else:
        # If no studio in episode details, try to get from TV show
        tvshowid = item.get("tvshowid")
        if tvshowid:
            try:
                from kodi_np.rpc import kodi_rpc

                tvshow_response = kodi_rpc("VideoLibrary.GetTVShowDetails", {
                    "tvshowid": tvshowid,
                    "properties": ["studio"]
                }, server_id=active_server_id)
                if tvshow_response and tvshow_response.get("result"):
                    tvshow_details = tvshow_response["result"].get("tvshowdetails", {})
                    tvshow_studio_list = tvshow_details.get("studio", [])
                    if isinstance(tvshow_studio_list, list) and tvshow_studio_list:
                        studio_names = ", ".join(tvshow_studio_list)
            except Exception as e:
                logger.debug(f"Failed to get TV show studio info: {e}")
    
    # Cast strip (names immediate; thumbs lazy-loaded after paint)
    cast_list = details.get("cast", [])
    cast_html = build_cast_html(cast_list, limit=8)
    
    # Genre and formatting
    genre_list = details.get("genre", [])
    if not isinstance(genre_list, list):
        genre_list = []
    genres = [g.capitalize() for g in genre_list]
    genre_badges = genres[:3]
    
    # Format media info - use enhanced video info first, fallback to streamdetails
    width, height = video_dimensions(enhanced_video_info, video_info)
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
    percent = int((elapsed / duration) * 100) if duration else 0
    paused = progress_data.get("paused", False)

    show = html_escape(show)
    title_badge = html_escape(title_badge)
    season_badge = html_escape(season_badge)
    episode_badge = html_escape(episode_badge)
    plot = html_escape(plot)
    imdb_url = html_escape(imdb_url)
    raw_director_names = director_names if director_names and director_names != "N/A" else ""
    raw_release_year = release_year
    director_names = html_escape(director_names)
    studio_names = html_escape(studio_names)
    tagline = html_escape(show_tagline)
    season_plot_escaped = html_escape(season_plot)
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
    show_poster_html = (
        f"<img class='show-poster' id='soft-show-poster' src='{show_poster_url}' />" if show_poster_url else "<img class='show-poster' id='soft-show-poster' style='display:none' src='' />"
    )
    season_poster_html = (
        f"<img class='season-poster' id='soft-season-poster' src='{season_poster_url}' />" if season_poster_url else "<img class='season-poster' id='soft-season-poster' style='display:none' src='' />"
    )
    if clearlogo_url:
        title_banner_html = f"<img class='logo' src='{clearlogo_url}' />"
    elif banner_url:
        title_banner_html = f"<img class='banner' src='{banner_url}' />"
    else:
        title_banner_html = f"<h2 style='margin-bottom: 4px;'>📺 {show}</h2>"
    tagline_html = (
        f'<p id="soft-tagline" class="show-tagline episode-tagline-block">{tagline}</p>'
        if show_tagline
        else '<p id="soft-tagline" class="show-tagline episode-tagline-block" hidden></p>'
    )
    show_title_html = (
        f"<div class='show-title'>{show}</div>"
        if not clearlogo_url and not banner_url
        else ""
    )
    season_badge_html = (
        f"<span class='badge episode-badge' id='soft-badge-season'>{season_badge}</span>" if season_badge else "<span class='badge episode-badge' id='soft-badge-season' style='display:none'></span>"
    )
    episode_badge_html = (
        f"<span class='badge episode-badge' id='soft-badge-episode'>{episode_badge}</span>" if episode_badge else "<span class='badge episode-badge' id='soft-badge-episode' style='display:none'></span>"
    )
    title_badge_html = (
        f"<span class='badge episode-badge' id='soft-badge-title'>{title_badge}</span>" if title_badge else "<span class='badge episode-badge' id='soft-badge-title' style='display:none'></span>"
    )
    year_director_html = build_meta_labeled_lines(
        build_meta_labeled_line("Year", raw_release_year),
        build_meta_labeled_line("Director", raw_director_names),
    )
    season_heading = format_season_plot_heading(season, named_seasons, "number_and_named")
    named_for_season = ""
    if season is not None:
        try:
            sn = int(season)
            named_for_season = html_escape(
                named_seasons.get(sn) or named_seasons.get(str(sn)) or ""
            )
        except (TypeError, ValueError):
            named_for_season = ""
    if season_plot:
        season_plot_html = (
            f'<div id="soft-season-plot" class="meta-plot-block episode-season-plot-block" '
            f'data-season="{html_escape(season)}" data-named-season="{named_for_season}">'
            f'<div class="meta-heading" id="soft-season-plot-heading">{html_escape(season_heading)}</div>'
            f'<p id="soft-season-plot-text">{season_plot_escaped}</p>'
            f"</div>"
        )
    else:
        season_plot_html = (
            '<div id="soft-season-plot" class="meta-plot-block episode-season-plot-block" '
            'style="display:none" data-season="" data-named-season="">'
            '<div class="meta-heading" id="soft-season-plot-heading">Season Plot</div>'
            '<p id="soft-season-plot-text"></p>'
            "</div>"
        )
    plot_html = (
        f"<div id='soft-plot' class='meta-plot-block episode-plot-block'>"
        f"<div class='meta-heading'>Episode Plot</div>"
        f"<p id='soft-plot-text'>{plot}</p></div>"
        if plot and plot.strip()
        else (
            "<div id='soft-plot' class='meta-plot-block episode-plot-block' style='display:none'>"
            "<div class='meta-heading'>Episode Plot</div>"
            "<p id='soft-plot-text'></p></div>"
        )
    )
    episode_meta_json = json.dumps(
        {
            "season": season,
            "named_seasons": {str(k): v for k, v in named_seasons.items()},
        }
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
    audio_badge_extra_class = " expandable-language" if len(all_audio_languages) > 1 else ""
    subtitle_badge_extra_class = "expandable-language" if len(all_subtitle_languages) > 1 else ""
    all_audio_languages_str = ", ".join(all_audio_languages) if all_audio_languages else current_audio
    all_subtitle_languages_str = ", ".join(all_subtitle_languages)
    genre_badges_html = "".join(f"<span class='badge'>{g}</span>" for g in genre_badges)
    elapsed_display = format_playback_time(elapsed, duration)
    duration_display = format_playback_time(duration, duration)
    paused_js = str(paused).lower()
    soft_identity = {
        "media_type": "episode",
        "item_id": f"episode_{item.get('id')}" if item.get("id") is not None else "",
        "tvshow_id": item.get("tvshowid"),
        "season": season,
        "album_id": None,
        "artist_id": None,
    }
    soft_identity_json = json.dumps(soft_identity)

    return render_template(
        "episode_nowplaying.html",
        percent=percent,
        elapsed=elapsed,
        duration=duration,
        paused_js=paused_js,
        fanart_slides_html=fanart_slides_html,
        fanart_pending_json=fanart_pending_json,
        show_poster_html=show_poster_html,
        season_poster_html=season_poster_html,
        title_banner_html=title_banner_html,
        tagline_html=tagline_html,
        show_title_html=show_title_html,
        season_badge_html=season_badge_html,
        episode_badge_html=episode_badge_html,
        title_badge_html=title_badge_html,
        year_director_html=year_director_html,
        cast_html=cast_html,
        season_plot_html=season_plot_html,
        plot_html=plot_html,
        episode_meta_json=episode_meta_json,
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
        soft_identity_json=soft_identity_json,
        up_next_html=build_up_next_html(details),
    )

