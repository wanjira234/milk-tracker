"""Feed purchases, counts and the forecast against real Postgres. Need TEST_DATABASE_URL."""
import os
from datetime import date, timedelta

import psycopg2
import pytest

if not os.environ.get("TEST_DATABASE_URL"):
    pytest.skip("set TEST_DATABASE_URL to run DB tests", allow_module_level=True)

os.environ["DATABASE_URL"] = os.environ["TEST_DATABASE_URL"]

from src import accounts, db, ledger, stock  # noqa: E402

TODAY = date(2026, 11, 3)


@pytest.fixture(autouse=True)
def clean():
    db._query("TRUNCATE feed_stock_counts, feed_purchases, charge_payments, charges, feed_logs, feed_catalogue, farmers, users "
              "RESTART IDENTITY CASCADE")


@pytest.fixture
def world():
    farm_a, farm_b = db.add_farmer("Mama A", "+254700000001", "A Farm"), db.add_farmer("Mama B", "+254700000002", "B Farm")
    user_a = accounts.session_user(db.get_user(accounts.create_account("farmer", "Mama A", phone="0700000001", farmer_id=farm_a)))
    user_b = accounts.session_user(db.get_user(accounts.create_account("farmer", "Mama B", phone="0700000002", farmer_id=farm_b)))
    napier = db.upsert_catalogue_item(farm_a, "napier", "truck", 3000, 5000)
    other = db.upsert_catalogue_item(farm_b, "napier", "truck", 3000, 5000)
    return dict(farm_a=farm_a, farm_b=farm_b, user_a=user_a, user_b=user_b, napier=napier, other=other)


def test_a_priced_purchase_is_also_a_feed_charge_on_the_money_page(world):
    u, f = world["user_a"], world["farm_a"]
    pid = stock.record_purchase(u, f, world["napier"], "1", TODAY, supplier="Kamau transport", terms="credit", today=TODAY)
    (p,) = db.feed_purchases(f)
    assert p["id"] == pid and float(p["kg"]) == 3000 and float(p["cost_kes"]) == 5000
    c = db.get_charge(p["charge_id"])
    assert c["category"] == "feed" and float(c["amount_kes"]) == 5000 and c["terms"] == "credit"
    assert c["provider_name"] == "Kamau transport" and c["description"] == "1 truck napier"


def test_half_a_truck_at_a_price_paid_now(world):
    u, f = world["user_a"], world["farm_a"]
    stock.record_purchase(u, f, world["napier"], "0.5", TODAY, supplier="Kamau", price="2,800", terms="paid", method="mpesa",
                          today=TODAY)
    (p,) = db.feed_purchases(f)
    c = db.get_charge(p["charge_id"])
    assert float(p["kg"]) == 1500 and float(c["amount_kes"]) == 2800 and float(c["paid_kes"]) == 2800


def test_free_feed_needs_no_supplier_and_makes_no_charge(world):
    stock.record_purchase(world["user_a"], world["farm_a"], world["napier"], "1", TODAY, price="0", today=TODAY)
    (p,) = db.feed_purchases(world["farm_a"])
    assert p["charge_id"] is None and db.charges_for_farm(world["farm_a"]) == []


def test_a_bad_charge_saves_no_purchase(world):
    with pytest.raises(ValueError, match="who it was from"):
        stock.record_purchase(world["user_a"], world["farm_a"], world["napier"], "1", TODAY, today=TODAY)
    assert db.feed_purchases(world["farm_a"]) == []


def test_stock_is_only_recorded_for_your_own_farm_and_feeds(world):
    for who, item in ((world["user_b"], world["napier"]), (world["user_a"], world["other"])):
        with pytest.raises(ValueError, match="own farm|farm setup"):
            stock.record_purchase(who, world["farm_a"], item, "1", TODAY, price="0", today=TODAY)
    with pytest.raises(ValueError, match="farm setup"):
        stock.record_count(world["user_a"], world["farm_a"], world["other"], TODAY, "0", today=TODAY)
    db.retire_catalogue_item(world["napier"], world["farm_b"])  # another farm's id: nothing happens
    assert len(db.list_catalogue(world["farm_a"])) == 1
    db.retire_catalogue_item(world["napier"], world["farm_a"])
    with pytest.raises(ValueError, match="farm setup"):
        stock.record_purchase(world["user_a"], world["farm_a"], world["napier"], "1", TODAY, price="0", today=TODAY)


def test_the_database_refuses_a_purchase_of_another_farms_feed(world):
    with pytest.raises(psycopg2.IntegrityError):
        db.add_feed_purchase({"farmer_id": world["farm_a"], "catalogue_id": world["other"], "purchased_on": TODAY,
                              "units": 1, "kg": 3000, "cost_kes": 0})


def test_input_checks(world):
    u, f, n = world["user_a"], world["farm_a"], world["napier"]
    for units, why in (("0", "more than 0"), ("-1", "negative"), ("lots", "a number"), ("20000", "too large")):
        with pytest.raises(ValueError, match=why):
            stock.record_purchase(u, f, n, units, TODAY, price="0", today=TODAY)
    for d, why in ((TODAY + timedelta(days=1), "future"), (TODAY - timedelta(days=61), "last 60 days")):
        with pytest.raises(ValueError, match=why):
            stock.record_count(u, f, n, d, "0", today=TODAY)
    for days, why in (("x", "whole number"), (61, "between")):
        with pytest.raises(ValueError, match=why):
            stock.set_warning_days(u, f, n, days)


def test_the_forecast_end_to_end_from_trucks_and_a_finish(world):
    u, f, n = world["user_a"], world["farm_a"], world["napier"]
    stock.record_purchase(u, f, n, "1", TODAY - timedelta(days=30), price="0", today=TODAY)
    stock.record_count(u, f, n, TODAY - timedelta(days=20), "0", today=TODAY)       # lasted 10 days
    stock.record_purchase(u, f, n, "1", TODAY - timedelta(days=20), price="0", today=TODAY)
    stock.record_count(u, f, n, TODAY - timedelta(days=20), "0", today=TODAY)       # same day again: replaced, not doubled
    stock.set_warning_days(u, f, n, 12)
    (s,) = stock.farm_stock(f, TODAY)
    assert s["rate_from"] == "last load" and s["daily_kg"] == 300 and s["days_left"] == 10 and s["low"]
    assert [r["name"] for r in stock.running_low(f, TODAY)] == ["napier"]


def test_feed_logged_in_plain_kg_counts_for_the_catalogue_item_of_that_name(world):
    u, f, n = world["user_a"], world["farm_a"], world["napier"]
    stock.record_purchase(u, f, n, "1", TODAY - timedelta(days=5), price="0", today=TODAY)
    for k in range(1, 6):
        db.add_feed(f, TODAY - timedelta(days=k), "napier", 200)                    # plain kg, no catalogue id
    (s,) = stock.farm_stock(f, TODAY)
    assert s["on_hand_kg"] == 3000 - 5 * 200 and s["rate_from"] == "feed log" and s["daily_kg"] == 200


def test_a_feed_purchase_replaces_the_feed_log_cost_on_the_statement(world):
    u, f = world["user_a"], world["farm_a"]
    db.add_feed(f, TODAY, "napier", 500, cost_kes=800)
    start = TODAY.replace(day=1)
    before = ledger.statement(0, None, db.month_feed_spend(f, start), db.charges_for_farm(f, start, TODAY), [], TODAY)
    assert before["feed_from_log"] and before["total_costs"] == 800
    stock.record_purchase(u, f, world["napier"], "1", TODAY, supplier="Kamau", terms="paid", method="cash", today=TODAY)
    after = ledger.statement(0, None, db.month_feed_spend(f, start), db.charges_for_farm(f, start, TODAY), [], TODAY)
    assert not after["feed_from_log"] and after["total_costs"] == 5000


def test_deleting_a_farm_with_paid_purchases_removes_everything(world):
    stock.record_purchase(world["user_a"], world["farm_a"], world["napier"], "1", TODAY, supplier="Kamau", terms="paid",
                          method="cash", today=TODAY)
    db.delete_farm(world["farm_a"])
    assert db._query("SELECT COUNT(*) AS n FROM feed_purchases", one=True)["n"] == 0
    assert db._query("SELECT COUNT(*) AS n FROM charges", one=True)["n"] == 0
