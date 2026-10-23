"""Service requests, the vet's semen list and the day/attendance views. Need TEST_DATABASE_URL."""
import os
from datetime import date, timedelta

import pytest

if not os.environ.get("TEST_DATABASE_URL"):
    pytest.skip("set TEST_DATABASE_URL to run DB tests", allow_module_level=True)

os.environ["DATABASE_URL"] = os.environ["TEST_DATABASE_URL"]

from src import accounts, db, services  # noqa: E402
from src.ingestion import manual_entry as me  # noqa: E402

TODAY = date(2026, 10, 22)
TOMORROW = TODAY + timedelta(days=1)


@pytest.fixture(autouse=True)
def clean():
    db._query("TRUNCATE sms_log, monthly_budgets, feed_logs, yield_logs, herd_log, feed_catalogue, farmers, users, routes RESTART IDENTITY CASCADE")


@pytest.fixture
def world():
    """Two routes, a vet on each; one farm on 4A (with a cow, a heifer and a calf) and one on 5B."""
    route_a, route_b = accounts.record_route("4A"), accounts.record_route("5B")
    vet_a = accounts.create_account("vet", "Dr Kibet", phone="0712345678")
    vet_b = accounts.create_account("vet", "Dr Achieng", phone="0722222222")
    accounts.allocate_vet(route_a, vet_a)
    accounts.allocate_vet(route_b, vet_b)
    farm_a, farm_b = db.add_farmer("Mama A", "+254700000001", "A Farm"), db.add_farmer("Mama B", "+254700000002", "B Farm")
    accounts.assign_route(farm_a, route_a)
    accounts.assign_route(farm_b, route_b)
    cow = me.record_cow(farm_a, "Njeri")["id"]
    other_cow = me.record_cow(farm_b, "Zawadi")["id"]
    as_user = lambda uid: accounts.session_user(db.get_user(uid))  # noqa: E731
    return dict(vet_a=as_user(vet_a), vet_b=as_user(vet_b), farm_a=farm_a, farm_b=farm_b, cow=cow, other_cow=other_cow)


def ai(world, **kw):
    semen = services.record_vet_semen(world["vet_a"], "Friesian - Kamau", 1500)
    return services.request_service(world["farm_a"], "ai", TODAY, cow_id=world["cow"], semen_id=semen, today=TODAY, **kw), semen


# --- the vet's semen list ----------------------------------------------------------------------


def test_a_vet_keeps_a_priced_semen_list_and_can_reprice_or_retire(world):
    sid = services.record_vet_semen(world["vet_a"], "  Friesian - Kamau ", "1500")
    assert services.record_vet_semen(world["vet_a"], "Friesian - Kamau", 1800) == sid  # same bull: repriced
    assert [(s["name"], float(s["price_kes"])) for s in db.list_vet_semen(world["vet_a"]["id"])] == [("Friesian - Kamau", 1800.0)]
    db.retire_vet_semen(world["vet_a"]["id"], sid)
    assert db.list_vet_semen(world["vet_a"]["id"]) == []


def test_semen_list_validation_and_only_vets_have_one(world):
    for name, price, why in (("", 100, "bull name"), ("X", "abc", "price"), ("X", 0, "more than 0"), ("X", -5, "more than 0"), ("X", 10 ** 6, "at most"), ("X" * 81, 100, "too long")):
        with pytest.raises(ValueError, match=why):
            services.record_vet_semen(world["vet_a"], name, price)
    with pytest.raises(ValueError, match="only a vet"):
        services.record_vet_semen({"id": 1, "role": "farmer"}, "X", 100)


def test_a_vet_cannot_retire_another_vets_semen(world):
    sid = services.record_vet_semen(world["vet_a"], "Friesian - Kamau", 1500)
    db.retire_vet_semen(world["vet_b"]["id"], sid)
    assert len(db.list_vet_semen(world["vet_a"]["id"])) == 1


# --- farmer requests ---------------------------------------------------------------------------


def test_an_ai_request_quotes_the_route_vets_price(world):
    rid, semen = ai(world)
    q = db.get_request(rid)
    assert q["status"] == "open" and q["vet_name"] == "Dr Kibet" and q["route_code"] == "4A"
    assert float(q["semen_price_kes"]) == 1500 and q["cow_tag"] == "Njeri"


def test_request_validation(world):
    f, cow = world["farm_a"], world["cow"]
    calf = me.record_cow(f, "Baby")["id"]
    db.set_cow_kind(f, calf, "calf")
    for kw, why in (
        (dict(kind="vaccination"), "what you need"),
        (dict(kind="sick", preferred_date=TODAY - timedelta(days=1), cow_id=cow), "past"),
        (dict(kind="sick", preferred_date=TODAY + timedelta(days=90), cow_id=cow), "within the next"),
        (dict(kind="sick", cow_id=None), "choose the cow"),
        (dict(kind="sick", cow_id=world["other_cow"]), "choose the cow"),  # another farm's cow
        (dict(kind="ai", cow_id=calf), "calf"),
        (dict(kind="other"), "say what you need"),
        (dict(kind="other", notes="x" * 301), "too long"),
        (dict(kind="ai", cow_id=cow, semen_id=9999), "your vet's list"),
    ):
        args = dict(kind="sick", preferred_date=TODAY, cow_id=cow) | kw
        with pytest.raises(ValueError, match=why):
            services.request_service(f, args.pop("kind"), args.pop("preferred_date"), today=TODAY, **args)


def test_semen_from_a_different_vet_or_a_retired_one_is_refused(world):
    other = services.record_vet_semen(world["vet_b"], "Jersey - Tuma", 1200)
    with pytest.raises(ValueError, match="your vet's list"):
        services.request_service(world["farm_a"], "ai", TODAY, cow_id=world["cow"], semen_id=other, today=TODAY)
    mine = services.record_vet_semen(world["vet_a"], "Friesian - Kamau", 1500)
    db.retire_vet_semen(world["vet_a"]["id"], mine)
    with pytest.raises(ValueError, match="your vet's list"):
        services.request_service(world["farm_a"], "ai", TODAY, cow_id=world["cow"], semen_id=mine, today=TODAY)


def test_the_same_cow_cannot_have_two_open_requests_of_one_kind_and_a_farm_cannot_flood(world):
    services.request_service(world["farm_a"], "sick", TODAY, cow_id=world["cow"], today=TODAY)
    with pytest.raises(ValueError, match="already has an open request"):
        services.request_service(world["farm_a"], "sick", TODAY, cow_id=world["cow"], today=TODAY)
    for i in range(services.MAX_OPEN - 1):
        services.request_service(world["farm_a"], "other", TODAY, notes=f"thing {i}", today=TODAY)
    with pytest.raises(ValueError, match="open requests"):
        services.request_service(world["farm_a"], "other", TODAY, notes="one more", today=TODAY)


def test_a_farmer_cancels_only_their_own_open_request(world):
    rid = services.request_service(world["farm_a"], "sick", TODAY, cow_id=world["cow"], today=TODAY)
    with pytest.raises(ValueError, match="not yours"):
        services.cancel_request(rid, world["farm_b"])
    services.cancel_request(rid, world["farm_a"])
    assert db.get_request(rid)["status"] == "cancelled"
    with pytest.raises(ValueError, match="only a waiting"):
        services.cancel_request(rid, world["farm_a"])


def test_a_request_from_a_farm_with_no_vet_is_saved_and_shows_as_unattended(world):
    lone = db.add_farmer("Lone", "+254700000003")
    cow = me.record_cow(lone, "Solo")["id"]
    services.request_service(lone, "sick", TODAY, cow_id=cow, today=TODAY)
    assert len(services.attendance(TODAY)["unattended"]) == 1


# --- the vet's actions ---------------------------------------------------------------------------


def test_a_vet_only_acts_on_requests_from_their_own_routes(world):
    rid = services.request_service(world["farm_a"], "sick", TODAY, cow_id=world["cow"], today=TODAY)
    for act in (lambda: services.schedule_request(rid, world["vet_b"], TODAY, today=TODAY),
                lambda: services.complete_request(rid, world["vet_b"], today=TODAY)):
        with pytest.raises(ValueError, match="not on your routes"):
            act()
    with pytest.raises(ValueError, match="only a vet"):
        services.complete_request(rid, {"id": 1, "role": "farmer"}, today=TODAY)
    assert db.get_request(rid)["status"] == "open"
    assert [q["id"] for q in services.inbox(world["vet_a"])] == [rid] and services.inbox(world["vet_b"]) == []


def test_scheduling_and_the_day_sheet_with_what_to_carry(world):
    rid_ai, semen = ai(world)
    sick = me.record_cow(world["farm_a"], "Wambui")["id"]
    rid_sick = services.request_service(world["farm_a"], "sick", TODAY, cow_id=sick, today=TODAY)
    for rid in (rid_ai, rid_sick):
        services.schedule_request(rid, world["vet_a"], TOMORROW, today=TODAY)
    with pytest.raises(ValueError, match="past"):
        services.schedule_request(rid_ai, world["vet_a"], TODAY - timedelta(days=1), today=TODAY)
    sheet = services.day_sheet(world["vet_a"], TOMORROW)
    assert sheet["total"] == 2 and sheet["done"] == 0 and len(sheet["farms"]) == 1
    assert sheet["farms"][0]["farm"] == "A Farm" and len(sheet["farms"][0]["visits"]) == 2
    assert sheet["carry"] == ["Friesian - Kamau: 1 straw", "treatment kit for 1 sick-cow visit"]
    assert services.day_sheet(world["vet_a"], TODAY)["total"] == 0
    assert services.day_sheet(world["vet_b"], TOMORROW)["total"] == 0


def test_completing_an_ai_visit_records_the_service_on_the_cow_and_the_cost(world):
    rid, semen = ai(world)
    services.complete_request(rid, world["vet_a"], notes="Done, calm cow", today=TODAY)
    q = db.get_request(rid)
    assert q["status"] == "done" and q["done_on"] == TODAY and q["vet_notes"] == "Done, calm cow"
    events = db.breeding_events(world["farm_a"], world["cow"])
    assert [(e["kind"], e["semen"], e["event_date"]) for e in events] == [("served", "Friesian - Kamau", TODAY)]
    assert db.semen_cost(world["farm_a"], TODAY, TODAY) == (1500.0, 1)
    assert db.semen_cost(world["farm_a"], TOMORROW, TOMORROW) == (0.0, 0)
    assert db.semen_cost(world["farm_b"], TODAY, TODAY) == (0.0, 0)
    with pytest.raises(ValueError, match="already closed"):
        services.complete_request(rid, world["vet_a"], today=TODAY)


def test_the_quoted_price_stands_but_a_different_semen_uses_its_own_price(world):
    rid, semen = ai(world)
    services.record_vet_semen(world["vet_a"], "Friesian - Kamau", 2500)  # price rises after the farmer asked
    services.complete_request(rid, world["vet_a"], today=TODAY)
    assert db.semen_cost(world["farm_a"], TODAY, TODAY)[0] == 1500.0
    cow2 = me.record_cow(world["farm_a"], "Wambui")["id"]
    rid2 = services.request_service(world["farm_a"], "ai", TODAY, cow_id=cow2, today=TODAY)  # no semen chosen
    with pytest.raises(ValueError, match="choose the semen"):
        services.complete_request(rid2, world["vet_a"], today=TODAY)
    jersey = services.record_vet_semen(world["vet_a"], "Jersey - Tuma", 1200)
    services.complete_request(rid2, world["vet_a"], semen_id=jersey, today=TODAY)
    assert db.semen_cost(world["farm_a"], TODAY, TODAY) == (2700.0, 2)


def test_a_vet_cannot_use_another_vets_semen(world):
    rid = services.request_service(world["farm_a"], "ai", TODAY, cow_id=world["cow"], today=TODAY)
    theirs = services.record_vet_semen(world["vet_b"], "Jersey - Tuma", 1200)
    with pytest.raises(ValueError, match="your own list"):
        services.complete_request(rid, world["vet_a"], semen_id=theirs, today=TODAY)
    assert db.get_request(rid)["status"] == "open" and db.breeding_events(world["farm_a"], world["cow"]) == []


def test_a_sick_cow_visit_is_completed_with_notes_and_costs_nothing(world):
    rid = services.request_service(world["farm_a"], "sick", TODAY, cow_id=world["cow"], today=TODAY)
    services.complete_request(rid, world["vet_a"], notes="Mastitis, gave antibiotics", today=TODAY)
    assert db.semen_cost(world["farm_a"], TODAY, TODAY) == (0.0, 0)
    assert db.breeding_events(world["farm_a"], world["cow"]) == []


# --- the admin's view ----------------------------------------------------------------------------


def test_attendance_shows_done_to_do_late_and_waiting_per_vet(world):
    done, _ = ai(world)
    services.complete_request(done, world["vet_a"], today=TODAY)
    c2, c3, c4 = (me.record_cow(world["farm_a"], t)["id"] for t in ("C2", "C3", "C4"))
    todo = services.request_service(world["farm_a"], "sick", TODAY, cow_id=c2, today=TODAY)
    services.schedule_request(todo, world["vet_a"], TODAY, today=TODAY)
    late = services.request_service(world["farm_a"], "sick", TODAY - timedelta(days=0), cow_id=c3, today=TODAY)
    services.schedule_request(late, world["vet_a"], TODAY, today=TODAY)
    waiting = services.request_service(world["farm_a"], "sick", TOMORROW, cow_id=c4, today=TODAY)
    view = services.attendance(TODAY + timedelta(days=0))
    a = next(v for v in view["vets"] if v["vet"] == "Dr Kibet")
    assert (a["done_today"], a["booked_today"], len(a["to_do_today"]), a["waiting"]) == (1, 3, 2, 1)
    # the next morning, what was not done is late
    next_day = services.attendance(TOMORROW)
    a = next(v for v in next_day["vets"] if v["vet"] == "Dr Kibet")
    assert len(a["late"]) == 2 and a["done_today"] == 0


def test_the_day_sheet_for_a_vet_with_no_route_is_empty():
    nobody = accounts.session_user(db.get_user(accounts.create_account("vet", "New Vet", phone="0733333333")))
    assert services.day_sheet(nobody, TODAY)["total"] == 0 and services.inbox(nobody) == []


def test_carry_list_is_pure_and_plural_aware():
    v = lambda **k: {"kind": "ai", "semen_name": None} | k  # noqa: E731
    assert services.carry_list([]) == []
    assert services.carry_list([v(semen_name="A"), v(semen_name="A"), v(kind="other")]) == ["A: 2 straws", "1 other request: read the notes"]
    assert services.carry_list([v()]) == ["semen (to be chosen): 1 straw"]
