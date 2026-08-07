"""Now-playing HTML build, load jobs, and soft-update payloads."""
from __future__ import annotations

import logging
import re
import time
import uuid

from flask import render_template, render_template_string

from kodi_np import config as _c
from kodi_np.art import (
    cleanup_old_artwork_files,
    empty_share,
    prepare_and_download_art,
    primary_artist_id,
    share_scope_matches,
)
from kodi_np.cache import (
    cache_session_id_for,
    clear_cache_playback,
    get_cache_entry,
    make_playback_fingerprint,
    set_cache_entry,
    store_playing_cache,
)
from kodi_np.overview import _format_overview_title
from kodi_np.rpc import kodi_rpc
from kodi_np.servers import get_active_server
from kodi_np.util import html_escape, prune_load_jobs
from parser import route_media_display

logger = logging.getLogger("kodi.nowplaying")

def build_nowplaying_html(progress_cb=None, session_id=None, as_payload=False):
    def update(progress, message):
        if progress_cb:
            progress_cb(progress, message)

    def _payload(html, *, idle=False, downloaded_art=None, fingerprint=None, title=None, media_type=None, paused=False, used_session_id=None, share=None):
        result = {
            "html": html,
            "idle": idle,
            "downloaded_art": downloaded_art or {},
            "fingerprint": fingerprint,
            "title": title,
            "media_type": media_type,
            "paused": paused,
            "session_id": used_session_id,
        }
        if share is not None:
            result["share"] = share
        return result if as_payload else html

    # Get active players - this is critical, so if it fails, show error
    try:
        update(5, "Checking player")
        active_response = kodi_rpc("Player.GetActivePlayers")
        active = active_response.get("result") if active_response else None
        if not active:
            update(100, "Idle")
            return _payload(render_template("index.html"), idle=True)

        player_id = active[0]["playerid"]
        active_server = get_active_server()
        active_server_id = active_server.get("id") if active_server else None
        prior_cache = get_cache_entry(active_server_id) if active_server_id is not None else None
        prior_share = (prior_cache or {}).get("share") or empty_share()
        build_share = empty_share()
        
        # Get current item - this is critical, so if it fails, show error
        try:
            update(12, "Loading item")
            item_response = kodi_rpc("Player.GetItem", {
                "playerid": player_id,
                "properties": [
                    "title", "album", "artist", "season", "episode", "showtitle",
                        "tvshowid", "duration", "file", "director", "art", "plot", 
                        "cast", "resume", "genre", "rating", "streamdetails", "year"
                ]
            })
            result = item_response.get("result", {})
            item = result.get("item", {})
        except Exception as e:
            logger.error(f"Failed to get current item: {e}")
            raise e  # This is critical, so re-raise
        
        # Get item type to know which API call to make
        playback_type = item.get("type", "unknown")
        
        # Initialize details with basic fallback structure
        details = {
            "album": {"title": item.get("album", ""), "year": item.get("year", "")},
            "artist": {"label": ", ".join(item.get("artist", [])) if item.get("artist") else "Unknown Artist"}
        }
        if active_server_id is not None:
            details["active_server_id"] = active_server_id
        
        # Get enhanced details for episodes, movies, and songs
        update(20, "Loading metadata")
        logger.debug(f"Playback type detected: {playback_type}")
        logger.debug(f"Available IDs - songid: {item.get('songid')}, albumid: {item.get('albumid')}, artistid: {item.get('artistid')}")
        if playback_type == "episode":
            try:
                update(24, "Loading episode metadata")
                logger.debug(f"Getting enhanced details for episode")
                episode_response = kodi_rpc("VideoLibrary.GetEpisodeDetails", {
                    "episodeid": item.get("id"),
                "properties": ["streamdetails", "genre", "director", "cast", "uniqueid", "rating", "studio"]
            })
                if episode_response and episode_response.get("result"):
                    episode_details = episode_response["result"].get("episodedetails", {})
                    # Merge enhanced details with basic item data
                    details.update(episode_details)
                    # Ensure basic item data is preserved
                    details.update({
                        "title": item.get("title", ""),
                        "plot": item.get("plot", ""),
                        "season": item.get("season", 0),
                        "episode": item.get("episode", 0),
                        "showtitle": item.get("showtitle", ""),
                        "director": item.get("director", []),
                        "cast": item.get("cast", []),
                        "year": item.get("year", "")
                    })
                    logger.debug(f"Enhanced episode details loaded")
                tvshowid = item.get("tvshowid")
                build_share["tvshow_id"] = tvshowid
                build_share["season"] = item.get("season")
                if tvshowid:
                    reuse_tvshow = share_scope_matches(prior_share, "tvshow", tvshowid)
                    if reuse_tvshow and prior_share.get("tvshow_meta"):
                        meta = prior_share.get("tvshow_meta") or {}
                        if meta.get("studio") and not details.get("studio"):
                            details["studio"] = meta.get("studio")
                        build_share["tvshow_meta"] = meta
                        logger.debug("Reusing cached TV show metadata for tvshowid=%s", tvshowid)
                    else:
                        try:
                            tvshow_response = kodi_rpc("VideoLibrary.GetTVShowDetails", {
                                "tvshowid": tvshowid,
                                "properties": ["studio", "art"]
                            }, server_id=active_server_id)
                            if tvshow_response and tvshow_response.get("result"):
                                tvshow_details = tvshow_response["result"].get("tvshowdetails", {})
                                tvshow_studio = tvshow_details.get("studio", [])
                                if isinstance(tvshow_studio, list) and tvshow_studio:
                                    if not details.get("studio"):
                                        details["studio"] = tvshow_studio
                                tvshow_art = tvshow_details.get("art", {})
                                if isinstance(tvshow_art, dict) and tvshow_art:
                                    if not isinstance(item.get("art"), dict):
                                        item["art"] = {}
                                    for art_key, art_value in tvshow_art.items():
                                        if not art_value:
                                            continue
                                        namespaced_key = f"tvshow.{art_key}"
                                        if namespaced_key not in item["art"]:
                                            item["art"][namespaced_key] = art_value
                                build_share["tvshow_meta"] = {"studio": details.get("studio") or tvshow_studio}
                        except Exception as e:
                            logger.warning(f"Failed to get tvshow details for episode: {e}")
            except Exception as e:
                logger.warning(f"Failed to get enhanced episode details: {e}")
                logger.debug(f"Using basic item data for {playback_type}")
        elif playback_type == "movie":
            try:
                update(24, "Loading movie metadata")
                logger.debug(f"Getting enhanced details for movie")
                movie_response = kodi_rpc("VideoLibrary.GetMovieDetails", {
                    "movieid": item.get("id"),
                "properties": ["streamdetails", "genre", "director", "cast", "uniqueid", "rating", "studio", "tagline"]
            })
                if movie_response and movie_response.get("result"):
                    movie_details = movie_response["result"].get("moviedetails", {})
                    # Merge enhanced details with basic item data
                    details.update(movie_details)
                    # Ensure basic item data is preserved
                    details.update({
                        "title": item.get("title", ""),
                        "plot": item.get("plot", ""),
                        "director": item.get("director", []),
                        "cast": item.get("cast", []),
                        "year": item.get("year", "")
                    })
                    logger.debug(f"Enhanced movie details loaded")
            except Exception as e:
                logger.warning(f"Failed to get enhanced movie details: {e}")
                logger.debug(f"Using basic item data for {playback_type}")
        elif playback_type == "song":
            try:
                update(24, "Loading song metadata")
                logger.debug(f"Getting enhanced details for song")
                logger.debug(f"Basic item ID: {item.get('id')}")
                # Get song details using the basic item ID
                song_response = kodi_rpc("AudioLibrary.GetSongDetails", {
                    "songid": item.get("id"),
                    "properties": ["title", "album", "artist", "duration", "rating", "year", "genre", "fanart", "thumbnail", "albumid", "artistid", "bitrate", "channels", "samplerate", "bpm", "comment", "lyrics", "mood", "playcount", "track", "disc"]
                })
                song_details = {}
                if song_response and song_response.get("result"):
                    song_details = song_response["result"].get("songdetails", {})
                    details.update(song_details)
                    logger.debug(f"Enhanced song details loaded")
                
                # Get album details if we have albumid
                albumid = song_details.get("albumid")
                build_share["album_id"] = albumid
                if albumid:
                    if share_scope_matches(prior_share, "album", albumid) and prior_share.get("album_details"):
                        album_details = prior_share["album_details"]
                        logger.debug("Reusing cached album metadata for albumid=%s", albumid)
                    else:
                        album_details = {}
                        try:
                            update(30, "Loading album metadata")
                            album_response = kodi_rpc("AudioLibrary.GetAlbumDetails", {
                                "albumid": albumid,
                                "properties": ["title", "artist", "year", "rating", "fanart", "thumbnail", "description", "genre", "mood", "style", "theme", "albumduration", "playcount", "albumlabel", "compilation", "totaldiscs"]
                            })
                            if album_response and album_response.get("result"):
                                album_details = album_response["result"].get("albumdetails", {}) or {}
                                logger.debug(f"Enhanced album details loaded")
                        except Exception as e:
                            logger.warning(f"Failed to get album details: {e}")
                    # Online album text (TheAudioDB/Wikipedia) is loaded async after page render
                    details["album"] = album_details
                    build_share["album_details"] = album_details
                
                # Get artist details if we have artistid
                artistid = primary_artist_id(song_details.get("artistid"))
                build_share["artist_id"] = artistid
                if artistid:
                    if share_scope_matches(prior_share, "artist", artistid) and prior_share.get("artist_details"):
                        artist_details = prior_share["artist_details"]
                        logger.debug("Reusing cached artist metadata for artistid=%s", artistid)
                    else:
                        artist_details = {}
                        try:
                            update(34, "Loading artist metadata")
                            artist_response = kodi_rpc("AudioLibrary.GetArtistDetails", {
                                "artistid": artistid,
                                "properties": ["fanart", "thumbnail", "description", "born", "formed", "died", "disbanded", "genre", "mood", "style", "yearsactive"]
                            })
                            if artist_response and artist_response.get("result"):
                                artist_details = artist_response["result"].get("artistdetails", {}) or {}
                                logger.debug(f"Enhanced artist details loaded")
                        except Exception as e:
                            logger.warning(f"Failed to get artist details: {e}")
                    # Online artist bio is loaded async after page render
                    details["artist"] = artist_details
                    build_share["artist_details"] = artist_details
                
                # Ensure basic item data is preserved (but don't overwrite detailed album/artist objects)
                details.update({
                    "title": item.get("title", ""),
                    "year": item.get("year", "")
                })
                
            except Exception as e:
                logger.warning(f"Failed to get enhanced song details: {e}")
                logger.debug(f"Using basic item data for {playback_type}")
        else:
            logger.debug(f"Using basic item data for {playback_type}")


        # Playback progress
        update(40, "Loading playback")
        progress_response = kodi_rpc("Player.GetProperties", {
            "playerid": player_id,
            "properties": ["time", "totaltime", "speed"]
        })
        progress = progress_response.get("result") if progress_response else {}
        t = progress.get("time", {})
        d = progress.get("totaltime", {})
        speed = progress.get("speed", 0)
        def to_secs(t): return t.get("hours", 0) * 3600 + t.get("minutes", 0) * 60 + t.get("seconds", 0)
        elapsed = to_secs(t)
        duration = to_secs(d)
        percent = int((elapsed / duration) * 100) if duration else 0
        paused = speed == 0

        cleanup_old_artwork_files()
        fingerprint = make_playback_fingerprint(item)
        active_server_id_for_cache = active_server_id
        if not session_id:
            if active_server_id_for_cache is not None and fingerprint:
                session_id = cache_session_id_for(active_server_id_for_cache, fingerprint)
            else:
                session_id = uuid.uuid4().hex
        
        # Try to download artwork, but don't fail if this breaks
        share_out = empty_share()
        try:
            update(50, "Loading posters")
            def art_progress(current, total, label):
                if total <= 0:
                    return
                progress = 50 + int((current / total) * 32)
                update(progress, label)
            share_context = {
                "media_type": playback_type,
                "prior_share": prior_share,
                "tvshow_id": build_share.get("tvshow_id") if playback_type == "episode" else None,
                "season": build_share.get("season") if playback_type == "episode" else None,
                "album_id": build_share.get("album_id") if playback_type == "song" else None,
                "artist_id": build_share.get("artist_id") if playback_type == "song" else None,
            }
            downloaded_art, share_out = prepare_and_download_art(
                item, session_id, progress_cb=art_progress, share_context=share_context
            )
        except Exception as e:
            logger.warning(f"Artwork download failed, continuing without artwork: {e}")
            downloaded_art = {}  # Empty artwork - page will still work
            share_out = empty_share()

        pending_fanarts = list(share_out.get("pending_fanarts") or [])

        if playback_type in ("episode", "song"):
            for key in ("art_files", "art_sources", "tvshow_id", "season", "album_id", "artist_id"):
                if share_out.get(key) is not None:
                    build_share[key] = share_out[key]
            if share_out.get("tvshow_meta") and not build_share.get("tvshow_meta"):
                build_share["tvshow_meta"] = share_out["tvshow_meta"]
            if share_out.get("album_details") and not build_share.get("album_details"):
                build_share["album_details"] = share_out["album_details"]
            if share_out.get("artist_details") and not build_share.get("artist_details"):
                build_share["artist_details"] = share_out["artist_details"]
            final_share = build_share
        else:
            # Movies: leave prior episode/music share intact
            final_share = prior_share

        # Prepare progress data
        update(85, "Rendering")
        progress_data = {
            "elapsed": elapsed,
            "duration": duration,
            "paused": paused
        }

        display_title, overview_media_type = _format_overview_title(item)

        # Attach pending fanarts for progressive slideshow hydration after paint
        if not isinstance(details, dict):
            details = {}
        else:
            details = dict(details)
        details["pending_fanarts"] = pending_fanarts
        details["art_session_id"] = session_id

        # Check if media type is unknown - if so, show fallback message
        from parser import infer_playback_type
        playback_type_from_parser = infer_playback_type(item)
        if playback_type_from_parser == "unknown":
            logger.info(f"Unknown media type detected, showing fallback message")
            update(100, "Done")
            unknown_html = render_template_string("""
            <!DOCTYPE html>
            <html>
            <head>
                <title>Unknown Media Type</title>
                <style>
                    body {
                        font-family: Arial, sans-serif;
                        background: linear-gradient(to bottom right, #222, #444);
                        color: white;
                        margin: 0;
                        padding: 0;
                        display: flex;
                        justify-content: center;
                        align-items: center;
                        height: 100vh;
                    }
                    .message-box {
                        background: rgba(0,0,0,0.6);
                        padding: 40px;
                        border-radius: 12px;
                        box-shadow: 0 4px 20px rgba(0,0,0,0.8);
                        font-size: 1.5em;
                        text-align: center;
                        max-width: 600px;
                    }
                </style>
            </head>
            <body>
                <div class="message-box">
                    Unknown media type/Media not properly scraped to library.<br>
                    Please scrape and replay media again
                </div>
            </body>
            </html>
            """)
            return _payload(
                unknown_html,
                idle=False,
                downloaded_art=downloaded_art,
                fingerprint=fingerprint,
                title=display_title,
                media_type="other",
                paused=paused,
                used_session_id=session_id,
                share=final_share,
            )

        # Use the modular system to generate HTML
        html = route_media_display(item, session_id, downloaded_art, progress_data, details)
        update(100, "Done")
        return _payload(
            render_template_string(html),
            idle=False,
            downloaded_art=downloaded_art,
            fingerprint=fingerprint,
            title=display_title,
            media_type=overview_media_type,
            paused=paused,
            used_session_id=session_id,
            share=final_share,
        )
    except Exception as e:
        logger.error(f"Critical failure in now_playing route: {e}")
        update(100, "Error")
        return _payload(render_template("index.html"), idle=True)

def update_job(job_id: str, progress: int, message: str = None, status: str = "running"):
    with _c.load_lock:
        job = _c.load_jobs.get(job_id)
        if not job:
            return
        job["progress"] = min(100, max(0, int(progress)))
        if message is not None:
            job["message"] = message
        job["status"] = status
        job["updated_at"] = time.time()

def run_nowplaying_job(job_id: str):
    try:
        def progress_cb(progress, message):
            update_job(job_id, progress, message)
        with _c.load_lock:
            job = _c.load_jobs.get(job_id)
            server_id = job.get("server_id") if job else None
        if server_id is not None:
            _c.active_server_override.server_id = server_id
        try:
            with _c.app.app_context():
                payload = build_nowplaying_html(progress_cb, as_payload=True)
                html = payload.get("html") if isinstance(payload, dict) else payload
                with _c.load_lock:
                    job = _c.load_jobs.get(job_id)
                    if job is not None:
                        job["html"] = html
                if server_id is not None and isinstance(payload, dict):
                    if payload.get("idle") or not payload.get("html"):
                        clear_cache_playback(server_id, {"connected": True, "error": None})
                    else:
                        store_playing_cache(server_id, payload)
                update_job(job_id, 100, "Done", status="done")
        finally:
            if hasattr(_c.active_server_override, "server_id"):
                del _c.active_server_override.server_id
    except Exception as e:
        update_job(job_id, 100, f"Error: {str(e)}", status="error")

def build_nowplaying_soft_update(prev):
    """Build soft-update JSON for same-show episode or same-album/same-artist song."""
    active_response = kodi_rpc("Player.GetActivePlayers")
    active = active_response.get("result") if active_response else None
    if not active:
        return {"soft": False, "reason": "idle"}

    player_id = active[0]["playerid"]
    active_server = get_active_server()
    active_server_id = active_server.get("id") if active_server else None
    prior_cache = get_cache_entry(active_server_id) if active_server_id is not None else None
    prior_share = (prior_cache or {}).get("share") or empty_share()

    item_response = kodi_rpc("Player.GetItem", {
        "playerid": player_id,
        "properties": [
            "title", "album", "artist", "season", "episode", "showtitle",
            "tvshowid", "duration", "file", "art", "plot", "year",
        ],
    })
    item = (item_response or {}).get("result", {}).get("item", {}) or {}
    media_type = item.get("type") or "unknown"
    prev_type = (prev or {}).get("media_type") or ""

    progress_response = kodi_rpc("Player.GetProperties", {
        "playerid": player_id,
        "properties": ["time", "totaltime", "speed"],
    })
    progress = progress_response.get("result") if progress_response else {}
    t = progress.get("time", {}) or {}
    d = progress.get("totaltime", {}) or {}
    speed = progress.get("speed", 0)

    def to_secs(chunk):
        return chunk.get("hours", 0) * 3600 + chunk.get("minutes", 0) * 60 + chunk.get("seconds", 0)

    elapsed = to_secs(t)
    duration = to_secs(d)
    paused = speed == 0

    if media_type == "episode":
        return _soft_update_episode(item, prev, prev_type, prior_share, active_server_id, elapsed, duration, paused)
    if media_type == "song":
        return _soft_update_song(item, prev, prev_type, prior_share, active_server_id, elapsed, duration, paused)
    return {"soft": False, "reason": "unsupported_type", "media_type": media_type}


def _soft_update_episode(item, prev, prev_type, prior_share, active_server_id, elapsed, duration, paused):
    if prev_type != "episode":
        return {"soft": False, "reason": "type_mismatch"}
    tvshow_id = item.get("tvshowid")
    season = item.get("season")
    episode = item.get("episode")
    item_id = item.get("id")
    if tvshow_id is None or prev.get("tvshow_id") is None or tvshow_id != prev.get("tvshow_id"):
        return {"soft": False, "reason": "different_show"}

    episode_response = kodi_rpc("VideoLibrary.GetEpisodeDetails", {
        "episodeid": item_id,
        "properties": ["plot", "streamdetails", "rating", "uniqueid"],
    })
    episode_details = {}
    if episode_response and episode_response.get("result"):
        episode_details = episode_response["result"].get("episodedetails", {}) or {}

    title = item.get("title") or episode_details.get("title") or ""
    plot = item.get("plot") or episode_details.get("plot") or ""
    show = item.get("showtitle") or ""
    season_changed = prev.get("season") is None or prev.get("season") != season

    art = {"season_poster": None, "show_poster": None, "clearlogo": None}
    if season_changed and active_server_id is not None:
        fingerprint = make_playback_fingerprint(item)
        session_id = cache_session_id_for(active_server_id, fingerprint) if fingerprint else uuid.uuid4().hex
        share_context = {
            "media_type": "episode",
            "prior_share": prior_share,
            "tvshow_id": tvshow_id,
            "season": season,
            "album_id": None,
            "artist_id": None,
        }
        downloaded_art, share_out = prepare_and_download_art(
            item, session_id, share_context=share_context
        )
        if downloaded_art.get("season.poster"):
            art["season_poster"] = f"/media/{downloaded_art['season.poster']}"
        # Persist updated share (season art) without wiping HTML if present
        merged = dict(prior_share)
        for key in ("art_files", "art_sources", "tvshow_id", "season"):
            if share_out.get(key) is not None:
                merged[key] = share_out[key]
        set_cache_entry(active_server_id, share=merged)

    import re as _re
    season_badge = f"Season {season}" if season and season > 0 else ""
    episode_badge = f"Episode {episode}" if episode and episode > 0 else ""
    title_badge = ""
    if title and not _re.match(r"^Episode\s*#?\s*\d+\s*$", title, _re.IGNORECASE):
        title_badge = title

    return {
        "soft": True,
        "scope": "episode",
        "item_id": f"episode_{item_id}" if item_id is not None else f"other_{title}",
        "media_type": "episode",
        "tvshow_id": tvshow_id,
        "season": season,
        "episode": episode,
        "showtitle": show,
        "title": title,
        "plot": plot,
        "season_changed": bool(season_changed),
        "art": art,
        "badges": {
            "season": season_badge,
            "episode": episode_badge,
            "title": title_badge,
        },
        "elapsed": elapsed,
        "duration": duration,
        "paused": paused,
        "identity": {
            "media_type": "episode",
            "item_id": f"episode_{item_id}" if item_id is not None else "",
            "tvshow_id": tvshow_id,
            "season": season,
            "album_id": None,
            "artist_id": None,
        },
    }


def _soft_update_song(item, prev, prev_type, prior_share, active_server_id, elapsed, duration, paused):
    if prev_type != "song":
        return {"soft": False, "reason": "type_mismatch"}

    song_response = kodi_rpc("AudioLibrary.GetSongDetails", {
        "songid": item.get("id"),
        "properties": [
            "title", "album", "artist", "duration", "year", "albumid", "artistid",
            "track", "disc", "bitrate", "channels", "samplerate", "lyrics",
        ],
    })
    song_details = {}
    if song_response and song_response.get("result"):
        song_details = song_response["result"].get("songdetails", {}) or {}

    album_id = song_details.get("albumid")
    artist_id = primary_artist_id(song_details.get("artistid"))
    prev_album = prev.get("album_id")
    prev_artist = prev.get("artist_id")

    same_album = album_id is not None and prev_album is not None and album_id == prev_album
    same_artist = artist_id is not None and prev_artist is not None and artist_id == prev_artist
    if not same_album and not same_artist:
        return {"soft": False, "reason": "different_album_and_artist"}

    album_changed = not same_album
    artist_changed = not same_artist

    album_details = None
    artist_details = None
    if same_album and prior_share.get("album_details"):
        album_details = prior_share["album_details"]
    elif album_id:
        album_response = kodi_rpc("AudioLibrary.GetAlbumDetails", {
            "albumid": album_id,
            "properties": ["title", "year", "description", "rating", "albumlabel", "totaldiscs"],
        })
        if album_response and album_response.get("result"):
            album_details = album_response["result"].get("albumdetails", {})

    if same_artist and prior_share.get("artist_details"):
        artist_details = prior_share["artist_details"]
    elif artist_id:
        # Load when artist changed OR first time (missing from share)
        artist_response = kodi_rpc("AudioLibrary.GetArtistDetails", {
            "artistid": artist_id,
            "properties": ["description", "born", "genre", "style"],
        })
        if artist_response and artist_response.get("result"):
            artist_details = artist_response["result"].get("artistdetails", {})

    # Enrich empty descriptions asynchronously on the client; keep Kodi text only here.
    art = {"cover": None, "back": None, "discart": None, "clearlogo": None}
    merged = dict(prior_share or {})
    merged["album_id"] = album_id
    merged["artist_id"] = artist_id
    if album_details:
        merged["album_details"] = album_details
    if artist_details:
        merged["artist_details"] = artist_details

    if (album_changed or artist_changed) and active_server_id is not None:
        fingerprint = make_playback_fingerprint(item)
        session_id = cache_session_id_for(active_server_id, fingerprint) if fingerprint else uuid.uuid4().hex
        share_context = {
            "media_type": "song",
            "prior_share": prior_share,
            "tvshow_id": None,
            "season": None,
            "album_id": album_id,
            "artist_id": artist_id,
        }
        downloaded_art, share_out = prepare_and_download_art(
            item, session_id, share_context=share_context
        )
        for key in ("front", "frontcover", "cover", "thumbnail", "poster"):
            if downloaded_art.get(key):
                art["cover"] = f"/media/{downloaded_art[key]}"
                break
        for key in ("back", "backcover", "rear"):
            if downloaded_art.get(key):
                art["back"] = f"/media/{downloaded_art[key]}"
                break
        if downloaded_art.get("discart"):
            art["discart"] = f"/media/{downloaded_art['discart']}"
        elif downloaded_art.get("cdart"):
            art["discart"] = f"/media/{downloaded_art['cdart']}"
        if artist_changed and downloaded_art.get("clearlogo"):
            art["clearlogo"] = f"/media/{downloaded_art['clearlogo']}"
        if artist_changed:
            fanart_urls = []
            for key, value in downloaded_art.items():
                if key.startswith("extrafanart"):
                    fanart_urls.append(f"/media/{value}")
            if not fanart_urls:
                for fanart_key in (
                    "fanart", "fanart1", "fanart2", "fanart3", "fanart4",
                    "fanart5", "fanart6", "fanart7", "fanart8", "fanart9",
                ):
                    if downloaded_art.get(fanart_key):
                        fanart_urls.append(f"/media/{downloaded_art[fanart_key]}")
            art["fanart_slides"] = fanart_urls
            art["fanart_pending"] = {
                "session_id": session_id,
                "items": list(share_out.get("pending_fanarts") or []),
            }
        for key in ("art_files", "art_sources", "album_id", "artist_id"):
            if share_out.get(key) is not None:
                merged[key] = share_out[key]

    if active_server_id is not None:
        set_cache_entry(active_server_id, share=merged)

    title = song_details.get("title") or item.get("title") or ""
    album = song_details.get("album") or item.get("album") or ""
    if isinstance(item.get("artist"), list):
        artist = ", ".join(item.get("artist"))
    else:
        artist = song_details.get("artist") or ""
        if isinstance(artist, list):
            artist = ", ".join(artist)

    track = song_details.get("track") or 0
    disc = song_details.get("disc") or 0
    total_discs = int((album_details or {}).get("totaldiscs") or 1)
    album_year = (album_details or {}).get("year") or item.get("year") or ""
    item_id = item.get("id")
    # Match music_nowplaying.py: only show disc badge for multi-disc albums
    disc_badge = f"Disc {disc}" if disc and disc > 0 and total_discs >= 2 else ""
    track_badge = f"Track {track:02d}" if track and track > 0 else ""
    album_description = (album_details or {}).get("description") or ""
    artist_bio = (artist_details or {}).get("description") or ""
    prior_album_desc = ((prior_share or {}).get("album_details") or {}).get("description") or ""
    prior_artist_bio = ((prior_share or {}).get("artist_details") or {}).get("description") or ""
    refresh_album_text = bool(album_changed) or (bool(album_description) and not prior_album_desc)
    refresh_artist_text = bool(artist_changed) or (bool(artist_bio) and not prior_artist_bio)

    return {
        "soft": True,
        "scope": "song",
        "item_id": f"song_{item_id}" if item_id is not None else f"other_{title}",
        "media_type": "song",
        "album_id": album_id,
        "artist_id": artist_id,
        "title": title,
        "album": album,
        "artist": artist,
        "track": track,
        "disc": disc,
        "album_year": album_year,
        "album_changed": bool(album_changed),
        "artist_changed": bool(artist_changed),
        "refresh_album_text": refresh_album_text,
        "refresh_artist_text": refresh_artist_text,
        "album_description": album_description,
        "artist_bio": artist_bio,
        "artist_born": (artist_details or {}).get("born") or "",
        "need_album_meta": not bool((album_description or "").strip()),
        "need_artist_meta": not bool((artist_bio or "").strip()),
        "art": art,
        "badges": {
            "album": f"{album}" + (f" ({album_year})" if album_year else "") if album else "",
            "disc": disc_badge,
            "track": track_badge,
            "title": title,
        },
        "elapsed": elapsed,
        "duration": duration,
        "paused": paused,
        "lyrics": {
            "artist": artist,
            "title": title,
            "album": album,
            "duration": duration,
            "kodi_lyrics": song_details.get("lyrics") or "",
        },
        "identity": {
            "media_type": "song",
            "item_id": f"song_{item_id}" if item_id is not None else "",
            "tvshow_id": None,
            "season": None,
            "album_id": album_id,
            "artist_id": artist_id,
        },
    }

def generate_fallback_html(item, progress_data):
    """Generate basic HTML when the modular system fails"""
    title = html_escape(item.get("title", "Unknown Title"))
    artist = html_escape(", ".join(item.get("artist", [])) if item.get("artist") else "Unknown Artist")
    album = html_escape(item.get("album", ""))
    elapsed = progress_data.get("elapsed", 0)
    duration = progress_data.get("duration", 0)
    paused = progress_data.get("paused", False)
    
    # Format time
    def format_time(seconds):
        if seconds == 0:
            return "0:00"
        minutes = int(seconds // 60)
        secs = int(seconds % 60)
        return f"{minutes}:{secs:02d}"
    
    return f"""
    <html>
    <head>
        <title>Now Playing - {title}</title>
        <style>
            body {{
                margin: 0;
                padding: 0;
                background: linear-gradient(to bottom right, #222, #444);
                font-family: sans-serif;
                color: white;
                display: flex;
                justify-content: center;
                align-items: center;
                height: 100vh;
            }}
            .now-playing {{
                background: rgba(0,0,0,0.6);
                padding: 40px;
                border-radius: 12px;
                box-shadow: 0 4px 20px rgba(0,0,0,0.8);
                text-align: center;
                max-width: 600px;
            }}
            .title {{
                font-size: 2em;
                font-weight: bold;
                margin-bottom: 10px;
            }}
            .artist {{
                font-size: 1.5em;
                margin-bottom: 5px;
                color: #ccc;
            }}
            .album {{
                font-size: 1.2em;
                margin-bottom: 20px;
                color: #aaa;
            }}
            .progress {{
                font-size: 1em;
                color: #888;
            }}
            .status {{
                font-size: 1.2em;
                margin-top: 20px;
                color: {'#ff6b6b' if paused else '#4caf50'};
            }}
        </style>
    </head>
    <body>
        <div class="now-playing">
            <div class="title">{title}</div>
            <div class="artist">{artist}</div>
            <div class="album">{album}</div>
            <div class="progress">{format_time(elapsed)} / {format_time(duration)}</div>
            <div class="status">{'⏸️ Paused' if paused else '▶️ Playing'}</div>
        </div>
    </body>
    </html>
    """
