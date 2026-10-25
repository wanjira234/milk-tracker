"""Optional two-factor login against a real Postgres. Need TEST_DATABASE_URL."""
import os
from datetime import datetime, timedelta, timezone

import pytest

if not os.environ.get("TEST_DATABASE_URL"):
    pytest.skip("set TEST_DATABASE_URL to run DB tests", allow_module_level=True)

os.environ["DATABASE_URL"] = os.environ["TEST_DATABASE_URL"]

from src import accounts, db, totp  # noqa: E402

NOW = datetime(2026, 10, 22, 12, 0, tzinfo=timezone.utc)


@pytest.fixture(autouse=True)
def clean():
    db._query("TRUNCATE sms_log, monthly_budgets, feed_logs, yield_logs, herd_log, feed_catalogue, farmers, users, routes RESTART IDENTITY CASCADE")


@pytest.fixture
def uid():
    return accounts.create_account("admin", "Ann", email="ann@example.com", temp_password="longenough1")


def code_now(uid, at=NOW):
    return totp.code_for(db.get_totp(uid)["secret"], totp.step_at(at.timestamp()))


def enable(uid, at=NOW):
    accounts.begin_totp_setup(uid)
    assert accounts.confirm_totp_setup(uid, code_now(uid, at), now=at)


def test_off_by_default_and_a_wrong_first_code_does_not_turn_it_on(uid):
    assert not accounts.totp_required(uid)
    accounts.begin_totp_setup(uid)
    assert not accounts.confirm_totp_setup(uid, "000000", now=NOW) and not accounts.totp_required(uid)


def test_setup_then_login_needs_a_fresh_valid_code(uid):
    enable(uid)
    assert accounts.totp_required(uid)
    later = NOW + timedelta(seconds=60)
    assert not accounts.verify_totp_login(uid, "123456", now=later)
    assert accounts.verify_totp_login(uid, code_now(uid, later), now=later)


def test_a_code_cannot_be_used_twice(uid):
    enable(uid)
    later = NOW + timedelta(seconds=60)
    c = code_now(uid, later)
    assert accounts.verify_totp_login(uid, c, now=later)
    assert not accounts.verify_totp_login(uid, c, now=later)


def test_five_wrong_codes_lock_the_account_and_the_password_step_respects_it(uid):
    enable(uid)
    for _ in range(5):
        assert not accounts.verify_totp_login(uid, "000000", now=NOW)
    assert accounts.login_password("ann@example.com", "longenough1", now=NOW) is None  # locked: password alone no longer works
    assert accounts.locked_message_for_id(uid, now=NOW)
    after = NOW + timedelta(minutes=16)
    assert accounts.login_password("ann@example.com", "longenough1", now=after)


def test_starting_over_with_the_password_does_not_reset_the_wrong_code_count(uid):
    enable(uid)
    for _ in range(4):
        assert not accounts.verify_totp_login(uid, "000000", now=NOW)
        assert accounts.login_password("ann@example.com", "longenough1", now=NOW)  # right password again
    assert not accounts.verify_totp_login(uid, "000000", now=NOW)  # fifth wrong code still locks
    assert accounts.login_password("ann@example.com", "longenough1", now=NOW) is None


def test_turning_it_off_needs_a_current_code_and_an_admin_can_reset_it(uid):
    enable(uid)
    later = NOW + timedelta(seconds=60)
    assert not accounts.disable_totp(uid, "000000", now=later) and accounts.totp_required(uid)
    assert accounts.disable_totp(uid, code_now(uid, later), now=later) and not accounts.totp_required(uid)
    enable(uid, later + timedelta(seconds=120))
    accounts.admin_reset_totp({"role": "admin", "id": None}, uid)
    assert not accounts.totp_required(uid)


def test_a_farmer_cannot_reset_someone_elses_two_factor(uid):
    enable(uid)
    with pytest.raises(ValueError):
        accounts.admin_reset_totp({"role": "farmer", "id": 99}, uid)
    assert accounts.totp_required(uid)


def test_the_app_still_works_if_the_two_factor_columns_do_not_exist_yet(uid, monkeypatch):
    def boom(*a, **k):
        import psycopg2.errors

        raise psycopg2.errors.UndefinedColumn("no such column")

    monkeypatch.setattr(db, "_query", boom)
    assert db.get_totp(uid) is None and not accounts.totp_required(uid)
    assert not accounts.totp_available(uid)
    with pytest.raises(ValueError, match="not switched on"):
        accounts.begin_totp_setup(uid)  # a plain message, not a database traceback


def test_login_screen_asks_for_the_code_after_the_password_and_lets_the_right_code_in(uid, monkeypatch):
    from streamlit.testing.v1 import AppTest

    monkeypatch.setenv("APP_PASSWORD", "owner-pass-xyz")
    db.update_user(uid, must_change_password=False)
    enable(uid, datetime.now(timezone.utc) - timedelta(seconds=90))  # an older step, so the current code is fresh
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    at = AppTest.from_file(os.path.join(root, "app.py"), default_timeout=30).run()
    next(w for w in at.text_input if w.key == "login_email").set_value("ann@example.com")
    next(w for w in at.text_input if w.key == "login_password").set_value("longenough1")
    next(b for b in at.button if b.label == "Log in").click()
    at.run()
    assert "pending_2fa" in at.session_state and "user" not in at.session_state  # password alone is not enough
    next(w for w in at.text_input if w.key == "second_factor_code").set_value("000000")
    next(b for b in at.button if b.label == "Verify").click()
    at.run()
    assert "user" not in at.session_state
    next(w for w in at.text_input if w.key == "second_factor_code").set_value(code_now(uid, datetime.now(timezone.utc)))
    next(b for b in at.button if b.label == "Verify").click()
    at.run()
    assert at.session_state["user"]["id"] == uid and "pending_2fa" not in at.session_state
