"""The demo accounts and data for the judges. Need TEST_DATABASE_URL."""
import os
from datetime import date, timedelta

import pytest

if not os.environ.get("TEST_DATABASE_URL"):
    pytest.skip("set TEST_DATABASE_URL to run DB tests", allow_module_level=True)

os.environ["DATABASE_URL"] = os.environ["TEST_DATABASE_URL"]

from src import accounts, db, demo_seed, loader  # noqa: E402
from src.ingestion import manual_entry as me  # noqa: E402


@pytest.fixture(autouse=True)
def clean():
    db._query("TRUNCATE sms_log, monthly_budgets, feed_logs, yield_logs, herd_log, feed_catalogue, farmers, users, routes RESTART IDENTITY CASCADE")


def test_the_four_demo_logins_work_and_see_the_right_things():
    made = demo_seed.create_demo("demo-pass-123")
    assert set(made) == {demo_seed.ADMIN_EMAIL, demo_seed.VET_EMAIL, demo_seed.FARMER_EMAIL, demo_seed.FRESH_EMAIL}
    users = {e: accounts.login_password(e, "demo-pass-123") for e in made}
    assert all(users.values()) and not any(u["must_change_password"] for u in users.values())
    farm = db.farmer_by_phone(demo_seed.DEMO_FARM_PHONE)
    fresh = db.farmer_by_phone(demo_seed.FRESH_FARM_PHONE)
    both = sorted([farm["id"], fresh["id"]])
    for e in (demo_seed.ADMIN_EMAIL, demo_seed.VET_EMAIL):
        assert sorted(f["id"] for f in accounts.visible_farmers(accounts.session_user(users[e]))) == both
    assert [f["id"] for f in accounts.visible_farmers(accounts.session_user(users[demo_seed.FARMER_EMAIL]))] == [farm["id"]]
    assert [f["id"] for f in accounts.visible_farmers(accounts.session_user(users[demo_seed.FRESH_EMAIL]))] == [fresh["id"]]


def test_running_it_twice_changes_nothing_and_the_farm_has_enough_data_for_the_model():
    demo_seed.create_demo("demo-pass-123")
    assert demo_seed.create_demo("other-pass-456") == {}
    assert len(db.list_farmers()) == 2 and len(db.list_users()) == 4
    farm = db.farmer_by_phone(demo_seed.DEMO_FARM_PHONE)
    result = loader.assess_farmer(farm["id"], date.today())
    assert result["usable_days"] >= 14


def test_the_seed_command_asks_first_and_writes_nothing_unless_told_to(capsys):
    assert demo_seed.main(ask=lambda prompt: "no") == 1
    assert db.list_users() == [] and "Cancelled" in capsys.readouterr().out
    assert demo_seed.main(ask=lambda prompt: " Demo ") == 0
    assert len(db.list_users()) == 4
    out = capsys.readouterr().out
    assert "localhost" in out and "milk" not in out.split("database at:")[1].split("\n")[0]  # host shown, no password


def _fresh():
    return db.farmer_by_phone(demo_seed.FRESH_FARM_PHONE)["id"]


def test_the_fresh_farm_is_one_logged_day_short_and_yesterday_unlocks_the_advice():
    demo_seed.create_demo("demo-pass-123")
    fid = _fresh()
    before = loader.assess_farmer(fid, date.today())
    assert before["usable_days"] == 13 and before["decision"]["kind"] == "nudge"
    yesterday = date.today() - timedelta(days=1)
    assert not db.daily_yield(fid, yesterday, yesterday)  # the judge fills this day in
    for session, litres in (("morning", 31), ("afternoon", 14), ("evening", 24)):
        me.record_yield(fid, yesterday, session, litres)
    me.record_feed(fid, yesterday, "dairy meal", 6.0, cost_kes=300)
    me.record_feed(fid, yesterday, "napier", 60, cost_kes=300)
    after = loader.assess_farmer(fid, date.today())
    assert after["usable_days"] == 14
    assert next(e for e in after["effects"] if e["feed"] == "dairy meal")["status"] in ("clear", "unclear")  # no longer 'too few days'


def test_the_reset_command_puts_the_fresh_farm_back_and_leaves_the_other_farm_alone():
    demo_seed.create_demo("demo-pass-123")
    fid, other = _fresh(), db.farmer_by_phone(demo_seed.DEMO_FARM_PHONE)["id"]
    start, end = date.today() - timedelta(days=60), date.today()
    n_other = len(db.daily_yield(other, start, end))
    yesterday = date.today() - timedelta(days=1)
    me.record_yield(fid, yesterday, "morning", 20)
    assert demo_seed.reset_fresh_farm() == fid
    assert not db.daily_yield(fid, yesterday, yesterday)
    assert loader.assess_farmer(fid, date.today())["usable_days"] == 13
    assert len(db.daily_yield(other, start, end)) == n_other


def test_reset_asks_first_and_says_so_when_there_is_no_fresh_farm_yet(capsys):
    assert demo_seed.main(ask=lambda p: "no", argv=["--reset-fresh"]) == 1 and "Cancelled" in capsys.readouterr().out
    assert demo_seed.main(ask=lambda p: "demo", argv=["--reset-fresh"]) == 0 and "does not exist yet" in capsys.readouterr().out
