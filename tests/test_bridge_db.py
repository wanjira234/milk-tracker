"""Maziwa as a bridge: the shop's catalogue comes from its own system or a price list, farmers order for one of
the shop's time slots, the order is handed to the shop's system and its alert, and the shop confirms in the app.
Need TEST_DATABASE_URL."""
import os
from datetime import date, datetime, time, timedelta

import pytest

if not os.environ.get("TEST_DATABASE_URL"):
    pytest.skip("set TEST_DATABASE_URL to run DB tests", allow_module_level=True)

os.environ["DATABASE_URL"] = os.environ["TEST_DATABASE_URL"]

from streamlit.testing.v1 import AppTest  # noqa: E402

from src import accounts, bridges, catalogue, db, notifications, orders  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TODAY = date(2026, 11, 2)            # a Monday
EARLY = datetime(2026, 11, 2, 7, 0)  # before the shop opens
WEEK = {wd: {"opens": time(8), "closes": time(12), "delivers": wd == 1} for wd in range(6)}


@pytest.fixture(autouse=True)
def clean(monkeypatch):
    monkeypatch.setenv("APP_PASSWORD", "pw")
    db._query("TRUNCATE bridge_outbox, shop_hours, promotions, order_lines, orders, farm_agrovets, agrovet_products, feed_purchases, "
              "charge_payments, charges, feed_catalogue, farmers, users, routes, orgs RESTART IDENTITY CASCADE")


@pytest.fixture
def world():
    as_user = lambda uid: accounts.session_user(db.get_user(uid))  # noqa: E731
    farm = db.add_farmer("Mama A", "+254700000001", "A Farm")
    farmer = as_user(accounts.create_account("farmer", "Mama A", phone="0700000001", farmer_id=farm))
    shop = as_user(accounts.create_account("agrovet", "Mboga Center", phone="0720000000"))
    store = as_user(accounts.create_account("agrovet", "Fresha store", phone="0720000001"))
    db.set_shop_hours(shop["id"], WEEK, 60)
    return dict(farm=farm, farmer=farmer, shop=shop, store=store)


def test_the_bridge_fills_the_catalogue_and_out_of_stock_cannot_be_ordered(world):
    store = world["store"]
    with pytest.raises(ValueError, match="isn't connected"):
        bridges.sync(store)
    db.set_bridge(store["id"], "demo_fresha")
    n, off, problems = bridges.sync(store)
    assert n == 7 and off == 0 and not problems
    by_name = {p["name"]: p for p in db.list_products(store["id"])}
    assert by_name["Silage"]["in_stock"] is False and by_name["Dairy meal"]["source"] == "bridge"
    assert by_name["Dairy meal"]["external_ref"] == "FS-001" and db.shop(store["id"])["catalogue_synced_at"]
    with pytest.raises(ValueError, match="out of stock"):
        orders.place_order(world["farmer"], world["farm"], store["id"], [(by_name["Silage"]["id"], 1)], TODAY, "pickup", today=TODAY)
    oid = orders.place_order(world["farmer"], world["farm"], store["id"], [(by_name["Dairy meal"]["id"], 2)], TODAY, "pickup",
                             today=TODAY)
    pos, wa = sorted(db.outbox_for(store["id"]), key=lambda m: m["channel"])
    assert (pos["channel"], pos["event"], pos["status"], pos["external_ref"]) == ("pos", "placed", "sent", f"POS-{oid:05d}")
    assert pos["payload"]["lines"] == [{"item": "Dairy meal", "unit": "70 kg bag", "qty": 2.0}]
    assert wa["channel"] == "whatsapp" and wa["status"] == "queued" and "Dairy meal" in wa["payload"]["text"]


def test_an_uploaded_price_list_replaces_the_old_one(world):
    shop = world["shop"]
    orders.record_product(shop, "Old thing", "each", "100")
    n, off, _ = catalogue.upload(shop, "list.csv", b"Product,Unit,Price,In stock\nDairy meal,70 kg bag,2600,yes\nHay,bale,380,no\n")
    assert (n, off) == (2, 1) and {p["name"] for p in db.list_products(shop["id"])} == {"Dairy meal", "Hay"}
    with pytest.raises(ValueError, match="only an agrovet"):
        catalogue.upload(world["farmer"], "list.csv", b"Product,Price\nx,1\n")


def test_the_farmer_orders_for_a_slot_the_shop_serves_and_the_shop_keeps_it(world):
    shop, farmer, farm = world["shop"], world["farmer"], world["farm"]
    pid = orders.record_product(shop, "Dairy meal", "70 kg bag", "2600")
    tue = TODAY + timedelta(days=1)
    choices = dict(orders.available(db.shop(shop["id"]), "delivery", TODAY, now=EARLY))
    assert list(choices) == [tue, tue + timedelta(days=7)] and choices[tue][0] == time(8)
    for day, t, how, msg in ((TODAY, time(9), "delivery", "doesn't deliver"), (TODAY, time(9, 30), "pickup", "shop's times"),
                             (TODAY, None, "pickup", "choose a time"), (TODAY + timedelta(days=6), time(9), "pickup", "closed")):
        with pytest.raises(ValueError, match=msg):
            orders.place_order(farmer, farm, shop["id"], [(pid, 1)], day, how, today=TODAY, wanted_time=t, now=EARLY)
    oid = orders.place_order(farmer, farm, shop["id"], [(pid, 1)], tue, "delivery", today=TODAY, wanted_time=time(10), now=EARLY)
    assert db.get_order(oid)["wanted_time"] == time(10)
    assert [m["channel"] for m in db.outbox_for(shop["id"])] == ["whatsapp"]  # no POS bridge: the in-app alert is the inbox
    assert any("1 new order" in t for t, _ in notifications.for_user(shop, TODAY))
    orders.confirm_order(shop, oid, tue, today=TODAY)
    assert db.get_order(oid)["ready_time"] == time(10)
    later = orders.place_order(farmer, farm, shop["id"], [(pid, 1)], tue, "delivery", today=TODAY, wanted_time=time(8), now=EARLY)
    orders.confirm_order(shop, later, tue, today=TODAY, ready_time=time(9))
    assert [o["id"] for o in orders.rounds(shop, tue)["deliveries"]["no route"]] == [later, oid]  # by time


def test_hours_are_set_by_the_shop_only(world):
    rows = [{"weekday": 0, "open": True, "opens": time(9), "closes": time(13), "delivers": False}]
    orders.set_hours(world["shop"], rows, 30)
    assert db.shop_hours(world["shop"]["id"]) == {0: {"opens": time(9), "closes": time(13), "delivers": False}}
    assert db.shop(world["shop"]["id"])["slot_minutes"] == 30
    with pytest.raises(ValueError, match="only an agrovet"):
        orders.set_hours(world["farmer"], rows, 30)
    with pytest.raises(ValueError, match="at least one day"):
        orders.set_hours(world["shop"], [], 30)


def open_page(name, user):
    at = AppTest.from_file(os.path.join(ROOT, name), default_timeout=30)
    at.session_state["user"] = user
    return at.run()


def widget(at, kind, key):
    return next(w for w in getattr(at, kind) if w.key == key)


def test_the_pages_offer_the_shops_days_and_times(world):
    shop, farmer = world["shop"], world["farmer"]
    orders.record_product(shop, "Dairy meal", "70 kg bag", "2600")
    tomorrow = date.today() + timedelta(days=1)
    db.set_shop_hours(shop["id"], {wd: {"opens": time(8), "closes": time(10), "delivers": True} for wd in range(7)}, 60)
    at = open_page("pages/16_order.py", farmer)
    assert not at.exception
    day = widget(at, "selectbox", "order_day")
    assert "Tomorrow" in day.options
    day.set_value(tomorrow).run()
    assert [str(o) for o in widget(at, "selectbox", "order_time").options] == ["08:00-09:00", "09:00-10:00"]
    (product,) = db.list_products(shop["id"])
    widget(at, "number_input", f"qty_{product['id']}").set_value(1)
    widget(at, "selectbox", "order_time").set_value(time(9))
    next(b for b in at.button if b.label == "Send order").click().run()
    assert not at.exception
    (o,) = db.orders_for_farm(world["farm"])
    assert (o["wanted_on"], o["wanted_time"]) == (tomorrow, time(9))
    page = open_page("pages/17_orders.py", shop)
    assert not page.exception and any("09:00-10:00" in m.value for m in page.markdown)


def test_the_shop_saves_its_hours_on_the_page(world):
    shop = world["shop"]
    db._query("DELETE FROM shop_hours")
    at = open_page("pages/17_orders.py", shop)
    assert not at.exception and any("Hours" in i.value for i in at.info)
    next(b for b in at.button if b.label == "Save hours").click().run()
    assert not at.exception, at.exception
    h = db.shop_hours(shop["id"])
    assert sorted(h) == [0, 1, 2, 3, 4, 5] and h[0]["opens"] == time(8) and not h[0]["delivers"]
