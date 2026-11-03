"""The pre-order journey through the real pages: the farmer picks a shop from the list and pays by M-Pesa,
the agrovet confirms, sees the payment and hands over; both see the money and the feed stock goes up.
Need TEST_DATABASE_URL."""
import os
from datetime import date

import pytest

if not os.environ.get("TEST_DATABASE_URL"):
    pytest.skip("set TEST_DATABASE_URL to run DB tests", allow_module_level=True)

os.environ["DATABASE_URL"] = os.environ["TEST_DATABASE_URL"]

from streamlit.testing.v1 import AppTest  # noqa: E402

from src import accounts, db, orders, stock  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


@pytest.fixture(autouse=True)
def clean(monkeypatch):
    monkeypatch.setenv("APP_PASSWORD", "pw")
    db._query("TRUNCATE promotions, order_lines, orders, farm_agrovets, agrovet_products, feed_stock_counts, feed_purchases, "
              "charge_payments, charges, feed_logs, feed_catalogue, farmers, users, routes, orgs RESTART IDENTITY CASCADE")


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
    db.set_farm_town(farm, "Limuru")
    as_user = lambda uid: accounts.session_user(db.get_user(uid))  # noqa: E731
    farmer = as_user(accounts.create_account("farmer", "Mama A", phone="0700000001", farmer_id=farm))
    shop = as_user(accounts.create_account("agrovet", "Mboga Center", phone="0720000000"))
    db.upsert_catalogue_item(farm, "dairy meal", "bag", 70, 2600)
    return dict(farm=farm, farmer=farmer, shop=shop)


def test_the_whole_pre_order_journey(world):
    farmer, shop, farm = world["farmer"], world["shop"], world["farm"]

    # the agrovet sets up the shop (town and till) and lists dairy meal
    at = open_page("pages/17_orders.py", shop)
    assert at.warning and "My shop" in at.warning[0].value
    widget(at, "text_input", "shop_town").set_value("Limuru")
    widget(at, "text_input", "shop_number").set_value("123456")
    press(at, "Save")
    assert not at.exception and db.shop(shop["id"])["pay_number"] == "123456"
    at = open_page("pages/17_orders.py", shop)
    widget(at, "text_input", "p_name").set_value("Dairy meal")
    widget(at, "text_input", "p_unit").set_value("70 kg bag")
    widget(at, "text_input", "p_price").set_value("2600")
    press(at, "Add or update")
    (product,) = db.list_products(shop["id"])

    # the farmer sees the shop in the list (near her), orders 2 bags to pay by M-Pesa
    at = open_page("pages/16_order.py", farmer)
    assert not at.exception and "near you" in widget(at, "selectbox", "order_shop").options[0]
    assert any("Adds to your dairy meal stock" in m.value for m in at.markdown)
    widget(at, "number_input", f"qty_{product['id']}").set_value(2)
    widget(at, "radio", "order_pay").set_value("mpesa")
    press(at, "Send order")
    assert not at.exception
    (o,) = db.orders_for_farm(farm)
    assert o["status"] == "requested" and o["payment_method"] == "mpesa"

    # the agrovet confirms it for today
    at = open_page("pages/17_orders.py", shop)
    widget(at, "date_input", f"ready_{o['id']}").set_value(date.today())
    press(at, "Confirm at today's prices")
    assert not at.exception and db.get_order(o["id"])["status"] == "confirmed"

    # the farmer sees where to pay and enters the code
    at = open_page("pages/16_order.py", farmer)
    assert any("Till 123456" in i.value and "KES 5,200" in i.value for i in at.info)
    widget(at, "text_input", f"code_{o['id']}").set_value("SK3ABC12XY")
    press(at, "I've paid")
    assert not at.exception and db.get_order(o["id"])["payment_status"] == "reported"

    # the agrovet sees the code, confirms the money arrived, and hands over
    at = open_page("pages/17_orders.py", shop)
    assert any(m.label == "Payments to check" and m.value == "1" for m in at.metric)
    assert any("SK3ABC12XY" in i.value for i in at.info)
    press(at, "Payment received")
    assert not at.exception and db.get_order(o["id"])["payment_status"] == "received"
    at = open_page("pages/17_orders.py", shop)
    press(at, "Handed over")
    assert not at.exception and db.get_order(o["id"])["status"] == "collected"

    # both sides see it; the farm's dairy meal stock went up by 2 bags; the sales tab shows it
    at = open_page("pages/16_order.py", farmer)
    assert any("Collected" in c.value for c in at.caption)
    (s,) = stock.farm_stock(farm, date.today())
    assert s["on_hand_kg"] == 140
    assert orders.sales(shop)["kes"] == 5200
    at = open_page("pages/17_orders.py", shop)
    assert any(m.label == "Sold, last 30 days" and m.value == "KES 5,200" for m in at.metric)


def test_a_shop_without_a_till_takes_cash_only(world):
    orders.set_shop(world["shop"], "Limuru", "till", "")
    orders.record_product(world["shop"], "Dairy meal", "70 kg bag", "2600")
    at = open_page("pages/16_order.py", world["farmer"])
    assert widget(at, "radio", "order_pay").options == ["Cash when I collect"]


def test_agrovets_cannot_open_farm_or_alert_pages(world):
    for page in ("pages/11_alerts.py", "pages/12_vaccination.py", "pages/16_order.py", "pages/15_stock.py", "pages/1_dashboard.py"):
        at = open_page(page, world["shop"])
        assert at.error and "not available" in at.error[0].value, page
    home = open_page("app.py", world["shop"])
    assert not home.exception and any(m.label == "New orders" for m in home.metric)
