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


def key(at, kind, k):
    return next(w for w in getattr(at, kind) if w.key == k)


@pytest.fixture(autouse=True)
def no_admin_phone(monkeypatch):
    monkeypatch.delenv("ADMIN_PHONE", raising=False)


@pytest.mark.parametrize("page", PAGES)
def test_every_page_offers_the_logins_and_never_touches_the_database(monkeypatch, page):
    monkeypatch.setenv("APP_PASSWORD", "open-sesame")
    at = run(page)
    assert not at.exception  # a database call would have raised
    assert [t.label for t in at.tabs] == ["SMS code", "Email & password", "Sign up", "Owner password"]
    assert key(at, "text_input", "owner_password")


@pytest.mark.parametrize("page", PAGES)
def test_a_page_opened_directly_shows_nothing_without_login(monkeypatch, page):
    monkeypatch.setenv("APP_PASSWORD", "open-sesame")
    at = run(page)
    assert not at.metric and not at.dataframe and "user" not in at.session_state


def test_wrong_owner_password_is_refused_and_locks_after_too_many_tries(monkeypatch):
    monkeypatch.setenv("APP_PASSWORD", "open-sesame")
    monkeypatch.setattr("time.sleep", lambda s: None)
    at = run("app.py")
    for _ in range(MAX_WRONG):
        key(at, "text_input", "owner_password").set_value("nope")
        at.button[-1].click().run()
        assert "user" not in at.session_state
    at = at.run()
    assert "Too many" in at.error[0].value and not at.text_input


def test_right_owner_password_logs_in_as_admin(monkeypatch):
    monkeypatch.setenv("APP_PASSWORD", "open-sesame")
    monkeypatch.setattr("src.db.list_farmers", lambda *a, **k: [])  # stand-in for the database
    at = run("app.py")
    key(at, "text_input", "owner_password").set_value("open-sesame")
    at.button[-1].click().run()
    assert not at.exception and at.session_state["user"]["role"] == "admin"
    assert at.expander[0].label == "Add a farmer"  # the real home page is showing
    assert any(b.label == "Log out" for b in at.sidebar.button)


def test_a_farmer_cannot_open_the_admin_page_or_add_farmers(monkeypatch):
    monkeypatch.setenv("APP_PASSWORD", "x")
    monkeypatch.setattr("src.accounts.visible_farmers", lambda u: [])
    farmer = {"id": 5, "role": "farmer", "name": "F", "farmer_id": 9, "must_change_password": False}
    at = AppTest.from_file(os.path.join(ROOT, "pages/7_admin.py"), default_timeout=20)
    at.session_state["user"] = farmer
    at.run()
    assert at.error and "not available" in at.error[0].value
    at = AppTest.from_file(os.path.join(ROOT, "app.py"), default_timeout=20)
    at.session_state["user"] = farmer
    at.run()
    assert not at.exception and not at.expander  # no "Add a farmer"
    assert at.info and "No farm is linked" in at.info[0].value


def test_a_temporary_password_must_be_changed_before_anything_else(monkeypatch):
    monkeypatch.setenv("APP_PASSWORD", "x")
    at = AppTest.from_file(os.path.join(ROOT, "app.py"), default_timeout=20)
    at.session_state["user"] = {"id": 5, "role": "farmer", "name": "F", "farmer_id": 9, "must_change_password": True}
    at.run()
    assert not at.exception and at.title[0].value == "Choose your own password"
    assert not at.metric


def test_each_role_sees_only_its_own_pages_in_the_menu():
    from src.auth import ALL_PAGES, hide_other_pages_css

    farmer, vet, admin = (hide_other_pages_css(r) for r in ("farmer", "vet", "admin"))
    assert '"/admin"' in farmer and '"/my_day"' in farmer and '"/ask_the_vet"' not in farmer
    assert '"/ask_the_vet"' in vet and '"/my_day"' not in vet and '"/admin"' in vet
    assert '"/attendance"' not in admin and '"/my_day"' in admin and '"/ask_the_vet"' in admin
    assert hide_other_pages_css("stranger") == ""  # unknown role: change nothing (the pages still refuse)
    assert ALL_PAGES >= {"admin", "my_day", "ask_the_vet", "attendance"}
