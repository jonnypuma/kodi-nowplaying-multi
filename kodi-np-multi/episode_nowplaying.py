"""
TV Episode-specific HTML generation for Kodi Now Playing application.
Handles TV episode display with show poster, season poster, and episode information.
"""

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
    print(f"[DEBUG] Episode handler called for: {item.get('title', 'Unknown')}", flush=True)
    # Extract URLs for artwork
    # For TV episodes, 'poster' is typically the show poster, and we need to get season poster separately
    show_poster_url = f"/media/{downloaded_art.get('poster')}" if downloaded_art.get("poster") else ""
    season_poster_url = f"/media/{downloaded_art.get('season.poster')}" if downloaded_art.get("season.poster") else ""
    
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
    print(f"[DEBUG] Episode fanart variants found: {len(fanart_variants)}", flush=True)
    print(f"[DEBUG] Episode fanart variants: {fanart_variants}", flush=True)
    
    banner_url = f"/media/{downloaded_art.get('banner')}" if downloaded_art.get("banner") else ""
    clearlogo_url = f"/media/{downloaded_art.get('clearlogo')}" if downloaded_art.get("clearlogo") else ""
    clearart_url = f"/media/{downloaded_art.get('clearart')}" if downloaded_art.get("clearart") else ""
    
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
    imdb_id = details.get("uniqueid", {}).get("imdb", "")
    imdb_url = f"https://www.imdb.com/title/{imdb_id}" if imdb_id else ""
    
    # Get rating from details or fallback
    rating = round(details.get("rating", 0.0), 1)
    rating_html = f"<strong>⭐ {rating}</strong>" if rating > 0 else ""
    
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
        print(f"[DEBUG] Using streamdetails from item: {streamdetails}", flush=True)
    
    video_info = streamdetails.get("video", [{}])[0] if isinstance(streamdetails.get("video"), list) and len(streamdetails.get("video", [])) > 0 else {}
    audio_info = streamdetails.get("audio", []) if isinstance(streamdetails.get("audio"), list) else []
    subtitle_info = streamdetails.get("subtitle", []) if isinstance(streamdetails.get("subtitle"), list) else []
    
    # HDR type
    hdr_type = video_info.get("hdrtype", "").upper() or "SDR"
    
    # Get enhanced video information using XBMC.GetInfoLabels for real-time data
    enhanced_video_info = {}
    player_id = 1  # Default, will be updated if we can get active player
    try:
        # Import the kodi_rpc function from the main module
        import sys
        import os
        import importlib.util
        
        # Load the kodi-nowplaying.py module (with hyphen)
        spec = importlib.util.spec_from_file_location("kodi_nowplaying", "kodi-nowplaying.py")
        kodi_module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(kodi_module)
        kodi_rpc = kodi_module.kodi_rpc
        
        # Get active player ID
        try:
            active_players_response = kodi_rpc("Player.GetActivePlayers", {})
            if active_players_response and active_players_response.get("result"):
                active_players = active_players_response.get("result", [])
                if active_players:
                    player_id = active_players[0].get("playerid", 1)
                    print(f"[DEBUG] Got active player ID: {player_id}", flush=True)
        except Exception as e:
            print(f"[DEBUG] Failed to get active player ID, using default 1: {e}", flush=True)
        
        print(f"[DEBUG] Attempting to get enhanced video info via XBMC.GetInfoLabels", flush=True)
        
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
            print(f"[DEBUG] Player.GetProperties audiostreams response: {audio_streams_response}", flush=True)
            
            if audio_streams_response and audio_streams_response.get("result"):
                audio_streams = audio_streams_response.get("result", {}).get("audiostreams", [])
                print(f"[DEBUG] Available audio streams: {audio_streams}", flush=True)
                
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
                    print(f"[DEBUG] Converted audio_info from Player.GetProperties: {audio_info}", flush=True)
        except Exception as e:
            print(f"[DEBUG] Failed to get audio streams: {e}", flush=True)
        
        # Try to get available subtitle streams using Player.GetProperties
        try:
            subtitle_streams_response = kodi_rpc("Player.GetProperties", {
                "playerid": player_id,
                "properties": ["subtitles"]
            })
            print(f"[DEBUG] Player.GetProperties subtitles response: {subtitle_streams_response}", flush=True)
            
            if subtitle_streams_response and subtitle_streams_response.get("result"):
                subtitle_streams = subtitle_streams_response.get("result", {}).get("subtitles", [])
                print(f"[DEBUG] Available subtitle streams: {subtitle_streams}", flush=True)
                
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
                    print(f"[DEBUG] Converted subtitle_info: {subtitle_info}", flush=True)
        except Exception as e:
            print(f"[DEBUG] Failed to get subtitle streams: {e}", flush=True)
        
        print(f"[DEBUG] XBMC.GetInfoLabels response: {infolabels_response}", flush=True)
        
        if infolabels_response and infolabels_response.get("result"):
            enhanced_video_info = infolabels_response.get("result", {})
            print(f"[DEBUG] Enhanced video info extracted: {enhanced_video_info}", flush=True)
        else:
            print(f"[DEBUG] No result in XBMC.GetInfoLabels response", flush=True)
    except Exception as e:
        print(f"[DEBUG] Failed to get enhanced video info: {e}", flush=True)
        import traceback
        print(f"[DEBUG] Traceback: {traceback.format_exc()}", flush=True)
        enhanced_video_info = {}
    
    # Debug audio and subtitle info
    print(f"[DEBUG] Episode audio_info: {audio_info}", flush=True)
    print(f"[DEBUG] Episode subtitle_info: {subtitle_info}", flush=True)
    
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
    
    print(f"[DEBUG] Episode current audio: {current_audio}, all audio: {all_audio_languages}, count: {len(all_audio_languages)}", flush=True)
    print(f"[DEBUG] Episode current subtitle: {current_subtitle}, all subtitle: {all_subtitle_languages}, count: {len(all_subtitle_languages)}", flush=True)
    print(f"[DEBUG] Audio badge will have expandable class: {len(all_audio_languages) > 1}", flush=True)
    print(f"[DEBUG] Subtitle badge will have expandable class: {len(all_subtitle_languages) > 1}", flush=True)
    
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
    
    # Studio and tagline - for episodes, get studio from TV show details
    studio_names = ""
    tagline = details.get("tagline", "")
    
    # Try to get studio from episode details first
    studio_list = details.get("studio", [])
    if isinstance(studio_list, list) and studio_list:
        studio_names = ", ".join(studio_list)
    else:
        # If no studio in episode details, try to get from TV show
        tvshowid = item.get("tvshowid")
        if tvshowid:
            try:
                # Import kodi_rpc function
                import sys
                import os
                import importlib.util
                
                # Load the kodi-nowplaying.py module (with hyphen)
                spec = importlib.util.spec_from_file_location("kodi_nowplaying", "kodi-nowplaying.py")
                kodi_module = importlib.util.module_from_spec(spec)
                spec.loader.exec_module(kodi_module)
                kodi_rpc = kodi_module.kodi_rpc
                
                tvshow_response = kodi_rpc("VideoLibrary.GetTVShowDetails", {
                    "tvshowid": tvshowid,
                    "properties": ["studio"]
                })
                if tvshow_response and tvshow_response.get("result"):
                    tvshow_details = tvshow_response["result"].get("tvshowdetails", {})
                    tvshow_studio_list = tvshow_details.get("studio", [])
                    if isinstance(tvshow_studio_list, list) and tvshow_studio_list:
                        studio_names = ", ".join(tvshow_studio_list)
            except Exception as e:
                print(f"[DEBUG] Failed to get TV show studio info: {e}", flush=True)
    
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
    audio_codec = enhanced_video_info.get("VideoPlayer.AudioCodec", audio_info[0].get("codec", "Unknown") if audio_info else "Unknown").upper()
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
    percent = int((elapsed / duration) * 100) if duration else 0
    paused = progress_data.get("paused", False)
    
    # Generate HTML
    html = f"""
    <!DOCTYPE html>
    <html>
    <head>
      <link rel="icon" type="image/x-icon" href="/static/favicon.ico">
      <style>
        body {{
          font-family: sans-serif;
          animation: fadeIn 1s;
          position: relative;
          margin: 0;
          padding: 0;
          opacity: 1;
          transition: opacity 1.5s ease;
        }}
        
        /* Fanart Slideshow Styles */
        .fanart-container {{
          position: fixed;
          top: 0;
          left: 0;
          width: 100%;
          height: 100%;
          z-index: -1;
        }}
        
        .fanart-slide {{
          position: absolute;
          top: 0;
          left: 0;
          width: 100%;
          height: 100%;
          background-size: cover;
          background-position: center;
          background-repeat: no-repeat;
          opacity: 0;
          transition: opacity 2s ease-in-out;
        }}
        
        .fanart-slide.active {{
          opacity: 1;
        }}
        
        .fanart-slide.fade-out {{
          opacity: 0;
        }}
        body.fade-out {{
          opacity: 0;
        }}
        .content {{
          position: relative;
          background: rgba(0,0,0,0.5);
          border-radius: 12px;
          padding: 40px;
          backdrop-filter: blur(5px);
          box-shadow: 0 8px 32px rgba(0,0,0,0.8);
          display: flex;
          gap: 40px;
          color: white;
          text-shadow: 0 2px 6px rgba(0,0,0,0.7), 0 0 8px rgba(0,0,0,0.5);
        }}
        .left-section {{
          display: flex;
          gap: 40px;
        }}
        .right-section {{
          display: flex;
          align-items: center;
          justify-content: center;
        }}
        .poster-container {{
          display: flex;
          flex-direction: column;
          gap: 20px;
          align-items: flex-start;
        }}
        .show-poster {{
          height: 300px;
          border-radius: 8px;
          box-shadow: 0 2px 8px rgba(0,0,0,0.6);
          position: relative;
          z-index: 2;
          cursor: zoom-in !important;
        }}
        .season-poster {{
          height: 300px;
          border-radius: 8px;
          box-shadow: 0 2px 8px rgba(0,0,0,0.6);
          position: relative;
          z-index: 2;
          cursor: zoom-in !important;
        }}
        .progress-wrapper {{
          display: flex;
          align-items: center;
          gap: 12px;
          margin-top: 6px;
          width: 100%;
          max-width: 600px;
          box-sizing: border-box;
        }}
        .progress-container {{
          flex: 1;
          min-width: 0;
          overflow: hidden;
          position: relative;
          flex-shrink: 1;
        }}
        .progress {{
          background: #2a2a2a;
          border-radius: 15px;
          height: 20px;
          overflow: hidden;
          border: 1px solid rgba(0,0,0,0.75);
          box-shadow: 
            inset 0 1px 0 rgba(255,255,255,0.1),
            inset 0 0 5px rgba(0,0,0,0.3),
            0 2px 2px rgba(255,255,255,0.1),
            inset 0 5px 10px rgba(0,0,0,0.4);
          position: relative;
          width: 100%;
          box-sizing: border-box;
        }}
        .bar {{
          background: linear-gradient(135deg, #4caf50 0%, #45a049 50%, #4caf50 100%);
          height: 20px;
          border-radius: 15px 3px 3px 15px;
          width: {percent}%;
          transition: width 0.5s;
          position: relative;
          box-shadow: 
            inset 0 8px 0 rgba(255,255,255,0.2),
            inset 0 1px 1px rgba(0,0,0,0.125);
          border-right: 1px solid rgba(0,0,0,0.3);
        }}
        .small {{
          font-size: 0.9em;
          color: #ccc;
        }}
        .badges {{
          display: flex;
          gap: 8px;
          margin-top: 10px;
          flex-wrap: wrap;
          align-items: center;
          max-width: 100%;
          overflow: hidden;
          width: 100%;
        }}
        .badge {{
          background: #333;
          color: white;
          padding: 4px 10px;
          border-radius: 20px;
          font-size: 0.8em;
          box-shadow: 0 2px 6px rgba(0,0,0,0.4);
          text-shadow: none;
        }}
        
        .expandable-language {{
          cursor: pointer;
          transition: all 0.3s ease;
          position: relative;
        }}
        
        .expandable-language:hover {{
          background: #444;
          transform: scale(1.05);
        }}
        
        .expandable-language.expanded {{
          background: #333;
          border: 1px solid rgba(255, 255, 255, 0.2);
        }}
        
        .current-lang {{
          font-weight: bold;
        }}
        
        .all-langs {{
          transition: opacity 0.3s ease;
        }}
        
        .active-language {{
          background: rgba(76, 175, 80, 0.6);
          color: white;
          font-weight: bold;
          padding: 2px 4px;
          border-radius: 3px;
          margin: 0 1px;
          text-shadow: 0 1px 3px rgba(0,0,0,0.6);
        }}
        .episode-badges {{
          display: flex;
          gap: 10px;
          margin: 10px 0;
          flex-wrap: wrap;
        }}
        .episode-badge {{
          background: #4caf50;
          color: white;
          padding: 8px 15px;
          border-radius: 25px;
          font-size: 1.0em;
          font-weight: bold;
          box-shadow: 0 3px 8px rgba(0,0,0,0.4);
          text-shadow: 0 1px 3px rgba(0,0,0,0.6);
        }}
        .badge-imdb {{
          display: flex;
          align-items: center;
          gap: 4px;
          background: #f5c518;
          color: black;
          padding: 4px 10px;
          border-radius: 20px;
          font-size: 0.8em;
          box-shadow: 0 2px 6px rgba(0,0,0,0.4);
          text-decoration: none;
          font-weight: bold;
          text-shadow: none !important;
        }}
        .badge-imdb img {{
          height: 14px;
        }}
        
        #playback-button {{
          display: inline-block !important;
          vertical-align: middle;
          margin-right: 4px;
        }}
        .banner {{
          display: block;
          margin-bottom: 10px;
          max-width: 360px;
          width: 100%;
        }}
        .logo {{
          display: block;
          margin-bottom: 10px;
          height: 150px;
          width: auto;
          object-fit: contain;
          object-position: left center;
        }}
        .clearart {{
          display: block;
          max-height: 400px;
          max-width: 300px;
        }}
        .episode-info {{
          margin-bottom: 20px;
        }}
        .episode-title {{
          font-size: 1.2em;
          font-weight: bold;
          margin-bottom: 5px;
        }}
        .show-title {{
          font-size: 1.5em;
          font-weight: bold;
          margin-bottom: 10px;
          color: #4caf50;
        }}
        .marquee {{
          position: fixed;
          top: 0;
          left: 0;
          width: 100%;
          height: 80px;
          background: linear-gradient(135deg, #1a1a1a 0%, #2d2d2d 50%, #1a1a1a 100%);
          border: 3px solid #333;
          border-radius: 0 0 15px 15px;
          display: flex;
          align-items: center;
          justify-content: center;
          z-index: 1000;
          box-shadow: 0 4px 20px rgba(0,0,0,0.8);
          margin-bottom: 20px;
        }}
        .marquee-toggle {{
          position: absolute;
          bottom: -15px;
          left: 50%;
          transform: translateX(-50%);
          width: 50px;
          height: 15px;
          background: linear-gradient(135deg, #1a1a1a 0%, #2d2d2d 50%, #1a1a1a 100%);
          border: none;
          border-radius: 0 0 25px 25px;
          display: flex;
          align-items: center;
          justify-content: center;
          cursor: pointer;
          transition: all 0.3s ease;
          z-index: 1001;
        }}
        .marquee-toggle::before {{
          content: "";
          position: absolute;
          top: 0;
          left: 0;
          right: 0;
          bottom: 0;
          background: linear-gradient(45deg, #ff6b35, #f7931e, #ff6b35, #f7931e);
          border-radius: 0 0 25px 25px;
          z-index: -1;
          animation: marqueeGlow 2s ease-in-out infinite alternate;
        }}
        .marquee-toggle:hover {{
          transform: translateX(-50%) scale(1.05);
        }}
        .marquee-toggle.hidden {{
          background: linear-gradient(135deg, #1a1a1a 0%, #2d2d2d 50%, #1a1a1a 100%);
        }}
        .marquee-toggle.hidden::before {{
          opacity: 0.5;
        }}
        .arrow {{
          width: 0;
          height: 0;
          border-left: 8px solid transparent;
          border-right: 8px solid transparent;
          border-bottom: 12px solid white;
          transition: transform 0.3s ease;
        }}
        .arrow.up {{
          border-bottom: none;
          border-top: 12px solid white;
        }}
        .marquee::before {{
          content: "";
          position: absolute;
          top: -8px;
          left: -8px;
          right: -8px;
          bottom: -8px;
          background: linear-gradient(45deg, #ff6b35, #f7931e, #ff6b35, #f7931e);
          border-radius: 0 0 20px 20px;
          z-index: -1;
          animation: marqueeGlow 2s ease-in-out infinite alternate;
        }}
        .marquee-text {{
          font-family: 'Arial Black', Arial, sans-serif;
          font-size: 2.2em;
          font-weight: 900;
          color: #fff;
          text-shadow: 
            0 0 10px #ff6b35,
            0 0 20px #ff6b35,
            0 0 30px #ff6b35,
            2px 2px 4px rgba(0,0,0,0.8);
          letter-spacing: 4px;
          text-transform: uppercase;
          animation: marqueePulse 1.5s ease-in-out infinite alternate;
        }}
        .marquee-text.shimmer {{
          animation: marqueePulse 1.5s ease-in-out infinite alternate;
        }}
        .marquee-text .letter {{
          margin-right: 4px;
        }}
        .marquee-text .letter:last-child {{
          margin-right: 0px;
        }}
        .marquee-text .letter:nth-child(4) {{
          margin-right: 0px;
        }}
        .marquee-text.shimmer .letter {{
          display: inline-block;
          color: #fff;
          text-shadow: 0 0 10px #ff6b35, 0 0 20px #ff6b35, 0 0 30px #ff6b35, 2px 2px 4px rgba(0,0,0,0.8);
          animation: letterDarkWave 0.2s ease-in-out forwards, letterShimmer 0.3s ease-in-out 1.0s forwards, letterFadeToWhite 0.3s ease-in-out 1.1s forwards;
          animation-fill-mode: forwards;
        }}
        .marquee-text.shimmer .letter:nth-child(1) {{ animation-delay: 0s, 1.0s, 1.1s; }}
        .marquee-text.shimmer .letter:nth-child(2) {{ animation-delay: 0.08s, 1.08s, 1.18s; }}
        .marquee-text.shimmer .letter:nth-child(3) {{ animation-delay: 0.16s, 1.16s, 1.26s; }}
        .marquee-text.shimmer .letter:nth-child(4) {{ animation-delay: 0.24s, 1.24s, 1.34s; }}
        .marquee-text.shimmer .letter:nth-child(5) {{ animation-delay: 0.32s, 1.32s, 1.42s; }}
        .marquee-text.shimmer .letter:nth-child(6) {{ animation-delay: 0.4s, 1.4s, 1.5s; }}
        .marquee-text.shimmer .letter:nth-child(7) {{ animation-delay: 0.48s, 1.48s, 1.58s; }}
        .marquee-text.shimmer .letter:nth-child(8) {{ animation-delay: 0.56s, 1.56s, 1.66s; }}
        .marquee-text.shimmer .letter:nth-child(9) {{ animation-delay: 0.64s, 1.64s, 1.74s; }}
        .marquee-text.shimmer .letter:nth-child(10) {{ animation-delay: 0.72s, 1.72s, 1.82s; }}
        .marquee-text.shimmer .letter:nth-child(11) {{ animation-delay: 0.8s, 1.8s, 1.9s; }}
        @keyframes letterDarkWave {{
          0% {{
            color: #fff;
            text-shadow: 0 0 10px #ff6b35, 0 0 20px #ff6b35, 0 0 30px #ff6b35, 2px 2px 4px rgba(0,0,0,0.8);
          }}
          100% {{
            color: #222;
            text-shadow: none;
          }}
        }}
        @keyframes letterShimmer {{
          0% {{
            color: #222;
            text-shadow: none;
          }}
          100% {{
            color: #222;
            text-shadow: none;
          }}
        }}
        @keyframes letterFadeToWhite {{
          0% {{
            color: #222;
            text-shadow: none;
          }}
          100% {{
            color: #fff;
            text-shadow: 0 0 10px #ff6b35, 0 0 20px #ff6b35, 0 0 30px #ff6b35, 2px 2px 4px rgba(0,0,0,0.8);
          }}
        }}
        @keyframes marqueeGlow {{
          0% {{ opacity: 0.7; }}
          100% {{ opacity: 1; }}
        }}
        @keyframes marqueePulse {{
          0% {{ 
            text-shadow: 
              0 0 10px #ff6b35,
              0 0 20px #ff6b35,
              0 0 30px #ff6b35,
              2px 2px 4px rgba(0,0,0,0.8);
          }}
          100% {{ 
            text-shadow: 
              0 0 15px #ff6b35,
              0 0 25px #ff6b35,
              0 0 35px #ff6b35,
              2px 2px 4px rgba(0,0,0,0.8);
          }}
        }}
        .content {{
          margin-top: 100px;
        }}
        .marquee {{
          transition: transform 0.5s ease-in-out;
        }}
        .marquee.hidden {{
          transform: translateY(-100%);
        }}
        .content.no-marquee {{
          margin-top: 20px;
        }}
        
        /* Blur Toggle Button */
        .blur-toggle {{
          position: absolute;
          top: 15px;
          right: 15px;
          width: 36px;
          height: 36px;
          border-radius: 50%;
          background: rgba(0,0,0,0.6);
          border: 1px solid rgba(255,255,255,0.2);
          cursor: pointer;
          display: flex;
          align-items: center;
          justify-content: center;
          transition: all 0.3s ease;
          box-shadow: 0 0 10px rgba(255,255,255,0.1);
          animation: subtleGlow 3s ease-in-out infinite;
          z-index: 10;
        }}
        
        .blur-toggle:hover {{
          transform: scale(1.1);
          box-shadow: 0 0 15px rgba(255,255,255,0.3);
          background: rgba(0,0,0,0.8);
        }}
        
        .blur-toggle:active {{
          transform: scale(0.95);
        }}
        
        .blur-toggle svg {{
          width: 20px;
          height: 20px;
          fill: rgba(255,255,255,0.8);
          transition: fill 0.3s ease;
        }}
        
        .blur-toggle:hover svg {{
          fill: rgba(255,255,255,1);
        }}
        
        @keyframes subtleGlow {{
          0%, 100% {{ box-shadow: 0 0 10px rgba(255,255,255,0.1); }}
          50% {{ box-shadow: 0 0 15px rgba(255,255,255,0.2); }}
        }}
        
        /* Blur state classes */
        .content.blurred {{
          backdrop-filter: blur(5px);
        }}
        
        .content.non-blurred {{
          backdrop-filter: none;
        }}

        /* Poster Zoom Overlay */
        .poster-zoom-overlay {{
          position: fixed;
          inset: 0;
          background: rgba(0,0,0,0.85);
          display: none;
          align-items: center;
          justify-content: center;
          z-index: 2000;
        }}
        .poster-zoom-overlay.visible {{
          display: flex;
        }}
        .poster-zoom-image {{
          max-width: 80vw;
          max-height: 80vh;
          border-radius: 10px;
          box-shadow: 0 20px 60px rgba(0,0,0,0.9);
          transform: scale(0.7);
          opacity: 0;
          transition: transform 0.25s ease-out, opacity 0.25s ease-out;
        }}
        .poster-zoom-overlay.visible .poster-zoom-image {{
          transform: scale(1);
          opacity: 1;
        }}
        .poster-zoom-overlay img {{
          object-fit: contain;
        }}
        
        /* Side Panel Styles */
        .side-panel {{
          position: fixed;
          top: 0;
          right: -530px;
          width: 530px;
          max-width: calc(100vw - 40px);
          height: 100vh;
          background: rgba(0, 0, 0, 0.85);
          backdrop-filter: blur(10px);
          z-index: 1500;
          transition: right 0.5s ease-in-out;
          overflow: visible;
          padding: 20px;
          box-shadow: -5px 0 20px rgba(0, 0, 0, 0.5);
          box-sizing: border-box;
        }}
        
        .side-panel.open {{
          right: 0;
        }}
        
        .side-panel-toggle {{
          position: absolute;
          left: -20px;
          top: 50%;
          transform: translateY(-50%);
          width: 20px;
          height: 40px;
          background: rgba(0, 0, 0, 0.85);
          backdrop-filter: blur(10px);
          border-radius: 20px 0 0 20px;
          margin-right: 0;
          display: flex;
          align-items: center;
          justify-content: center;
          cursor: pointer;
          z-index: 1501;
          transition: all 0.3s ease;
          box-shadow: -2px 0 10px rgba(0, 0, 0, 0.3);
        }}
        
        .side-panel-toggle-arrow {{
          color: rgba(255, 255, 255, 0.8);
          font-size: 14px;
          font-weight: bold;
          transition: transform 0.3s ease;
          margin-left: 2px;
        }}
        
        .side-panel h2 {{
          color: white;
          margin: 0 0 20px 0;
          font-size: 1.5em;
          display: flex;
          align-items: center;
          gap: 10px;
        }}
        
        .side-panel select {{
          background: rgba(255, 255, 255, 0.1);
          border: 1px solid rgba(255, 255, 255, 0.2);
          color: white;
          padding: 8px 12px;
          border-radius: 5px;
          font-size: 14px;
          cursor: pointer;
          min-width: 150px;
        }}
        
        .side-panel select option {{
          background: white;
          color: black;
        }}
        
        .side-panel-section {{
          margin-bottom: 25px;
          padding-bottom: 20px;
          border-bottom: 1px solid rgba(255, 255, 255, 0.1);
        }}
        
        .side-panel-section:last-child {{
          border-bottom: none;
        }}
        
        .side-panel-section label {{
          display: block;
          color: rgba(255, 255, 255, 0.9);
          margin-bottom: 10px;
          font-size: 14px;
        }}
        
        .side-panel-row {{
          display: flex;
          align-items: center;
          gap: 15px;
          margin-bottom: 15px;
        }}
        
        /* Toggle Component Styles (adapted from provided CSS) */
        .toggle {{
          align-items: center;
          border-radius: 100px;
          display: flex;
          font-weight: 700;
          margin-bottom: 0;
        }}
        
        .toggle__input {{
          clip: rect(0 0 0 0);
          clip-path: inset(50%);
          height: 1px;
          overflow: hidden;
          position: absolute;
          white-space: nowrap;
          width: 1px;
        }}
        
        .toggle__input:not([disabled]):active + .toggle-track,
        .toggle__input:not([disabled]):focus + .toggle-track {{
          border: 1px solid transparent;
          box-shadow: 0px 0px 0px 2px rgba(0, 0, 0, 0.8);
        }}
        
        .toggle__input:disabled + .toggle-track {{
          cursor: not-allowed;
          opacity: 0.7;
        }}
        
        .toggle-track {{
          background: rgba(255, 255, 255, 0.2);
          border: 1px solid rgba(255, 255, 255, 0.3);
          border-radius: 100px;
          cursor: pointer;
          display: flex;
          height: 30px;
          margin-right: 12px;
          position: relative;
          width: 60px;
          transition: all 0.3s ease;
        }}
        
        .toggle-track:hover {{
          border-color: rgba(255, 255, 255, 0.5);
        }}
        
        .toggle-indicator {{
          align-items: center;
          background: rgba(255, 255, 255, 0.3);
          border-radius: 24px;
          top: 3px;
          display: flex;
          height: 24px;
          justify-content: center;
          left: 2px;
          outline: solid 2px transparent;
          position: absolute;
          transition: transform 0.3s ease, background 0.3s ease;
          width: 24px;
        }}
        
        .checkMark {{
          fill: #fff;
          height: 20px;
          width: 20px;
          opacity: 0;
          transition: opacity 0.3s ease-in-out;
        }}
        
        .toggle__input:checked + .toggle-track .toggle-indicator {{
          background: #4caf50;
          transform: translateX(30px);
          top: 3px;
        }}
        
        .toggle__input:checked + .toggle-track .checkMark {{
          opacity: 1;
          transition: opacity 0.3s ease-in-out;
        }}
        
        /* Slider Styles */
        .slider-container {{
          margin-top: 10px;
        }}
        
        .slider {{
          width: 100%;
          height: 6px;
          border-radius: 3px;
          background: rgba(255, 255, 255, 0.2);
          outline: none;
          -webkit-appearance: none;
          appearance: none;
          box-sizing: border-box;
        }}
        
        .slider::-webkit-slider-thumb {{
          -webkit-appearance: none;
          appearance: none;
          width: 18px;
          height: 18px;
          border-radius: 50%;
          background: #4caf50;
          cursor: pointer;
          transition: all 0.3s ease;
        }}
        
        .slider::-webkit-slider-thumb:hover {{
          background: #40c057;
          transform: scale(1.1);
        }}
        
        .slider::-moz-range-thumb {{
          width: 18px;
          height: 18px;
          border-radius: 50%;
          background: #4caf50;
          cursor: pointer;
          border: none;
          transition: all 0.3s ease;
        }}
        
        .slider::-moz-range-thumb:hover {{
          background: #40c057;
          transform: scale(1.1);
        }}
        
        .slider-value {{
          color: rgba(255, 255, 255, 0.7);
          font-size: 12px;
          margin-top: 5px;
          text-align: right;
        }}
        
        /* Retro Shadow Header */
        h1 {{
          font-family: "Avant Garde", Avantgarde, "Century Gothic", CenturyGothic, "AppleGothic", sans-serif;
          font-size: 35px;
          padding: 15px 15px;
          text-align: center;
          text-transform: uppercase;
          text-rendering: optimizeLegibility;
        }}
        h1.retroshadow {{
          color: #4caf50;
          letter-spacing: .05em;
          text-shadow: 
            3px 3px 3px #d5d5d5, 
            6px 6px 0px rgba(0, 0, 0, 0.2);
        }}
        
        /* New Dropdown Menu Styles */
        .sec-center {{
          position: relative;
          max-width: 100%;
          text-align: center;
          z-index: 200;
        }}
        [type="checkbox"]:checked,
        [type="checkbox"]:not(:checked){{
          position: absolute;
          left: -9999px;
          opacity: 0;
          pointer-events: none;
        }}
        .dropdown:checked + label,
        .dropdown:not(:checked) + label{{
          position: relative;
          font-weight: 500;
          font-size: 24px;
          line-height: 2;
          height: 50px;
          transition: all 200ms linear;
          border-radius: 4px;
          width: 100%;
          letter-spacing: 1px;
          display: -webkit-inline-flex;
          display: -ms-inline-flexbox;
          display: inline-flex;
          -webkit-align-items: center;
          -moz-align-items: center;
          -ms-align-items: center;
          align-items: center;
          -webkit-justify-content: center;
          -moz-justify-content: center;
          -ms-justify-content: center;
          justify-content: center;
          -ms-flex-pack: center;
          text-align: center;
          border: none;
          background-color: #4caf50;
          cursor: pointer;
          color: #fff;
          box-shadow: 0 12px 35px 0 rgba(76,175,80,.15);
        }}
        .dropdown:checked + label span,
        .dropdown:not(:checked) + label span {{
          color: #fff;
        }}
        .dropdown:checked + label:before,
        .dropdown:not(:checked) + label:before{{
          position: fixed;
          top: 0;
          left: 0;
          content: '';
          width: 100%;
          height: 100%;
          z-index: -1;
          cursor: auto;
          pointer-events: none;
        }}
        .dropdown:checked + label:before{{
          pointer-events: auto;
        }}
        .dropdown:not(:checked) + label span {{
          font-size: 24px;
          margin-left: 10px;
          transition: transform 200ms linear;
        }}
        .dropdown:checked + label span {{
          transform: rotate(180deg);
          font-size: 24px;
          margin-left: 10px;
          transition: transform 200ms linear;
        }}
        .section-dropdown {{
          position: absolute;
          padding: 5px;
          background-color: rgba(0, 0, 0, 0.95);
          top: 70px;
          left: 0;
          width: 100%;
          border-radius: 4px;
          display: block;
          box-shadow: 0 14px 35px 0 rgba(0,0,0,0.8);
          z-index: 2;
          opacity: 0;
          pointer-events: none;
          transform: translateY(20px);
          transition: all 200ms linear;
        }}
        .dropdown:checked ~ .section-dropdown{{
          opacity: 1;
          pointer-events: auto;
          transform: translateY(0);
        }}
        .section-dropdown:before {{
          position: absolute;
          top: -20px;
          left: 0;
          width: 100%;
          height: 20px;
          content: '';
          display: block;
          z-index: 1;
        }}
        .section-dropdown:after {{
          position: absolute;
          top: -7px;
          left: 30px;
          width: 0; 
          height: 0; 
          border-left: 8px solid transparent;
          border-right: 8px solid transparent; 
          border-bottom: 8px solid rgba(0, 0, 0, 0.95);
          content: '';
          display: block;
          z-index: 2;
          transition: all 200ms linear;
        }}
        .section-dropdown a {{
          position: relative;
          color: #fff;
          transition: all 200ms linear;
          font-weight: 500;
          font-size: 24px;
          border-radius: 2px;
          padding: 5px 0;
          padding-left: 20px;
          padding-right: 15px;
          margin: 2px 0;
          text-align: left;
          text-decoration: none;
          display: -ms-flexbox;
          display: flex;
          -webkit-align-items: center;
          -moz-align-items: center;
          -ms-align-items: center;
          align-items: center;
          justify-content: space-between;
          -ms-flex-pack: distribute;
        }}
        .section-dropdown a:hover {{
          color: #fff;
          background-color: #4caf50;
        }}
        .section-dropdown a.current-server {{
          color: #4caf50;
          font-weight: bold;
        }}
        .section-dropdown a.current-server:hover {{
          color: #fff;
          background-color: #4caf50;
        }}
      </style>
      <script>
        let elapsed = {elapsed};
        let duration = {duration};
        let paused = {str(paused).lower()};
        let lastPlaybackState = null;
        
        // Function to attach expandable functionality to a badge
        function attachExpandableHandler(badge) {{
          if (badge.hasAttribute('data-handler-attached')) {{
            console.log(`[DEBUG] Handler already attached to ${{badge.dataset.type}} badge`);
            return; // Already has handler attached
          }}
          badge.setAttribute('data-handler-attached', 'true');
          console.log(`[DEBUG] Attaching expandable handler to ${{badge.dataset.type}} badge`);
          
          badge.addEventListener('click', function(e) {{
            e.stopPropagation();
            console.log(`[DEBUG] Clicked on ${{this.dataset.type}} badge`);
            const isExpanded = this.classList.contains('expanded');
            const currentLang = this.querySelector('.current-lang');
            const allLangs = this.querySelector('.all-langs');
            const currentLangText = this.dataset.current;
            const allLangsText = this.dataset.all;
            
            console.log(`[DEBUG] Badge state: expanded=${{isExpanded}}, currentLang=${{currentLangText}}, allLangs=${{allLangsText}}`);
            
            if (isExpanded) {{
              // Collapse: show only current language
              this.classList.remove('expanded');
              currentLang.style.display = 'inline';
              allLangs.style.display = 'none';
              // Store preference
              localStorage.setItem('language-badge-expanded-' + this.dataset.type, 'false');
              console.log(`[DEBUG] Collapsed ${{this.dataset.type}} badge`);
            }} else {{
              // Expand: show all languages with active language highlighted
              this.classList.add('expanded');
              currentLang.style.display = 'none';
              
              // Create highlighted language list
              const languages = allLangsText.split(', ');
              const highlightedLangs = languages.map(lang => {{
                const isActive = lang.trim() === currentLangText.trim();
                return isActive ? `<span class="active-language">${{lang}}</span>` : lang;
              }}).join(', ');
              
              allLangs.innerHTML = highlightedLangs;
              allLangs.style.display = 'inline';
              // Store preference
              localStorage.setItem('language-badge-expanded-' + this.dataset.type, 'true');
              console.log(`[DEBUG] Expanded ${{this.dataset.type}} badge`);
            }}
          }});
        }}
        
        // Function to initialize expandable language badges
        function initializeExpandableBadges() {{
          // Check all badges with data-type attribute, not just those with expandable-language class
          const allLanguageBadges = document.querySelectorAll('.badge[data-type="audio"], .badge[data-type="subtitle"]');
          console.log(`[DEBUG] initializeExpandableBadges: Found ${{allLanguageBadges.length}} language badges`);
          
          allLanguageBadges.forEach(badge => {{
            const allLangsText = badge.dataset.all;
            const langCount = allLangsText ? allLangsText.split(', ').filter(l => l.trim()).length : 0;
            console.log(`[DEBUG] Badge type: ${{badge.dataset.type}}, languages: "${{allLangsText}}", count: ${{langCount}}`);
            
            if (langCount > 1) {{
              badge.classList.add('expandable-language');
              console.log(`[DEBUG] Added expandable-language class to ${{badge.dataset.type}} badge`);
              attachExpandableHandler(badge);
              
              // Restore saved preference
              const savedState = localStorage.getItem('language-badge-expanded-' + badge.dataset.type);
              if (savedState === 'true') {{
                badge.classList.add('expanded');
                const currentLang = badge.querySelector('.current-lang');
                const allLangs = badge.querySelector('.all-langs');
                if (currentLang) currentLang.style.display = 'none';
                
                // Create highlighted language list for restored state
                const currentLangText = badge.dataset.current;
                const allLangsText = badge.dataset.all;
                const languages = allLangsText.split(', ').filter(l => l.trim());
                const highlightedLangs = languages.map(lang => {{
                  const isActive = lang.trim() === currentLangText.trim();
                  return isActive ? `<span class="active-language">${{lang}}</span>` : lang;
                }}).join(', ');
                
                if (allLangs) {{
                  allLangs.innerHTML = highlightedLangs;
                  allLangs.style.display = 'inline';
                }}
              }}
            }} else {{
              console.log(`[DEBUG] Badge ${{badge.dataset.type}} has only ${{langCount}} language(s), not making expandable`);
            }}
          }});
        }}
        
        // Expandable language badges functionality
        document.addEventListener('DOMContentLoaded', function() {{
          console.log('[DEBUG] DOMContentLoaded fired, initializing expandable badges');
          initializeExpandableBadges();
        }});
        
        // Also try after a short delay in case badges are added dynamically
        setTimeout(function() {{
          console.log('[DEBUG] Delayed initialization of expandable badges');
          initializeExpandableBadges();
        }}, 500);

        function updateTime() {{
          if (!paused && elapsed < duration) {{
            elapsed++;
            let percent = Math.floor((elapsed / duration) * 100);
            document.querySelector('.bar').style.width = percent + '%';
            
            // Format time based on duration
            let elapsedTime, totalTime;
            
            if (duration < 3600) {{
              // Less than 1 hour: show mm:ss
              let elapsedMinutes = Math.floor(elapsed / 60);
              let elapsedSeconds = elapsed % 60;
              elapsedTime = elapsedMinutes.toString().padStart(2, '0') + ':' + elapsedSeconds.toString().padStart(2, '0');
              
              let totalMinutes = Math.floor(duration / 60);
              let totalSeconds = duration % 60;
              totalTime = totalMinutes.toString().padStart(2, '0') + ':' + totalSeconds.toString().padStart(2, '0');
            }} else {{
              // 1 hour or more: show hh:mm:ss
              let hours = Math.floor(elapsed / 3600);
              let minutes = Math.floor((elapsed % 3600) / 60);
              let seconds = elapsed % 60;
              elapsedTime = hours.toString().padStart(2, '0') + ':' + minutes.toString().padStart(2, '0') + ':' + seconds.toString().padStart(2, '0');
              
              let totalHours = Math.floor(duration / 3600);
              let totalMinutes = Math.floor((duration % 3600) / 60);
              let totalSeconds = duration % 60;
              totalTime = totalHours.toString().padStart(2, '0') + ':' + totalMinutes.toString().padStart(2, '0') + ':' + totalSeconds.toString().padStart(2, '0');
            }}
            
            // Update timer text, preserving the button
            const timeDisplay = document.getElementById('time-display');
            const button = timeDisplay.querySelector('#playback-button');
            const timeText = elapsedTime + ' / ' + totalTime;
            
            // Skip timer update if button update is in progress
            if (buttonUpdateInProgress) {{
              console.log('[DEBUG] Skipping timer update - button update in progress');
              return;
            }}
            
            if (button) {{
              // If button exists, find or create a text node after the button
              let textNode = button.nextSibling;
              
              // Check if next sibling is a text node
              if (textNode && textNode.nodeType === Node.TEXT_NODE) {{
                // Update existing text node
                textNode.textContent = ' ' + timeText;
              }} else {{
                // Remove any non-text nodes after the button
                while (textNode && textNode.id !== 'playback-button') {{
                  const next = textNode.nextSibling;
                  if (textNode.nodeType !== Node.TEXT_NODE) {{
                    timeDisplay.removeChild(textNode);
                  }}
                  textNode = next;
                }}
                
                // Create and append new text node after button
                textNode = document.createTextNode(' ' + timeText);
                timeDisplay.appendChild(textNode);
              }}
            }} else {{
              // If no button, just update text
              timeDisplay.textContent = timeText;
            }}
          }}
        }}

        function resyncTime() {{
          fetch('/nowplaying?json=1')
            .then(res => res.json())
            .then(data => {{
              elapsed = data.elapsed;
              duration = data.duration;
              paused = data.paused;
            }});
        }}

        let lastItemId = null;
        let lastPausedState = null;
        let lastAudioLang = null;
        let lastSubtitleLang = null;
        let cachedButton = null;
        let buttonUpdateInProgress = false;
        
        function getOrCreateButton() {{
          // Get time-display element
          const timeDisplay = document.getElementById('time-display');
          if (!timeDisplay) {{
            console.log('[ERROR] time-display element not found, cannot recreate button');
            return null;
          }}
          
          // Try to get cached button first
          if (cachedButton && document.contains(cachedButton)) {{
            return cachedButton;
          }}
          
          // Try to find existing button
          let button = document.getElementById('playback-button');
          if (button) {{
            cachedButton = button;
            return button;
          }}
          
          // Button not found, try to recreate it
          console.log('[DEBUG] Button not found, attempting to recreate...');
          if (timeDisplay) {{
            // Create new button element
            button = document.createElement('img');
            button.id = 'playback-button';
            button.src = '/play-button.png';
            button.alt = 'Play';
            button.style.cssText = 'width: 20px; height: 20px; opacity: 1; transition: opacity 0.5s ease; display: inline-block; vertical-align: middle; margin-right: 4px;';
            
            // Add error handling for failed image loads
            button.onerror = function() {{
              console.log('[DEBUG] Button image failed to load, trying to reload...');
              this.style.opacity = '0.5';
              // Retry loading the image after a short delay
              setTimeout(() => {{
                this.src = this.src + '?retry=' + Date.now();
              }}, 1000);
            }};
            
            button.onload = function() {{
              console.log('[DEBUG] Button image loaded successfully');
              this.style.opacity = '1';
            }};
            
            // Insert at the beginning of time-display
            timeDisplay.insertBefore(button, timeDisplay.firstChild);
            cachedButton = button;
            console.log('[DEBUG] Button recreated successfully');
            return button;
          }} else {{
            console.log('[ERROR] time-display element not found, cannot recreate button');
            return null;
          }}
        }}
        
        function updatePlaybackButton(paused) {{
          // Prevent multiple simultaneous button updates
          if (buttonUpdateInProgress) {{
            console.log('[DEBUG] Button update already in progress, skipping...');
            return;
          }}
          
          // Get time-display element for setTimeout callbacks
          const timeDisplay = document.getElementById('time-display');
          
          const button = getOrCreateButton();
          console.log(`[DEBUG] updatePlaybackButton called: paused=${{paused}}, button found=${{!!button}}`);
          if (button) {{
            console.log(`[DEBUG] Button current src: ${{button.src}}`);
            
            // Determine new image source
            const newSrc = paused ? '/pause-button.png' : '/play-button.png';
            const newAlt = paused ? 'Pause' : 'Play';
            
            // If the image is already correct, no need to change
            if (button.src.endsWith(newSrc.split('/').pop())) {{
              console.log('[DEBUG] Button image already correct, no change needed');
              return;
            }}
            
            // Mark button update as in progress
            buttonUpdateInProgress = true;
            
            // Fade out → change image → fade in
            button.style.opacity = '0';
            
            setTimeout(() => {{
              // Double-check button still exists after timeout
              const currentButton = timeDisplay.querySelector('#playback-button');
              if (currentButton) {{
                currentButton.src = newSrc;
                currentButton.alt = newAlt;
                console.log(`[DEBUG] Button new src: ${{currentButton.src}}`);
                
                // Fade back in
                setTimeout(() => {{
                  currentButton.style.opacity = '1';
                  buttonUpdateInProgress = false; // Mark update as complete
                }}, 50); // Small delay to ensure image loads
              }} else {{
                console.log('[DEBUG] Button disappeared during update, recreating...');
                buttonUpdateInProgress = false; // Reset flag before retry
                // Button was removed during transition, recreate it
                setTimeout(() => updatePlaybackButton(paused), 100);
              }}
            }}, 250); // Half of transition duration for smooth effect
            
            // Ensure button is visible
            button.style.display = 'inline-block';
          }} else {{
            console.log('[ERROR] Could not get or create playback button!');
          }}
        }}
        
        function updateLanguageBadge(type, newLanguage) {{
          // Try multiple selectors to find the badge
          let badge = document.querySelector(`span.badge[data-type="${{type}}"]`);
          if (!badge) {{
            badge = document.querySelector(`.badge[data-type="${{type}}"]`);
          }}
          if (!badge) {{
            // Try finding by the text content
            const badges = document.querySelectorAll('.badge');
            for (let b of badges) {{
              if (b.dataset.type === type) {{
                badge = b;
                break;
              }}
            }}
          }}
          
          if (badge) {{
            console.log(`[DEBUG] Found ${{type}} badge`);
            console.log(`[DEBUG] Badge HTML:`, badge.outerHTML.substring(0, 200));
            const currentLangSpan = badge.querySelector('.current-lang');
            if (currentLangSpan) {{
              currentLangSpan.textContent = newLanguage;
              console.log(`[DEBUG] Updated ${{type}} badge to ${{newLanguage}}`);
            }}
            
            // Update the data-current attribute
            badge.dataset.current = newLanguage;
            
            // Ensure expandable-language class is present if there are multiple languages
            let allLangsText = badge.dataset.all;
            console.log(`[DEBUG] updateLanguageBadge for ${{type}}: allLangsText="${{allLangsText}}", has expandable class: ${{badge.classList.contains('expandable-language')}}`);
            
            // If allLangsText is empty or only has one language, try to get available languages from Player.GetProperties
            if (!allLangsText || allLangsText.split(', ').filter(l => l.trim()).length <= 1) {{
              console.log(`[DEBUG] ${{type}} badge has insufficient languages, attempting to fetch from player...`);
              // For now, we'll rely on the data-all attribute being set correctly in HTML
              // But we can try to re-initialize the badge
              initializeExpandableBadges();
              allLangsText = badge.dataset.all; // Re-read after initialization
            }}
            
            if (allLangsText) {{
              const languages = allLangsText.split(', ').filter(l => l.trim());
              const langCount = languages.length;
              console.log(`[DEBUG] Language count for ${{type}}: ${{langCount}}, languages: ${{JSON.stringify(languages)}}`);
              
              if (langCount > 1) {{
                badge.classList.add('expandable-language');
                console.log(`[DEBUG] Added expandable-language class to ${{type}} badge`);
                // Ensure click handler is attached
                attachExpandableHandler(badge);
                console.log(`[DEBUG] Attached expandable handler to ${{type}} badge`);
              }} else {{
                console.log(`[DEBUG] Not adding expandable class - only ${{langCount}} language(s) available: ${{languages}}`);
              }}
            }} else {{
              console.log(`[DEBUG] No allLangsText found for ${{type}} badge`);
            }}
            
            // If the badge is expanded, update the highlighted language
            if (badge.classList.contains('expanded')) {{
              const allLangsSpan = badge.querySelector('.all-langs');
              if (allLangsSpan) {{
                const allLangsText = badge.dataset.all;
                const languages = allLangsText.split(', ').filter(l => l.trim());
                const highlightedLangs = languages.map(lang => {{
                  const isActive = lang.trim() === newLanguage.trim();
                  return isActive ? `<span class="active-language">${{lang}}</span>` : lang;
                }}).join(', ');
                
                allLangsSpan.innerHTML = highlightedLangs;
                console.log(`[DEBUG] Updated expanded ${{type}} badge highlighting`);
              }}
            }}
          }} else {{
            console.log(`[DEBUG] Badge not found for type: ${{type}}`);
            // Try to find it after a short delay
            setTimeout(() => {{
              const badge = document.querySelector(`span.badge[data-type="${{type}}"]`) || document.querySelector(`.badge[data-type="${{type}}"]`);
              if (badge) {{
                console.log(`[DEBUG] Found ${{type}} badge after delay, updating...`);
                updateLanguageBadge(type, newLanguage);
              }}
            }}, 100);
          }}
        }}
        
        function checkPlaybackChange() {{
          fetch('/poll_playback')
            .then(res => {{
              if (!res.ok) {{
                throw new Error(`HTTP ${{res.status}}`);
              }}
              return res.json();
            }})
            .then(data => {{
              const currentState = data.playing;
              const currentItemId = data.item_id;
              const currentPaused = data.paused;
              const currentAudioLang = data.current_audio_lang || '';
              const currentSubtitleLang = data.current_subtitle_lang || '';
              
              console.log(`[DEBUG] Poll result: playing=${{currentState}}, item_id=${{currentItemId}}, lastItemId=${{lastItemId}}, paused=${{currentPaused}}, audio=${{currentAudioLang}}, subtitle=${{currentSubtitleLang}}`);
              
              // Update playback button based on pause state
              if (currentPaused !== lastPausedState) {{
                updatePlaybackButton(currentPaused);
                lastPausedState = currentPaused;
              }}
              
              // Check for language changes and update badges
              if (currentAudioLang && currentAudioLang !== lastAudioLang) {{
                console.log(`[DEBUG] Audio language changed from ${{lastAudioLang}} to ${{currentAudioLang}}`);
                updateLanguageBadge('audio', currentAudioLang);
                lastAudioLang = currentAudioLang;
              }}
              
              if (currentSubtitleLang && currentSubtitleLang !== lastSubtitleLang) {{
                console.log(`[DEBUG] Subtitle language changed from ${{lastSubtitleLang}} to ${{currentSubtitleLang}}`);
                updateLanguageBadge('subtitle', currentSubtitleLang);
                lastSubtitleLang = currentSubtitleLang;
              }}
              
              // Check for playback state change (start/stop)
              if (lastPlaybackState === null) {{
                lastPlaybackState = currentState;
                lastItemId = currentItemId;
                lastPausedState = currentPaused;
                lastAudioLang = currentAudioLang;
                lastSubtitleLang = currentSubtitleLang;
                updatePlaybackButton(currentPaused);
                console.log(`[DEBUG] Initial state set: lastPlaybackState=${{lastPlaybackState}}, lastItemId=${{lastItemId}}, lastPausedState=${{lastPausedState}}, audio=${{lastAudioLang}}, subtitle=${{lastSubtitleLang}}`);
              }} else if (currentState !== lastPlaybackState) {{
                // Only redirect if playback stops (true -> false), not when it starts (false -> true)
                // When it starts, we're already on the nowplaying page
                if (lastPlaybackState === true && currentState === false) {{
                  document.body.classList.add('fade-out');
                  setTimeout(() => {{
                    window.location.href = '/'; // Redirect to root when playback stops
                  }}, 1500);
                }}
                lastPlaybackState = currentState;
              }}
              // Check for item change (new track/episode while playing)
              else if (currentState && currentItemId && lastItemId && currentItemId !== lastItemId) {{
                console.log(`[DEBUG] Item changed from ${{lastItemId}} to ${{currentItemId}}`);
                document.body.classList.add('fade-out');
                setTimeout(() => {{
                  window.location.href = '/loading'; // Show loading screen then reload
                }}, 800);
              }}
              
              // Always update tracking variables at the end
              lastPlaybackState = currentState;
              lastItemId = currentItemId;
            }})
            .catch(error => {{
              console.error('Polling error:', error);
              // Retry after shorter interval on error
              setTimeout(checkPlaybackChange, 2000);
            }});
        }}

        function toggleMarquee() {{
          const marquee = document.querySelector('.marquee');
          const toggle = document.querySelector('.marquee-toggle');
          const content = document.querySelector('.content');
          
          marquee.classList.toggle('hidden');
          toggle.classList.toggle('hidden');
          
          if (marquee.classList.contains('hidden')) {{
            content.classList.add('no-marquee');
            toggle.innerHTML = '<div class="arrow up"></div>';
            toggle.title = 'Show Marquee';
          }} else {{
            content.classList.remove('no-marquee');
            toggle.innerHTML = '<div class="arrow"></div>';
            toggle.title = 'Hide Marquee';
          }}
        }}

        // Initialize button immediately and on DOM ready
        function initializeButton() {{
          console.log('[DEBUG] Initializing playback button');
          updatePlaybackButton(false); // Initialize as playing
        }}
        
        // Shimmer effect timer - trigger every 60 seconds
        function startShimmerTimer() {{
          setInterval(() => {{
            const marqueeText = document.querySelector('.marquee-text');
            if (marqueeText && !marqueeText.classList.contains('hidden')) {{
              console.log('[DEBUG] Triggering shimmer effect');
              
              // Remove any existing shimmer class first
              marqueeText.classList.remove('shimmer');
              
              // Reset all letter animations by temporarily removing and re-adding the class
              const letters = marqueeText.querySelectorAll('.letter');
              letters.forEach(letter => {{
                letter.style.animation = 'none';
              }});
              
              // Force a reflow to ensure the reset takes effect
              marqueeText.offsetHeight;
              
              // Clear the inline styles to let CSS take over
              letters.forEach(letter => {{
                letter.style.animation = '';
              }});
              
              // Add shimmer class
              marqueeText.classList.add('shimmer');
              
              // Remove shimmer class after animation completes
              setTimeout(() => {{
                marqueeText.classList.remove('shimmer');
                // Reset all letters to normal state
                const letters = marqueeText.querySelectorAll('.letter');
                letters.forEach(letter => {{
                  letter.style.animation = 'none';
                  letter.style.color = '';
                  letter.style.textShadow = '';
                }});
              }}, 6000); // Match animation duration (5s total)
            }}
          }}, 10000); // 10 seconds for testing - will be overridden by slider
        }}
        
        // Side Panel Functions
        function toggleSidePanel() {{
          try {{
            const panel = document.getElementById('sidePanel');
            const arrow = document.querySelector('.side-panel-toggle-arrow');
            if (!panel) {{
              console.error('[DEBUG] Side panel not found');
              return;
            }}
            if (!arrow) {{
              console.error('[DEBUG] Side panel arrow not found');
              return;
            }}
            panel.classList.toggle('open');
            if (panel.classList.contains('open')) {{
              arrow.style.transform = 'rotate(180deg)';
            }} else {{
              arrow.style.transform = 'rotate(0deg)';
            }}
          }} catch (error) {{
            console.error('[DEBUG] Error in toggleSidePanel:', error);
          }}
        }}
        
        // Ensure function is globally accessible
        window.toggleSidePanel = toggleSidePanel;
        
        // Server Management Functions
        let currentServerId = null;
        let shimmerInterval = null;
        let fanartInterval = null;
        
        async function loadServers() {{
          try {{
            const response = await fetch('/api/servers');
            const data = await response.json();
            
            if (data.servers && data.servers.length > 0) {{
              // Get current server
              const currentResponse = await fetch('/api/current-server');
              const currentData = await currentResponse.json();
              
              if (currentData.server_id) {{
                currentServerId = currentData.server_id;
              }} else {{
                // Default to first server
                currentServerId = data.servers[0].id;
                // Switch to first server if none selected
                await switchServerFromDropdown(data.servers[0].id);
                return;
              }}
              
              // Populate new dropdown menu
              populateServerDropdown(data.servers, currentData.server_id || data.servers[0].id);
            }}
          }} catch (error) {{
            console.error('Failed to load servers:', error);
          }}
        }}
        
        function populateServerDropdown(servers, currentServerId) {{
          const dropdownList = document.getElementById('serverDropdownList');
          const dropdownLabel = document.getElementById('serverDropdownLabel');
          
          if (!dropdownList || !dropdownLabel) return;
          
          dropdownList.innerHTML = '';
          
          if (servers && servers.length > 0) {{
            servers.forEach(server => {{
              const serverIp = server.ip || server.host;
              const isCurrent = server.id === currentServerId;
              
              const link = document.createElement('a');
              link.href = '#';
              link.textContent = serverIp;
              link.dataset.serverId = server.id;
              link.onclick = function(e) {{
                e.preventDefault();
                const serverId = parseInt(this.dataset.serverId);
                if (serverId && serverId !== currentServerId) {{
                  switchServerFromDropdown(serverId);
                }}
                // Close dropdown
                document.getElementById('serverDropdown').checked = false;
              }};
              
              if (isCurrent) {{
                link.classList.add('current-server');
                dropdownLabel.innerHTML = `${{serverIp}} <span style="font-size: 24px; margin-left: 10px; transition: transform 200ms linear; color: #fff;">▼</span>`;
              }}
              
              dropdownList.appendChild(link);
            }});
          }}
        }}
        
        async function switchServerFromDropdown(serverId) {{
          if (!serverId) return;
          
          try {{
            const response = await fetch(`/api/switch-server/${{serverId}}`, {{
              method: 'POST'
            }});
            const data = await response.json();
            
            if (data.success) {{
              currentServerId = serverId;
              // Show loading screen then reload
              document.body.classList.add('fade-out');
              setTimeout(() => {{
                window.location.href = '/loading';
              }}, 500);
            }}
          }} catch (error) {{
            console.error('Failed to switch server:', error);
          }}
        }}
        
        async function switchServer() {{
          const select = document.getElementById('serverSelect');
          const serverId = parseInt(select.value);
          
          if (!serverId) return;
          
          try {{
            const response = await fetch(`/api/switch-server/${{serverId}}`, {{
              method: 'POST'
            }});
            const data = await response.json();
            
            if (data.success) {{
              currentServerId = serverId;
              // Reload immediately without delay to avoid double reload
              location.reload();
            }}
          }} catch (error) {{
            console.error('Failed to switch server:', error);
          }}
        }}
        
        // Preference Management Functions (Server-side storage with localStorage fallback)
        async function loadPreferences() {{
          try {{
            const response = await fetch('/api/preferences');
            if (response.ok) {{
              const prefs = await response.json();
              // Merge with localStorage as fallback
              return {{
                blurPreference: prefs.blurPreference || localStorage.getItem('blurPreference') || 'blurred',
                blurAmount: prefs.blurAmount || localStorage.getItem('blurAmount') || '50',
                overlayPreference: prefs.overlayPreference || localStorage.getItem('overlayPreference') || 'enabled',
                overlayOpacity: prefs.overlayOpacity || localStorage.getItem('overlayOpacity') || '85',
                marqueeInterval: prefs.marqueeInterval || localStorage.getItem('marqueeInterval') || '10',
                fanartInterval: prefs.fanartInterval || localStorage.getItem('fanartInterval') || '20'
              }};
            }}
          }} catch (error) {{
            console.log('[DEBUG] Failed to load preferences from server, using localStorage:', error);
          }}
          // Fallback to localStorage
          return {{
            blurPreference: localStorage.getItem('blurPreference') || 'blurred',
            blurAmount: localStorage.getItem('blurAmount') || '50',
            overlayPreference: localStorage.getItem('overlayPreference') || 'enabled',
            overlayOpacity: localStorage.getItem('overlayOpacity') || '85',
            marqueeInterval: localStorage.getItem('marqueeInterval') || '10',
            fanartInterval: localStorage.getItem('fanartInterval') || '20'
          }};
        }}
        
        async function savePreference(key, value) {{
          // Save to localStorage immediately for responsiveness
          localStorage.setItem(key, value);
          
          // Also save to server
          try {{
            const response = await fetch('/api/preferences', {{
              method: 'POST',
              headers: {{ 'Content-Type': 'application/json' }},
              body: JSON.stringify({{ [key]: value }})
            }});
            if (!response.ok) {{
              console.log(`[DEBUG] Failed to save preference ${{key}} to server, using localStorage only`);
            }}
          }} catch (error) {{
            console.log(`[DEBUG] Error saving preference ${{key}} to server:`, error);
          }}
        }}
        
        // Blur Toggle Functionality
        function toggleBlur() {{
          const content = document.querySelector('.content');
          const blurToggle = document.getElementById('blurToggle');
          const blurSliderContainer = document.getElementById('blurSliderContainer');
          const isEnabled = blurToggle.checked;
          
          if (isEnabled) {{
            // Enable blur - apply saved blur amount
            const savedBlurAmount = parseInt(localStorage.getItem('blurAmount') || '50');
            content.style.backdropFilter = `blur(${{savedBlurAmount / 10}}px)`;
            content.style.webkitBackdropFilter = `blur(${{savedBlurAmount / 10}}px)`;
            blurSliderContainer.style.display = 'block';
            savePreference('blurPreference', 'blurred');
          }} else {{
            // Disable blur - hide it
            content.style.backdropFilter = 'none';
            content.style.webkitBackdropFilter = 'none';
            blurSliderContainer.style.display = 'none';
            savePreference('blurPreference', 'non-blurred');
          }}
        }}
        
        function updateBlurAmount(value) {{
          const content = document.querySelector('.content');
          const blurToggle = document.getElementById('blurToggle');
          const blurValue = parseInt(value);
          document.getElementById('blurValue').textContent = blurValue + '%';
          
          // Only apply blur if toggle is enabled
          if (blurToggle.checked) {{
            content.style.backdropFilter = `blur(${{blurValue / 10}}px)`;
            content.style.webkitBackdropFilter = `blur(${{blurValue / 10}}px)`;
          }}
          
          savePreference('blurAmount', blurValue.toString());
        }}
        
        // Overlay Toggle Functionality
        function toggleOverlay() {{
          const content = document.querySelector('.content');
          const overlayToggle = document.getElementById('overlayToggle');
          const opacitySliderContainer = document.getElementById('opacitySliderContainer');
          const isEnabled = overlayToggle.checked;
          
          if (isEnabled) {{
            // Enable overlay - apply saved opacity
            const savedOpacity = parseInt(localStorage.getItem('overlayOpacity') || '85');
            const opacity = savedOpacity / 100;
            content.style.backgroundColor = `rgba(0, 0, 0, ${{opacity * 0.85}})`;
            content.style.boxShadow = '0 8px 32px rgba(0,0,0,0.8)';
            opacitySliderContainer.style.display = 'block';
            savePreference('overlayPreference', 'enabled');
          }} else {{
            // Disable overlay - hide it
            content.style.backgroundColor = 'rgba(0, 0, 0, 0)';
            content.style.boxShadow = 'none';
            opacitySliderContainer.style.display = 'none';
            savePreference('overlayPreference', 'disabled');
          }}
        }}
        
        function updateOverlayOpacity(value) {{
          const content = document.querySelector('.content');
          const overlayToggle = document.getElementById('overlayToggle');
          const opacityValue = parseInt(value);
          document.getElementById('opacityValue').textContent = opacityValue + '%';
          
          // Only apply opacity if overlay toggle is enabled
          if (overlayToggle.checked) {{
            const opacity = opacityValue / 100;
            content.style.backgroundColor = `rgba(0, 0, 0, ${{opacity * 0.85}})`;
            content.style.boxShadow = '0 8px 32px rgba(0,0,0,0.8)';
          }} else {{
            // Remove all overlay effects if toggle is disabled
            content.style.backgroundColor = 'rgba(0, 0, 0, 0)';
            content.style.boxShadow = 'none';
          }}
          
          savePreference('overlayOpacity', opacityValue.toString());
        }}
        
        function updateMarqueeInterval(value) {{
          const intervalValue = parseInt(value);
          document.getElementById('marqueeIntervalValue').textContent = intervalValue + 's';
          
          // Clear existing interval
          if (shimmerInterval) {{
            clearInterval(shimmerInterval);
          }}
          
          // Set new interval (convert seconds to milliseconds)
          shimmerInterval = setInterval(() => {{
            const marqueeText = document.querySelector('.marquee-text');
            if (marqueeText && !marqueeText.classList.contains('hidden')) {{
              marqueeText.classList.remove('shimmer');
              const letters = marqueeText.querySelectorAll('.letter');
              letters.forEach(letter => {{
                letter.style.animation = 'none';
              }});
              marqueeText.offsetHeight;
              letters.forEach(letter => {{
                letter.style.animation = '';
              }});
              marqueeText.classList.add('shimmer');
              setTimeout(() => {{
                marqueeText.classList.remove('shimmer');
              }}, 2000);
            }}
          }}, intervalValue * 1000);
          
          savePreference('marqueeInterval', intervalValue.toString());
        }}
        
        function updateFanartInterval(value) {{
          const intervalValue = parseInt(value);
          document.getElementById('fanartIntervalValue').textContent = intervalValue + 's';
          
          // Clear existing interval
          if (fanartInterval) {{
            clearInterval(fanartInterval);
          }}
          
          // Set new interval (convert seconds to milliseconds)
          // Note: This requires the cycleFanarts function to be accessible
          if (typeof cycleFanarts === 'function') {{
            fanartInterval = setInterval(cycleFanarts, intervalValue * 1000);
          }}
          
          savePreference('fanartInterval', intervalValue.toString());
        }}
        
        async function initializeBlurToggle() {{
          const content = document.querySelector('.content');
          const blurToggle = document.getElementById('blurToggle');
          const overlayToggle = document.getElementById('overlayToggle');
          const blurSliderContainer = document.getElementById('blurSliderContainer');
          const opacitySliderContainer = document.getElementById('opacitySliderContainer');
          
          // Load preferences from server (with localStorage fallback)
          const prefs = await loadPreferences();
          const savedBlurPreference = prefs.blurPreference;
          const savedOverlayPreference = prefs.overlayPreference;
          const savedBlurAmount = prefs.blurAmount;
          const savedOpacity = prefs.overlayOpacity;
          const savedMarqueeInterval = prefs.marqueeInterval;
          const savedFanartInterval = prefs.fanartInterval;
          
          // Initialize blur toggle
          if (savedBlurPreference === 'blurred') {{
            blurToggle.checked = true;
            content.style.backdropFilter = `blur(${{parseInt(savedBlurAmount) / 10}}px)`;
            content.style.webkitBackdropFilter = `blur(${{parseInt(savedBlurAmount) / 10}}px)`;
            content.classList.remove('non-blurred');
            content.classList.add('blurred');
            if (blurSliderContainer) blurSliderContainer.style.display = 'block';
          }} else {{
            blurToggle.checked = false;
            content.style.backdropFilter = 'none';
            content.style.webkitBackdropFilter = 'none';
            content.classList.remove('blurred');
            content.classList.add('non-blurred');
            if (blurSliderContainer) blurSliderContainer.style.display = 'none';
          }}
          
          // Set blur slider value
          if (document.getElementById('blurSlider')) {{
            document.getElementById('blurSlider').value = savedBlurAmount;
            document.getElementById('blurValue').textContent = savedBlurAmount + '%';
          }}
          
          // Initialize overlay toggle
          if (savedOverlayPreference === 'enabled') {{
            overlayToggle.checked = true;
            const opacity = parseInt(savedOpacity) / 100;
            content.style.backgroundColor = `rgba(0, 0, 0, ${{opacity * 0.85}})`;
            content.style.boxShadow = '0 8px 32px rgba(0,0,0,0.8)';
            opacitySliderContainer.style.display = 'block';
          }} else {{
            overlayToggle.checked = false;
            content.style.backgroundColor = 'rgba(0, 0, 0, 0)';
            content.style.boxShadow = 'none';
            opacitySliderContainer.style.display = 'none';
          }}
          
          // Set opacity slider value
          if (document.getElementById('opacitySlider')) {{
            document.getElementById('opacitySlider').value = savedOpacity;
            document.getElementById('opacityValue').textContent = savedOpacity + '%';
          }}
          
          // Initialize intervals
          if (document.getElementById('marqueeIntervalSlider')) {{
            updateMarqueeInterval(savedMarqueeInterval);
            document.getElementById('marqueeIntervalSlider').value = savedMarqueeInterval;
          }}
          
          if (document.getElementById('fanartIntervalSlider')) {{
            updateFanartInterval(savedFanartInterval);
            document.getElementById('fanartIntervalSlider').value = savedFanartInterval;
          }}
        }}
        
        // Wait for DOM to be ready before initializing
        function waitForDOM() {{
          if (document.readyState === 'loading') {{
            document.addEventListener('DOMContentLoaded', initializeAll);
          }} else {{
            initializeAll();
          }}
        }}
        
        async function initializeAll() {{
          // Wait a bit more for all elements to be rendered
          setTimeout(async () => {{
            initializeButton();
            startShimmerTimer();
            loadServers();
            await initializeBlurToggle();
          }}, 200);
        }}
        
        waitForDOM();
        
        setInterval(updateTime, 1000);
        setInterval(resyncTime, 5000);
        setInterval(checkPlaybackChange, 2000);
        
        // Fanart slideshow functionality
        setTimeout(function() {{
          let currentFanartIndex = 0;
          const fanartSlides = document.querySelectorAll('.fanart-slide');
          const totalFanarts = fanartSlides.length;
          
          console.log(`[DEBUG] Found ${{totalFanarts}} fanart slides`);
          
          function cycleFanarts() {{
            if (totalFanarts <= 1) return;
            
            console.log(`[DEBUG] Cycling fanarts - current: ${{currentFanartIndex}}, next: ${{(currentFanartIndex + 1) % totalFanarts}}`);
            
            const currentSlide = fanartSlides[currentFanartIndex];
            currentSlide.classList.remove('active');
            currentSlide.classList.add('fade-out');
            
            currentFanartIndex = (currentFanartIndex + 1) % totalFanarts;
            
            const nextSlide = fanartSlides[currentFanartIndex];
            nextSlide.classList.remove('fade-out');
            nextSlide.classList.add('active');
            
            console.log(`[DEBUG] Now showing fanart ${{currentFanartIndex}}`);
          }}
          
          // Start slideshow if we have multiple fanarts
          if (totalFanarts > 1) {{
            console.log('[DEBUG] Starting fanart slideshow with 20 second intervals');
            // Store cycleFanarts globally so it can be accessed by updateFanartInterval
            window.cycleFanarts = cycleFanarts;
            const savedFanartInterval = localStorage.getItem('fanartInterval') || '20';
            fanartInterval = setInterval(cycleFanarts, parseInt(savedFanartInterval) * 1000);
          }} else {{
            console.log('[DEBUG] Not enough fanarts for slideshow');
          }}
        }}, 100); // Wait 100ms for DOM to be ready
        
        function initializeBlurToggle() {{
          const content = document.querySelector('.content');
          const blurToggle = document.getElementById('blurToggle');
          const savedPreference = localStorage.getItem('blurPreference');
          const savedBlurAmount = localStorage.getItem('blurAmount') || '50';
          const savedOpacity = localStorage.getItem('overlayOpacity') || '85';
          const savedMarqueeInterval = localStorage.getItem('marqueeInterval') || '10';
          const savedFanartInterval = localStorage.getItem('fanartInterval') || '20';
          
          // Default: blurred for episodes and music, non-blurred for movies
          const defaultPreference = 'blurred';
          const preference = savedPreference || defaultPreference;
          
          if (preference === 'blurred') {{
            content.classList.add('blurred');
            content.classList.remove('non-blurred');
            if (blurToggle) blurToggle.checked = true;
          }} else {{
            content.classList.add('non-blurred');
            content.classList.remove('blurred');
            if (blurToggle) blurToggle.checked = false;
          }}
          
          // Restore blur amount
          if (document.getElementById('blurSlider')) {{
            updateBlurAmount(savedBlurAmount);
            document.getElementById('blurSlider').value = savedBlurAmount;
          }}
          
          // Restore overlay opacity
          if (document.getElementById('opacitySlider')) {{
            updateOverlayOpacity(savedOpacity);
            document.getElementById('opacitySlider').value = savedOpacity;
          }}
          
          // Restore intervals
          if (document.getElementById('marqueeIntervalSlider')) {{
            updateMarqueeInterval(savedMarqueeInterval);
            document.getElementById('marqueeIntervalSlider').value = savedMarqueeInterval;
          }}
          
          if (document.getElementById('fanartIntervalSlider')) {{
            updateFanartInterval(savedFanartInterval);
            document.getElementById('fanartIntervalSlider').value = savedFanartInterval;
          }}
          
          console.log('[DEBUG] Blur toggle initialized with preference:', savedPreference || 'blurred (default)');
        }}
        
        // Legacy initialization (for backward compatibility)
        function initializeBlurToggleLegacy() {{
          const content = document.querySelector('.content');
          const savedPreference = localStorage.getItem('blurPreference');
          
          // For episodes, default to blurred (current behavior)
          if (savedPreference === 'non-blurred') {{
            content.classList.add('non-blurred');
            content.classList.remove('blurred');
          }} else {{
            content.classList.add('blurred');
            content.classList.remove('non-blurred');
          }}
          
          console.log('[DEBUG] Blur toggle initialized with preference:', savedPreference || 'blurred (default)');
        }}
        
        // Initialize blur toggle on page load
        setTimeout(initializeBlurToggle, 100);

        // Poster Zoom Logic
        (function() {{
          function setupPosterZoom() {{
            const posters = document.querySelectorAll('img.poster, img.show-poster, img.season-poster');
            if (!posters.length) return;

            let overlay = document.querySelector('.poster-zoom-overlay');
            if (!overlay) {{
              overlay = document.createElement('div');
              overlay.className = 'poster-zoom-overlay';
              overlay.innerHTML = '<img class="poster-zoom-image" src="" alt="Expanded artwork">';
              document.body.appendChild(overlay);
            }}

            const overlayImg = overlay.querySelector('.poster-zoom-image');

            function openOverlay(src, alt) {{
              if (!src) return;
              overlayImg.src = src;
              overlayImg.alt = alt || 'Expanded artwork';
              overlay.classList.add('visible');
            }}

            function closeOverlay() {{
              overlay.classList.remove('visible');
              overlayImg.src = '';
            }}

            posters.forEach(poster => {{
              poster.style.cursor = 'pointer';
              poster.addEventListener('click', (e) => {{
                // Skip non-image fallback icons if any are marked with .no-image
                if (poster.classList.contains('no-image')) return;
                e.stopPropagation();
                openOverlay(poster.src, poster.alt);
              }});
            }});

            overlay.addEventListener('click', () => {{
              closeOverlay();
            }});

            document.addEventListener('keydown', (e) => {{
              if (e.key === 'Escape') {{
                closeOverlay();
              }}
            }});
          }}

          if (document.readyState === 'loading') {{
            document.addEventListener('DOMContentLoaded', setupPosterZoom);
          }} else {{
            setupPosterZoom();
          }}
        }})();
      </script>
    </head>
    <body>
      <!-- Fanart Slideshow Container -->
      <div class="fanart-container">
        {''.join([f'<div class="fanart-slide{" active" if i == 0 else ""}" style="background-image: url(\'{fanart}\')"></div>' for i, fanart in enumerate(fanart_variants)]) if fanart_variants else ''}
      </div>
      
      <div class="marquee">
        <div class="marquee-text"><span class="letter">N</span><span class="letter">O</span><span class="letter">W</span><span class="letter">&nbsp;</span><span class="letter">P</span><span class="letter">L</span><span class="letter">A</span><span class="letter">Y</span><span class="letter">I</span><span class="letter">N</span><span class="letter">G</span></div>
        <div class="marquee-toggle" onclick="toggleMarquee()" title="Hide Marquee">
          <div style="color: white; font-size: 16px; font-weight: bold;">▲</div>
        </div>
      </div>
      <div class="content">
        <div class="left-section">
          <div class="poster-container">
            {f"<img class='show-poster' src='{show_poster_url}' />" if show_poster_url else ""}
            {f"<img class='season-poster' src='{season_poster_url}' />" if season_poster_url else ""}
          </div>
          <div>
            {f"<img class='logo' src='{clearlogo_url}' />" if clearlogo_url else (f"<img class='banner' src='{banner_url}' />" if banner_url else f"<h2 style='margin-bottom: 4px;'>📺 {show}</h2>")}
            {f"<p style='font-style: italic; color: #ccc; margin-top: 8px;'>{tagline}</p>" if tagline else ""}
            
            <div class="episode-info">
              {f"<div class='show-title'>{show}</div>" if not clearlogo_url and not banner_url else ""}
              <div class="episode-badges">
                {f"<span class='badge episode-badge'>{season_badge}</span>" if season_badge else ""}
                {f"<span class='badge episode-badge'>{episode_badge}</span>" if episode_badge else ""}
                {f"<span class='badge episode-badge'>{title_badge}</span>" if title_badge else ""}
              </div>
            </div>
            
            {f"<p><strong>Year:</strong> {release_year}</p>" if release_year else ""}
            {f"<p><strong>Director:</strong> {director_names}</p>" if director_names and director_names != "N/A" else ""}
            {f"<p><strong>Cast:</strong> {cast_names}</p>" if cast_names and cast_names != "N/A" else ""}
            {f"<h3 style='margin-top:20px;'>Plot</h3><p style='max-width:600px;'>{plot}</p>" if plot and plot.strip() else ""}
            <div class="badges">
              {rating_html}
              {f'<a href="{imdb_url}" target="_blank" class="badge-imdb"><span>IMDb</span></a>' if imdb_url else ''}
              {f"<span class='badge'>{resolution}</span>" if resolution else ""}
              {f"<span class='badge'>{aspect_ratio}</span>" if aspect_ratio else ""}
              <span class="badge">{video_codec}</span>
              {f"<span class='badge'>{container_format}</span>" if container_format else ""}
              <span class="badge">{audio_codec} {channels}ch</span>
              <span class="badge">{hdr_type}</span>
              {f"<span class='badge'>{studio_names}</span>" if studio_names else ""}
              <span class="badge{' expandable-language' if len(all_audio_languages) > 1 else ''}" data-current="{current_audio}" data-all="{', '.join(all_audio_languages) if all_audio_languages else current_audio}" data-type="audio">
                Audio: <span class="current-lang">{current_audio}</span>
                <span class="all-langs" style="display: none;">{', '.join(all_audio_languages) if all_audio_languages else current_audio}</span>
              </span>
              <span class="badge {'expandable-language' if len(all_subtitle_languages) > 1 else ''}" data-current="{current_subtitle}" data-all="{', '.join(all_subtitle_languages)}" data-type="subtitle">
                Subs: <span class="current-lang">{current_subtitle}</span>
                <span class="all-langs" style="display: none;">{', '.join(all_subtitle_languages)}</span>
              </span>
              {"".join(f"<span class='badge'>{g}</span>" for g in genre_badges)}
            </div>
            <div class="progress-wrapper">
              <span class="badge" id="time-display" style="display: flex; align-items: center; gap: 8px; flex-shrink: 0;">
                <img id="playback-button" src="/play-button.png" alt="Play" style="width: 20px; height: 20px; opacity: 1; transition: opacity 0.5s ease;">
                {f"{elapsed//60:02d}:{elapsed%60:02d}" if duration < 3600 else f"{elapsed//3600:02d}:{(elapsed//60)%60:02d}:{elapsed%60:02d}"} / {f"{duration//60:02d}:{duration%60:02d}" if duration < 3600 else f"{duration//3600:02d}:{(duration//60)%60:02d}:{duration%60:02d}"}
              </span>
              <div class="progress-container">
                <div class="progress">
                  <div class="bar"></div>
                </div>
              </div>
            </div>
          </div>
        </div>
        <!-- Clearart removed as requested -->
      </div>
      
      <!-- Side Panel -->
      <div class="side-panel" id="sidePanel">
        <!-- Side Panel Toggle Button -->
        <div class="side-panel-toggle" onclick="toggleSidePanel()">
          <div class="side-panel-toggle-arrow">◄</div>
        </div>
        
        <div style="overflow-y: auto; height: 100%; padding-top: 20px; padding-left: 15px; padding-right: 10px; box-sizing: border-box;">
          <h1 class="retroshadow">Now Playing On</h1>
          
          <div class="side-panel-section">
            <div class="sec-center">
              <input class="dropdown" type="checkbox" id="serverDropdown" name="serverDropdown">
              <label class="for-dropdown" for="serverDropdown" id="serverDropdownLabel">Select Server <span style="font-size: 24px; margin-left: 10px; transition: transform 200ms linear; color: #fff;">▼</span></label>
              <div class="section-dropdown">
                <div id="serverDropdownList"></div>
              </div>
            </div>
          </div>
          
          <div class="side-panel-section">
            <div class="side-panel-row">
              <label>Toggle blur:</label>
              <label class="toggle">
                <input type="checkbox" class="toggle__input" id="blurToggle" onchange="toggleBlur()">
                <span class="toggle-track">
                  <span class="toggle-indicator">
                    <svg class="checkMark" viewBox="0 0 20 20">
                      <path d="M7.629,14.566c0.125,0.125,0.291,0.188,0.456,0.188c0.164,0,0.329-0.062,0.456-0.188l5.123-5.404c0.199-0.209,0.199-0.549,0-0.757c-0.198-0.209-0.52-0.209-0.717,0l-4.567,4.816l-2.125-2.125c-0.198-0.198-0.52-0.198-0.717,0c-0.197,0.199-0.197,0.52,0,0.717L7.629,14.566z"/>
                    </svg>
                  </span>
                </span>
              </label>
            </div>
            <div class="slider-container" id="blurSliderContainer">
              <label>Blur amount: <span class="slider-value" id="blurValue">50%</span></label>
              <input type="range" min="0" max="100" value="50" class="slider" id="blurSlider" oninput="updateBlurAmount(this.value)">
            </div>
          </div>
          
          <div class="side-panel-section">
            <div class="side-panel-row">
              <label>Toggle overlay:</label>
              <label class="toggle">
                <input type="checkbox" class="toggle__input" id="overlayToggle" onchange="toggleOverlay()">
                <span class="toggle-track">
                  <span class="toggle-indicator">
                    <svg class="checkMark" viewBox="0 0 20 20">
                      <path d="M7.629,14.566c0.125,0.125,0.291,0.188,0.456,0.188c0.164,0,0.329-0.062,0.456-0.188l5.123-5.404c0.199-0.209,0.199-0.549,0-0.757c-0.198-0.209-0.52-0.209-0.717,0l-4.567,4.816l-2.125-2.125c-0.198-0.198-0.52-0.198-0.717,0c-0.197,0.199-0.197,0.52,0,0.717L7.629,14.566z"/>
                    </svg>
                  </span>
                </span>
              </label>
            </div>
            <div class="slider-container" id="opacitySliderContainer">
              <label>Overlay opacity: <span class="slider-value" id="opacityValue">85%</span></label>
              <input type="range" min="0" max="100" value="85" class="slider" id="opacitySlider" oninput="updateOverlayOpacity(this.value)">
            </div>
          </div>
          
          <div class="side-panel-section">
            <div class="slider-container">
              <label>Marquee shimmer interval: <span class="slider-value" id="marqueeIntervalValue">10s</span></label>
              <input type="range" min="5" max="60" value="10" class="slider" id="marqueeIntervalSlider" oninput="updateMarqueeInterval(this.value)">
            </div>
          </div>
          
          <div class="side-panel-section">
            <div class="slider-container">
              <label>Fanart slideshow interval: <span class="slider-value" id="fanartIntervalValue">20s</span></label>
              <input type="range" min="5" max="120" value="20" class="slider" id="fanartIntervalSlider" oninput="updateFanartInterval(this.value)">
            </div>
          </div>
        </div>
      </div>
    </body>
    </html>
    """
    return html
