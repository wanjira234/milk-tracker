"""The Feed stock page and the Home warning, through the real pages. Need TEST_DATABASE_URL."""
import os
from datetime import date, timedelta

import pytest

if not os.environ.get("TEST_DATABASE_URL"):
    pytest.skip("set TEST_DATABASE_URL to run DB tests", allow_module_level=True)

os.environ["DATABASE_URL"] = os.environ["TEST_DATABASE_URL"]

from streamlit.testing.v1 import AppTest  # noqa: E402

from src import accounts, db, stock  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


@pytest.fixture(autouse=True)
def clean(monkeypatch):
    monkeypatch.setenv("APP_PASSWORD", "pw")
    db._query("TRUNCATE feed_stock_counts, feed_purchases, charge_payments, charges, feed_logs, feed_catalogue, farmers, users "
              "RESTART IDENTITY CASCADE")


def open_page(name, user):
    at = AppTest.from_file(os.path.join(ROOT, name), default_timeout=30)
    at.session_state["user"] = user
    return at.run()


def widget(at, kind, key):
    return next(w for w in getattr(at, kind) if w.key == key)


def press(at, label):
    next(b for b in at.button if b.label == label).click().run()


@pytest.fixture
def farm():
    f = db.add_farmer("Mama A", "+254700000001", "A Farm")
    u = accounts.session_user(db.get_user(accounts.create_account("farmer", "Mama A", phone="0700000001", farmer_id=f)))
    item = db.upsert_catalogue_item(f, "napier", "truck", 3000, 5000)
    return dict(farm=f, user=u, item=item)


def test_a_farm_without_feeds_is_sent_to_farm_setup():
    f = db.add_farmer("Mama B", "+254700000002")
    u = accounts.session_user(db.get_user(accounts.create_account("farmer", "Mama B", phone="0700000002", farmer_id=f)))
    at = open_page("pages/15_stock.py", u)
    assert not at.exception and "Farm setup" in at.info[0].value


def test_a_truck_arrives_on_credit_and_shows_on_money(farm):
    at = open_page("pages/15_stock.py", farm["user"])
    widget(at, "text_input", "buy_from").set_value("Kamau transport")
    widget(at, "radio", "buy_terms").set_value("credit")
    press(at, "Save the load")
    assert not at.exception
    (p,) = db.feed_purchases(farm["farm"])
    assert float(p["units"]) == 1 and db.get_charge(p["charge_id"])["terms"] == "credit"
    money = open_page("pages/14_money.py", farm["user"])
    assert any("Kamau transport" in m.value for m in money.markdown)


def test_marking_a_load_finished_from_the_page(farm):
    stock.record_purchase(farm["user"], farm["farm"], farm["item"], "1", date.today() - timedelta(days=3), price="0")
    at = open_page("pages/15_stock.py", farm["user"])
    press(at, "Save")  # the first Save is the count form: 0 left (finished), today
    assert not at.exception
    (c,) = db.stock_counts(farm["farm"])
    assert float(c["kg"]) == 0 and c["counted_on"] == date.today()


def test_a_feed_running_out_is_flagged_on_the_page_and_on_home(farm):
    u, f, n = farm["user"], farm["farm"], farm["item"]
    today = date.today()
    stock.record_purchase(u, f, n, "1", today - timedelta(days=12), price="0")
    stock.record_count(u, f, n, today - timedelta(days=2), "0")                 # that truck lasted 10 days: 300 kg a day
    stock.record_purchase(u, f, n, "0.5", today - timedelta(days=2), price="0")  # half a truck since: 1500 kg, about 5 days
    stock.set_warning_days(u, f, n, 6)
    at = open_page("pages/15_stock.py", u)
    assert not at.exception and at.warning and "napier" in at.warning[0].value
    home = open_page("app.py", u)
    assert not home.exception and any("napier" in w.value and "Feed stock" in w.value for w in home.warning)


def test_the_feed_stock_page_is_for_farmers_only(farm):
    vet = accounts.session_user(db.get_user(accounts.create_account("vet", "Dr Kibet", phone="0712345678")))
    at = open_page("pages/15_stock.py", vet)
    assert at.error and "not available" in at.error[0].value
