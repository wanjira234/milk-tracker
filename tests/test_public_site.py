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
    assert "<video" not in html and "hero-cow.jpg" in html and 'alt="' in html
    assert 'data-goto="Sign up"' in html and 'data-goto="Log in"' in html


def test_hero_uses_video_when_present(monkeypatch, tmp_path):
    clip = tmp_path / "hero.mp4"
    clip.write_bytes(b"x")
    monkeypatch.setattr(public_site, "HERO_VIDEO", str(clip))
    html = public_site._hero()
    assert "<video" in html and "muted" in html and "aria-hidden" in html


def test_static_serving_is_on():
    assert "enableStaticServing = true" in open(".streamlit/config.toml").read()
