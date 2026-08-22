from pathlib import Path


def test_cast_strip_css_keeps_horizontal_row():
    css = (
        Path(__file__).resolve().parents[1]
        / "kodi-np-multi"
        / "nowplaying-common.css"
    ).read_text(encoding="utf-8")
    assert ".cast-heading {" in css
    heading_block = css.split(".cast-heading {", 1)[1].split("}", 1)[0]
    assert "text-transform: uppercase" in heading_block
    row_block = css.split(".cast-row {", 1)[1].split("}", 1)[0]
    assert "display: flex" in row_block
    assert "flex-direction: row" in row_block
    assert "flex-wrap: nowrap" in row_block
    for chunk in css.split(".badge.live-badge {")[1:]:
        after_rule = chunk.split("}", 1)[1].lstrip()
        assert not after_rule.startswith("font-size"), (
            "orphaned declarations after .badge.live-badge would swallow .cast-row"
        )


def test_nowplaying_runtime_is_shared():
    js = (Path(__file__).resolve().parents[1] / "kodi-np-multi" / "nowplaying-common.js").read_text(encoding="utf-8")
    assert "window.NowPlayingRuntime" in js
    assert "startClock:" in js
    assert "startPlaybackMonitor:" in js
    assert "/api/events?topic=playback" in js


def test_templates_boot_shared_runtime():
    root = Path(__file__).resolve().parents[1] / "kodi-np-multi" / "templates"
    for name in ("movie_nowplaying.html", "episode_nowplaying.html", "music_nowplaying.html"):
        html = (root / name).read_text(encoding="utf-8")
        assert "NowPlayingRuntime.startClock" in html
        assert "NowPlayingRuntime.startPlaybackMonitor" in html
        assert "up_next_html" in html


def test_overview_has_auto_switch_toggle():
    html = (
        Path(__file__).resolve().parents[1]
        / "kodi-np-multi"
        / "templates"
        / "overview.html"
    ).read_text(encoding="utf-8")
    assert "autoSwitchToggle" in html
    assert "Auto-switch to playing" in html
    assert "addServerForm" in html
    assert "/api/events?topic=overview" in html
    assert "backoff_remaining" in html


def test_idle_page_does_not_fade_on_transient_or_error_polls():
    html = (
        Path(__file__).resolve().parents[1]
        / "kodi-np-multi"
        / "templates"
        / "index.html"
    ).read_text(encoding="utf-8")
    assert "data.transient_idle === true" in html
    assert "cancelPlaybackRedirect" in html
    assert "playbackRedirecting" in html
    assert "body.page-enter" in html
    assert "animation: fadeIn 1.5s ease;" not in html.split("body.page-enter", 1)[0]


def test_loading_page_navigates_instead_of_document_write():
    html = (
        Path(__file__).resolve().parents[1]
        / "kodi-np-multi"
        / "templates"
        / "loading.html"
    ).read_text(encoding="utf-8")
    assert "document.write" not in html
    assert "window.location.replace('/nowplaying')" in html or 'window.location.replace(path)' in html
    assert "data.idle" in html
    assert "goTo(data.idle ? '/' : '/nowplaying')" in html


def test_idle_page_polls_immediately():
    html = (
        Path(__file__).resolve().parents[1]
        / "kodi-np-multi"
        / "templates"
        / "index.html"
    ).read_text(encoding="utf-8")
    assert "checkPlaybackChange();" in html
    assert "setInterval(checkPlaybackChange, PLAYBACK_POLL_MS)" in html
