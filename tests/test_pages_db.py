"""The calculator and the profit view, through the real pages against a real Postgres."""
import os
from datetime import date, timedelta

import pytest

if not os.environ.get("TEST_DATABASE_URL"):
    pytest.skip("set TEST_DATABASE_URL to run DB tests", allow_module_level=True)

os.environ["DATABASE_URL"] = os.environ["TEST_DATABASE_URL"]

from streamlit.testing.v1 import AppTest  # noqa: E402

from src import db  # noqa: E402

from src.auth import OWNER_USER  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


@pytest.fixture(autouse=True)
def clean(monkeypatch):
    monkeypatch.setenv("APP_PASSWORD", "pw")
    db._query("TRUNCATE sms_log, monthly_budgets, feed_logs, yield_logs, herd_log, feed_catalogue, farmers RESTART IDENTITY CASCADE")


def page(name):
    at = AppTest.from_file(os.path.join(ROOT, name), default_timeout=30)
    if name.startswith("pages/7_"):  # the admin page is the owner's; farm pages are a farmer's own view
        at.session_state["user"] = dict(OWNER_USER)
    else:
        farm = db.list_farmers()[0]
        at.session_state["user"] = {"id": None, "role": "farmer", "name": farm["name"],
                                    "farmer_id": farm["id"], "must_change_password": False}
    return at.run()


def widget(at, kind, key):
    return next(w for w in getattr(at, kind) if w.key == key)


def test_the_calculator_saves_a_truck_load_as_a_price_per_mtungi():
    fid = db.add_farmer("Sim", "+254700000001", "Sim Farm")
    at = page("pages/4_farm_setup.py")
    widget(at, "radio", "calc_how").set_value("I counted it in measures")
    at.run()
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


def test_a_truck_load_fed_in_buckets_is_priced_per_bucket():
    fid = db.add_farmer("Sim", "+254700000001", "Sim Farm")
    at = page("pages/4_farm_setup.py")  # the default way of counting is the truck load fed out in buckets
    widget(at, "text_input", "calc_name").set_value("napier")
    widget(at, "number_input", "calc_price").set_value(5000)
    widget(at, "number_input", "calc_days").set_value(10)
    widget(at, "number_input", "calc_perday").set_value(5)
    at.run()
    assert not at.exception and any("KES 100 a bucket" in m.value for m in at.markdown)  # 50 buckets
    assert not any(b.key == "calc_save" for b in at.button)  # no kg yet, so nothing to save
    widget(at, "number_input", "calc_bucket").set_value(15)
    at.run()
    assert any("One bucket of napier costs about KES 100" in m.value for m in at.markdown)
    widget(at, "button", "calc_save").click().run()
    item = db.list_catalogue(fid)[0]
    assert item["unit"] == "bucket" and float(item["kg_per_unit"]) == 15 and float(item["kes_per_unit"]) == 100


def test_wheat_bought_in_50_kg_bags_is_priced_per_bag():
    fid = db.add_farmer("Sim", "+254700000001", "Sim Farm")
    at = page("pages/4_farm_setup.py")
    widget(at, "radio", "calc_how").set_value("I counted it in measures")
    at.run()
    widget(at, "text_input", "calc_name").set_value("wheat bran")
    widget(at, "number_input", "calc_price").set_value(35000)
    widget(at, "selectbox", "calc_counted").select("50 kg bag")
    widget(at, "number_input", "calc_count").set_value(100)
    at.run()
    widget(at, "selectbox", "calc_pick").select("50 kg bag")
    widget(at, "button", "calc_save").click().run()
    item = db.list_catalogue(fid)[0]
    assert item["unit"] == "bag" and float(item["kg_per_unit"]) == 50 and float(item["kes_per_unit"]) == 350  # 5,000 kg for 35,000


def test_feed_grown_on_the_farm_can_be_saved_at_no_cost():
    fid = db.add_farmer("Sim", "+254700000001", "Sim Farm")
    at = page("pages/4_farm_setup.py")
    widget(at, "radio", "calc_source").set_value("I grow or harvest it on my farm")
    at.run()
    widget(at, "text_input", "calc_name").set_value("napier")
    widget(at, "number_input", "calc_days").set_value(10)
    widget(at, "number_input", "calc_perday").set_value(5)
    widget(at, "number_input", "calc_bucket").set_value(15)
    at.run()
    widget(at, "button", "calc_save").click().run()
    item = db.list_catalogue(fid)[0]
    assert item["unit"] == "bucket" and float(item["kes_per_unit"]) == 0


def test_the_calculator_refuses_a_save_with_no_feed_name():
    db.add_farmer("Sim", "+254700000001")
    at = page("pages/4_farm_setup.py")
    widget(at, "radio", "calc_how").set_value("I counted it in measures")
    at.run()
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
    assert at.get("vega_lite_chart"), "one complete day must still draw the milk chart (a dot, since a line needs two)"


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
    from src import accounts

    db._query("TRUNCATE users, routes RESTART IDENTITY CASCADE")
    fid = db.add_farmer("Sim", "+254700000001")
    vet = accounts.create_account("vet", "Dr K", phone="0712345678")
    route = accounts.record_route("4A")
    accounts.allocate_vet(route, vet)
    accounts.assign_route(fid, route)
    db.add_vet_semen(vet, "Friesian - Kamau", 3500)  # the farmer picks from the route vet's list
    at = page("pages/5_cows.py")
    assert not any(t.key == "new_semen" for t in at.text_input)  # a farmer cannot make up semen choices
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


def test_with_no_route_vet_a_service_is_saved_without_semen():
    from src import accounts

    db._query("TRUNCATE users, routes RESTART IDENTITY CASCADE")
    fid = db.add_farmer("Sim", "+254700000001")
    db.add_cow(fid, "Wanjiku")
    at = page("pages/5_cows.py")
    at.selectbox(key="ev_kind").set_value("served")
    at.run()
    assert not at.exception and not [x for x in at.selectbox if x.key == "ev_semen"]
    assert any("not on a route" in c.value for c in at.caption)


def test_the_cows_page_refuses_a_pregnancy_result_with_no_service():
    fid = db.add_farmer("Sim", "+254700000001")
    db.add_cow(fid, "Wanjiku")
    at = page("pages/5_cows.py")
    at.selectbox(key="ev_kind").set_value("confirmed_pregnant")
    next(b for b in at.button if b.key == "ev_save").click()
    at.run()
    assert any("service first" in e.value for e in at.error) and db.breeding_events(fid) == []


def _all_text(at):
    return " ".join([m.value for m in at.markdown] + [c.value for c in at.caption])


def test_calving_adds_a_calf_with_its_mother_and_weaning_makes_a_heifer():
    fid = db.add_farmer("Sim", "+254700000001")
    db.add_cow(fid, "Wanjiku")
    at = page("pages/5_cows.py")
    at.selectbox(key="ev_kind").set_value("calved")
    at.run()
    at.text_input(key="ev_calf_tag").set_value("Nyota")
    at.date_input(key="ev_date").set_value(date.today() - timedelta(days=100))
    next(b for b in at.button if b.key == "ev_save").click()
    at.run()
    assert not at.exception
    text = _all_text(at)
    assert "Mother: Wanjiku" in text and "Calves: Nyota" in text and "Female calf, still on milk" in text
    next(b for b in at.button if b.key == "wean_save").click()
    at.run()
    assert not at.exception
    text = _all_text(at)
    assert "Waiting for first heat" in text and "Mother: Wanjiku" in text  # a heifer now, still linked to her mother
    assert [h["tag"] for h in db.list_cows(fid) if h["kind"] == "heifer"] == ["Nyota"]


def test_the_page_offers_to_update_cows_in_milk_from_the_cow_records():
    fid = db.add_farmer("Sim", "+254700000001")
    for tag in ("A", "B", "C"):
        db.add_cow(fid, tag)
    db.add_breeding_event(fid, db.list_cows(fid)[0]["id"], date.today(), "dried_off")  # one cow dry: 2 milking
    db.set_cows_in_milk(fid, date.today() - timedelta(days=5), 3)
    at = page("pages/5_cows.py")
    button = next(b for b in at.button if b.key == "sync_milking")
    assert "2" in button.label
    button.click()
    at.run()
    assert not at.exception and db.cows_in_milk_on(fid, date.today()) == 2
    assert not [b for b in at.button if b.key == "sync_milking"]  # nothing left to sync


def test_adding_a_heifer_and_a_calf_with_a_mother():
    fid = db.add_farmer("Sim", "+254700000001")
    mother = db.add_cow(fid, "Wanjiku")
    at = page("pages/5_cows.py")
    at.radio(key="add_kind").set_value("calf")
    at.run()
    at.text_input(key="new_cow").set_value("Nyota")
    at.selectbox(key="add_dam").set_value(mother)
    next(b for b in at.button if b.key == "add_cow").click()
    at.run()
    assert not at.exception
    calf = next(c for c in db.list_cows(fid) if c["tag"] == "Nyota")
    assert calf["kind"] == "calf" and calf["dam_id"] == mother


def test_admin_page_creates_routes_a_vet_and_a_farmer_login():
    db._query("TRUNCATE users, routes RESTART IDENTITY CASCADE")
    fid = db.add_farmer("Sim", "+254700000001", "Sim Farm")
    at = page("pages/7_admin.py")
    widget(at, "button", "example_routes").click().run()
    assert [r["code"] for r in db.list_routes()] == ["4A", "4B", "5A"]
    at = page("pages/7_admin.py")
    widget(at, "selectbox", "new_role").select("vet")
    widget(at, "text_input", "new_name").set_value("Dr Kibet")
    widget(at, "text_input", "new_phone").set_value("0712345678")
    next(b for b in at.button if b.label == "Create login").click().run()
    assert not at.exception and db.list_users("vet")[0]["name"] == "Dr Kibet"
    at = page("pages/7_admin.py")
    widget(at, "selectbox", "alloc_vet").select(db.list_users("vet")[0]["id"])
    next(b for b in at.button if b.label == "Allocate").click().run()
    assert db.list_routes()[0]["vet_name"] == "Dr Kibet"
    at = page("pages/7_admin.py")
    widget(at, "selectbox", "assign_route").select(db.list_routes()[0]["id"])
    next(b for b in at.button if b.label == "Assign").click().run()
    assert db.farmers_on_vet_routes(db.list_users("vet")[0]["id"])[0]["id"] == fid


def test_a_vet_sees_only_route_farms_and_the_home_page_is_a_visit_overview():
    from src import accounts

    db._query("TRUNCATE users, routes RESTART IDENTITY CASCADE")
    mine, other = db.add_farmer("Mine", "+254700000001"), db.add_farmer("Other", "+254700000002")
    vet = accounts.create_account("vet", "Dr K", phone="0712345678")
    route = accounts.record_route("4A")
    accounts.allocate_vet(route, vet)
    accounts.assign_route(mine, route)
    user = accounts.session_user(db.get_user(vet))
    assert [f["name"] for f in accounts.visible_farmers(user)] == ["Mine"]
    at = AppTest.from_file(os.path.join(ROOT, "app.py"), default_timeout=30)
    at.session_state["user"] = user
    at.run()
    assert not at.exception and not at.sidebar.selectbox  # no farm picker: the vet's home is about visits
    assert [m.label for m in at.metric] == ["Visits today", "Done", "Waiting for a day"]
