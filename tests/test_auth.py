"""The password screen. No database needed: a locked page must never reach the database."""
import glob
import os

import pytest
from streamlit.testing.v1 import AppTest

from src.auth import MAX_WRONG, password_ok

PAGES = ["app.py"] + sorted(glob.glob("pages/*.py"))
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


@pytest.fixture(autouse=True)
def no_real_database(monkeypatch):
    monkeypatch.setenv("DATABASE_URL", "postgresql://nobody:x@127.0.0.1:1/none")  # any DB call would raise
    monkeypatch.delenv("APP_PASSWORD", raising=False)


def run(page):
    return AppTest.from_file(os.path.join(ROOT, page), default_timeout=20).run()


def test_password_check():
    assert password_ok("secret", "secret")
    assert not password_ok("Secret", "secret") and not password_ok("", "secret")
    assert not password_ok("anything", "") and not password_ok("", "")


@pytest.mark.parametrize("page", PAGES)
def test_with_no_password_set_every_page_stays_locked(page):
    at = run(page)
    assert not at.exception and at.error and "locked" in at.error[0].value
    assert not at.text_input  # nothing to type into, and no data shown


@pytest.mark.parametrize("page", PAGES)
def test_every_page_asks_for_the_password_and_never_touches_the_database(monkeypatch, page):
    monkeypatch.setenv("APP_PASSWORD", "open-sesame")
    at = run(page)
    assert not at.exception  # a database call would have raised
    assert at.text_input[0].label == "Password"


def test_wrong_password_is_refused_and_locks_after_too_many_tries(monkeypatch):
    monkeypatch.setenv("APP_PASSWORD", "open-sesame")
    monkeypatch.setattr("time.sleep", lambda s: None)
    at = run("app.py")
    for _ in range(MAX_WRONG):
        at.text_input[0].set_value("nope")
        at.button[0].click().run()
        assert not at.session_state["logged_in"] if "logged_in" in at.session_state else True  # never let in
    at = at.run()
    assert "Too many" in at.error[0].value and not at.text_input


def test_right_password_logs_in(monkeypatch):
    monkeypatch.setenv("APP_PASSWORD", "open-sesame")
    monkeypatch.setattr("src.db.list_farmers", lambda *a, **k: [])  # stand-in for the database
    at = run("app.py")
    at.text_input[0].set_value("open-sesame")
    at.button[0].click().run()
    assert not at.exception and not [t for t in at.text_input if t.label == "Password"]
    assert at.expander[0].label == "Add a farmer"  # the real home page is showing
    assert any(b.label == "Log out" for b in at.sidebar.button)
