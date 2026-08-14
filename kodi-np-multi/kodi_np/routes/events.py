"""Server-sent events for playback and overview snapshots."""
from __future__ import annotations

import json
import time

from flask import Blueprint, Response, request, stream_with_context

from kodi_np import config as _c
from kodi_np.cache import get_cache_entry
from kodi_np.overview import overview_fast_snapshot
from kodi_np.servers import get_active_server

bp = Blueprint("events", __name__)


def _playback_snapshot():
    active = get_active_server()
    server_id = active.get("id") if active else None
    entry = get_cache_entry(server_id) if server_id is not None else None
    return {
        "topic": "playback",
        "playing": bool((entry or {}).get("playing")),
        "paused": bool((entry or {}).get("paused")),
        "item_id": (entry or {}).get("item_id"),
        "title": (entry or {}).get("title"),
        "media_type": (entry or {}).get("media_type"),
        "error": bool((entry or {}).get("error")),
        "server_id": server_id,
    }


def _overview_snapshot():
    servers = []
    for server_id in sorted(_c.KODI_SERVERS.keys()):
        snap = overview_fast_snapshot(server_id)
        if snap is not None:
            servers.append(snap)
    return {"topic": "overview", "servers": servers}


@bp.route("/api/events")
def sse_events():
    topic = (request.args.get("topic") or "playback").strip().lower()
    if topic not in {"playback", "overview"}:
        topic = "playback"

    def generate():
        last = None
        idle_ticks = 0
        while True:
            try:
                payload = _overview_snapshot() if topic == "overview" else _playback_snapshot()
                encoded = json.dumps(payload, default=str, sort_keys=True)
            except Exception:
                encoded = last or json.dumps({"topic": topic, "error": True})
            if encoded != last:
                yield f"data: {encoded}\n\n"
                last = encoded
                idle_ticks = 0
            else:
                idle_ticks += 1
                if idle_ticks >= 5:
                    yield ": keepalive\n\n"
                    idle_ticks = 0
            time.sleep(2)

    return Response(
        stream_with_context(generate()),
        mimetype="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
            "Connection": "keep-alive",
        },
    )
