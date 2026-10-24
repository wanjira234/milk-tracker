"""Vaccination days: posting, booking, the vet's sheet and cancelling. Need TEST_DATABASE_URL."""
import os
from datetime import date, timedelta

import pytest

if not os.environ.get("TEST_DATABASE_URL"):
    pytest.skip("set TEST_DATABASE_URL to run DB tests", allow_module_level=True)

os.environ["DATABASE_URL"] = os.environ["TEST_DATABASE_URL"]

from src import accounts, db, services, vaccinations  # noqa: E402

TODAY = date(2026, 10, 24)
DAY = TODAY + timedelta(days=5)


@pytest.fixture(autouse=True)
def clean():
    db._query("TRUNCATE sms_log, alerts, vaccination_days, monthly_budgets, feed_logs, yield_logs, herd_log, feed_catalogue, farmers, users, routes RESTART IDENTITY CASCADE")


@pytest.fixture
def world():
    r4a, r5b = accounts.record_route("4A"), accounts.record_route("5B")
    as_user = lambda uid: accounts.session_user(db.get_user(uid))  # noqa: E731
    vet_a = as_user(accounts.create_account("vet", "Dr Kibet", phone="0712345678"))
    vet_b = as_user(accounts.create_account("vet", "Dr Achieng", phone="0722222222"))
    admin = as_user(accounts.create_account("admin", "Fresha Admin", phone="0733333333"))
    accounts.allocate_vet(r4a, vet_a["id"])
    accounts.allocate_vet(r5b, vet_b["id"])
    fa, fa2, fb = db.add_farmer("A1", "+254700000001", "A1 Farm"), db.add_farmer("A2", "+254700000002", "A2 Farm"), db.add_farmer("B1", "+254700000003")
    for f, r in ((fa, r4a), (fa2, r4a), (fb, r5b)):
        accounts.assign_route(f, r)
    return dict(r4a=r4a, r5b=r5b, vet_a=vet_a, vet_b=vet_b, admin=admin, fa=fa, fa2=fa2, fb=fb)


def post(w, who="admin", route="r4a", **kw):
    args = dict(vaccine="Foot and mouth", day=DAY, place="Tigoni market", today=TODAY)
    return vaccinations.post_day(w[who], route_id=w.get(route) if route else None, **(args | kw))


# --- posting -------------------------------------------------------------------------------------


def test_who_may_post_for_which_routes(world):
    assert post(world) and post(world, route=None) and post(world, who="vet_a")
    with pytest.raises(ValueError, match="your routes"):
        post(world, who="vet_a", route="r5b")
    with pytest.raises(ValueError, match="only for their own routes"):
        post(world, who="vet_a", route=None)
    farmer = {"id": 99, "role": "farmer", "farmer_id": world["fa"]}
    with pytest.raises(ValueError, match="only an admin or a vet"):
        vaccinations.post_day(farmer, "X", DAY, today=TODAY)


def test_post_validation(world):
    for kw, why in (
        (dict(vaccine=" "), "enter the vaccine"), (dict(vaccine="x" * 41), "too long"), (dict(day=TODAY - timedelta(days=1)), "past"),
        (dict(day=TODAY + timedelta(days=90)), "within the next"), (dict(place="x" * 101), "too long"), (dict(notes="x" * 201), "too long"),
    ):
        with pytest.raises(ValueError, match=why):
            post(world, **kw)
    with pytest.raises(ValueError, match="your routes"):
        vaccinations.post_day(world["admin"], "X", DAY, route_id=9999, today=TODAY)


def test_posting_creates_a_notice_for_the_route_unless_told_not_to(world):
    post(world)
    (a,) = db.list_alerts(TODAY)
    assert a["kind"] == "notice" and a["route_id"] == world["r4a"] and "Foot and mouth vaccination" in a["title"]
    assert "Tigoni market" in a["body"] and a["expires_on"] == DAY and a["sms_sent_at"] is None  # not texted until confirmed
    post(world, announce=False, vaccine="Anthrax")
    assert len(db.list_alerts(TODAY)) == 1


# --- seeing and booking --------------------------------------------------------------------------


def test_farmers_see_only_days_for_their_route_and_all_routes(world):
    mine, theirs, everyone = post(world), post(world, route="r5b", vaccine="Lumpy skin"), post(world, route=None, vaccine="Rabies")
    farmer = lambda f: {"id": 1, "role": "farmer", "farmer_id": f}  # noqa: E731
    vaccines = lambda u: sorted(d["vaccine"] for d in vaccinations.days_for(u, TODAY))  # noqa: E731
    assert vaccines(farmer(world["fa"])) == ["Foot and mouth", "Rabies"]
    assert vaccines(farmer(world["fb"])) == ["Lumpy skin", "Rabies"]
    assert vaccines(world["vet_a"]) == ["Foot and mouth", "Rabies"] and len(vaccinations.days_for(world["admin"], TODAY)) == 3
    assert vaccinations.days_for(world["admin"], DAY + timedelta(days=1)) == []  # past days drop off
    assert mine and theirs and everyone


def test_booking_becomes_a_scheduled_visit_with_the_doses(world):
    day_id = post(world)
    rid = vaccinations.book(world["fa"], day_id, 6, today=TODAY)
    q = db.get_request(rid)
    assert q["kind"] == "vaccination" and q["status"] == "scheduled" and q["scheduled_for"] == DAY
    assert q["animals"] == 6 and q["vaccine"] == "Foot and mouth" and q["vet_name"] == "Dr Kibet"
    assert vaccinations.my_booking(world["fa"], day_id)["id"] == rid and vaccinations.my_booking(world["fa2"], day_id) is None


def test_the_vet_day_sheet_adds_up_the_doses_across_farms(world):
    day_id = post(world)
    vaccinations.book(world["fa"], day_id, 6, today=TODAY)
    vaccinations.book(world["fa2"], day_id, 4, today=TODAY)
    sheet = services.day_sheet(world["vet_a"], DAY)
    assert sheet["total"] == 2 and len(sheet["farms"]) == 2 and sheet["carry"] == ["Foot and mouth: 10 doses"]
    assert services.day_sheet(world["vet_b"], DAY)["total"] == 0
    # and the admin's attendance view counts them as booked visits for that day
    a = next(v for v in services.attendance(DAY)["vets"] if v["vet"] == "Dr Kibet")
    assert a["booked_today"] == 2 and len(a["to_do_today"]) == 2


def test_the_vet_completes_a_vaccination_visit_with_notes(world):
    day_id = post(world)
    rid = vaccinations.book(world["fa"], day_id, 3, today=TODAY)
    services.complete_request(rid, world["vet_a"], notes="All three done", today=DAY)
    q = db.get_request(rid)
    assert q["status"] == "done" and q["vet_notes"] == "All three done"
    assert services.carry_list([dict(kind="vaccination", vaccine="Rabies", animals=1)]) == ["Rabies: 1 dose"]


def test_booking_rules(world):
    day_id, other = post(world), post(world, route="r5b", vaccine="Lumpy skin")
    with pytest.raises(ValueError, match="not for your route"):
        vaccinations.book(world["fa"], other, 2, today=TODAY)
    for bad, why in ((0, "between 1 and"), (201, "between 1 and"), ("lots", "how many"), (None, "how many")):
        with pytest.raises(ValueError, match=why):
            vaccinations.book(world["fa"], day_id, bad, today=TODAY)
    with pytest.raises(ValueError, match="already passed"):
        vaccinations.book(world["fa"], day_id, 2, today=DAY + timedelta(days=1))
    with pytest.raises(ValueError, match="not open"):
        vaccinations.book(world["fa"], 9999, 2, today=TODAY)
    vaccinations.book(world["fa"], day_id, 2, today=TODAY)
    with pytest.raises(ValueError, match="already booked"):
        vaccinations.book(world["fa"], day_id, 3, today=TODAY)


def test_a_cancelled_booking_can_be_rebooked_with_a_new_number(world):
    day_id = post(world)
    rid = vaccinations.book(world["fa"], day_id, 2, today=TODAY)
    services.cancel_request(rid, world["fa"])
    vaccinations.book(world["fa"], day_id, 5, today=TODAY)
    assert vaccinations.my_booking(world["fa"], day_id)["animals"] == 5
    assert db.get_vaccination_day(day_id)["animals"] == 5  # the cancelled one is not counted


def test_cancelling_a_day_cancels_open_bookings_but_keeps_done_ones(world):
    day_id = post(world)
    done = vaccinations.book(world["fa"], day_id, 2, today=TODAY)
    open_one = vaccinations.book(world["fa2"], day_id, 3, today=TODAY)
    services.complete_request(done, world["vet_a"], today=DAY)
    with pytest.raises(ValueError, match="not on your routes"):
        vaccinations.cancel_day(world["vet_b"], day_id)
    vaccinations.cancel_day(world["vet_a"], day_id)
    assert db.get_request(open_one)["status"] == "cancelled" and db.get_request(done)["status"] == "done"
    assert vaccinations.days_for(world["admin"], TODAY) == []
    with pytest.raises(ValueError, match="not open"):
        vaccinations.book(world["fa"], day_id, 1, today=TODAY)
    with pytest.raises(ValueError, match="not open"):
        vaccinations.cancel_day(world["admin"], day_id)


def test_only_an_admin_can_cancel_an_all_routes_day(world):
    day_id = post(world, route=None)
    with pytest.raises(ValueError, match="not on your routes"):
        vaccinations.cancel_day(world["vet_a"], day_id)
    vaccinations.cancel_day(world["admin"], day_id)


def test_the_database_itself_refuses_a_double_booking(world):
    day_id = post(world)
    db.add_vaccination_booking(world["fa"], day_id, DAY, 2, "x")
    import psycopg2

    with pytest.raises(psycopg2.errors.UniqueViolation):
        db.add_vaccination_booking(world["fa"], day_id, DAY, 3, "y")
