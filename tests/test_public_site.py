import os
import re

from src import public_site


def test_every_image_the_pages_use_exists():
    names = set(re.findall(r'IMG}([\w-]+\.jpg)|"([\w-]+\.jpg)"', open(public_site.__file__).read()))
    names = {a or b for a, b in names}
    assert names
    for n in names:
        assert os.path.exists(os.path.join("static", "img", n)), n


def test_hero_shows_photo_without_video(monkeypatch):
    monkeypatch.setattr(public_site, "HERO_VIDEO", "/nonexistent/hero.mp4")
    html = public_site._hero()
    assert "<video" not in html and "hero-farm.jpg" in html and 'alt="' in html
    assert 'data-goto="Sign up"' in html and 'data-goto="Log in"' in html


def test_hero_uses_video_when_present(monkeypatch, tmp_path):
    clip = tmp_path / "hero.mp4"
    clip.write_bytes(b"x")
    monkeypatch.setattr(public_site, "HERO_VIDEO", str(clip))
    html = public_site._hero()
    assert "<video" in html and "muted" in html and "aria-hidden" in html


def test_static_serving_is_on():
    assert "enableStaticServing = true" in open(".streamlit/config.toml").read()


def test_cards_flip_and_every_card_has_a_back():
    steps, roles = public_site._steps(), public_site._roles()
    assert steps.count('class="flipc"') == 3 and roles.count('class="flipc"') == 3
    for html in (steps, roles):
        assert html.count(" front\"") == html.count(" back\"") == 3
        assert 'tabindex="0"' in html and "aria-label=" in html  # reachable by keyboard and named for screen readers
    assert "flipc" in public_site.GOTO_JS and "data-tilt" in public_site._bento()


def test_click_handlers_are_built_in_the_main_page_so_they_survive_the_helper_frame_being_removed():
    js = public_site.GOTO_JS
    assert "P.Function" in js and "function install()" in js  # not left inside the tiny frame that Streamlit removes on a page change
    assert "var p=window,d=document" in js  # inside install, window/document are the main page's
