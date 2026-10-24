"""Vaccination days through the real pages: admin posts, farmer books, vet sees doses. Need TEST_DATABASE_URL."""
import os
from datetime import date, timedelta

import pytest

if not os.environ.get("TEST_DATABASE_URL"):
    pytest.skip("set TEST_DATABASE_URL to run DB tests", allow_module_level=True)

os.environ["DATABASE_URL"] = os.environ["TEST_DATABASE_URL"]

from streamlit.testing.v1 import AppTest  # noqa: E402

from src import accounts, db, demo_seed  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


@pytest.fixture(autouse=True)
def clean(monkeypatch):
    monkeypatch.setenv("APP_PASSWORD", "pw")
    db._query("TRUNCATE sms_log, alerts, vaccination_days, monthly_budgets, feed_logs, yield_logs, herd_log, feed_catalogue, farmers, users, routes RESTART IDENTITY CASCADE")
    demo_seed.create_demo("demo-pass-123")


def open_page(name, email):
    at = AppTest.from_file(os.path.join(ROOT, name), default_timeout=30)
    at.session_state["user"] = accounts.session_user(db.user_by_email(email))
    return at.run()


def widget(at, kind, key):
    return next(w for w in getattr(at, kind) if w.key == key)


def press(at, label):
    next(b for b in at.button if b.label == label).click().run()


def test_admin_posts_farmer_books_and_the_vet_sees_the_doses():
    route = db.list_routes()[0]["id"]
    day = date.today() + timedelta(days=3)

    at = open_page("pages/12_vaccination.py", demo_seed.ADMIN_EMAIL)
    widget(at, "text_input", "vac_name").set_value("Foot and mouth")
    widget(at, "date_input", "vac_day").set_value(day)
    widget(at, "selectbox", "vac_route").select(route)
    widget(at, "text_input", "vac_place").set_value("Tigoni market")
    press(at, "Post")
    assert not at.exception and [d["vaccine"] for d in db.list_vaccination_days(date.today())] == ["Foot and mouth"]
    assert [a["kind"] for a in db.list_alerts(date.today())] == ["notice"]  # the announcement notice

    at = open_page("pages/12_vaccination.py", demo_seed.FARMER_EMAIL)
    assert not at.exception and any("Foot and mouth" in m.value for m in at.markdown)
    assert not at.expander and not [b for b in at.button if b.label == "Post"]  # a farmer cannot post
    day_id = db.list_vaccination_days(date.today())[0]["id"]
    widget(at, "number_input", f"animals_{day_id}").set_value(4)
    press(at, "Book")
    assert not at.exception
    (booking,) = db.bookings_for_day(day_id)
    assert booking["animals"] == 4 and booking["status"] == "scheduled"
    at = open_page("pages/12_vaccination.py", demo_seed.FARMER_EMAIL)
    assert any("You booked 4 animals" in s.value for s in at.success)  # and can now cancel, not book again
    labels = [b.label for b in at.button]
    assert "Cancel my booking" in labels and "Book" not in labels

    at = open_page("pages/8_my_day.py", demo_seed.VET_EMAIL)
    widget(at, "date_input", "day").set_value(day).run()
    assert not at.exception
    assert any("Foot and mouth: 4 doses" in m.value for m in at.markdown)  # what to carry
    assert any("Foot and mouth: 4 animals" in m.value for m in at.markdown)  # on the visit itself

    at = open_page("pages/12_vaccination.py", demo_seed.VET_EMAIL)
    assert any("1 farm(s) booked · 4 animal(s)" in m.value for m in at.markdown)
    assert [o for o in widget(at, "selectbox", "vac_route").options] == ["Route 4A"]  # a vet cannot post for all routes
