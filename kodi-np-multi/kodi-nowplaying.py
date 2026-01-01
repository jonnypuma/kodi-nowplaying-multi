from flask import Flask, render_template_string, request, jsonify, send_file, session
import requests
import os
import urllib.parse
import uuid
import re
from parser import route_media_display

app = Flask(__name__)
app.secret_key = os.getenv("FLASK_SECRET_KEY", uuid.uuid4().hex)  # For session management

HEADERS = {"Content-Type": "application/json"}

# Parse multiple Kodi servers from environment variables
def parse_kodi_servers():
    """Parse Kodi servers from environment variables (KODI_HOST_1, KODI_HOST_2, etc.)"""
    servers = {}
    i = 1
    while True:
        host_key = f"KODI_HOST_{i}"
        user_key = f"KODI_USERNAME_{i}"
        pass_key = f"KODI_PASSWORD_{i}"
        
        host = os.getenv(host_key)
        if not host:
            break
        
        username = os.getenv(user_key, "")
        password = os.getenv(pass_key, "")
        
        # Extract IP from host for sorting
        ip_match = re.search(r'(\d+\.\d+\.\d+\.\d+)', host)
        ip = ip_match.group(1) if ip_match else host
        
        servers[i] = {
            "id": i,
            "host": host,
            "username": username,
            "password": password,
            "auth": (username, password) if username else None,
            "ip": ip
        }
        i += 1
    
    # If no numbered servers found, try legacy single server format
    if not servers:
        legacy_host = os.getenv("KODI_HOST")
        if legacy_host:
            legacy_user = os.getenv("KODI_USER", os.getenv("KODI_USERNAME", ""))
            legacy_pass = os.getenv("KODI_PASS", os.getenv("KODI_PASSWORD", ""))
            ip_match = re.search(r'(\d+\.\d+\.\d+\.\d+)', legacy_host)
            ip = ip_match.group(1) if ip_match else legacy_host
            
            servers[1] = {
                "id": 1,
                "host": legacy_host,
                "username": legacy_user,
                "password": legacy_pass,
                "auth": (legacy_user, legacy_pass) if legacy_user else None,
                "ip": ip
            }
    
    return servers

# Parse all available servers
KODI_SERVERS = parse_kodi_servers()

def get_active_server():
    """Get the currently active server from session, or default to first server"""
    server_id = session.get('active_server_id', 1)
    if server_id in KODI_SERVERS:
        return KODI_SERVERS[server_id]
    # Fallback to first server
    if KODI_SERVERS:
        return list(KODI_SERVERS.values())[0]
    return None

ART_TYPES = ["poster", "front", "back", "fanart", "clearlogo", "clearart", "discart", "cdart", "banner", "season.poster", "thumbnail"]

# Global variables to track episode transitions and prevent reload loops
last_known_episode = None
last_check_time = 0
EPISODE_CHECK_INTERVAL = 10  # Check for episode changes every 10 seconds

# API endpoints for server management
@app.route("/api/servers")
def get_servers():
    """Get list of available Kodi servers, sorted by IP"""
    servers_list = []
    for server_id, server in KODI_SERVERS.items():
        servers_list.append({
            "id": server_id,
            "host": server["host"],
            "ip": server["ip"]
        })
    
    # Sort by IP address
    servers_list.sort(key=lambda x: [int(part) for part in x["ip"].split(".") if part.isdigit()])
    
    return jsonify({"servers": servers_list})

@app.route("/api/test-connection/<int:server_id>")
def test_connection(server_id):
    """Test connection to a specific Kodi server"""
    if server_id not in KODI_SERVERS:
        return jsonify({"connected": False, "error": "Server not found"}), 404
    
    server = KODI_SERVERS[server_id]
    
    try:
        # Try a simple RPC call to test connection
        payload = {
            "jsonrpc": "2.0",
            "method": "JSONRPC.Version",
            "params": {},
            "id": 1
        }
        r = requests.post(f"{server['host']}/jsonrpc", headers=HEADERS, json=payload, auth=server['auth'], timeout=5)
        r.raise_for_status()
        response = r.json()
        
        if response.get("result"):
            return jsonify({"connected": True})
        else:
            return jsonify({"connected": False, "error": "Invalid response"})
    except requests.exceptions.Timeout:
        return jsonify({"connected": False, "error": "Connection timeout"})
    except requests.exceptions.ConnectionError:
        return jsonify({"connected": False, "error": "Connection failed"})
    except requests.exceptions.HTTPError as e:
        if e.response.status_code == 401:
            return jsonify({"connected": False, "error": "Authentication failed"})
        return jsonify({"connected": False, "error": f"HTTP {e.response.status_code}"})
    except Exception as e:
        return jsonify({"connected": False, "error": str(e)})

@app.route("/api/switch-server/<int:server_id>", methods=["POST"])
def switch_server(server_id):
    """Switch the active Kodi server"""
    if server_id not in KODI_SERVERS:
        return jsonify({"success": False, "error": "Server not found"}), 404
    
    session['active_server_id'] = server_id
    return jsonify({"success": True, "server_id": server_id})

@app.route("/api/current-server")
def get_current_server():
    """Get the currently active server ID"""
    server_id = session.get('active_server_id', 1)
    if server_id not in KODI_SERVERS:
        server_id = 1 if KODI_SERVERS else None
    return jsonify({"server_id": server_id})

@app.route("/")
def index():
    return """
    <!DOCTYPE html>
    <html>
    <head>
        <title>Kodi Now Playing</title>
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
                opacity: 1;
                transition: opacity 1.5s ease;
                animation: fadeIn 1.5s ease;
            }
            body.fade-out {
                opacity: 0;
            }
            @keyframes fadeIn {
                from { opacity: 0; }
                to { opacity: 1; }
            }
            .message-box {
                background: rgba(0,0,0,0.6);
                padding: 40px;
                border-radius: 12px;
                box-shadow: 0 4px 20px rgba(0,0,0,0.8);
                font-size: 1.5em;
                font-style: italic;
                text-align: center;
            }
            
            /* Side Panel Styles */
            .side-panel {
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
            }
            
            .side-panel.open {
                right: 0;
            }
            
            .side-panel-toggle {
                position: absolute;
                left: -20px;
                top: 50%;
                transform: translateY(-50%);
                width: 20px;
                height: 40px;
                background: rgba(0, 0, 0, 0.85);
                backdrop-filter: blur(10px);
                border-radius: 20px 0 0 20px;
                display: flex;
                align-items: center;
                justify-content: center;
                cursor: pointer;
                z-index: 1501;
                transition: all 0.3s ease;
                box-shadow: -2px 0 10px rgba(0, 0, 0, 0.3);
            }
            
            .side-panel-toggle-arrow {
                color: rgba(255, 255, 255, 0.8);
                font-size: 14px;
                font-weight: bold;
                transition: transform 0.3s ease;
                margin-left: 2px;
            }
            
            .side-panel-toggle:hover {
                background: rgba(0, 0, 0, 0.95);
            }
            
            
            .side-panel h2 {
                color: white;
                margin: 0 0 20px 0;
                font-size: 1.5em;
                display: flex;
                align-items: center;
                gap: 10px;
            }
            
            .side-panel select {
                background: rgba(255, 255, 255, 0.1);
                border: 1px solid rgba(255, 255, 255, 0.2);
                color: white;
                padding: 8px 12px;
                border-radius: 5px;
                font-size: 14px;
                cursor: pointer;
                min-width: 150px;
            }
            
            .side-panel select option {
                background: white;
                color: black;
            }
            
            .side-panel select option:checked {
                background: #51cf66;
                color: white;
            }
            
            .side-panel select:focus {
                outline: 2px solid #51cf66;
                outline-offset: 2px;
            }
            
            .side-panel-section {
                margin-bottom: 25px;
                padding-bottom: 20px;
                border-bottom: 1px solid rgba(255, 255, 255, 0.1);
            }
            
            .side-panel-section:last-child {
                border-bottom: none;
            }
            
            /* Toggle Component Styles */
            .toggle {
                align-items: center;
                border-radius: 100px;
                display: flex;
                font-weight: 700;
                margin-bottom: 0;
            }
            
            .toggle__input {
                clip: rect(0 0 0 0);
                clip-path: inset(50%);
                height: 1px;
                overflow: hidden;
                position: absolute;
                white-space: nowrap;
                width: 1px;
            }
            
            .toggle__input:disabled + .toggle-track {
                cursor: not-allowed;
                opacity: 0.7;
            }
            
            .toggle-track {
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
            }
            
            .toggle-indicator {
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
            }
            
            .checkMark {
                fill: #fff;
                height: 20px;
                width: 20px;
                opacity: 0;
                transition: opacity 0.3s ease-in-out;
            }
            
            .toggle__input:checked + .toggle-track .toggle-indicator {
                background: #51cf66;
                transform: translateX(30px);
                top: 3px;
            }
            
            .toggle__input:checked + .toggle-track .checkMark {
                opacity: 1;
                transition: opacity 0.3s ease-in-out;
            }
        </style>
    </head>
    <body>
        <div class="message-box">
            <div id="serverMessage">🎬 No Media Currently Playing<br>Awaiting Media Playback</div>
        </div>
        
        <!-- Side Panel -->
        <div class="side-panel" id="sidePanel">
            <!-- Side Panel Toggle Button -->
            <div class="side-panel-toggle" onclick="toggleSidePanel()">
                <div class="side-panel-toggle-arrow">◄</div>
            </div>
            
            <div style="overflow-y: auto; height: 100%;">
                <h2>Now playing on:
                    <select id="serverSelect" onchange="switchServer()">
                        <option value="">Loading servers...</option>
                    </select>
                </h2>
            </div>
        </div>
        
        <script>
            let lastPlaybackState = false; // Initialize to false
            let currentServerId = null;

            function toggleSidePanel() {
                const panel = document.getElementById('sidePanel');
                const arrow = document.querySelector('.side-panel-toggle-arrow');
                panel.classList.toggle('open');
                if (panel.classList.contains('open')) {
                    arrow.style.transform = 'rotate(180deg)';
                } else {
                    arrow.style.transform = 'rotate(0deg)';
                }
            }
            
            function updateServerMessage(serverIp) {
                const messageDiv = document.getElementById('serverMessage');
                if (serverIp) {
                    messageDiv.innerHTML = `🎬 No media playing on selected server: ${serverIp}`;
                } else {
                    messageDiv.innerHTML = '🎬 No Media Currently Playing<br>Awaiting Media Playback';
                }
            }
            
            async function loadServers() {
                try {
                    const response = await fetch('/api/servers');
                    const data = await response.json();
                    const select = document.getElementById('serverSelect');
                    select.innerHTML = '';
                    
                    if (data.servers && data.servers.length > 0) {
                        data.servers.forEach(server => {
                            const option = document.createElement('option');
                            option.value = server.id;
                            option.textContent = server.ip || server.host;
                            select.appendChild(option);
                        });
                        
                        // Get current server and set it
                        const currentResponse = await fetch('/api/current-server');
                        const currentData = await currentResponse.json();
                        let selectedServer = null;
                        
                        if (currentData.server_id) {
                            select.value = currentData.server_id;
                            currentServerId = currentData.server_id;
                            // Find the server IP for the message
                            selectedServer = data.servers.find(s => s.id === currentData.server_id);
                        } else {
                            // Default to first server
                            select.value = data.servers[0].id;
                            currentServerId = data.servers[0].id;
                            selectedServer = data.servers[0];
                            switchServer();
                        }
                        
                        // Update the message with server IP
                        if (selectedServer) {
                            updateServerMessage(selectedServer.ip || selectedServer.host);
                        }
                    } else {
                        select.innerHTML = '<option value="">No servers configured</option>';
                    }
                } catch (error) {
                    console.error('Failed to load servers:', error);
                    document.getElementById('serverSelect').innerHTML = '<option value="">Error loading servers</option>';
                }
            }
            
            async function switchServer() {
                const select = document.getElementById('serverSelect');
                const serverId = parseInt(select.value);
                
                if (!serverId) return;
                
                try {
                    const response = await fetch(`/api/switch-server/${serverId}`, {
                        method: 'POST'
                    });
                    const data = await response.json();
                    
                    if (data.success) {
                        currentServerId = serverId;
                        
                        // Update message with new server IP
                        const option = select.options[select.selectedIndex];
                        const serverIp = option.textContent;
                        updateServerMessage(serverIp);
                        
                        // Reload page to poll the new server
                        setTimeout(() => {
                            location.reload();
                        }, 500);
                    }
                } catch (error) {
                    console.error('Failed to switch server:', error);
                }
            }
            

            function checkPlaybackChange() {
                fetch('/poll_playback')
                    .then(res => {
                        if (!res.ok) {
                            throw new Error(`HTTP ${res.status}`);
                        }
                        return res.json();
                    })
                    .then(data => {
                        const currentState = data.playing;
                        // Only fade out and redirect if media starts playing (transitions from false to true)
                        // Don't fade if transitioning from true to false (that would make screen dim)
                        if (currentState === true && lastPlaybackState === false) {
                            document.body.classList.add('fade-out');
                            setTimeout(() => {
                                window.location.href = '/nowplaying';
                            }, 1500);
                        }
                        lastPlaybackState = currentState;
                    })
                    .catch(error => {
                        console.error('Polling error:', error);
                        // Don't change state on error, just retry
                        setTimeout(checkPlaybackChange, 3000);
                    });
            }
            
            // Initialize on page load
            document.addEventListener('DOMContentLoaded', () => {
                loadServers();
                // Check initial state of side panel and set arrow accordingly
                const panel = document.getElementById('sidePanel');
                const arrow = document.querySelector('.side-panel-toggle-arrow');
                if (panel && arrow) {
                    if (panel.classList.contains('open')) {
                        arrow.style.transform = 'rotate(180deg)';
                    }
                }
            });
            
            setInterval(checkPlaybackChange, 2000); // Poll every 2 seconds
        </script>
    </body>
    </html>
    """

@app.route("/poll_playback")
def poll_playback():
    global last_known_episode, last_check_time
    
    try:
        players = kodi_rpc("Player.GetActivePlayers")
        print(f"[DEBUG] Poll playback - Players response: {players}", flush=True)
        if players and players.get("result"):
            # Always try to get current episode info
            import time
            current_time = time.time()
            
            # Check if it's time to verify episode (every 10 seconds) OR if we don't have episode info yet
            if current_time - last_check_time >= EPISODE_CHECK_INTERVAL or last_known_episode is None:
                last_check_time = current_time
                
                try:
                    # Get active players first
                    players_response = kodi_rpc("Player.GetActivePlayers", {})
                    if players_response and players_response.get("result"):
                        active_players = players_response.get("result", [])
                        if active_players:
                            player_id = active_players[0].get("playerid")
                            item = kodi_rpc("Player.GetItem", {"playerid": player_id, "properties": ["title", "album", "artist", "showtitle", "season", "episode", "file"]})
                            if item and item.get("result") and item.get("result", {}).get("item"):
                                current_item = item.get("result", {}).get("item", {})
                                
                                # Create current item identifier using actual database IDs
                                current_item_id = ""
                                item_id = current_item.get("id")
                                if current_item.get("type") == "song" and item_id:
                                    current_item_id = f"song_{item_id}"
                                    print(f"[DEBUG] Song ID: {item_id} - {current_item.get('title', 'unknown')}", flush=True)
                                elif current_item.get("type") == "episode" and item_id:
                                    current_item_id = f"episode_{item_id}"
                                    print(f"[DEBUG] Episode ID: {item_id} - {current_item.get('showtitle', '')} S{current_item.get('season', 0):02d}E{current_item.get('episode', 0):02d}", flush=True)
                                elif current_item.get("type") == "movie" and item_id:
                                    current_item_id = f"movie_{item_id}"
                                    print(f"[DEBUG] Movie ID: {item_id} - {current_item.get('title', 'unknown')}", flush=True)
                                else:
                                    # Fallback to custom ID if no database ID available
                                    current_item_id = f"other_{current_item.get('title', 'unknown')}"
                                    print(f"[DEBUG] No database ID available, using fallback: {current_item_id}", flush=True)
                                
                                # Check if item has changed
                                if last_known_episode is not None and current_item_id != last_known_episode:
                                    print(f"[DEBUG] Item changed: {last_known_episode} -> {current_item_id}", flush=True)
                                    last_known_episode = current_item_id
                                    # Return unique ID to trigger reload
                                    change_id = f"item_changed_{int(current_time)}"
                                    return jsonify({
                                        "playing": True, 
                                        "item_id": change_id,
                                        "item_type": "item_change"
                                    })
                                
                                # Update last known item
                                if last_known_episode != current_item_id:
                                    print(f"[DEBUG] Setting item: {current_item_id}", flush=True)
                                    last_known_episode = current_item_id
                                else:
                                    print(f"[DEBUG] Item check: {current_item_id} (no change)", flush=True)
                            else:
                                print(f"[DEBUG] Failed to get episode info from Player.GetItem", flush=True)
                        else:
                            print(f"[DEBUG] No active players found", flush=True)
                    else:
                        print(f"[DEBUG] Failed to get active players", flush=True)
                        
                except Exception as e:
                    print(f"[DEBUG] Failed to check episode: {e}", flush=True)
            
            # Get player properties to check pause state and current languages
            active_players = players.get("result", [])
            if active_players:
                player_id = active_players[0].get("playerid")
                progress_response = kodi_rpc("Player.GetProperties", {
                    "playerid": player_id,
                    "properties": ["speed"]
                })
                speed = 0
                if progress_response and progress_response.get("result"):
                    speed = progress_response.get("result", {}).get("speed", 0)
                
                is_paused = speed == 0
                
                # Get current language information
                try:
                    language_response = kodi_rpc("XBMC.GetInfoLabels", {
                        "labels": ["VideoPlayer.AudioLanguage", "VideoPlayer.SubtitlesLanguage"]
                    })
                    current_audio_lang = ""
                    current_subtitle_lang = ""
                    if language_response and language_response.get("result"):
                        result = language_response.get("result", {})
                        current_audio_lang = result.get("VideoPlayer.AudioLanguage", "")[:3].upper()
                        current_subtitle_lang = result.get("VideoPlayer.SubtitlesLanguage", "")[:3].upper()
                        
                        # Apply language normalization
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
                        
                        current_audio_lang = language_normalization.get(current_audio_lang, current_audio_lang)
                        current_subtitle_lang = language_normalization.get(current_subtitle_lang, current_subtitle_lang)
                        
                        print(f"[DEBUG] Current languages - Audio: {current_audio_lang}, Subtitle: {current_subtitle_lang}", flush=True)
                except Exception as e:
                    print(f"[DEBUG] Failed to get current languages: {e}", flush=True)
                    current_audio_lang = ""
                    current_subtitle_lang = ""
            else:
                is_paused = False
                current_audio_lang = ""
                current_subtitle_lang = ""
            
            # Return current episode ID (stable) with pause state and language info
            if last_known_episode:
                print(f"[DEBUG] Poll playback - Returning playing: True, item: {last_known_episode}", flush=True)
                return jsonify({
                    "playing": True, 
                    "paused": is_paused,
                    "item_id": last_known_episode,
                    "item_type": "episode",
                    "current_audio_lang": current_audio_lang,
                    "current_subtitle_lang": current_subtitle_lang
                })
            else:
                print(f"[DEBUG] No episode info available, returning episode_unknown", flush=True)
                print(f"[DEBUG] Poll playback - Returning playing: True, item: episode_unknown", flush=True)
                return jsonify({
                    "playing": True, 
                    "paused": is_paused,
                    "item_id": "episode_unknown",
                    "item_type": "episode",
                    "current_audio_lang": current_audio_lang,
                    "current_subtitle_lang": current_subtitle_lang
                })
            
        # No active players - reset tracking variables
        last_known_episode = None
        last_check_time = 0
        print(f"[DEBUG] Poll playback - No active players, returning playing: False", flush=True)
        return jsonify({"playing": False})
    except Exception as e:
        print(f"[ERROR] Poll playback failed: {e}", flush=True)
        # Return False on error - this will trigger retry logic on frontend
        return jsonify({"playing": False, "error": True})

def kodi_rpc(method, params=None, server_id=None):
    """
    Make RPC call to Kodi server.
    
    Args:
        method: RPC method name
        params: RPC parameters
        server_id: Optional server ID to use (if None, uses active server from session)
    """
    # Get server to use
    if server_id and server_id in KODI_SERVERS:
        server = KODI_SERVERS[server_id]
    else:
        server = get_active_server()
    
    if not server:
        print(f"[ERROR] No Kodi server available", flush=True)
        return None
    
    payload = {
        "jsonrpc": "2.0",
        "method": method,
        "params": params or {},
        "id": 1
    }
    try:
        r = requests.post(f"{server['host']}/jsonrpc", headers=HEADERS, json=payload, auth=server['auth'], timeout=8)
        r.raise_for_status()
        response_json = r.json()
        print(f"[DEBUG] Kodi response for {method} (server {server['id']}):", response_json, flush=True)
        return response_json
    except Exception as e:
        print(f"[ERROR] Kodi RPC failed for method {method} (server {server['id']}): {e}", flush=True)
        return None



def prepare_and_download_art(item, session_id):
    downloaded = {}
    
    # Get active server for this request
    server = get_active_server()
    if not server:
        print(f"[ERROR] No active server available for artwork download", flush=True)
        return downloaded

    art_map = item.get("art", {})
    if item.get("thumbnail") and not art_map.get("poster"):
        art_map["poster"] = item["thumbnail"]

    # Handle TV show artwork with tvshow. prefix
    tvshow_art_map = {}
    for key, value in art_map.items():
        if key.startswith("tvshow."):
            # Map tvshow.poster to poster, tvshow.fanart to fanart, etc.
            clean_key = key.replace("tvshow.", "")
            tvshow_art_map[clean_key] = value

    # Handle music artwork with album., artist., and albumartist. prefixes
    music_art_map = {}
    for key, value in art_map.items():
        if key.startswith("album."):
            # Map album.thumb to thumbnail, album.poster to poster, etc.
            clean_key = key.replace("album.", "")
            if clean_key == "thumb":
                clean_key = "thumbnail"
            music_art_map[clean_key] = value
            # Also map album.front to front and album.back to back for cover art
            if clean_key == "front":
                music_art_map["front"] = value
            elif clean_key == "back":
                music_art_map["back"] = value
        elif key.startswith("artist."):
            # Map artist.fanart to fanart, artist.clearlogo to clearlogo, etc.
            clean_key = key.replace("artist.", "")
            music_art_map[clean_key] = value
        elif key.startswith("albumartist."):
            # Map albumartist.fanart to fanart, albumartist.clearlogo to clearlogo, etc.
            clean_key = key.replace("albumartist.", "")
            music_art_map[clean_key] = value

    # Merge all artwork (music takes precedence, then TV show, then regular)
    art_map = {**art_map, **tvshow_art_map, **music_art_map}
    
    # Debug logging for artwork
    print(f"[DEBUG] Original art_map keys: {list(item.get('art', {}).keys())}", flush=True)
    print(f"[DEBUG] Final art_map keys: {list(art_map.keys())}", flush=True)

    # Special handling for fanart - collect all variants for slideshow
    fanart_variants = {}
    for key, value in art_map.items():
        # Collect both regular fanart variants and extrafanart variants
        if (key.startswith("fanart") and (key == "fanart" or key.startswith("fanart"))) or key.startswith("extrafanart"):
            fanart_variants[key] = value
    
    print(f"[DEBUG] Found fanart variants: {list(fanart_variants.keys())}", flush=True)
    print(f"[DEBUG] Total fanart variants found: {len(fanart_variants)}", flush=True)
    
    # For music, try to find common front cover files if Kodi provided audio file instead of image
    def _is_image_path(path: str) -> bool:
        if not path:
            return False
        lowered = path.lower()
        return lowered.endswith((".jpg", ".jpeg", ".png", ".webp"))

    def _clean_image_protocol(path: str) -> str:
        if not path:
            return ""
        cleaned = path
        if cleaned.startswith("image://"):
            cleaned = urllib.parse.unquote(cleaned[len("image://"):])
        return cleaned.rstrip("/")

    if item.get("type") == "song" and item.get("file"):
        current_file = item.get("file", "")
        album_dir = os.path.dirname(current_file.rstrip("/"))

        # Determine if Kodi gave us a proper image thumbnail
        kodi_thumbnail = art_map.get("thumbnail") or art_map.get("thumb") or art_map.get("album.thumb")
        cleaned_thumbnail = _clean_image_protocol(kodi_thumbnail)
        has_valid_cover = _is_image_path(cleaned_thumbnail)

        if not has_valid_cover:
            front_cover_candidates = {
                "folder", "cover", "thumb", "front", "album", "artist",
                "frontcover", "albumcover", "cd", "cdcover"
            }

            def find_cover(start_dir: str, max_depth: int = 3) -> str:
                checked = set()
                current_dir = start_dir

                for depth in range(max_depth + 1):
                    if not current_dir or current_dir in checked:
                        break
                    checked.add(current_dir)
                    try:
                        dir_response = kodi_rpc("Files.GetDirectory", {
                            "directory": current_dir,
                            "properties": ["file"]
                        })

                        if dir_response and dir_response.get("result") and not dir_response.get("error"):
                            files = dir_response.get("result", {}).get("files", [])
                            print(f"[DEBUG] Music cover scan (depth {depth}) found {len(files)} files in {current_dir}", flush=True)

                            for file_info in files:
                                if not isinstance(file_info, dict):
                                    continue
                                file_path = file_info.get("file", "")
                                file_type = file_info.get("filetype", "")
                                if file_type != "file" or not file_path:
                                    continue

                                lower_path = file_path.lower()
                                if not lower_path.endswith((".jpg", ".jpeg", ".png", ".webp")):
                                    continue

                                base_name = os.path.basename(lower_path)
                                name_without_ext, _ = os.path.splitext(base_name)

                                if (name_without_ext in front_cover_candidates or
                                        any(candidate in name_without_ext for candidate in front_cover_candidates)):
                                    print(f"[DEBUG] Found fallback album cover at depth {depth}: {file_path}", flush=True)
                                    return file_path
                        else:
                            print(f"[DEBUG] Music cover directory scan failed for {current_dir}: {dir_response}", flush=True)
                    except Exception as scan_error:
                        print(f"[DEBUG] Error scanning directory {current_dir} for cover art: {scan_error}", flush=True)

                    # Move one level up
                    parent_dir = os.path.dirname(current_dir.rstrip("/"))
                    if parent_dir == current_dir:
                        break
                    current_dir = parent_dir

                return ""

            potential_cover = find_cover(album_dir)
            if potential_cover:
                art_map["thumbnail"] = potential_cover
                art_map["thumb"] = potential_cover
                print(f"[DEBUG] Using fallback music thumbnail: {potential_cover}", flush=True)
            else:
                print(f"[DEBUG] No fallback album cover found for {album_dir}", flush=True)

    # For movies and episodes, try to find additional fanart files in the media folder
    if item.get("type") in ["movie", "episode"] and item.get("file"):
        current_file = item.get("file", "")
        if current_file.startswith("nfs://"):
            try:
                # For TV episodes, we need to look in the TV show's root directory, not the episode's directory
                if item.get("type") == "episode":
                    # Get the TV show's root directory by going up from the episode file
                    # Episode path: /Show/Season XX/episode.mkv
                    # We want: /Show/
                    episode_dir = os.path.dirname(current_file)  # Season XX directory
                    media_dir = os.path.dirname(episode_dir)     # Show root directory
                    print(f"[DEBUG] TV Episode detected - looking for fanart in show root directory: {media_dir}", flush=True)
                else:
                    # For movies, use the movie's directory
                    media_dir = os.path.dirname(current_file)
                    print(f"[DEBUG] Looking for additional fanart in directory: {media_dir}", flush=True)
                
                # Try to list the directory contents using Kodi's Files.GetDirectory API
                try:
                    dir_response = kodi_rpc("Files.GetDirectory", {
                        "directory": media_dir,
                        "properties": ["file"]
                    })
                    
                    if dir_response and dir_response.get("result") and not dir_response.get("error"):
                        files = dir_response.get("result", {}).get("files", [])
                        print(f"[DEBUG] Found {len(files)} files in directory", flush=True)
                        
                        # Look for fanart files in the directory listing
                        for file_info in files:
                            if isinstance(file_info, dict):
                                file_path = file_info.get("file", "")
                                file_type = file_info.get("filetype", "")
                                
                                # Check if this is the extrafanart directory
                                if file_path and file_type == "directory" and "extrafanart" in file_path.lower():
                                    print(f"[DEBUG] Found extrafanart directory: {file_path}", flush=True)
                                    
                                    # Scan the extrafanart directory
                                    try:
                                        extrafanart_response = kodi_rpc("Files.GetDirectory", {
                                            "directory": file_path,
                                            "properties": ["file"]
                                        })
                                        
                                        if extrafanart_response and extrafanart_response.get("result") and not extrafanart_response.get("error"):
                                            extrafanart_files = extrafanart_response.get("result", {}).get("files", [])
                                            print(f"[DEBUG] Found {len(extrafanart_files)} files in extrafanart directory", flush=True)
                                            
                                            # Process each fanart file in the extrafanart directory
                                            for extrafanart_file in extrafanart_files:
                                                if isinstance(extrafanart_file, dict):
                                                    extrafanart_path = extrafanart_file.get("file", "")
                                                    if extrafanart_path and extrafanart_path.lower().endswith((".jpg", ".jpeg", ".png")):
                                                        filename = os.path.basename(extrafanart_path)
                                                        print(f"[DEBUG] Found extrafanart file: {extrafanart_path}", flush=True)
                                                        
                                                        # Create a unique key for this extrafanart file
                                                        if filename.lower() == "fanart.jpg":
                                                            fanart_variants["extrafanart_main"] = extrafanart_path
                                                            print(f"[DEBUG] Added extrafanart main: {extrafanart_path}", flush=True)
                                                        else:
                                                            # Use filename as key (fanart2.jpg -> extrafanart2, etc.)
                                                            key_name = f"extrafanart_{filename.lower().replace('.jpg', '').replace('.jpeg', '').replace('.png', '')}"
                                                            fanart_variants[key_name] = extrafanart_path
                                                            print(f"[DEBUG] Added extrafanart: {key_name} -> {extrafanart_path}", flush=True)
                                        else:
                                            print(f"[DEBUG] Failed to scan extrafanart directory: {extrafanart_response}", flush=True)
                                            
                                    except Exception as extrafanart_e:
                                        print(f"[DEBUG] Error scanning extrafanart directory: {extrafanart_e}", flush=True)
                                
                                # Also check for fanart files directly in the main directory
                                elif file_path and "fanart" in file_path.lower() and file_type == "file":
                                    print(f"[DEBUG] Found potential fanart file: {file_path}", flush=True)
                                    
                                    # Try to determine the fanart variant name
                                    filename = os.path.basename(file_path)
                                    if filename.lower() == "fanart.jpg":
                                        # This is the main fanart, skip it
                                        continue
                                    elif filename.lower().startswith("fanart") and filename.lower().endswith((".jpg", ".jpeg", ".png")):
                                        # Extract the variant number
                                        variant_name = filename.lower().replace("fanart", "").replace(".jpg", "").replace(".jpeg", "").replace(".png", "")
                                        if variant_name.isdigit():
                                            fanart_variants[f"fanart{variant_name}"] = file_path
                                            print(f"[DEBUG] Added fanart variant: fanart{variant_name} -> {file_path}", flush=True)
                                        elif variant_name == "":
                                            # This is fanart.jpg, skip it
                                            continue
                                        else:
                                            # Custom fanart name
                                            fanart_variants[f"fanart_{variant_name}"] = file_path
                                            print(f"[DEBUG] Added custom fanart: fanart_{variant_name} -> {file_path}", flush=True)
                    else:
                        print(f"[DEBUG] Failed to get directory listing: {dir_response}", flush=True)
                        
                except Exception as dir_e:
                    print(f"[DEBUG] Directory listing failed: {dir_e}", flush=True)
                    
                    # Fallback: try to find fanart1, fanart2, etc. by testing individual files
                    print(f"[DEBUG] Falling back to individual file testing", flush=True)
                    for i in range(1, 10):  # fanart1 through fanart9
                        fanart_filename = f"fanart{i}.jpg"
                        fanart_path = f"{media_dir}/{fanart_filename}"
                        
                        print(f"[DEBUG] Testing fanart{i}: {fanart_path}", flush=True)
                        
                        # Try to access the file directly through Kodi's HTTP interface
                        try:
                            response = kodi_rpc("Files.PrepareDownload", {"path": fanart_path})
                            if response and response.get("result") and not response.get("error"):
                                details = response.get("result", {}).get("details", {})
                                token = details.get("token")
                                path = details.get("path")
                                
                                if token:
                                    basename = os.path.basename(fanart_path)
                                    image_url = f"{server['host']}/vfs/{token}/{urllib.parse.quote(basename)}"
                                    # Test if the image actually exists
                                    try:
                                        test_response = requests.head(image_url, auth=server['auth'], timeout=3)
                                        if test_response.status_code == 200:
                                            fanart_variants[f"fanart{i}"] = fanart_path
                                            print(f"[DEBUG] Found additional fanart: fanart{i} at {fanart_path}", flush=True)
                                    except Exception as test_e:
                                        print(f"[DEBUG] Test request failed for fanart{i}: {test_e}", flush=True)
                                elif path:
                                    # Test if the image actually exists
                                    try:
                                        test_response = requests.head(f"{server['host']}/{path}", auth=server['auth'], timeout=3)
                                        if test_response.status_code == 200:
                                            fanart_variants[f"fanart{i}"] = fanart_path
                                            print(f"[DEBUG] Found additional fanart: fanart{i} at {fanart_path}", flush=True)
                                    except Exception as test_e:
                                        print(f"[DEBUG] Test request failed for fanart{i}: {test_e}", flush=True)
                        except Exception as e:
                            print(f"[DEBUG] Failed to check fanart{i}: {e}", flush=True)
                            pass
                        
            except Exception as e:
                print(f"[DEBUG] Failed to scan for additional fanart: {e}", flush=True)
    
    print(f"[DEBUG] Total fanart variants found: {list(fanart_variants.keys())}", flush=True)

    for art_type in ART_TYPES:
        raw_path = art_map.get(art_type)
        print(f"[DEBUG] Processing art_type: {art_type}, raw_path: {raw_path}", flush=True)
        if not raw_path:
            continue

        if raw_path and raw_path.startswith("image://"):
            raw_path = urllib.parse.unquote(raw_path[len("image://"):])
        if raw_path and raw_path.endswith("/"):
            raw_path = raw_path[:-1]

        # Handle external URLs directly (like fanart.tv, theaudiodb.com)
        if raw_path and (raw_path.startswith("https://") or raw_path.startswith("http://")):
            image_url = raw_path
        else:
            # Handle local Kodi paths
            image_url = None
            try:
                if raw_path:
                    response = kodi_rpc("Files.PrepareDownload", {"path": raw_path})
                else:
                    response = None
                details = response.get("result", {}).get("details", {}) if response else {}
                token = details.get("token")
                path = details.get("path")

                if token and raw_path:
                    basename = os.path.basename(raw_path)
                    image_url = f"{server['host']}/vfs/{token}/{urllib.parse.quote(basename)}"
                elif path:
                    image_url = f"{server['host']}/{path}"
                else:
                    print(f"[ERROR] No valid download path for {art_type}", flush=True)
            except Exception as e:
                print(f"[WARNING] Failed to prepare download for {art_type}: {e}", flush=True)
            
            # If primary path failed, try fallback paths for artist artwork
            if not image_url and art_type in ["fanart", "clearlogo", "clearart", "banner", "front", "back", "discart"]:
                print(f"[DEBUG] Primary path failed, trying fallback paths for {art_type}", flush=True)
                # Try to construct fallback paths based on album/artist folder structure
                current_file = item.get("file", "")
                if current_file.startswith("nfs://"):
                    try:
                        # Traverse upwards to find directories that contain fanart files
                        # This is the most reliable way since fanart is typically only in artist directories
                        current_path = current_file
                        fallback_paths = []
                        
                        print(f"[DEBUG] Traversing upwards from: {current_path}")
                        
                        # Traverse upwards to find directories with fanart files
                        for level in range(8):  # Limit to 8 levels up to avoid infinite loops
                            parent_path = os.path.dirname(current_path)
                            if parent_path == current_path:  # Reached root
                                break
                            
                            dir_name = os.path.basename(parent_path)
                            
                            # Skip system directories
                            if any(x in dir_name.upper() for x in ['MEDIA', 'MUSIC', 'VIDEO', 'TV', 'MOVIES']):
                                current_path = parent_path
                                pass
                            
                            # Try to find fanart files in this directory
                            # This works for both artist directories (which have fanart) and album directories (which might have other artwork)
                            fanart_png = f"{parent_path}/fanart.png"
                            fanart_jpg = f"{parent_path}/fanart.jpg"
                            clearlogo_png = f"{parent_path}/clearlogo.png"
                            clearlogo_jpg = f"{parent_path}/clearlogo.jpg"
                            clearart_png = f"{parent_path}/clearart.png"
                            clearart_jpg = f"{parent_path}/clearart.jpg"
                            banner_png = f"{parent_path}/banner.png"
                            banner_jpg = f"{parent_path}/banner.jpg"
                            Front_jpg = f"{parent_path}/Front.jpg"
                            Front_png = f"{parent_path}/Front.png"
                            Front_jpeg = f"{parent_path}/Front.jpeg"
                            front_jpg = f"{parent_path}/front.jpg"
                            front_png = f"{parent_path}/front.png"
                            front_jpeg = f"{parent_path}/front.jpeg"
                            Back_jpg = f"{parent_path}/Back.jpg"
                            Back_png = f"{parent_path}/Back.png"
                            Back_jpeg = f"{parent_path}/Back.jpeg"
                            back_jpg = f"{parent_path}/back.jpg"
                            back_png = f"{parent_path}/back.png"
                            back_jpeg = f"{parent_path}/back.jpeg"
                            discart_png = f"{parent_path}/discart.png"
                            discart_jpg = f"{parent_path}/discart.jpg"
                            discart_jpeg = f"{parent_path}/discart.jpeg"
                            Discart_png = f"{parent_path}/Discart.png"
                            Discart_jpg = f"{parent_path}/Discart.jpg"
                            Discart_jpeg = f"{parent_path}/Discart.jpeg"
                            
                            # Add paths for the specific art type we're looking for
                            if art_type == "fanart":
                                fallback_paths.append(f"image://{urllib.parse.quote(fanart_png, safe='')}/")
                                fallback_paths.append(f"image://{urllib.parse.quote(fanart_jpg, safe='')}/")
                                # First, try extrafanart folder (fanart.jpg, fanart2.jpg, etc.)
                                for i in range(1, 10):  # fanart1 through fanart9 in extrafanart folder
                                    extrafanart_png = f"{parent_path}/extrafanart/fanart{i}.png"
                                    extrafanart_jpg = f"{parent_path}/extrafanart/fanart{i}.jpg"
                                    extrafanart_jpeg = f"{parent_path}/extrafanart/fanart{i}.jpeg"
                                    fallback_paths.extend([
                                        f"image://{urllib.parse.quote(extrafanart_png, safe='')}/",
                                        f"image://{urllib.parse.quote(extrafanart_jpg, safe='')}/",
                                        f"image://{urllib.parse.quote(extrafanart_jpeg, safe='')}/"
                                    ])
                                
                                # Also try the main fanart.jpg in extrafanart folder
                                extrafanart_main_png = f"{parent_path}/extrafanart/fanart.png"
                                extrafanart_main_jpg = f"{parent_path}/extrafanart/fanart.jpg"
                                extrafanart_main_jpeg = f"{parent_path}/extrafanart/fanart.jpeg"
                                fallback_paths.extend([
                                    f"image://{urllib.parse.quote(extrafanart_main_png, safe='')}/",
                                    f"image://{urllib.parse.quote(extrafanart_main_jpg, safe='')}/",
                                    f"image://{urllib.parse.quote(extrafanart_main_jpeg, safe='')}/"
                                ])
                                
                                # Also try fanart variants (fanart1, fanart2, etc.)
                                for i in range(1, 10):  # fanart1 through fanart9
                                    fanart_var_png = f"{parent_path}/fanart{i}.png"
                                    fanart_var_jpg = f"{parent_path}/fanart{i}.jpg"
                                    fanart_var_jpeg = f"{parent_path}/fanart{i}.jpeg"
                                    fallback_paths.extend([
                                        f"image://{urllib.parse.quote(fanart_var_png, safe='')}/",
                                        f"image://{urllib.parse.quote(fanart_var_jpg, safe='')}/",
                                        f"image://{urllib.parse.quote(fanart_var_jpeg, safe='')}/"
                                    ])
                            elif art_type == "clearlogo":
                                fallback_paths.append(f"image://{urllib.parse.quote(clearlogo_png, safe='')}/")
                                fallback_paths.append(f"image://{urllib.parse.quote(clearlogo_jpg, safe='')}/")
                            elif art_type == "clearart":
                                fallback_paths.append(f"image://{urllib.parse.quote(clearart_png, safe='')}/")
                                fallback_paths.append(f"image://{urllib.parse.quote(clearart_jpg, safe='')}/")
                            elif art_type == "banner":
                                fallback_paths.append(f"image://{urllib.parse.quote(banner_png, safe='')}/")
                                fallback_paths.append(f"image://{urllib.parse.quote(banner_jpg, safe='')}/")
                            elif art_type == "front":
                                fallback_paths.append(f"image://{urllib.parse.quote(Front_jpg, safe='')}/")
                                fallback_paths.append(f"image://{urllib.parse.quote(Front_png, safe='')}/")
                                fallback_paths.append(f"image://{urllib.parse.quote(Front_jpeg, safe='')}/")
                                fallback_paths.append(f"image://{urllib.parse.quote(front_jpg, safe='')}/")
                                fallback_paths.append(f"image://{urllib.parse.quote(front_png, safe='')}/")
                                fallback_paths.append(f"image://{urllib.parse.quote(front_jpeg, safe='')}/")
                            elif art_type == "back":
                                fallback_paths.append(f"image://{urllib.parse.quote(Back_jpg, safe='')}/")
                                fallback_paths.append(f"image://{urllib.parse.quote(Back_png, safe='')}/")
                                fallback_paths.append(f"image://{urllib.parse.quote(Back_jpeg, safe='')}/")
                                fallback_paths.append(f"image://{urllib.parse.quote(back_jpg, safe='')}/")
                                fallback_paths.append(f"image://{urllib.parse.quote(back_png, safe='')}/")
                                fallback_paths.append(f"image://{urllib.parse.quote(back_jpeg, safe='')}/")
                            elif art_type == "discart":
                                fallback_paths.append(f"image://{urllib.parse.quote(discart_png, safe='')}/")
                                fallback_paths.append(f"image://{urllib.parse.quote(discart_jpg, safe='')}/")
                                fallback_paths.append(f"image://{urllib.parse.quote(discart_jpeg, safe='')}/")
                                fallback_paths.append(f"image://{urllib.parse.quote(Discart_png, safe='')}/")
                                fallback_paths.append(f"image://{urllib.parse.quote(Discart_jpg, safe='')}/")
                                fallback_paths.append(f"image://{urllib.parse.quote(Discart_jpeg, safe='')}/")
                            
                            print(f"[DEBUG] Level {level}: Checking {parent_path} for {art_type}")
                            
                            current_path = parent_path
                        
                        # Try each fallback path
                        for fallback_path in fallback_paths:
                            try:
                                print(f"[DEBUG] Trying fallback path: {fallback_path}")
                                response = kodi_rpc("Files.PrepareDownload", {"path": fallback_path})
                                details = response.get("result", {}).get("details", {})
                                token = details.get("token")
                                path = details.get("path")
                                
                                if token:
                                    basename = os.path.basename(fallback_path)
                                    image_url = f"{server['host']}/vfs/{token}/{urllib.parse.quote(basename)}"
                                    print(f"[DEBUG] Found fallback path for {art_type}: {image_url}")
                                    break
                                elif path:
                                    image_url = f"{server['host']}/{path}"
                                    print(f"[DEBUG] Found fallback path for {art_type}: {image_url}")
                                    break
                            except Exception as e:
                                print(f"[DEBUG] Fallback path failed for {art_type}: {e}")
                                pass
                    except Exception as e:
                        print(f"[DEBUG] Failed to construct fallback paths for {art_type}: {e}")
            
            if not image_url:
                print(f"[ERROR] No valid download path found for {art_type}", flush=True)
                continue

        filename = f"{session_id}_{art_type}.jpg"
        local_path = f"/tmp/{filename}"

        try:
            # Use authentication only for Kodi internal URLs
            if image_url.startswith(server['host']):
                print(f"[DEBUG] Downloading with auth: {image_url}", flush=True)
                r = requests.get(image_url, auth=server['auth'], timeout=5)
            else:
                print(f"[DEBUG] Downloading without auth: {image_url}", flush=True)
                r = requests.get(image_url, timeout=5)
            r.raise_for_status()
            with open(local_path, "wb") as f:
                f.write(r.content)
            downloaded[art_type] = filename
            print(f"[INFO] Downloaded {art_type} to {local_path}", flush=True)
        except Exception as e:
            print(f"[ERROR] Failed to download {art_type}: {e}", flush=True)
            
            # If download failed with 401, try fallback paths for artist artwork
            if "401" in str(e) and art_type in ["fanart", "clearlogo", "clearart", "banner", "front", "back", "discart"]:
                print(f"[DEBUG] Download failed with 401, trying fallback paths for {art_type}", flush=True)
                # Try to construct fallback paths based on album/artist folder structure
                current_file = item.get("file", "")
                if current_file.startswith("nfs://"):
                    try:
                        # Traverse upwards to find directories that contain fanart files
                        # This is the most reliable way since fanart is typically only in artist directories
                        current_path = current_file
                        fallback_paths = []
                        
                        print(f"[DEBUG] Traversing upwards from: {current_path}")
                        
                        # Traverse upwards to find directories with fanart files
                        for level in range(8):  # Limit to 8 levels up to avoid infinite loops
                            parent_path = os.path.dirname(current_path)
                            if parent_path == current_path:  # Reached root
                                break
                            
                            dir_name = os.path.basename(parent_path)
                            
                            # Skip system directories
                            if any(x in dir_name.upper() for x in ['MEDIA', 'MUSIC', 'VIDEO', 'TV', 'MOVIES']):
                                current_path = parent_path
                                pass
                            
                            # Try to find fanart files in this directory
                            # This works for both artist directories (which have fanart) and album directories (which might have other artwork)
                            fanart_png = f"{parent_path}/fanart.png"
                            fanart_jpg = f"{parent_path}/fanart.jpg"
                            clearlogo_png = f"{parent_path}/clearlogo.png"
                            clearlogo_jpg = f"{parent_path}/clearlogo.jpg"
                            clearart_png = f"{parent_path}/clearart.png"
                            clearart_jpg = f"{parent_path}/clearart.jpg"
                            banner_png = f"{parent_path}/banner.png"
                            banner_jpg = f"{parent_path}/banner.jpg"
                            front_png = f"{parent_path}/front.png"
                            front_jpg = f"{parent_path}/front.jpg"
                            front_jpeg = f"{parent_path}/front.jpeg"
                            Front_png = f"{parent_path}/Front.png"
                            Front_jpg = f"{parent_path}/Front.jpg"
                            Front_jpeg = f"{parent_path}/Front.jpeg"
                            back_png = f"{parent_path}/back.png"
                            back_jpg = f"{parent_path}/back.jpg"
                            back_jpeg = f"{parent_path}/back.jpeg"
                            Back_png = f"{parent_path}/Back.png"
                            Back_jpg = f"{parent_path}/Back.jpg"
                            Back_jpeg = f"{parent_path}/Back.jpeg"
                            discart_png = f"{parent_path}/discart.png"
                            discart_jpg = f"{parent_path}/discart.jpg"
                            discart_jpeg = f"{parent_path}/discart.jpeg"
                            Discart_png = f"{parent_path}/Discart.png"
                            Discart_jpg = f"{parent_path}/Discart.jpg"
                            Discart_jpeg = f"{parent_path}/Discart.jpeg"
                            
                            # Add paths for the specific art type we're looking for
                            if art_type == "fanart":
                                fallback_paths.append(f"image://{urllib.parse.quote(fanart_png, safe='')}/")
                                fallback_paths.append(f"image://{urllib.parse.quote(fanart_jpg, safe='')}/")
                                # First, try extrafanart folder (fanart.jpg, fanart2.jpg, etc.)
                                for i in range(1, 10):  # fanart1 through fanart9 in extrafanart folder
                                    extrafanart_png = f"{parent_path}/extrafanart/fanart{i}.png"
                                    extrafanart_jpg = f"{parent_path}/extrafanart/fanart{i}.jpg"
                                    extrafanart_jpeg = f"{parent_path}/extrafanart/fanart{i}.jpeg"
                                    fallback_paths.extend([
                                        f"image://{urllib.parse.quote(extrafanart_png, safe='')}/",
                                        f"image://{urllib.parse.quote(extrafanart_jpg, safe='')}/",
                                        f"image://{urllib.parse.quote(extrafanart_jpeg, safe='')}/"
                                    ])
                                
                                # Also try the main fanart.jpg in extrafanart folder
                                extrafanart_main_png = f"{parent_path}/extrafanart/fanart.png"
                                extrafanart_main_jpg = f"{parent_path}/extrafanart/fanart.jpg"
                                extrafanart_main_jpeg = f"{parent_path}/extrafanart/fanart.jpeg"
                                fallback_paths.extend([
                                    f"image://{urllib.parse.quote(extrafanart_main_png, safe='')}/",
                                    f"image://{urllib.parse.quote(extrafanart_main_jpg, safe='')}/",
                                    f"image://{urllib.parse.quote(extrafanart_main_jpeg, safe='')}/"
                                ])
                                
                                # Also try fanart variants (fanart1, fanart2, etc.)
                                for i in range(1, 10):  # fanart1 through fanart9
                                    fanart_var_png = f"{parent_path}/fanart{i}.png"
                                    fanart_var_jpg = f"{parent_path}/fanart{i}.jpg"
                                    fanart_var_jpeg = f"{parent_path}/fanart{i}.jpeg"
                                    fallback_paths.extend([
                                        f"image://{urllib.parse.quote(fanart_var_png, safe='')}/",
                                        f"image://{urllib.parse.quote(fanart_var_jpg, safe='')}/",
                                        f"image://{urllib.parse.quote(fanart_var_jpeg, safe='')}/"
                                    ])
                            elif art_type == "clearlogo":
                                fallback_paths.append(f"image://{urllib.parse.quote(clearlogo_png, safe='')}/")
                                fallback_paths.append(f"image://{urllib.parse.quote(clearlogo_jpg, safe='')}/")
                            elif art_type == "clearart":
                                fallback_paths.append(f"image://{urllib.parse.quote(clearart_png, safe='')}/")
                                fallback_paths.append(f"image://{urllib.parse.quote(clearart_jpg, safe='')}/")
                            elif art_type == "banner":
                                fallback_paths.append(f"image://{urllib.parse.quote(banner_png, safe='')}/")
                                fallback_paths.append(f"image://{urllib.parse.quote(banner_jpg, safe='')}/")
                            elif art_type == "front":
                                fallback_paths.append(f"image://{urllib.parse.quote(Front_jpg, safe='')}/")
                                fallback_paths.append(f"image://{urllib.parse.quote(Front_png, safe='')}/")
                                fallback_paths.append(f"image://{urllib.parse.quote(Front_jpeg, safe='')}/")
                                fallback_paths.append(f"image://{urllib.parse.quote(front_jpg, safe='')}/")
                                fallback_paths.append(f"image://{urllib.parse.quote(front_png, safe='')}/")
                                fallback_paths.append(f"image://{urllib.parse.quote(front_jpeg, safe='')}/")
                            elif art_type == "back":
                                fallback_paths.append(f"image://{urllib.parse.quote(Back_jpg, safe='')}/")
                                fallback_paths.append(f"image://{urllib.parse.quote(Back_png, safe='')}/")
                                fallback_paths.append(f"image://{urllib.parse.quote(Back_jpeg, safe='')}/")
                                fallback_paths.append(f"image://{urllib.parse.quote(back_jpg, safe='')}/")
                                fallback_paths.append(f"image://{urllib.parse.quote(back_png, safe='')}/")
                                fallback_paths.append(f"image://{urllib.parse.quote(back_jpeg, safe='')}/")
                            elif art_type == "discart":
                                fallback_paths.append(f"image://{urllib.parse.quote(discart_png, safe='')}/")
                                fallback_paths.append(f"image://{urllib.parse.quote(discart_jpg, safe='')}/")
                                fallback_paths.append(f"image://{urllib.parse.quote(discart_jpeg, safe='')}/")
                                fallback_paths.append(f"image://{urllib.parse.quote(Discart_png, safe='')}/")
                                fallback_paths.append(f"image://{urllib.parse.quote(Discart_jpg, safe='')}/")
                                fallback_paths.append(f"image://{urllib.parse.quote(Discart_jpeg, safe='')}/")
                            
                            print(f"[DEBUG] Level {level}: Checking {parent_path} for {art_type}")
                            
                            current_path = parent_path
                        
                        # Try each fallback path
                        for fallback_path in fallback_paths:
                            try:
                                print(f"[DEBUG] Trying fallback path: {fallback_path}")
                                response = kodi_rpc("Files.PrepareDownload", {"path": fallback_path})
                                details = response.get("result", {}).get("details", {})
                                token = details.get("token")
                                path = details.get("path")
                                
                                if token:
                                    basename = os.path.basename(fallback_path)
                                    fallback_image_url = f"{server['host']}/vfs/{token}/{urllib.parse.quote(basename)}"
                                elif path:
                                    fallback_image_url = f"{server['host']}/{path}"
                                else:
                                    pass
                                
                                # Try to download the fallback image
                                print(f"[DEBUG] Trying to download fallback: {fallback_image_url}")
                                r = requests.get(fallback_image_url, auth=server['auth'], timeout=5)
                                r.raise_for_status()
                                with open(local_path, "wb") as f:
                                    f.write(r.content)
                                downloaded[art_type] = filename
                                print(f"[INFO] Downloaded {art_type} from fallback path to {local_path}")
                                break  # Success, stop trying other fallback paths
                            except Exception as fallback_e:
                                print(f"[DEBUG] Fallback path failed for {art_type}: {fallback_e}")
                                pass
                    except Exception as fallback_construct_e:
                        print(f"[DEBUG] Failed to construct fallback paths for {art_type}: {fallback_construct_e}")

    # Process fanart variants for slideshow
    if len(fanart_variants) > 1:
        print(f"[DEBUG] Processing {len(fanart_variants)} fanart variants for slideshow", flush=True)
        
        # Download additional fanart variants
        for variant_key, variant_path in fanart_variants.items():
            if variant_key == "fanart":
                continue  # Skip the main fanart as it's already processed
                
            try:
                # Prepare download for this fanart variant
                # Handle different path formats
                if variant_path.startswith("image://"):
                    print(f"[DEBUG] Processing fanart variant {variant_key}: {variant_path}", flush=True)
                    
                    # Handle artist information paths with fallback logic
                    if "ArtistInformation" in variant_path:
                        print(f"[DEBUG] Processing artist information path for {variant_key}: {variant_path}", flush=True)
                        
                        # Extract the artist name and filename from the path
                        original_path = urllib.parse.unquote(variant_path[len("image://"):])
                        if original_path.endswith("/"):
                            original_path = original_path[:-1]
                        
                        # Extract artist name from path like U:\Kodi\ArtistInformation\AURORA\fanart1.jpg
                        path_parts = original_path.split("\\")
                        if len(path_parts) >= 4:
                            artist_name = path_parts[3]  # AURORA
                            filename = path_parts[-1]    # fanart1.jpg
                            
                            # Get the artist folder path from the current file
                            current_file = item.get("file", "")
                            if current_file.startswith("nfs://"):
                                file_parts = current_file.split("/")
                                if "Music" in file_parts:
                                    music_index = file_parts.index("Music")
                                    if music_index + 1 < len(file_parts):
                                        artist_folder = file_parts[music_index + 1]
                                        
                                        # Try multiple fallback paths with different formats
                                        fallback_paths = []
                                        
                                        # Build base path from current file's path
                                        file_parts = current_file.split("/")
                                        if "Music" in file_parts:
                                            music_index = file_parts.index("Music")
                                            base_path = "/".join(file_parts[:music_index + 1])  # Everything up to and including "Music"
                                        
                                        # 1. Try direct artist folder path with original extension
                                        fallback_paths.append(f"{base_path}/{artist_folder}/{filename}")
                                        
                                        # 2. Try different file extensions (jpg, jpeg, png)
                                        base_filename = filename.rsplit('.', 1)[0] if '.' in filename else filename
                                        for ext in ['jpg', 'jpeg', 'png']:
                                            fallback_paths.append(f"{base_path}/{artist_folder}/{base_filename}.{ext}")
                                        
                                        # 3. Try extrafanart folder with original extension
                                        fallback_paths.append(f"{base_path}/{artist_folder}/extrafanart/{filename}")
                                        
                                        # 4. Try extrafanart folder with different extensions
                                        for ext in ['jpg', 'jpeg', 'png']:
                                            fallback_paths.append(f"{base_path}/{artist_folder}/extrafanart/{base_filename}.{ext}")
                                        
                                        # Try each fallback path
                                        for fallback_path in fallback_paths:
                                            image_protocol_path = f"image://{urllib.parse.quote(fallback_path, safe='')}/"
                                            print(f"[DEBUG] Trying fallback path: {image_protocol_path}", flush=True)
                                            
                                            response = kodi_rpc("Files.PrepareDownload", {"path": image_protocol_path})
                                            if response and response.get("result") and not response.get("error"):
                                                details = response.get("result", {}).get("details", {})
                                                token = details.get("token")
                                                path = details.get("path")
                                                
                                                if token:
                                                    basename = os.path.basename(fallback_path)
                                                    image_url = f"{server['host']}/vfs/{token}/{urllib.parse.quote(basename)}"
                                                elif path:
                                                    image_url = f"{server['host']}/{path}"
                                                else:
                                                    continue
                                                
                                                # Download the fanart variant
                                                filename_local = f"{session_id}_{variant_key}.jpg"
                                                local_path = f"/tmp/{filename_local}"
                                                
                                                try:
                                                    r = requests.get(image_url, auth=server['auth'], timeout=5)
                                                    r.raise_for_status()
                                                    with open(local_path, "wb") as f:
                                                        f.write(r.content)
                                                    downloaded[variant_key] = filename_local
                                                    print(f"[INFO] Downloaded {variant_key} from fallback path to {local_path}", flush=True)
                                                    break  # Success, exit fallback loop
                                                except Exception as e:
                                                    print(f"[DEBUG] Failed to download from fallback path: {e}", flush=True)
                                                    continue
                                            else:
                                                print(f"[DEBUG] Fallback path failed: {image_protocol_path}", flush=True)
                                    else:
                                        print(f"[DEBUG] Could not find artist folder in current file path", flush=True)
                                else:
                                    print(f"[DEBUG] Could not find Music in current file path", flush=True)
                            else:
                                print(f"[DEBUG] Current file is not an NFS path", flush=True)
                        else:
                            print(f"[DEBUG] Could not parse artist information path: {original_path}", flush=True)
                    
                    # Standard image protocol path handling
                    response = kodi_rpc("Files.PrepareDownload", {"path": variant_path})
                    if response and response.get("result") and not response.get("error"):
                        details = response.get("result", {}).get("details", {})
                        token = details.get("token")
                        path = details.get("path")
                        
                        if token:
                            # Extract the original path from the image:// protocol
                            original_path = urllib.parse.unquote(variant_path[len("image://"):])
                            if original_path.endswith("/"):
                                original_path = original_path[:-1]
                            basename = os.path.basename(original_path)
                            image_url = f"{server['host']}/vfs/{token}/{urllib.parse.quote(basename)}"
                        elif path:
                            image_url = f"{server['host']}/{path}"
                        else:
                            continue
                        
                        # Download the fanart variant
                        filename = f"{session_id}_{variant_key}.jpg"
                        local_path = f"/tmp/{filename}"
                        
                        try:
                            r = requests.get(image_url, auth=server['auth'], timeout=5)
                            r.raise_for_status()
                            with open(local_path, "wb") as f:
                                f.write(r.content)
                            downloaded[variant_key] = filename
                            print(f"[INFO] Downloaded {variant_key} to {local_path}", flush=True)
                        except Exception as e:
                            print(f"[ERROR] Failed to download {variant_key}: {e}", flush=True)
                    else:
                        print(f"[DEBUG] Failed to prepare download for {variant_key}: {response}", flush=True)
                elif variant_path.startswith("nfs://"):
                    # Direct NFS path
                    response = kodi_rpc("Files.PrepareDownload", {"path": variant_path})
                    if response and response.get("result") and not response.get("error"):
                        details = response.get("result", {}).get("details", {})
                        token = details.get("token")
                        path = details.get("path")
                        
                        if token:
                            basename = os.path.basename(variant_path)
                            image_url = f"{server['host']}/vfs/{token}/{urllib.parse.quote(basename)}"
                        elif path:
                            image_url = f"{server['host']}/{path}"
                        else:
                            continue
                        
                        # Download the fanart variant
                        filename = f"{session_id}_{variant_key}.jpg"
                        local_path = f"/tmp/{filename}"
                        
                        try:
                            r = requests.get(image_url, auth=server['auth'], timeout=5)
                            r.raise_for_status()
                            with open(local_path, "wb") as f:
                                f.write(r.content)
                            downloaded[variant_key] = filename
                            print(f"[INFO] Downloaded {variant_key} to {local_path}", flush=True)
                        except Exception as e:
                            print(f"[ERROR] Failed to download {variant_key}: {e}", flush=True)
                            
            except Exception as e:
                print(f"[ERROR] Failed to process fanart variant {variant_key}: {e}", flush=True)
    
    # Final debug logging
    final_fanart_count = len([k for k in downloaded.keys() if k.startswith(("fanart", "extrafanart"))])
    print(f"[DEBUG] Final downloaded fanart count: {final_fanart_count}", flush=True)
    print(f"[DEBUG] Downloaded fanart keys: {[k for k in downloaded.keys() if k.startswith(('fanart', 'extrafanart'))]}", flush=True)
    
    return downloaded

@app.route("/media/<filename>")
def serve_image(filename):
    path = f"/tmp/{filename}"
    if os.path.exists(path):
        return send_file(path, mimetype="image/jpeg")
    return "Image not found", 404

@app.route("/play-button.png")
def play_button():
    try:
        button_path = os.path.join(os.path.dirname(__file__), "play-button.png")
        if os.path.exists(button_path):
            return send_file(button_path, mimetype="image/png")
        else:
            print(f"[ERROR] Play button file not found at: {button_path}", flush=True)
            return "Play button not found", 404
    except Exception as e:
        print(f"[ERROR] Play button route error: {e}", flush=True)
        return "Play button error", 500

@app.route("/pause-button.png")
def pause_button():
    try:
        button_path = os.path.join(os.path.dirname(__file__), "pause-button.png")
        if os.path.exists(button_path):
            return send_file(button_path, mimetype="image/png")
        else:
            print(f"[ERROR] Pause button file not found at: {button_path}", flush=True)
            return "Pause button not found", 404
    except Exception as e:
        print(f"[ERROR] Pause button route error: {e}", flush=True)
        return "Pause button error", 500

# New route to serve static files like the IMDb icon
@app.route("/static/<filename>")
def serve_static(filename):
    return send_file(os.path.join(os.path.dirname(__file__), filename))

# Specific favicon route to ensure it works
@app.route("/favicon.ico")
def favicon():
    try:
        favicon_path = os.path.join(os.path.dirname(__file__), "favicon.ico")
        print(f"[DEBUG] Favicon path: {favicon_path}", flush=True)
        print(f"[DEBUG] Favicon exists: {os.path.exists(favicon_path)}", flush=True)
        if os.path.exists(favicon_path):
            return send_file(favicon_path, mimetype="image/x-icon")
        else:
            print(f"[ERROR] Favicon file not found at: {favicon_path}", flush=True)
            return "Favicon not found", 404
    except Exception as e:
        print(f"[ERROR] Favicon route error: {e}", flush=True)
        return "Favicon error", 500


@app.route("/nowplaying")
def now_playing():
    if request.args.get("json") == "1":
        active_response = kodi_rpc("Player.GetActivePlayers")
        active = active_response.get("result") if active_response else None
        if not active:
            return jsonify({"elapsed": 0, "duration": 0, "paused": True})
        player_id = active[0]["playerid"]
        progress_response = kodi_rpc("Player.GetProperties", {
            "playerid": player_id,
            "properties": ["time", "totaltime", "speed"]
        })
        progress = progress_response.get("result") if progress_response else {}
        t = progress.get("time", {})
        d = progress.get("totaltime", {})
        speed = progress.get("speed", 0)
        def to_secs(t): return t.get("hours", 0) * 3600 + t.get("minutes", 0) * 60 + t.get("seconds", 0)
        return jsonify({
            "elapsed": to_secs(t),
            "duration": to_secs(d),
            "paused": speed == 0
        })

    # Get active players - this is critical, so if it fails, show error
    try:
        active_response = kodi_rpc("Player.GetActivePlayers")
        active = active_response.get("result") if active_response else None
        if not active:
            return render_template_string(index())

        player_id = active[0]["playerid"]
        
        # Get current item - this is critical, so if it fails, show error
        try:
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
            print(f"[ERROR] Failed to get current item: {e}", flush=True)
            raise e  # This is critical, so re-raise
        
        # Get item type to know which API call to make
        playback_type = item.get("type", "unknown")
        
        # Initialize details with basic fallback structure
        details = {
            "album": {"title": item.get("album", ""), "year": item.get("year", "")},
            "artist": {"label": ", ".join(item.get("artist", [])) if item.get("artist") else "Unknown Artist"}
        }
        
        # Get enhanced details for episodes, movies, and songs
        print(f"[DEBUG] Playback type detected: {playback_type}", flush=True)
        print(f"[DEBUG] Available IDs - songid: {item.get('songid')}, albumid: {item.get('albumid')}, artistid: {item.get('artistid')}", flush=True)
        if playback_type == "episode":
            try:
                print(f"[DEBUG] Getting enhanced details for episode", flush=True)
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
                    print(f"[DEBUG] Enhanced episode details loaded", flush=True)
            except Exception as e:
                print(f"[WARNING] Failed to get enhanced episode details: {e}", flush=True)
                print(f"[DEBUG] Using basic item data for {playback_type}", flush=True)
        elif playback_type == "movie":
            try:
                print(f"[DEBUG] Getting enhanced details for movie", flush=True)
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
                    print(f"[DEBUG] Enhanced movie details loaded", flush=True)
            except Exception as e:
                print(f"[WARNING] Failed to get enhanced movie details: {e}", flush=True)
                print(f"[DEBUG] Using basic item data for {playback_type}", flush=True)
        elif playback_type == "song":
            try:
                print(f"[DEBUG] Getting enhanced details for song", flush=True)
                print(f"[DEBUG] Basic item ID: {item.get('id')}", flush=True)
                # Get song details using the basic item ID
                song_response = kodi_rpc("AudioLibrary.GetSongDetails", {
                    "songid": item.get("id"),
                    "properties": ["title", "album", "artist", "duration", "rating", "year", "genre", "fanart", "thumbnail", "albumid", "artistid", "bitrate", "channels", "samplerate", "bpm", "comment", "lyrics", "mood", "playcount", "track", "disc"]
                })
                if song_response and song_response.get("result"):
                    song_details = song_response["result"].get("songdetails", {})
                    details.update(song_details)
                    print(f"[DEBUG] Enhanced song details loaded", flush=True)
                
                # Get album details if we have albumid
                albumid = song_details.get("albumid")
                if albumid:
                    try:
                        album_response = kodi_rpc("AudioLibrary.GetAlbumDetails", {
                            "albumid": albumid,
                            "properties": ["title", "artist", "year", "rating", "fanart", "thumbnail", "description", "genre", "mood", "style", "theme", "albumduration", "playcount", "albumlabel", "compilation", "totaldiscs"]
                        })
                        if album_response and album_response.get("result"):
                            album_details = album_response["result"].get("albumdetails", {})
                            details["album"] = album_details
                            print(f"[DEBUG] Enhanced album details loaded", flush=True)
                    except Exception as e:
                        print(f"[WARNING] Failed to get album details: {e}", flush=True)
                
                # Get artist details if we have artistid
                artistid = song_details.get("artistid")
                if artistid:
                    # Handle artistid as array (take first one) or single value
                    print(f"[DEBUG] Original artistid: {artistid}, type: {type(artistid)}", flush=True)
                    if isinstance(artistid, list) and len(artistid) > 0:
                        artistid = artistid[0]
                        print(f"[DEBUG] Converted artistid to: {artistid}, type: {type(artistid)}", flush=True)
                    try:
                        artist_response = kodi_rpc("AudioLibrary.GetArtistDetails", {
                            "artistid": artistid,
                            "properties": ["fanart", "thumbnail", "description", "born", "formed", "died", "disbanded", "genre", "mood", "style", "yearsactive"]
                        })
                        if artist_response and artist_response.get("result"):
                            artist_details = artist_response["result"].get("artistdetails", {})
                            details["artist"] = artist_details
                            print(f"[DEBUG] Enhanced artist details loaded", flush=True)
                    except Exception as e:
                        print(f"[WARNING] Failed to get artist details: {e}", flush=True)
                
                # Ensure basic item data is preserved (but don't overwrite detailed album/artist objects)
                details.update({
                    "title": item.get("title", ""),
                    "year": item.get("year", "")
                })
                
            except Exception as e:
                print(f"[WARNING] Failed to get enhanced song details: {e}", flush=True)
                print(f"[DEBUG] Using basic item data for {playback_type}", flush=True)
        else:
            print(f"[DEBUG] Using basic item data for {playback_type}", flush=True)


        # Playback progress
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

        session_id = uuid.uuid4().hex
        
        # Try to download artwork, but don't fail if this breaks
        try:
            downloaded_art = prepare_and_download_art(item, session_id)
        except Exception as e:
            print(f"[WARNING] Artwork download failed, continuing without artwork: {e}", flush=True)
            downloaded_art = {}  # Empty artwork - page will still work

        # Prepare progress data
        progress_data = {
            "elapsed": elapsed,
            "duration": duration,
            "paused": paused
        }

        # Check if media type is unknown - if so, show fallback message
        from parser import infer_playback_type
        playback_type_from_parser = infer_playback_type(item)
        if playback_type_from_parser == "unknown":
            print(f"[INFO] Unknown media type detected, showing fallback message", flush=True)
            return render_template_string("""
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

        # Use the modular system to generate HTML
        html = route_media_display(item, session_id, downloaded_art, progress_data, details)
        return render_template_string(html)
    except Exception as e:
        print(f"[ERROR] Critical failure in now_playing route: {e}", flush=True)
        return render_template_string(index())

def generate_fallback_html(item, progress_data):
    """Generate basic HTML when the modular system fails"""
    title = item.get("title", "Unknown Title")
    artist = ", ".join(item.get("artist", [])) if item.get("artist") else "Unknown Artist"
    album = item.get("album", "")
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
                color: {'#ff6b6b' if paused else '#51cf66'};
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

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=6001)
