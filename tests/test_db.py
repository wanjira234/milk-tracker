"""DB layer tests. Run against TEST_DATABASE_URL only; they truncate tables."""
import os
from datetime import date

import pytest

if not os.environ.get("TEST_DATABASE_URL"):
    pytest.skip("set TEST_DATABASE_URL to run DB tests", allow_module_level=True)

os.environ["DATABASE_URL"] = os.environ["TEST_DATABASE_URL"]

from src import db  # noqa: E402


@pytest.fixture(autouse=True)
def clean():
    db._query("TRUNCATE sms_log, monthly_budgets, feed_logs, yield_logs, farmers RESTART IDENTITY CASCADE")


@pytest.fixture
def farmer():
    return db.add_farmer("Test Farmer", "+254700000001", "Test Farm", 6)


def test_add_farmer_is_idempotent_on_phone(farmer):
    again = db.add_farmer("Renamed", "+254700000001")
    assert again == farmer
    rows = db.list_farmers()
    assert len(rows) == 1
    assert rows[0]["name"] == "Renamed"
    assert rows[0]["farm_name"] == "Test Farm"  # not wiped by the None


def test_yield_upsert_overwrites_same_session(farmer):
    d = date(2026, 10, 1)
    db.upsert_yield(farmer, d, "morning", 10)
    db.upsert_yield(farmer, d, "morning", 12.5)
    db.upsert_yield(farmer, d, "evening", 7)
    rows = db.daily_yield(farmer, d, d)
    assert len(rows) == 1
    assert float(rows[0]["litres"]) == 19.5
    assert rows[0]["sessions"] == 2


def test_bad_session_rejected(farmer):
    with pytest.raises(Exception):
        db.upsert_yield(farmer, date(2026, 10, 1), "midnight", 5)


def test_daily_feed_groups_by_type(farmer):
    d = date(2026, 10, 1)
    db.add_feed(farmer, d, "dairy meal", 4, 240)
    db.add_feed(farmer, d, "dairy meal", 2, 120)
    db.add_feed(farmer, d, "napier", 30, 0)
    rows = {r["feed_type"]: r for r in db.daily_feed(farmer, d, d)}
    assert float(rows["dairy meal"]["kg"]) == 6
    assert float(rows["dairy meal"]["cost_kes"]) == 360
    assert float(rows["napier"]["kg"]) == 30


def test_month_spend_only_counts_that_month(farmer):
    db.add_feed(farmer, date(2026, 9, 30), "dairy meal", 5, 300)
    db.add_feed(farmer, date(2026, 10, 1), "dairy meal", 5, 310)
    db.add_feed(farmer, date(2026, 10, 31), "dairy meal", 5, 320)
    db.add_feed(farmer, date(2026, 11, 1), "dairy meal", 5, 330)
    assert float(db.month_feed_spend(farmer, date(2026, 10, 15))) == 630


def test_budget_roundtrip_normalises_to_month_start(farmer):
    assert db.get_budget(farmer, date(2026, 10, 20)) is None
    db.set_budget(farmer, date(2026, 10, 20), 15000)
    db.set_budget(farmer, date(2026, 10, 3), 16000)
    assert float(db.get_budget(farmer, date(2026, 10, 28))) == 16000


def test_log_sms(farmer):
    db.log_sms(farmer, "hello", status="sent", provider_ref="abc")
    row = db._query("SELECT * FROM sms_log", one=True)
    assert row["body"] == "hello" and row["status"] == "sent"


def test_monthly_feed_spend_groups_by_month_and_flags_uncosted(farmer):
    db.add_feed(farmer, date(2026, 8, 20), "dairy meal", 5, 300)
    db.add_feed(farmer, date(2026, 9, 5), "dairy meal", 5, 310)
    db.add_feed(farmer, date(2026, 9, 6), "hay", 5, None)
    db.add_feed(farmer, date(2026, 10, 2), "dairy meal", 5, 320)
    db.add_feed(farmer, date(2026, 10, 20), "dairy meal", 5, 999)  # after "today": excluded
    rows = {str(r["month"]): r for r in db.monthly_feed_spend(farmer, date(2026, 10, 9), months=1)}
    assert set(rows) == {"2026-09-01", "2026-10-01"}  # August is outside months=1
    assert float(rows["2026-10-01"]["spent"]) == 320
    assert float(rows["2026-09-01"]["spent"]) == 310
    assert rows["2026-09-01"]["entries"] == 2 and rows["2026-09-01"]["uncosted"] == 1
