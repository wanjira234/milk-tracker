"""Route admins: an admin login limited to some routes. Need TEST_DATABASE_URL (tests truncate tables)."""
import os
from datetime import date, timedelta

import pytest

if not os.environ.get("TEST_DATABASE_URL"):
    pytest.skip("set TEST_DATABASE_URL to run DB tests", allow_module_level=True)

os.environ["DATABASE_URL"] = os.environ["TEST_DATABASE_URL"]

from streamlit.testing.v1 import AppTest  # noqa: E402

from src import accounts, alerts, db, services, vaccinations  # noqa: E402
from src.auth import menu_for, menu_key  # noqa: E402
from src.ingestion import manual_entry as me  # noqa: E402

TODAY = date(2026, 10, 22)
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


@pytest.fixture(autouse=True)
def clean():
    db._query("TRUNCATE sms_log, monthly_budgets, feed_logs, yield_logs, herd_log, feed_catalogue, farmers, users, routes, alerts, vaccination_days RESTART IDENTITY CASCADE")


@pytest.fixture
def world():
    ra, rb = accounts.record_route("4A"), accounts.record_route("5B")
    vet_a = accounts.create_account("vet", "Dr A", phone="0712345678")
    vet_b = accounts.create_account("vet", "Dr B", phone="0722222222")
    accounts.allocate_vet(ra, vet_a)
    accounts.allocate_vet(rb, vet_b)
    farm_a, farm_b = db.add_farmer("Mama A", "+254700000001", "A Farm"), db.add_farmer("Mama B", "+254700000002", "B Farm")
    accounts.assign_route(farm_a, ra)
    accounts.assign_route(farm_b, rb)
    head = accounts.create_account("admin", "Head", phone="0733333333")
    route_admin = accounts.create_account("admin", "Route admin A", phone="0744444444", route_ids=[ra])
    as_user = lambda uid: accounts.session_user(db.get_user(uid))  # noqa: E731
    for farm, cow_name in ((farm_a, "Njeri"), (farm_b, "Zawadi")):
        cow = me.record_cow(farm, cow_name)["id"]
        services.request_service(farm, "sick", TODAY, cow_id=cow, today=TODAY)
    return dict(ra=ra, rb=rb, farm_a=farm_a, farm_b=farm_b, head=as_user(head), ra_user=as_user(route_admin), route_admin_id=route_admin)


def test_a_route_admin_is_an_admin_login_limited_to_their_routes(world):
    u = world["ra_user"]
    assert u["role"] == "admin" and u["route_admin"] and not accounts.is_head_admin(u)
    assert accounts.admin_scope(u) == {world["ra"]}
    assert accounts.admin_scope(world["head"]) is None and accounts.is_head_admin(world["head"])
    assert [f["name"] for f in accounts.visible_farmers(u)] == ["Mama A"]
    assert {f["name"] for f in accounts.visible_farmers(world["head"])} == {"Mama A", "Mama B"}


def test_attendance_for_a_route_admin_shows_only_their_routes(world):
    scope = accounts.admin_scope(world["ra_user"])
    view = services.attendance(TODAY, scope)
    names = {q["farm_name"] for v in view["vets"] for q in v["late"] + v["to_do_today"]} | {q["farm_name"] for q in view["unattended"]}
    rows = [v["vet"] for v in view["vets"]]
    assert rows == ["Dr A"] and "B Farm" not in names
    assert {v["vet"] for v in services.attendance(TODAY)["vets"]} == {"Dr A", "Dr B"}  # the head admin sees both


def test_alerts_and_vaccination_days_stay_on_a_route_admins_routes(world):
    u = world["ra_user"]
    assert alerts.routes_of(u) == {world["ra"]}
    alerts.post_alert(u, "notice", "Dip day", "Bring cows", route_id=world["ra"], today=TODAY)
    with pytest.raises(ValueError):
        alerts.post_alert(u, "notice", "Everyone", "All routes", route_id=None, today=TODAY)
    with pytest.raises(ValueError):
        alerts.post_alert(u, "notice", "Other route", "No", route_id=world["rb"], today=TODAY)
    alerts.post_alert(world["head"], "outbreak", "FMD", "Near 5B", route_id=world["rb"], today=TODAY)
    assert [a["title"] for a in alerts.visible_alerts(u, today=TODAY)] == ["Dip day"]
    assert len(alerts.visible_alerts(world["head"], today=TODAY)) == 2
    day = TODAY + timedelta(days=3)
    vaccinations.post_day(u, "FMD", day, route_id=world["ra"], announce=False, today=TODAY)
    with pytest.raises(ValueError):
        vaccinations.post_day(u, "FMD", day, route_id=world["rb"], announce=False, today=TODAY)
    with pytest.raises(ValueError):
        vaccinations.post_day(u, "FMD", day, route_id=None, announce=False, today=TODAY)
    vaccinations.post_day(world["head"], "Anthrax", day, route_id=world["rb"], announce=False, today=TODAY)
    assert [d["vaccine"] for d in vaccinations.days_for(u, today=TODAY)] == ["FMD"]


def test_the_head_admin_sets_a_route_admins_routes_and_the_scope_follows(world):
    accounts.set_route_admin_routes(world["head"], world["route_admin_id"], [world["ra"], world["rb"]])
    assert accounts.admin_scope(world["ra_user"]) == {world["ra"], world["rb"]}
    assert len(accounts.visible_farmers(world["ra_user"])) == 2
    for actor in (world["ra_user"], None):
        with pytest.raises(ValueError, match="admin"):
            accounts.set_route_admin_routes(actor, world["route_admin_id"], [])
    with pytest.raises(ValueError, match="route admin"):
        accounts.set_route_admin_routes(world["head"], world["head"]["id"], [world["ra"]])
    with pytest.raises(ValueError, match="routes"):
        accounts.set_route_admin_routes(world["head"], world["route_admin_id"], [9999])


def test_a_route_admin_cannot_delete_or_open_the_admin_page(world):
    for fn, args in ((accounts.admin_delete_login, (world["head"]["id"], "DELETE")),
                     (accounts.admin_delete_farm, (world["farm_b"], "DELETE")),
                     (accounts.admin_delete_route, (world["rb"], "DELETE"))):
        with pytest.raises(ValueError, match="only an admin"):
            fn(world["ra_user"], *args)
    at = AppTest.from_file(os.path.join(ROOT, "pages/7_admin.py"), default_timeout=30)
    at.session_state["user"] = world["ra_user"]
    at.run()
    assert not at.exception and any("head admin" in e.value for e in at.error) and not at.text_input


def test_the_route_admin_menu_has_no_set_up_pages(world):
    assert menu_key(world["ra_user"]) == "route_admin" and menu_key(world["head"]) == "admin"
    labels = [label for _, label in menu_for("route_admin")]
    assert labels == ["Home", "Attendance", "Alerts", "Vaccination", "Website", "Account"]


def test_the_route_admin_home_is_scoped(world):
    at = AppTest.from_file(os.path.join(ROOT, "app.py"), default_timeout=30)
    at.session_state["user"] = world["ra_user"]
    at.run()
    assert not at.exception
    metrics = {m.label: m.value for m in at.metric}
    assert metrics["Farmers"] == "1" and metrics["Routes"] == "1" and metrics["Vets"] == "1" and "Signups waiting" not in metrics
