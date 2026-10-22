"""The demo accounts and data for the judges. Need TEST_DATABASE_URL."""
import os
from datetime import date

import pytest

if not os.environ.get("TEST_DATABASE_URL"):
    pytest.skip("set TEST_DATABASE_URL to run DB tests", allow_module_level=True)

os.environ["DATABASE_URL"] = os.environ["TEST_DATABASE_URL"]

from src import accounts, db, demo_seed, loader  # noqa: E402


@pytest.fixture(autouse=True)
def clean():
    db._query("TRUNCATE sms_log, monthly_budgets, feed_logs, yield_logs, herd_log, feed_catalogue, farmers, users, routes RESTART IDENTITY CASCADE")


def test_the_three_demo_logins_work_and_see_the_right_things():
    made = demo_seed.create_demo("demo-pass-123")
    assert set(made) == {demo_seed.ADMIN_EMAIL, demo_seed.VET_EMAIL, demo_seed.FARMER_EMAIL}
    users = {e: accounts.login_password(e, "demo-pass-123") for e in made}
    assert all(users.values()) and not any(u["must_change_password"] for u in users.values())
    farm = db.farmer_by_phone(demo_seed.DEMO_FARM_PHONE)
    for e in (demo_seed.ADMIN_EMAIL, demo_seed.VET_EMAIL, demo_seed.FARMER_EMAIL):
        assert [f["id"] for f in accounts.visible_farmers(accounts.session_user(users[e]))] == [farm["id"]]


def test_running_it_twice_changes_nothing_and_the_farm_has_enough_data_for_the_model():
    demo_seed.create_demo("demo-pass-123")
    assert demo_seed.create_demo("other-pass-456") == {}
    assert len(db.list_farmers()) == 1 and len(db.list_users()) == 3
    farm = db.farmer_by_phone(demo_seed.DEMO_FARM_PHONE)
    result = loader.assess_farmer(farm["id"], date.today())
    assert result["usable_days"] >= 14
