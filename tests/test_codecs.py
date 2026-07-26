"""Tests for pretty-printed codec / HDR badge labels."""
from kodi_np.codecs import format_audio_codec, format_hdr_label, format_video_codec


def test_format_audio_collapses_eac3_ddp_atmos():
    assert format_audio_codec("Eac3 Ddp Atmos") == "DD+ Atmos"
    assert format_audio_codec("eac3 ddp atmos") == "DD+ Atmos"
    assert format_audio_codec("EAC3") == "DD+"
    assert format_audio_codec("DDP") == "DD+"
    assert format_audio_codec("DD+") == "DD+"


def test_format_audio_truehd_atmos_and_dts():
    assert format_audio_codec("TrueHD Atmos") == "TrueHD Atmos"
    assert format_audio_codec("TRUEHDATMOS") == "TrueHD Atmos"
    assert format_audio_codec("dtshd_ma") == "DTS-HD MA"
    assert format_audio_codec("DTS:X") == "DTS:X"
    assert format_audio_codec("ac3") == "DD"
    assert format_audio_codec("flac") == "FLAC"


def test_format_hdr_dolby_vision():
    assert format_hdr_label("dolbyvision") == "Dolby Vision"
    assert format_hdr_label("DOLBYVISION") == "Dolby Vision"
    assert format_hdr_label("hdr10+") == "HDR10+"
    assert format_hdr_label("hdr10") == "HDR10"
    assert format_hdr_label("") == "SDR"


def test_format_video_codec():
    assert format_video_codec("h264") == "H.264"
    assert format_video_codec("hevc") == "HEVC"
    assert format_video_codec("h265") == "HEVC"
    assert format_video_codec("av1") == "AV1"
    assert format_video_codec("mpeg2") == "MPEG-2"
