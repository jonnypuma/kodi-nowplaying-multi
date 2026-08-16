"""Streaming behaviour of /api/events (3.1.9)."""
import json


def _first_frame(response):
    """Pull one frame off the stream without draining the infinite generator."""
    try:
        chunk = next(iter(response.response))
    finally:
        response.close()
    return chunk.decode("utf-8") if isinstance(chunk, bytes) else chunk


def test_playback_stream_sets_sse_headers(client):
    response = client.get("/api/events?topic=playback")
    try:
        assert response.status_code == 200
        assert response.mimetype == "text/event-stream"
        assert response.headers["Cache-Control"] == "no-cache"
        assert response.headers["X-Accel-Buffering"] == "no"
    finally:
        response.close()


def test_playback_stream_emits_a_playback_frame(client):
    response = client.get("/api/events?topic=playback")
    frame = _first_frame(response)
    assert frame.startswith("data: ")
    payload = json.loads(frame[len("data: "):].strip())
    assert payload["topic"] == "playback"
    assert "playing" in payload
    assert "server_id" in payload


def test_overview_stream_emits_an_overview_frame(client, app_module):
    app_module.KODI_SERVERS = {
        1: {"id": 1, "host": "http://10.0.0.1:8080", "ip": "10.0.0.1", "label": "", "auth": None},
    }
    response = client.get("/api/events?topic=overview")
    frame = _first_frame(response)
    payload = json.loads(frame[len("data: "):].strip())
    assert payload["topic"] == "overview"
    assert isinstance(payload["servers"], list)


def test_unknown_topic_falls_back_to_playback(client):
    response = client.get("/api/events?topic=nonsense")
    frame = _first_frame(response)
    payload = json.loads(frame[len("data: "):].strip())
    assert payload["topic"] == "playback"


def test_playback_snapshot_survives_a_missing_server(app_module):
    from kodi_np.routes.events import _playback_snapshot

    app_module.KODI_SERVERS = {}
    with app_module.app.test_request_context("/api/events"):
        snapshot = _playback_snapshot()
    assert snapshot["topic"] == "playback"
    assert snapshot["playing"] is False
