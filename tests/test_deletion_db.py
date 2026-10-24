"""Deleting accounts, farms and routes. Need TEST_DATABASE_URL (the tests truncate tables)."""
import os
from datetime import date, timedelta

import pytest

if not os.environ.get("TEST_DATABASE_URL"):
    pytest.skip("set TEST_DATABASE_URL to run DB tests", allow_module_level=True)

os.environ["DATABASE_URL"] = os.environ["TEST_DATABASE_URL"]

from src import accounts, db, services  # noqa: E402
from src.ingestion import manual_entry as me  # noqa: E402

TODAY = date(2026, 10, 22)


@pytest.fixture(autouse=True)
def clean():
    db._query("TRUNCATE sms_log, monthly_budgets, feed_logs, yield_logs, herd_log, feed_catalogue, farmers, users, routes, alerts, vaccination_days RESTART IDENTITY CASCADE")


@pytest.fixture
def world():
    route = accounts.record_route("4A")
    vet = accounts.create_account("vet", "Dr Kibet", phone="0712345678")
    admin = accounts.create_account("admin", "Boss", phone="0733333333")
    accounts.allocate_vet(route, vet)
    farm = db.add_farmer("Mama A", "+254700000001", "A Farm")
    other = db.add_farmer("Mama B", "+254700000002", "B Farm")
    login = accounts.create_account("farmer", "Mama A", phone="0700000001", farmer_id=farm)
    accounts.assign_route(farm, route)
    cow = me.record_cow(farm, "Njeri")["id"]
    db.upsert_yield(farm, TODAY, "morning", 10)
    db.add_feed(farm, TODAY, "napier", 50, 100)
    db.log_sms(farm, "hello")
    db.add_alert("notice", "Notice", "Body", route, vet)
    db.add_vaccination_day("FMD", TODAY + timedelta(days=5), route, vet)
    vet_user = accounts.session_user(db.get_user(vet))
    semen = services.record_vet_semen(vet_user, "Friesian - Kamau", 1500)
    services.request_service(farm, "ai", TODAY, cow_id=cow, semen_id=semen, today=TODAY)
    as_user = lambda uid: accounts.session_user(db.get_user(uid))  # noqa: E731
    return dict(route=route, vet=vet, admin=admin, farm=farm, other=other, login=login, vet_user=vet_user,
                admin_user=as_user(admin), farmer_user=as_user(login))


def count(table, **where):
    clause = " AND ".join(f"{k} = %s" for k in where) or "TRUE"
    return db._query(f"SELECT COUNT(*) AS n FROM {table} WHERE {clause}", tuple(where.values()), one=True)["n"]


def test_a_farmer_deleting_their_account_removes_the_farm_and_every_record(world):
    accounts.delete_own_account(world["farmer_user"], "DELETE")
    assert db.get_user(world["login"]) is None and db.get_farmer(world["farm"]) is None
    for table in ("cows", "yield_logs", "feed_logs", "sms_log", "service_requests"):
        assert count(table, farmer_id=world["farm"]) == 0, table
    assert db.get_farmer(world["other"])  # another farm is untouched


def test_deleting_needs_the_confirm_word_and_the_owner_login_has_nothing_to_delete(world):
    for wrong in ("", "delete me", "yes"):
        with pytest.raises(ValueError, match="DELETE"):
            accounts.delete_own_account(world["farmer_user"], wrong)
    assert db.get_farmer(world["farm"])
    with pytest.raises(ValueError, match="owner"):
        accounts.delete_own_account({"id": None, "role": "admin"}, "DELETE")


def test_a_vet_deleting_their_account_keeps_the_route_and_past_requests(world):
    accounts.delete_own_account(world["vet_user"], "DELETE")
    assert db.get_user(world["vet"]) is None
    route = next(r for r in db.list_routes() if r["id"] == world["route"])
    assert route["vet_user_id"] is None
    req = db._query("SELECT semen_id, semen_price_kes FROM service_requests WHERE farmer_id = %s", (world["farm"],), one=True)
    assert req["semen_id"] is None and float(req["semen_price_kes"]) == 1500  # the price paid is kept


def test_the_only_admin_cannot_be_deleted_but_one_of_two_can(world):
    with pytest.raises(ValueError, match="only admin"):
        accounts.delete_own_account(world["admin_user"], "DELETE")
    second = accounts.create_account("admin", "Second", phone="0744444444")
    accounts.delete_own_account(world["admin_user"], "DELETE")
    assert db.get_user(world["admin"]) is None and db.get_user(second)


def test_an_admin_deletes_a_login_a_farm_and_a_route(world):
    actor = world["admin_user"]
    accounts.admin_delete_login(actor, world["login"], "DELETE")
    assert db.get_user(world["login"]) is None and db.get_farmer(world["farm"])  # the farm and its records stay
    accounts.admin_delete_farm(actor, world["farm"], "DELETE")
    assert db.get_farmer(world["farm"]) is None and count("yield_logs", farmer_id=world["farm"]) == 0
    accounts.assign_route(world["other"], world["route"])
    accounts.admin_delete_route(actor, world["route"], "DELETE")
    assert db.list_routes() == [] and db.get_farmer(world["other"])["route_id"] is None
    assert count("alerts") == 0 and count("vaccination_days") == 0


def test_only_an_admin_can_use_the_admin_deletes_and_not_on_themselves(world):
    for name, args in (("admin_delete_login", (world["vet"], "DELETE")), ("admin_delete_farm", (world["farm"], "DELETE")),
                       ("admin_delete_route", (world["route"], "DELETE"))):
        for actor in (world["farmer_user"], world["vet_user"], None):
            with pytest.raises(ValueError, match="admin"):
                getattr(accounts, name)(actor, *args)
    with pytest.raises(ValueError, match="own login"):
        accounts.admin_delete_login(world["admin_user"], world["admin"], "DELETE")
    with pytest.raises(ValueError, match="DELETE"):
        accounts.admin_delete_farm(world["admin_user"], world["farm"], "")
    assert db.get_farmer(world["farm"]) and db.get_user(world["vet"])


def test_the_account_page_deletes_a_farmer_who_types_the_word_and_signs_them_out(world):
    from streamlit.testing.v1 import AppTest

    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    at = AppTest.from_file(os.path.join(root, "pages/6_account.py"), default_timeout=30)
    at.session_state["user"] = world["farmer_user"]
    at.run()
    box = next(t for t in at.text_input if t.key == "delete_me_confirm")
    box.set_value("nope")
    next(b for b in at.button if b.label == "Delete my account").click().run()
    assert at.error and db.get_farmer(world["farm"])  # a wrong word deletes nothing
    next(t for t in at.text_input if t.key == "delete_me_confirm").set_value("DELETE")
    next(b for b in at.button if b.label == "Delete my account").click().run()
    assert not at.exception and db.get_farmer(world["farm"]) is None
    assert not at.session_state["user"] if "user" in at.session_state else True
