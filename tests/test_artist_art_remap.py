"""Unit tests for artist-folder artwork path remapping helpers."""
from kodi_np import art as art_mod
# These helpers live in art_music; kodi_np.art only re-exports them, so patching
# has to target the defining module or the function will not see it.
from kodi_np import art_music as art_music_mod


def test_art_path_basename_strips_image_protocol_and_slash():
    path = "image://nfs%3A%2F%2Fnas%2FMusic%2FArtist%2Fclearlogo.png/"
    assert art_mod._art_path_basename(path) == "clearlogo.png"


def test_music_artist_directory_from_nfs_song():
    song = "nfs://nas/share/Music/2 Unlimited/No Limit/01 - No Limit.flac"
    assert art_mod._music_artist_directory(song) == "nfs://nas/share/Music/2 Unlimited"


def test_needs_artist_media_remap_for_artist_information():
    assert art_mod._needs_artist_media_remap(
        "image://U%3A%5CKodi%5CArtistInformation%5CAURORA%5Cclearlogo.png/"
    )
    assert art_mod._needs_artist_media_remap(r"U:\Kodi\ArtistInformation\AURORA\clearlogo.png")
    assert not art_mod._needs_artist_media_remap(
        "nfs://nas/share/Music/AURORA/clearlogo.png"
    )


def test_remap_artist_art_to_song_tree():
    song = "nfs://nas/share/Music/AURORA/All My Demons/01.flac"
    art = r"image://U:\Kodi\ArtistInformation\AURORA\clearlogo.png/"
    assert (
        art_mod._remap_artist_art_to_song_tree(art, song)
        == "nfs://nas/share/Music/AURORA/clearlogo.png"
    )


def test_music_artist_directory_one_up_from_album():
    song = "nfs://nas/share/Music/AURORA/A Different Kind of Human - Step 2 (2019)/01.flac"
    assert art_mod._music_artist_directory(song) == "nfs://nas/share/Music/AURORA"


def test_prefer_music_artist_folder_art_sets_clearlogo(monkeypatch):
    art_map = {
        "clearlogo": r"image://U:\Kodi\ArtistInformation\AURORA\clearlogo.png/",
    }
    buckets = {"artist": {}}

    def fake_probe(artist_dir, stems):
        assert artist_dir.endswith("/AURORA")
        if "clearlogo" in stems:
            return f"{artist_dir}/clearlogo.png"
        return ""

    monkeypatch.setattr(art_music_mod, "_probe_artist_folder_art", fake_probe)
    song = "nfs://nas/share/Music/AURORA/Album/track.flac"
    art_music_mod.prefer_music_artist_folder_art(song, art_map, buckets=buckets, key_scope={})
    assert art_map["clearlogo"] == "nfs://nas/share/Music/AURORA/clearlogo.png"
    assert buckets["artist"]["clearlogo"] == art_map["clearlogo"]


def test_prefer_music_artist_folder_art_accepts_clearart_as_logo(monkeypatch):
    art_map = {}
    monkeypatch.setattr(
        art_music_mod,
        "_probe_artist_folder_art",
        lambda artist_dir, stems: f"{artist_dir}/clearart.png" if "clearart" in stems else "",
    )
    song = "nfs://nas/share/Music/AURORA/Album/track.flac"
    art_music_mod.prefer_music_artist_folder_art(song, art_map, buckets={}, key_scope={})
    assert art_map["clearlogo"] == "nfs://nas/share/Music/AURORA/clearart.png"
