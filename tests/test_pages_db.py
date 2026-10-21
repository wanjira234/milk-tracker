"""The calculator and the profit view, through the real pages against a real Postgres."""
import os
from datetime import date, timedelta

import pytest

if not os.environ.get("TEST_DATABASE_URL"):
    pytest.skip("set TEST_DATABASE_URL to run DB tests", allow_module_level=True)

os.environ["DATABASE_URL"] = os.environ["TEST_DATABASE_URL"]

from streamlit.testing.v1 import AppTest  # noqa: E402

from src import db  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


@pytest.fixture(autouse=True)
def clean(monkeypatch):
    monkeypatch.setenv("APP_PASSWORD", "pw")
    db._query("TRUNCATE sms_log, monthly_budgets, feed_logs, yield_logs, herd_log, feed_catalogue, farmers RESTART IDENTITY CASCADE")


def page(name):
    at = AppTest.from_file(os.path.join(ROOT, name), default_timeout=30)
    at.session_state["logged_in"] = True
    return at.run()


def widget(at, kind, key):
    return next(w for w in getattr(at, kind) if w.key == key)


def test_the_calculator_saves_a_truck_load_as_a_price_per_mtungi():
    fid = db.add_farmer("Sim", "+254700000001", "Sim Farm")
    at = page("pages/4_farm_setup.py")
    widget(at, "text_input", "calc_name").set_value("napier")
    widget(at, "number_input", "calc_price").set_value(15000)
    widget(at, "selectbox", "calc_counted").select("big mtungi (about 20 kg)")
    widget(at, "number_input", "calc_count").set_value(150)
    at.run()
    assert not at.exception and any("5.00 per kg" in m.value for m in at.markdown)
    widget(at, "selectbox", "calc_pick").select("big mtungi (about 20 kg)")
    widget(at, "button", "calc_save").click().run()
    assert not at.exception
    item = db.list_catalogue(fid)[0]
    assert item["name"] == "napier" and item["unit"] == "mtungi"
    assert float(item["kg_per_unit"]) == 20 and float(item["kes_per_unit"]) == 100


def test_the_calculator_refuses_a_save_with_no_feed_name():
    db.add_farmer("Sim", "+254700000001")
    at = page("pages/4_farm_setup.py")
    widget(at, "number_input", "calc_price").set_value(15000)
    widget(at, "number_input", "calc_count").set_value(150)
    at.run()
    widget(at, "button", "calc_save").click().run()
    assert any("name is required" in e.value for e in at.error)


def test_the_dashboard_shows_profit_in_plain_words():
    fid = db.add_farmer("Sim", "+254700000001")
    db.set_milk_price(fid, 50)
    day = date.today() - timedelta(days=1)
    for session, litres in (("morning", 40), ("afternoon", 25), ("evening", 35)):
        db.upsert_yield(fid, day, session, litres)  # 100 L = KES 5,000
    db.add_feed(fid, day, "napier", 500, 1000)
    at = page("pages/1_dashboard.py")
    assert not at.exception
    text = " ".join(m.value for m in at.markdown)
    assert "100 litres" in text and "KES 5,000" in text and "KES 1,000" in text
    assert [m.value for m in at.metric if m.label == "Left after feed"] == ["KES 4,000"]
    assert "KES 20" in text  # out of every KES 100 of milk, KES 20 went on feed


def test_water_logged_in_buckets_is_saved_in_litres_and_shown_on_the_dashboard():
    fid = db.add_farmer("Sim", "+254700000001")
    db.set_cows_in_milk(fid, date.today() - timedelta(days=30), 5)
    at = page("pages/2_feed_log.py")
    at.number_input(key="w_amount").set_value(6.0)  # 6 buckets of 20 L (the default unit)
    next(b for b in at.button if b.label == "Save water").click()
    at.run()
    assert not at.exception and any("120 L of water" in s.value for s in at.success)
    assert [float(r["litres"]) for r in db.daily_water(fid, date.today(), date.today())] == [120.0]
    for session in ("morning", "afternoon", "evening"):  # a full day, so the dashboard has something to show
        db.upsert_yield(fid, date.today() - timedelta(days=1), session, 10)
    dash = page("pages/1_dashboard.py")
    assert not dash.exception
    assert {m.label: m.value for m in dash.metric}["Water per cow in milk"] == "24 L"  # 120 L / 5 cows


def test_the_cows_page_adds_a_cow_records_a_service_and_shows_her_status():
    fid = db.add_farmer("Sim", "+254700000001")
    db.add_semen(fid, "Friesian - Kamau")
    at = page("pages/5_cows.py")
    at.text_input(key="new_cow").set_value("Wanjiku")
    next(b for b in at.button if b.key == "add_cow").click()
    at.run()
    assert not at.exception and [c["tag"] for c in db.list_cows(fid)] == ["Wanjiku"]
    at.selectbox(key="ev_kind").set_value("served")
    at.run()
    assert at.selectbox(key="ev_semen").options  # the semen list appears once a service is chosen
    at.date_input(key="ev_date").set_value(date.today() - timedelta(days=30))
    next(b for b in at.button if b.key == "ev_save").click()
    at.run()
    assert not at.exception
    text = " ".join(m.value for m in at.markdown) + " ".join(c.value for c in at.caption)
    assert "Wanjiku" in text and "Served" in text and "Friesian - Kamau" in text
    assert "Deworming: Never recorded" in text
    assert any("Saved" in s.value for s in at.success)  # the message survives the reload


def test_the_cows_page_refuses_a_pregnancy_result_with_no_service():
    fid = db.add_farmer("Sim", "+254700000001")
    db.add_cow(fid, "Wanjiku")
    at = page("pages/5_cows.py")
    at.selectbox(key="ev_kind").set_value("confirmed_pregnant")
    next(b for b in at.button if b.key == "ev_save").click()
    at.run()
    assert any("service first" in e.value for e in at.error) and db.breeding_events(fid) == []
