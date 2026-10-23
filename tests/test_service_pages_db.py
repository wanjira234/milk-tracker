"""The judges' journey through the real pages: farmer asks, vet books and completes, admin checks."""
import os
from datetime import date

import pytest

if not os.environ.get("TEST_DATABASE_URL"):
    pytest.skip("set TEST_DATABASE_URL to run DB tests", allow_module_level=True)

os.environ["DATABASE_URL"] = os.environ["TEST_DATABASE_URL"]

from streamlit.testing.v1 import AppTest  # noqa: E402

from src import accounts, db, demo_seed, services  # noqa: E402
from src.auth import OWNER_USER  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


@pytest.fixture(autouse=True)
def clean(monkeypatch):
    monkeypatch.setenv("APP_PASSWORD", "pw")
    db._query("TRUNCATE sms_log, monthly_budgets, feed_logs, yield_logs, herd_log, feed_catalogue, farmers, users, routes RESTART IDENTITY CASCADE")


def open_page(name, user):
    at = AppTest.from_file(os.path.join(ROOT, name), default_timeout=30)
    at.session_state["user"] = user
    return at.run()


def widget(at, kind, key):
    return next(w for w in getattr(at, kind) if w.key == key)


def press(at, label):
    next(b for b in at.button if b.label == label).click().run()


def login(email):
    return accounts.session_user(db.user_by_email(email))


def test_the_whole_journey_farmer_vet_admin_and_profit():
    demo_seed.create_demo("demo-pass-123")
    farmer, vet, admin = login(demo_seed.FARMER_EMAIL), login(demo_seed.VET_EMAIL), login(demo_seed.ADMIN_EMAIL)
    farm = farmer["farmer_id"]

    # the vet lists semen with a price
    at = open_page("pages/8_my_day.py", vet)
    widget(at, "text_input", "semen_name").set_value("Friesian - Kamau")
    widget(at, "text_input", "semen_price").set_value("1500")
    press(at, "Add or update")
    assert not at.exception and [s["name"] for s in db.list_vet_semen(vet["id"])] == ["Friesian - Kamau"]

    # the farmer asks for AI on one of her cows, choosing that semen, and sees the price
    at = open_page("pages/9_ask_the_vet.py", farmer)
    assert not at.exception and any("Dr Demo Vet" in c.value for c in at.caption)
    cow = next(c for c in db.list_cows(farm) if c["tag"] == "Njeri")["id"]
    widget(at, "radio", "req_kind").set_value("ai").run()
    widget(at, "selectbox", "req_cow").select(cow)
    sem = widget(at, "selectbox", "req_semen")
    assert sem.options == ["Friesian - Kamau (KES 1,500)"]
    sem.select(db.list_vet_semen(vet["id"])[0]["id"])
    press(at, "Send request")
    assert not at.exception
    (req,) = db.requests_for_farm(farm)
    assert req["status"] == "open" and float(req["semen_price_kes"]) == 1500

    # the vet sees it waiting, books it for today
    at = open_page("pages/8_my_day.py", vet)
    assert not at.exception
    press(at, "Book")
    assert db.get_request(req["id"])["status"] == "scheduled"

    # and finds it on today's sheet with the semen to carry
    at = open_page("pages/8_my_day.py", vet)
    assert any("Friesian - Kamau: 1 straw" in m.value for m in at.markdown)

    # the admin sees one booked visit, not yet done
    at = open_page("pages/10_attendance.py", admin)
    assert not at.exception
    row = at.dataframe[0].value.iloc[0]
    assert row["Vet"] == "Dr Demo Vet" and row["Booked today"] == 1 and row["Done"] == 0 and row["Still to do today"] == 1

    # the vet marks it done
    widget(open_page("pages/8_my_day.py", vet), "selectbox", "used_%d" % req["id"])  # present for an AI visit
    at = open_page("pages/8_my_day.py", vet)
    widget(at, "text_input", "notes_%d" % req["id"]).set_value("Calm cow")
    press(at, "Mark done")
    assert not at.exception and db.get_request(req["id"])["status"] == "done"

    # admin now sees it done; the cow's record has the service; the farm's profit shows the semen
    row = open_page("pages/10_attendance.py", admin).dataframe[0].value.iloc[0]
    assert row["Done"] == 1 and row["Still to do today"] == 0
    assert [e["kind"] for e in db.breeding_events(farm, cow)] == ["served"]
    at = open_page("pages/1_dashboard.py", farmer)
    assert not at.exception
    assert any("Left after feed and semen" in m.label for m in at.metric)
    assert any("KES 1,500" in m.value for m in at.markdown)

    # and the farmer's list says it is done
    at = open_page("pages/9_ask_the_vet.py", farmer)
    assert any("done" in m.value for m in at.markdown)


def test_pages_are_closed_to_the_wrong_roles():
    demo_seed.create_demo("demo-pass-123")
    farmer, vet, admin = login(demo_seed.FARMER_EMAIL), login(demo_seed.VET_EMAIL), login(demo_seed.ADMIN_EMAIL)
    for page, allowed in (("pages/8_my_day.py", vet), ("pages/9_ask_the_vet.py", farmer), ("pages/10_attendance.py", admin)):
        for who in (farmer, vet, admin):
            at = open_page(page, who)
            blocked = bool(at.error and "not available" in at.error[0].value)
            assert blocked == (who is not allowed), (page, who["role"])


def test_a_farmer_cannot_book_for_another_farm_through_the_page():
    demo_seed.create_demo("demo-pass-123")
    farmer = login(demo_seed.FARMER_EMAIL)
    other = db.add_farmer("Other", "+254700000555")
    at = open_page("pages/9_ask_the_vet.py", farmer)
    assert at.session_state["farmer_id"] == farmer["farmer_id"] != other  # the picker is fixed to her own farm
