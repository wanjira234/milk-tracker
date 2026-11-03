"""Choosing a vet, billing a visit and the Money page, through the real pages. Need TEST_DATABASE_URL."""
import os
from datetime import date

import pytest

if not os.environ.get("TEST_DATABASE_URL"):
    pytest.skip("set TEST_DATABASE_URL to run DB tests", allow_module_level=True)

os.environ["DATABASE_URL"] = os.environ["TEST_DATABASE_URL"]

from streamlit.testing.v1 import AppTest  # noqa: E402

from src import accounts, db, ledger  # noqa: E402
from src.auth import OWNER_USER  # noqa: E402
from src.ingestion import manual_entry as me  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


@pytest.fixture(autouse=True)
def clean(monkeypatch):
    monkeypatch.setenv("APP_PASSWORD", "pw")
    db._query("TRUNCATE charge_payments, charges, farm_vets, sms_log, feed_logs, yield_logs, farmers, users, routes "
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
def world():
    route = accounts.record_route("4A")
    kibet = accounts.create_account("vet", "Dr Kibet", phone="0712345678")
    wanjiku = accounts.create_account("vet", "Dr Wanjiku", phone="0733333333")
    accounts.allocate_vet(route, kibet)
    farm = db.add_farmer("Mama A", "+254700000001", "A Farm")
    accounts.assign_route(farm, route)
    farmer = accounts.create_account("farmer", "Mama A", phone="0700000001", farmer_id=farm)
    me.record_cow(farm, "Njeri")
    as_user = lambda uid: accounts.session_user(db.get_user(uid))  # noqa: E731
    return dict(farm=farm, farmer=as_user(farmer), kibet=as_user(kibet), wanjiku=as_user(wanjiku))


def test_farmer_adds_her_own_vet_who_bills_on_credit_and_takes_payment(world):
    farmer, wanjiku, farm = world["farmer"], world["wanjiku"], world["farm"]

    # she adds Dr Wanjiku by phone and sends her a sick-cow request
    at = open_page("pages/9_ask_the_vet.py", farmer)
    widget(at, "text_input", "vet_phone").set_value("0733 333 333")
    press(at, "Add vet")
    assert not at.exception and [v["name"] for v in db.farm_vets(farm)] == ["Dr Wanjiku"]
    at = open_page("pages/9_ask_the_vet.py", farmer)
    widget(at, "selectbox", "req_vet").select(wanjiku["id"])
    at.run()
    widget(at, "radio", "req_kind").set_value("sick").run()
    widget(at, "selectbox", "req_cow").select(db.list_cows(farm)[0]["id"])
    press(at, "Send request")
    assert not at.exception
    (req,) = db.requests_for_farm(farm)
    assert req["vet_user_id"] == wanjiku["id"]

    # the route vet doesn't see it; Dr Wanjiku books it and bills the visit on credit
    assert not any("A Farm" in m.value for m in open_page("pages/8_my_day.py", world["kibet"]).markdown)
    at = open_page("pages/8_my_day.py", wanjiku)
    press(at, "Book")
    at = open_page("pages/8_my_day.py", wanjiku)
    assert widget(at, "radio", f"terms_{req['id']}").options == ["On credit", "Paid now"]  # no milk deduction for her
    widget(at, "text_input", f"fee_{req['id']}").set_value("800")
    widget(at, "text_input", f"drugs_{req['id']}").set_value("1200")
    press(at, "Mark done")
    assert not at.exception and db.get_request(req["id"])["status"] == "done"
    assert sum(ledger.owed(c) for c in db.charges_for_request(req["id"])) == 2000

    # her Money page shows the debt; she records a part payment
    at = open_page("pages/14_money.py", wanjiku)
    assert not at.exception and any(m.label == "Owed to you" and m.value == "KES 2,000" for m in at.metric)
    form_key = next(w.key for w in at.text_input if w.key.startswith("pay_") and w.key.endswith("_amt"))
    widget(at, "text_input", form_key).set_value("500")
    press(at, "Record payment")
    assert not at.exception
    assert sum(ledger.owed(c) for c in db.charges_for_request(req["id"])) == 1500

    # the farmer's Money page shows what she owes Dr Wanjiku
    at = open_page("pages/14_money.py", farmer)
    assert not at.exception
    assert any("Dr Wanjiku" in m.value and "KES 1,500" in m.value for m in at.markdown)


def test_farmer_records_an_agrovet_cost_and_sees_it_in_the_statement(world):
    farmer, farm = world["farmer"], world["farm"]
    db.set_milk_price(farm, 50)
    for session in ("morning", "afternoon", "evening"):
        db.upsert_yield(farm, date.today(), session, 20)
    at = open_page("pages/14_money.py", farmer)
    widget(at, "text_input", "cost_from").set_value("Mboga Center")
    widget(at, "text_input", "cost_amt").set_value("1500")
    widget(at, "radio", "cost_terms").set_value("milk_deduction")
    press(at, "Save")
    assert not at.exception
    at = open_page("pages/14_money.py", farmer)
    metrics = {m.label: m.value for m in at.metric}
    assert metrics["Milk income"] == "KES 3,000" and metrics["Buyer deductions"] == "KES 1,500"
    assert metrics["Expected payout"] == "KES 1,500"


def test_a_bad_amount_shows_an_error_and_saves_nothing(world):
    at = open_page("pages/14_money.py", world["farmer"])
    widget(at, "text_input", "cost_from").set_value("Mboga Center")
    widget(at, "text_input", "cost_amt").set_value("lots")
    press(at, "Save")
    assert at.error and "shillings" in at.error[0].value and db.charges_for_farm(world["farm"]) == []


def test_the_money_page_is_closed_to_admins(world):
    for who in (dict(OWNER_USER), world["farmer"], world["kibet"]):
        at = open_page("pages/14_money.py", who)
        blocked = bool(at.error and "not available" in at.error[0].value)
        assert blocked == (who["role"] == "admin")
