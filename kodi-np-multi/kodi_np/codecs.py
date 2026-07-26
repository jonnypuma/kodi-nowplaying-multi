"""Pretty-print Kodi video/audio/HDR codec labels for badge display."""
from __future__ import annotations

import re

_HDR_MAP = {
    "DOLBYVISION": "Dolby Vision",
    "HDR10PLUS": "HDR10+",
    "HDR10": "HDR10",
    "HLG": "HLG",
    "SDR": "SDR",
}

# Longer compound keys first so greedy whole-string match works.
_AUDIO_COMPOUND = {
    "TRUEHDATMOS": "TrueHD Atmos",
    "EAC3DDPATMOS": "DD+ Atmos",
    "EAC3ATMOS": "DD+ Atmos",
    "DDPATMOS": "DD+ Atmos",
    "DDPLUSATMOS": "DD+ Atmos",
    "DTSHDMA": "DTS-HD MA",
    "DTSHD": "DTS-HD",
    "DTSX": "DTS:X",
    "TRUEHD": "TrueHD",
    "EAC3": "DD+",
    "DDPLUS": "DD+",
    "DDP": "DD+",
    "AC3": "DD",
    "AAC": "AAC",
    "FLAC": "FLAC",
    "PCM": "PCM",
    "LPCM": "LPCM",
    "OPUS": "Opus",
    "VORBIS": "Vorbis",
    "MP3": "MP3",
    "WMA": "WMA",
    "ALAC": "ALAC",
    "DTS": "DTS",
    "ATMOS": "Atmos",
    "DD": "DD",
}

# Token lookup after stripping separators; synonyms collapse via same display label.
_AUDIO_TOKEN = {
    "TRUEHD": "TrueHD",
    "ATMOS": "Atmos",
    "DTSHDMA": "DTS-HD MA",
    "DTSHD": "DTS-HD",
    "DTSX": "DTS:X",
    "DTS": "DTS",
    "EAC3": "DD+",
    "EAC": "DD+",  # rare truncated
    "DDPLUS": "DD+",
    "DDP": "DD+",
    "DD": "DD",
    "AC3": "DD",
    "AAC": "AAC",
    "FLAC": "FLAC",
    "PCM": "PCM",
    "LPCM": "LPCM",
    "OPUS": "Opus",
    "VORBIS": "Vorbis",
    "MP3": "MP3",
    "WMA": "WMA",
    "ALAC": "ALAC",
}

_VIDEO_MAP = {
    "H264": "H.264",
    "AVC": "H.264",
    "X264": "H.264",
    "H265": "HEVC",
    "HEVC": "HEVC",
    "X265": "HEVC",
    "AV1": "AV1",
    "VP9": "VP9",
    "VP8": "VP8",
    "MPEG2": "MPEG-2",
    "MPEG4": "MPEG-4",
    "VC1": "VC-1",
    "WMV3": "VC-1",
    "AVS3": "AVS3",
    "AVS": "AVS",
}


def _norm_key(value: str) -> str:
    return re.sub(r"[^A-Za-z0-9+]", "", (value or "")).upper().replace("+", "PLUS")


def format_hdr_label(value: str) -> str:
    raw = (value or "").strip()
    if not raw:
        return "SDR"
    key = _norm_key(raw)
    # HDR10PLUS before HDR10 via exact map keys
    if key in _HDR_MAP:
        return _HDR_MAP[key]
    return (
        raw.replace("_", " ")
        .title()
        .replace("Hdr", "HDR")
        .replace("Sdr", "SDR")
        .replace("Hlg", "HLG")
        .replace("Dolbyvision", "Dolby Vision")
    )


def format_video_codec(value: str) -> str:
    raw = (value or "").strip()
    if not raw:
        return "Unknown"
    key = _norm_key(raw)
    if key in _VIDEO_MAP:
        return _VIDEO_MAP[key]
    # Keep common short codecs uppercase (e.g. "VC1" already mapped)
    if len(raw) <= 5 and raw.isalpha():
        return raw.upper()
    return raw.replace("_", " ")


def format_audio_codec(value: str) -> str:
    """Normalize Kodi AudioCodec strings (often multi-token, Title Case).

    Examples:
      Eac3 Ddp Atmos → DD+ Atmos
      TrueHD Atmos → TrueHD Atmos
      eac3 → DD+
    """
    raw = (value or "").strip()
    if not raw:
        return "Unknown"

    compound = _norm_key(raw)
    if compound in _AUDIO_COMPOUND:
        return _AUDIO_COMPOUND[compound]

    # Split on whitespace / punctuation but keep tokens
    parts = re.split(r"[\s_/|,;]+", raw)
    labels: list[str] = []
    seen: set[str] = set()
    for part in parts:
        if not part:
            continue
        key = _norm_key(part)
        # DD+ may arrive as "DD+" → norm becomes "DDPLUS"
        if key == "DDPLUS" or part.strip().upper() in ("DD+", "DDPLUS"):
            label = "DD+"
        else:
            label = _AUDIO_TOKEN.get(key)
            if label is None:
                # Unknown token: tidy casing lightly
                label = part.replace("_", " ")
                if label.isupper() or label.islower() or label.istitle():
                    # keep brand-ish tokens readable
                    if len(label) <= 4:
                        label = label.upper()
                    else:
                        label = label.title()
        if label in seen:
            continue
        # Prefer DD+ over DD if both somehow appear
        if label == "DD" and "DD+" in seen:
            continue
        if label == "DD+" and "DD" in seen:
            labels = [x if x != "DD" else "DD+" for x in labels]
            seen.discard("DD")
            seen.add("DD+")
            continue
        labels.append(label)
        seen.add(label)

    return " ".join(labels) if labels else raw.replace("_", " ").title()
