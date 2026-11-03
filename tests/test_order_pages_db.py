"""The pre-order journey through the real pages: farmer orders, agrovet confirms and hands over,
both see the money, and the farm's feed stock goes up. Need TEST_DATABASE_URL."""
import os
from datetime import date

import pytest

if not os.environ.get("TEST_DATABASE_URL"):
    pytest.skip("set TEST_DATABASE_URL to run DB tests", allow_module_level=True)

os.environ["DATABASE_URL"] = os.environ["TEST_DATABASE_URL"]

from streamlit.testing.v1 import AppTest  # noqa: E402

from src import accounts, db, ledger, stock  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


@pytest.fixture(autouse=True)
def clean(monkeypatch):
    monkeypatch.setenv("APP_PASSWORD", "pw")
    db._query("TRUNCATE order_lines, orders, farm_agrovets, agrovet_products, feed_stock_counts, feed_purchases, charge_payments, "
              "charges, feed_logs, feed_catalogue, farmers, users, routes RESTART IDENTITY CASCADE")


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
    farm = db.add_farmer("Mama A", "+254700000001", "A Farm")
    as_user = lambda uid: accounts.session_user(db.get_user(uid))  # noqa: E731
    farmer = as_user(accounts.create_account("farmer", "Mama A", phone="0700000001", farmer_id=farm))
    shop = as_user(accounts.create_account("agrovet", "Mboga Center", phone="0720000000"))
    feed = db.upsert_catalogue_item(farm, "dairy meal", "bag", 70, 2600)
    return dict(farm=farm, farmer=farmer, shop=shop, feed=feed)


def test_the_whole_pre_order_journey(world):
    farmer, shop, farm = world["farmer"], world["shop"], world["farm"]

    # the agrovet lists dairy meal
    at = open_page("pages/17_orders.py", shop)
    widget(at, "text_input", "p_name").set_value("Dairy meal")
    widget(at, "text_input", "p_unit").set_value("70 kg bag")
    widget(at, "text_input", "p_price").set_value("2600")
    press(at, "Add or update")
    assert not at.exception
    (product,) = db.list_products(shop["id"])

    # the farmer adds the shop by phone and orders 2 bags, tied to her dairy meal (guessed from the name)
    at = open_page("pages/16_order.py", farmer)
    widget(at, "text_input", "shop_phone").set_value("0720 000 000")
    press(at, "Add agrovet")
    assert not at.exception
    at = open_page("pages/16_order.py", farmer)
    assert widget(at, "selectbox", f"feed_{product['id']}").value == world["feed"]
    widget(at, "number_input", f"qty_{product['id']}").set_value(2.0)
    press(at, "Send order")
    assert not at.exception
    (o,) = db.orders_for_farm(farm)
    assert o["status"] == "requested"

    # the agrovet confirms it for today and hands it over on credit
    at = open_page("pages/17_orders.py", shop)
    assert any(m.label == "New orders" and m.value == "1" for m in at.metric)
    widget(at, "date_input", f"ready_{o['id']}").set_value(date.today())  # she wanted it tomorrow; it's ready today
    press(at, "Confirm at today's prices")
    assert not at.exception and db.get_order(o["id"])["status"] == "confirmed"
    at = open_page("pages/17_orders.py", shop)
    widget(at, "radio", f"hterms_{o['id']}").set_value("credit")
    press(at, "Handed over")
    assert not at.exception and db.get_order(o["id"])["status"] == "collected"

    # both sides see the bill; the farm's dairy meal stock went up by 2 bags
    assert sum(ledger.owed(c) for c in db.charges_for_farm(farm)) == 5200
    at = open_page("pages/14_money.py", shop)
    assert not at.exception and any(m.label == "Owed to you" and m.value == "KES 5,200" for m in at.metric)
    at = open_page("pages/14_money.py", farmer)
    assert any("Mboga Center" in m.value and "KES 5,200" in m.value for m in at.markdown)
    (s,) = stock.farm_stock(farm, date.today())
    assert s["on_hand_kg"] == 140
    at = open_page("pages/16_order.py", farmer)
    assert any("collected" in m.value for m in at.markdown)


def test_agrovet_home_and_who_can_open_what(world):
    home = open_page("app.py", world["shop"])
    assert not home.exception and any(m.label == "New orders" for m in home.metric)
    for page, allowed in (("pages/17_orders.py", "agrovet"), ("pages/16_order.py", "farmer"), ("pages/15_stock.py", "farmer"),
                          ("pages/8_my_day.py", "vet"), ("pages/1_dashboard.py", "farmer")):
        for who in (world["farmer"], world["shop"]):
            at = open_page(page, who)
            blocked = bool(at.error and "not available" in at.error[0].value)
            assert blocked == (who["role"] != allowed), (page, who["role"])
