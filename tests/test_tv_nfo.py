"""Tests for TV show / season NFO helpers."""
from kodi_np.tv_nfo import (
    format_season_plot_heading,
    named_seasons_from_nfo_text,
    plot_from_nfo_text,
    season_nfo_candidate_paths,
    show_root_from_episode_file,
    tagline_from_nfo_text,
    tvshow_nfo_candidate_paths,
)

SAMPLE_TVSHOW_NFO = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<tvshow>
  <tagline>To live, you need something to die for.</tagline>
  <namedseason number="0">season_0.0</namedseason>
  <namedseason number="1">season_1.0</namedseason>
  <namedseason number="2">season_2.0</namedseason>
</tvshow>
"""

SAMPLE_SEASON_NFO = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<season>
  <plot>Season plot text here.</plot>
</season>
"""


def test_show_root_from_episode_file():
    ep = "nfs://192.168.0.1/media/TV/Silo/Season 2/S02E01.mkv"
    assert show_root_from_episode_file(ep) == "nfs://192.168.0.1/media/TV/Silo"


def test_season_nfo_candidates_prefers_season_folder():
    ep = "nfs://host/media/Show/Season 2/S02E01.mkv"
    paths = season_nfo_candidate_paths(ep, 2)
    assert paths[0] == "nfs://host/media/Show/Season 2/season.nfo"
    assert "nfs://host/media/Show/season02.nfo" in paths


def test_tvshow_nfo_candidates():
    ep = "nfs://host/media/Show/Season 1/S01E01.mkv"
    paths = tvshow_nfo_candidate_paths(ep, "Silo")
    assert paths[0] == "nfs://host/media/Show/tvshow.nfo"
    assert "nfs://host/media/Show/Silo.nfo" in paths


def test_parse_tagline_and_named_seasons():
    assert tagline_from_nfo_text(SAMPLE_TVSHOW_NFO) == "To live, you need something to die for."
    assert named_seasons_from_nfo_text(SAMPLE_TVSHOW_NFO) == {
        0: "season_0.0",
        1: "season_1.0",
        2: "season_2.0",
    }


def test_parse_season_plot():
    assert plot_from_nfo_text(SAMPLE_SEASON_NFO) == "Season plot text here."


def test_format_season_plot_heading_modes():
    named = {1: "season_1.0", 2: "season_2.0"}
    assert format_season_plot_heading(1, named, "number_and_named") == "Season 1 season_1.0 Plot"
    assert format_season_plot_heading(1, named, "named_only") == "Season season_1.0 Plot"
    assert format_season_plot_heading(3, named, "named_only") == "Season 3 Plot"
    assert format_season_plot_heading(2, named, "number_and_named") == "Season 2 season_2.0 Plot"


def test_read_text_file_via_kodi_uses_plain_vfs_path(monkeypatch):
    from kodi_np import config as cfg
    from kodi_np.tv_nfo import read_text_file_via_kodi

    cfg.KODI_SERVERS[9] = {"id": 9, "host": "http://kodi.test", "auth": None}
    calls = []

    def fake_rpc(method, params=None, server_id=None):
        calls.append((method, params, server_id))
        if method == "Files.PrepareDownload":
            return {
                "result": {
                    "details": {"token": "abc123", "path": "vfs/abc123/tvshow.nfo"},
                }
            }
        return {}

    class FakeResp:
        content = SAMPLE_TVSHOW_NFO.encode("utf-8")

        def raise_for_status(self):
            return None

    monkeypatch.setattr("kodi_np.tv_nfo.kodi_rpc", fake_rpc)
    monkeypatch.setattr("kodi_np.tv_nfo.requests.get", lambda url, **kwargs: FakeResp())

    text = read_text_file_via_kodi("nfs://host/media/Silo/tvshow.nfo", server_id=9)
    assert "To live, you need something to die for." in text
    assert calls[0][0] == "Files.PrepareDownload"
    assert calls[0][1]["path"] == "nfs://host/media/Silo/tvshow.nfo"
    assert calls[0][2] == 9


def test_season_id_for_lookup(monkeypatch):
    from kodi_np.tv_nfo import _season_id_for

    def fake_rpc(method, params=None, server_id=None):
        assert method == "VideoLibrary.GetSeasons"
        return {
            "result": {
                "seasons": [
                    {"season": 2, "seasonid": 42},
                    {"season": 3, "seasonid": 99},
                ]
            }
        }

    monkeypatch.setattr("kodi_np.tv_nfo.kodi_rpc", fake_rpc)
    assert _season_id_for(2507, 3, server_id=2) == 99
    assert _season_id_for(2507, 1, server_id=2) is None
