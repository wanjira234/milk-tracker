"""The notification bell: what needs each role's attention. Need TEST_DATABASE_URL."""
import os
from datetime import date, timedelta

import pytest

if not os.environ.get("TEST_DATABASE_URL"):
    pytest.skip("set TEST_DATABASE_URL to run DB tests", allow_module_level=True)

os.environ["DATABASE_URL"] = os.environ["TEST_DATABASE_URL"]

from src import accounts, db, notifications  # noqa: E402

TODAY = date(2026, 10, 22)


@pytest.fixture(autouse=True)
def clean():
    db._query("TRUNCATE contact_messages, alerts, vaccination_days, service_requests, sms_log, monthly_budgets, feed_logs, yield_logs, herd_log, feed_catalogue, farmers, users, routes RESTART IDENTITY CASCADE")


@pytest.fixture
def world():
    route_a, route_b = accounts.record_route("4A"), accounts.record_route("5B")
    vet = accounts.create_account("vet", "Dr Kibet", phone="0712345678")
    accounts.allocate_vet(route_a, vet)
    admin = accounts.create_account("admin", "Ann", email="ann@example.com", temp_password="longenough1")
    farm_a = db.add_farmer("Mama A", "+254700000001", "A Farm")
    farm_b = db.add_farmer("Mama B", "+254700000002", "B Farm")
    accounts.assign_route(farm_a, route_a)
    accounts.assign_route(farm_b, route_b)
    fa = accounts.create_account("farmer", "Mama A", phone="0700000011", farmer_id=farm_a)
    fb = accounts.create_account("farmer", "Mama B", phone="0700000012", farmer_id=farm_b)
    as_user = lambda uid: accounts.session_user(db.get_user(uid))  # noqa: E731
    return dict(route_a=route_a, route_b=route_b, vet=as_user(vet), admin=as_user(admin), fa=as_user(fa), fb=as_user(fb), farm_a=farm_a)


def texts(user):
    return [t for t, _ in notifications.for_user(user, TODAY)]


def test_an_alert_reaches_only_its_route_and_only_for_a_week(world):
    db.add_alert("outbreak", "Anthrax", "Keep animals in.", world["route_a"], world["admin"]["id"], TODAY + timedelta(days=30))
    assert any("Anthrax" in t for t in texts(world["fa"]))
    assert not any("Anthrax" in t for t in texts(world["fb"]))  # another route's farmer hears nothing
    db._query("UPDATE alerts SET created_at = %s", (TODAY - timedelta(days=9),))
    assert not any("Anthrax" in t for t in texts(world["fa"]))  # old news leaves the bell


def test_a_vaccination_day_shows_until_the_farm_books_it(world):
    day = db.add_vaccination_day("Rabies", TODAY + timedelta(days=3), world["route_a"], world["admin"]["id"])
    assert any("Rabies" in t for t in texts(world["fa"]))
    assert not any("Rabies" in t for t in texts(world["fb"]))
    far = db.add_vaccination_day("Anthrax", TODAY + timedelta(days=40), world["route_a"], world["admin"]["id"])
    assert not any("Anthrax" in t for t in texts(world["fa"])) and far
    db._query(
        "INSERT INTO service_requests (farmer_id, kind, preferred_date, vaccination_day_id, animals) VALUES (%s, 'vaccination', %s, %s, 2)",
        (world["farm_a"], TODAY, day),
    )
    assert not any("Rabies" in t for t in texts(world["fa"]))  # booked: no need to nag


def test_a_booked_visit_and_a_finished_visit_reach_the_farmer(world):
    qid = db.add_request(world["farm_a"], "sick", TODAY)
    db.update_request(qid, status="scheduled", scheduled_for=TODAY + timedelta(days=1))
    assert any("booked for" in t for t in texts(world["fa"]))
    db.update_request(qid, status="done", done_on=TODAY)
    assert any("was done on" in t for t in texts(world["fa"]))
    assert not any("booked for" in t for t in texts(world["fa"]))


def test_a_vet_sees_waiting_requests_and_todays_visits(world):
    assert texts(world["vet"]) == []
    q1 = db.add_request(world["farm_a"], "sick", TODAY)
    assert texts(world["vet"]) == ["1 request is waiting for a day."]
    db.update_request(q1, status="scheduled", scheduled_for=TODAY)
    assert texts(world["vet"]) == ["1 visit to do today."]


def test_a_head_admin_sees_signups_messages_and_late_requests_but_a_route_admin_sees_none(world):
    assert texts(world["admin"]) == []
    accounts.signup("farmer", "New Farmer", "new@example.com", "longenough1", "0700000099", "New Farm")
    db._query("INSERT INTO contact_messages (name, contact, message) VALUES ('J', 'x', 'hi')")
    db.add_request(world["farm_a"], "sick", TODAY - timedelta(days=2))
    got = texts(world["admin"])
    assert "1 signup waiting for approval." in got
    assert "1 Contact us message to read." in got
    assert any("still open past the day" in t for t in got)
    route_admin = dict(world["admin"], route_admin=True)
    assert notifications.for_user(route_admin, TODAY) == []


def test_the_bell_never_breaks_a_page(world, monkeypatch):
    monkeypatch.setattr(db, "requests_for_vet", lambda *a, **k: 1 / 0)
    assert notifications.for_user(world["vet"], TODAY) == []
