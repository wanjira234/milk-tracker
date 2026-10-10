"""Loader tests against a real Postgres. Need TEST_DATABASE_URL; they truncate tables."""
import os
from datetime import date

import numpy as np
import pytest

if not os.environ.get("TEST_DATABASE_URL"):
    pytest.skip("set TEST_DATABASE_URL to run DB tests", allow_module_level=True)

os.environ["DATABASE_URL"] = os.environ["TEST_DATABASE_URL"]

from src import db  # noqa: E402
from src.ingestion.manual_entry import (  # noqa: E402
    record_catalogue_item,
    record_cows_in_milk,
    record_milk_price,
)
from src.loader import assess_farmer, describe  # noqa: E402
from tests.sim_farm import make_farm  # noqa: E402

TODAY = date(2026, 9, 30)  # the simulated farm covers 2026-08-01 .. 2026-09-29


@pytest.fixture(autouse=True)
def clean():
    db._query("TRUNCATE sms_log, monthly_budgets, feed_logs, yield_logs, herd_log, feed_catalogue, farmers RESTART IDENTITY CASCADE")


def seed(*, price=True, cows=True, catalogue=True, **farm_kw):
    """Write a simulated farm into the database through the same functions the app uses."""
    daily, feed_kg, _ = make_farm(np.random.default_rng(3), **{"effect": 1.0, "levels": (0, 4, 8, 12), **farm_kw})
    fid = db.add_farmer("Sim Farmer", "+254700000001", "Sim Farm", 6)
    if price:
        record_milk_price(fid, 50)
    if cows:
        record_cows_in_milk(fid, date(2026, 8, 1), 6)
    if catalogue:
        record_catalogue_item(fid, "dairy meal", "bag", 70, 350)
    yields = [
        (fid, day.date(), session, round(float(row.litres) * share, 2))
        for day, row in daily.iterrows()
        for session, share in (("morning", 0.4), ("afternoon", 0.25), ("evening", 0.35))
    ]
    feeds = [
        (fid, day.date(), name, float(kg))
        for day, row in feed_kg.iterrows()
        for name, kg in row.items()
        if kg > 0
    ]
    with db.get_conn() as conn, conn.cursor() as cur:  # one connection: this is test setup, not app code
        cur.executemany("INSERT INTO yield_logs (farmer_id, log_date, session, litres) VALUES (%s, %s, %s, %s)", yields)
        cur.executemany("INSERT INTO feed_logs (farmer_id, log_date, feed_type, kg) VALUES (%s, %s, %s, %s)", feeds)
    return fid


def test_a_set_up_farm_gets_advice_from_the_real_database():
    fid = seed()
    r = assess_farmer(fid, today=TODAY)
    d = r["decision"]
    assert d["kind"] == "advice", describe(r)
    assert d["advice"]["feed"] == "dairy meal" and d["advice"]["verdict"] == "increase"
    assert d["advice"]["step_kg"] <= 0.10 * r["recent_kg"]["dairy meal"] + 1e-9
    assert r["costs"]["dairy meal"] == pytest.approx(5.0)  # catalogue: KES 350 for a 70 kg bag


def test_a_farm_that_is_not_set_up_is_asked_for_the_basics():
    r = assess_farmer(seed(price=False, cows=False, catalogue=False), today=TODAY)
    codes = [n["code"] for n in r["decision"]["nudges"]]
    assert r["decision"]["kind"] == "nudge" and r["decision"]["advice"] is None
    assert "no_cows" in codes and "no_price" in codes


def test_a_brand_new_farmer_with_no_records_does_not_crash():
    fid = db.add_farmer("New", "+254700000009")
    r = assess_farmer(fid, today=TODAY)
    assert r["decision"]["kind"] == "nudge" and r["usable_days"] == 0


def test_farms_do_not_see_each_others_data():
    seed()
    other = db.add_farmer("Other", "+254700000002")
    r = assess_farmer(other, today=TODAY)
    assert r["decision"]["kind"] == "nudge" and r["effects"] == []


def test_todays_half_logged_data_is_left_out():
    fid = seed()
    before = describe(assess_farmer(fid, today=TODAY))
    db.upsert_yield(fid, TODAY, "morning", 400)           # one milking so far today
    db.add_feed(fid, TODAY, "dairy meal", 500, None)      # a feed entry today
    assert describe(assess_farmer(fid, today=TODAY)) == before


def test_the_price_in_the_catalogue_beats_what_was_paid_before():
    fid = seed(catalogue=False)
    db._query("UPDATE feed_logs SET cost_kes = kg * 30 WHERE feed_type = 'dairy meal'")  # paid KES 30 per kg
    assert assess_farmer(fid, today=TODAY)["costs"]["dairy meal"] == pytest.approx(30.0)
    record_catalogue_item(fid, "dairy meal", "bag", 70, 350)  # today's price: KES 5 per kg
    assert assess_farmer(fid, today=TODAY)["costs"]["dairy meal"] == pytest.approx(5.0)


def test_describe_is_readable():
    text = describe(assess_farmer(seed(), today=TODAY))
    assert text.startswith("Window ") and "Decision: advice" in text and "dairy meal" in text
