"""The nowplaying templates share CSS and JS through partials rather than copies.

These render through Jinja rather than reading the files, so a partial that is
renamed, moved, or dropped from one template fails here instead of silently
shipping an unstyled or half-wired page.
"""
import re

import pytest

PAGES = ("movie_nowplaying.html", "episode_nowplaying.html", "music_nowplaying.html")

CSS_PARTIALS = {
    "partials/_marquee.css.html": (".marquee {", ".marquee-text.shimmer .letter", "@keyframes marqueeGlow"),
    "partials/_side_panel_controls.css.html": (".toggle {", ".toggle__input:checked", ".slider-value {"),
    "partials/_side_panel_dropdown.css.html": (".section-dropdown a {", ".section-dropdown a.current-server"),
    "partials/_side_panel_sections.css.html": (".side-panel-section {", ".side-panel-row {"),
}

JS_PARTIALS = {
    "partials/_save_preference.js.html": ("async function savePreference(",),
    "partials/_playback_button.js.html": ("function getOrCreateButton(",),
    "partials/_server_management.js.html": ("Server Management Functions",),
    "partials/_playback_polling.js.html": ("function startPlaybackPolling(",),
    "partials/_server_switch.js.html": ("async function switchServerFromDropdown(",),
    "partials/_playback_config.js.html": ("const PLAYBACK_POLL_MS",),
}

ALL_PARTIALS = {**CSS_PARTIALS, **JS_PARTIALS}


@pytest.fixture
def jinja_env(app_module):
    return app_module.app.jinja_env


def source_of(env, name):
    return env.loader.get_source(env, name)[0]


def biggest_block(html, tag):
    blocks = re.findall(rf"<{tag}[^>]*>(.*?)</{tag}>", html, re.S | re.I)
    return max(blocks, key=len) if blocks else ""


@pytest.mark.parametrize("page", PAGES)
def test_page_includes_every_shared_partial(jinja_env, page):
    included = set(re.findall(r'\{%\s*include\s+"(partials/[^"]+)"\s*%\}', source_of(jinja_env, page)))
    assert included == set(ALL_PARTIALS), f"{page} include set drifted"


@pytest.mark.parametrize("page", PAGES)
def test_rendered_page_contains_shared_css(jinja_env, page):
    css = biggest_block(jinja_env.get_template(page).render(), "style")
    assert css, f"{page} lost its inline style block"
    for partial, selectors in CSS_PARTIALS.items():
        for selector in selectors:
            assert selector in css, f"{page} is missing {selector} from {partial}"


@pytest.mark.parametrize("page", PAGES)
def test_rendered_page_contains_shared_js(jinja_env, page):
    js = biggest_block(jinja_env.get_template(page).render(), "script")
    assert js, f"{page} lost its inline script block"
    for partial, markers in JS_PARTIALS.items():
        for marker in markers:
            assert marker in js, f"{page} is missing {marker} from {partial}"


@pytest.mark.parametrize("partial", sorted(ALL_PARTIALS))
def test_partials_are_self_contained(jinja_env, partial):
    source = source_of(jinja_env, partial)
    assert source.count("{") == source.count("}")
    # A partial is spliced verbatim into three pages, so it must not depend on
    # any one page's template context.
    assert "{%" not in source and "{{" not in source
