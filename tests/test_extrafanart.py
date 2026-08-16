"""Extrafanart directory parsing (regression cover for the 3.1.3 indentation bug)."""
from kodi_np.art import collect_extrafanart_variants


def test_main_fanart_maps_to_extrafanart_main():
    variants = collect_extrafanart_variants([
        {"file": "nfs://srv/movie/extrafanart/fanart.jpg"},
    ])
    assert variants == {"extrafanart_main": "nfs://srv/movie/extrafanart/fanart.jpg"}


def test_numbered_variants_get_their_own_keys():
    variants = collect_extrafanart_variants([
        {"file": "nfs://srv/movie/extrafanart/fanart1.jpg"},
        {"file": "nfs://srv/movie/extrafanart/fanart2.png"},
        {"file": "nfs://srv/movie/extrafanart/fanart3.jpeg"},
    ])
    assert variants == {
        "extrafanart_fanart1": "nfs://srv/movie/extrafanart/fanart1.jpg",
        "extrafanart_fanart2": "nfs://srv/movie/extrafanart/fanart2.png",
        "extrafanart_fanart3": "nfs://srv/movie/extrafanart/fanart3.jpeg",
    }


def test_leading_non_image_entry_does_not_abort_the_scan():
    """A subfolder first used to raise NameError and kill the whole listing."""
    variants = collect_extrafanart_variants([
        {"file": "nfs://srv/movie/extrafanart/thumbs", "filetype": "directory"},
        {"file": "nfs://srv/movie/extrafanart/fanart2.jpg"},
    ])
    assert variants == {"extrafanart_fanart2": "nfs://srv/movie/extrafanart/fanart2.jpg"}


def test_trailing_non_image_entry_does_not_reuse_previous_filename():
    """A .nfo after an image used to re-register the image under a stale key."""
    variants = collect_extrafanart_variants([
        {"file": "nfs://srv/movie/extrafanart/fanart2.jpg"},
        {"file": "nfs://srv/movie/extrafanart/movie.nfo"},
    ])
    assert variants == {"extrafanart_fanart2": "nfs://srv/movie/extrafanart/fanart2.jpg"}


def test_ignores_malformed_entries():
    assert collect_extrafanart_variants([]) == {}
    assert collect_extrafanart_variants(None) == {}
    assert collect_extrafanart_variants(["not-a-dict", {}, {"file": ""}]) == {}
