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


@pytest.fixture(autouse=True)
def no_owner_lockout_database(monkeypatch):
    """These tests run without a database; the shared owner lockout is tested against one in test_accounts_db."""
    monkeypatch.setattr("src.accounts.owner_locked_message", lambda *a, **k: None)
    monkeypatch.setattr("src.accounts.owner_login_failed", lambda *a, **k: None)
    monkeypatch.setattr("src.accounts.owner_login_ok", lambda *a, **k: None)


@pytest.mark.parametrize("page", PAGES)
def test_every_page_offers_the_logins_and_never_touches_the_database(monkeypatch, page):
    monkeypatch.setenv("APP_PASSWORD", "open-sesame")
    at = run(page)
    assert not at.exception  # a database call would have raised
    assert {"Home", "Log in", "Sign up"} <= {t.label for t in at.tabs}  # the public site
    assert {"Email & password", "SMS code", "Owner password"} <= {t.label for t in at.tabs}  # the ways to log in
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
        [b for b in at.button if b.label == "Log in"][-1].click().run()
        assert "user" not in at.session_state
    at = at.run()
    assert "Too many" in at.error[0].value and not at.text_input


def test_right_owner_password_logs_in_as_admin(monkeypatch):
    monkeypatch.setenv("APP_PASSWORD", "open-sesame")
    for fn in ("list_farmers", "list_routes", "list_users", "list_pending_users"):
        monkeypatch.setattr(f"src.db.{fn}", lambda *a, **k: [])  # stand-in for the database
    at = run("app.py")
    key(at, "text_input", "owner_password").set_value("open-sesame")
    [b for b in at.button if b.label == "Log in"][-1].click().run()
    assert not at.exception and at.session_state["user"]["role"] == "admin"
    assert at.expander[0].label == "Add a farmer without a login"  # the admin overview is showing
    assert at.metric[0].label == "Farmers"
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


def test_each_role_gets_its_own_menu_and_every_page_is_reachable_by_someone():
    from src.auth import MENU, menu_for

    labels = lambda r: [label for _, label in menu_for(r)]  # noqa: E731
    assert "Ask the vet" in labels("farmer") and "Admin" not in labels("farmer") and "My day" not in labels("farmer")
    assert "My day" in labels("vet") and "Ask the vet" not in labels("vet") and "Admin" not in labels("vet")
    assert "Admin" in labels("admin") and "Attendance" in labels("admin") and "My day" not in labels("admin")
    assert labels("farmer")[:3] == ["Home", "Feed log", "Dashboard"] and labels("farmer")[-1] == "Account"  # daily jobs first
    farm_pages = {"Dashboard", "Feed log", "Budget", "Farm setup", "Cows"}
    assert not farm_pages & set(labels("admin")), "an admin sees a farm only by logging in as that farmer"
    assert farm_pages <= set(labels("farmer")) and not farm_pages & set(labels("vet"))
    for role in MENU:  # alerts and vaccination are for everyone, and every link points at a real file
        assert {"Alerts", "Vaccination", "Home", "Account"} <= set(labels(role))
        assert all(os.path.exists(os.path.join(ROOT, path)) for path, _ in menu_for(role))
    reachable = {path for role in MENU for path, _ in menu_for(role)}
    assert reachable == {"app.py"} | set(glob.glob("pages/*.py")), "a page exists that no role can reach, or a menu link is dead"
    assert menu_for("stranger") == []


def test_the_sign_in_screen_hides_the_page_menu_and_a_logged_in_page_does_not(monkeypatch):
    from src.auth import LOGGED_OUT_CSS

    monkeypatch.setenv("APP_PASSWORD", "open-sesame")
    at = run("app.py")
    assert any(LOGGED_OUT_CSS in m.value for m in at.markdown)
    assert any("Maziwa" in m.value and 'data-scroll="about"' in m.value for m in at.markdown)  # our own top bar
    in_ = AppTest.from_file(os.path.join(ROOT, "app.py"), default_timeout=20)
    in_.session_state["user"] = {"id": None, "role": "admin", "name": "Owner", "farmer_id": None, "must_change_password": False}
    monkeypatch.setattr("src.accounts.visible_farmers", lambda u: [])
    in_.run()
    assert not any(LOGGED_OUT_CSS in m.value for m in in_.markdown)


@pytest.mark.parametrize("role", ["admin", "vet"])
def test_farm_pages_are_closed_to_the_admin_and_the_vet(monkeypatch, role):
    monkeypatch.setattr("src.db.list_farmers", lambda *a, **k: [])
    for path in ("pages/1_dashboard.py", "pages/2_feed_log.py", "pages/3_budget.py", "pages/4_farm_setup.py", "pages/5_cows.py"):
        at = AppTest.from_file(os.path.join(ROOT, path), default_timeout=20)
        at.session_state["user"] = {"id": None, "role": role, "name": "X", "farmer_id": None, "must_change_password": False}
        at = at.run()
        assert not at.exception and not at.metric and not at.number_input, path
