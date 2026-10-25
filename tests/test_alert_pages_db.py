"""The alerts page through the real app: admin posts and texts, farmer reads, farmer cannot send."""
import os

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
    monkeypatch.delenv("AT_USERNAME", raising=False)
    monkeypatch.delenv("AT_API_KEY", raising=False)
    db._query("TRUNCATE sms_log, alerts, monthly_budgets, feed_logs, yield_logs, herd_log, feed_catalogue, farmers, users, routes RESTART IDENTITY CASCADE")
    demo_seed.create_demo("demo-pass-123")


def open_alerts(email):
    at = AppTest.from_file(os.path.join(ROOT, "pages/11_alerts.py"), default_timeout=30)
    at.session_state["user"] = accounts.session_user(db.user_by_email(email))
    return at.run()


def widget(at, kind, key):
    return next(w for w in getattr(at, kind) if w.key == key)


def press(at, label):
    next(b for b in at.button if b.label == label).click().run()


def test_admin_posts_the_farmer_reads_it_and_the_farmer_has_no_way_to_post_or_text():
    route = db.list_routes()[0]["id"]
    at = open_alerts(demo_seed.ADMIN_EMAIL)
    widget(at, "text_input", "alert_title").set_value("Foot and mouth near Tigoni")
    widget(at, "text_area", "alert_body").set_value("Keep cows in. Call your vet if a cow limps.")
    widget(at, "selectbox", "alert_route").select(route)
    press(at, "Post alert")
    assert not at.exception and [a["title"] for a in db.list_alerts(__import__("datetime").date.today())] == ["Foot and mouth near Tigoni"]

    at = open_alerts(demo_seed.FARMER_EMAIL)
    assert not at.exception
    assert any("Foot and mouth near Tigoni" in m.value for m in at.markdown)
    assert not at.expander and not [b for b in at.button if b.label in ("Send SMS", "Post alert")]


def test_admin_texts_an_alert_from_the_page_and_everyone_can_then_read_the_outbox(monkeypatch):
    route = db.list_routes()[0]["id"]
    aid = db.add_alert("outbreak", "Mastitis cases", "Wash udders before milking.", route, None, None)
    at = open_alerts(demo_seed.ADMIN_EMAIL)
    assert any("SMS preview (1 segment(s))" in c.value for c in at.caption)
    send = next(b for b in at.button if b.label == "Send SMS")
    assert send.proto.disabled  # not until the box is ticked
    widget(at, "checkbox", f"sure_{aid}").check().run()
    press(at, "Send SMS")
    assert not at.exception
    a = db.get_alert(aid)
    assert a["sms_sent_at"] is not None and a["sms_ok"] + a["sms_failed"] == 2  # the two demo farms on the route
    assert not [b for b in open_alerts(demo_seed.ADMIN_EMAIL).button if b.label == "Send SMS"]  # no second send offered
    at = open_alerts(demo_seed.FARMER_EMAIL)
    assert any("Wash udders" in m.value for m in at.markdown)  # in the farmer's outbox (and the alert list)


def test_the_vet_can_post_only_to_their_own_route():
    at = open_alerts(demo_seed.VET_EMAIL)
    assert widget(at, "selectbox", "alert_route").options == ["Route 4A"]  # no "All routes" for a vet
