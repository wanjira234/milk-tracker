"""Agrovets, pre-orders, payments, hand-over, promotions and sales, against real Postgres. Need TEST_DATABASE_URL."""
import os
import threading
from datetime import date, timedelta

import pytest

if not os.environ.get("TEST_DATABASE_URL"):
    pytest.skip("set TEST_DATABASE_URL to run DB tests", allow_module_level=True)

os.environ["DATABASE_URL"] = os.environ["TEST_DATABASE_URL"]

from src import accounts, alerts, db, ledger, orders, stock  # noqa: E402

TODAY = date(2026, 11, 3)


@pytest.fixture(autouse=True)
def clean():
    db._query("TRUNCATE promotions, order_lines, orders, farm_agrovets, agrovet_products, feed_stock_counts, feed_purchases, "
              "charge_payments, charges, feed_logs, feed_catalogue, sms_log, farmers, users, routes, orgs RESTART IDENTITY CASCADE")


@pytest.fixture
def world():
    org = db.add_org("Fresha")
    route = accounts.record_route("4A")
    db.set_route_org(route, org)
    farm_a, farm_b = db.add_farmer("Mama A", "+254700000001", "A Farm"), db.add_farmer("Mama B", "+254700000002", "B Farm")
    accounts.assign_route(farm_a, route)
    db.set_farm_town(farm_a, "Limuru")
    as_user = lambda uid: accounts.session_user(db.get_user(uid))  # noqa: E731
    user_a = as_user(accounts.create_account("farmer", "Mama A", phone="0700000001", farmer_id=farm_a))
    user_b = as_user(accounts.create_account("farmer", "Mama B", phone="0700000002", farmer_id=farm_b))
    mboga = as_user(accounts.create_account("agrovet", "Mboga Center", phone="0720000000"))
    rival = as_user(accounts.create_account("agrovet", "Other Agrovet", phone="0721111111"))
    store = as_user(accounts.create_account("agrovet", "Fresha store", phone="0722222222"))
    db.set_user_org(store["id"], org)
    orders.set_shop(mboga, "Limuru", "till", "123456")
    orders.set_shop(rival, "Kiambu", "paybill", "400200", "A Farm")
    orders.set_shop(store, "Githunguri", "till", "654321")
    meal = orders.record_product(mboga, "Dairy meal", "70 kg bag", "2,600")
    lick = orders.record_product(mboga, "Mineral lick", "block", "900")
    rival_meal = orders.record_product(rival, "Dairy meal", "70 kg bag", "2,500")
    store_meal = orders.record_product(store, "Dairy meal", "70 kg bag", "2,550")
    feed = db.upsert_catalogue_item(farm_a, "dairy meal", "bag", 70, 2600)
    return dict(org=org, farm_a=farm_a, farm_b=farm_b, user_a=user_a, user_b=user_b, mboga=mboga, rival=rival, store=store,
                meal=meal, lick=lick, rival_meal=rival_meal, store_meal=store_meal, feed=feed)


def order(w, lines=None, pay="mpesa", shop="mboga", **kw):
    lines = lines if lines is not None else [(w["meal"], "2"), (w["lick"], "1")]
    return orders.place_order(w["user_a"], w["farm_a"], w[shop]["id"], lines, TODAY + timedelta(days=1), "pickup", pay,
                              today=TODAY, **kw)


def confirmed(w, **kw):
    oid = order(w, **kw)
    orders.confirm_order(w[kw.get("shop", "mboga")], oid, TODAY, today=TODAY)
    return oid


# --- the shop list and profile -------------------------------------------------------------------


def test_farmers_see_every_shop_with_products_their_own_town_first(world):
    assert [s["name"] for s in orders.shops_for(world["farm_a"])] == ["Mboga Center", "Fresha store", "Other Agrovet"]
    assert [s["name"] for s in orders.shops_for(world["farm_b"])] == ["Fresha store", "Mboga Center", "Other Agrovet"]  # no town: by name
    lonely = accounts.session_user(db.get_user(accounts.create_account("agrovet", "No Products", phone="0723333333")))
    orders.set_shop(lonely, "Limuru", "till", "111111")
    assert "No Products" not in [s["name"] for s in orders.shops_for(world["farm_a"])]  # nothing to order yet


def test_shop_details_are_checked(world):
    for args, why in ((("", "till", "123456"), "town"), (("Limuru", "till", "12"), "5 to 10 digits"),
                      (("Limuru", "nope", "123456"), "Till or Paybill")):
        with pytest.raises(ValueError, match=why):
            orders.set_shop(world["mboga"], *args)
    orders.set_shop(world["mboga"], "Limuru", "till", "", None)  # no M-Pesa number: cash only
    assert orders.payment_options(world["farm_a"], db.shop(world["mboga"]["id"])) == ["cash"]
    with pytest.raises(ValueError, match="only an agrovet"):
        orders.set_shop(world["user_a"], "Limuru", "till", "123456")
    assert orders.where_to_pay(db.shop(world["rival"]["id"])) == "Paybill 400200, account A Farm"


def test_only_the_buyers_own_store_can_take_milk_money(world):
    assert "milk_deduction" in orders.payment_options(world["farm_a"], db.shop(world["store"]["id"]))
    assert "milk_deduction" not in orders.payment_options(world["farm_a"], db.shop(world["mboga"]["id"]))
    assert "milk_deduction" not in orders.payment_options(world["farm_b"], db.shop(world["store"]["id"]))  # not on Fresha's route
    with pytest.raises(ValueError, match="doesn't take that"):
        order(world, pay="milk_deduction")


def test_an_agrovet_sees_no_farms_no_texts_and_no_alerts_page(world):
    assert accounts.visible_farmers(world["mboga"]) == []
    db.log_sms(world["farm_a"], "hello", status="sent")
    assert alerts.outbox(world["mboga"]) == []


# --- products match the farm's feeds -------------------------------------------------------------


def test_products_match_the_farms_feeds_and_their_kg():
    feeds = [{"id": 1, "name": "dairy meal", "unit": "bag", "kg_per_unit": 70},
             {"id": 2, "name": "hay", "unit": "bale", "kg_per_unit": 15}]
    assert orders.match_feed({"name": "Dairy meal 18%", "unit": "70 kg bag"}, feeds) == (feeds[0], 70)
    assert orders.match_feed({"name": "Hay", "unit": "bale"}, feeds)[1] == 15           # same unit as the farm's
    assert orders.match_feed({"name": "Hay", "unit": "tonne"}, feeds) == (None, None)  # can't tell the kg
    assert orders.match_feed({"name": "Mineral lick", "unit": "block"}, feeds) == (None, None)


# --- placing and paying --------------------------------------------------------------------------


def test_a_farmer_orders_from_any_shop_and_lines_match_her_feeds(world):
    oid = order(world, notes="before Friday please")
    o = db.get_order(oid)
    assert o["status"] == "requested" and o["payment_method"] == "mpesa" and o["payment_status"] == "unpaid"
    lines = db.order_lines(oid)
    assert [(ln["product_name"], float(ln["qty"]), ln["catalogue_id"], ln["kg_each"] and float(ln["kg_each"])) for ln in lines] == [
        ("Dairy meal", 2.0, world["feed"], 70.0), ("Mineral lick", 1.0, None, None)]
    assert [x["id"] for x in db.orders_for_agrovet(world["mboga"]["id"], ("requested",))] == [oid]
    assert db.orders_for_agrovet(world["rival"]["id"], ("requested",)) == []


def test_ordering_rules(world):
    w = world
    with pytest.raises(ValueError, match="this agrovet's list"):
        order(w, lines=[(w["rival_meal"], "1")])
    with pytest.raises(ValueError, match="at least one product"):
        order(w, lines=[(w["meal"], 0)])
    with pytest.raises(ValueError, match="at most 1,000"):
        order(w, lines=[(w["meal"], "5000")])
    with pytest.raises(ValueError, match="your own farm"):
        orders.place_order(w["user_b"], w["farm_a"], w["mboga"]["id"], [(w["meal"], "1")], TODAY, "pickup", "cash", today=TODAY)
    with pytest.raises(ValueError, match="list"):
        orders.place_order(w["user_a"], w["farm_a"], w["user_b"]["id"], [(w["meal"], "1")], TODAY, "pickup", "cash", today=TODAY)
    with pytest.raises(ValueError, match="past"):
        orders.place_order(w["user_a"], w["farm_a"], w["mboga"]["id"], [(w["meal"], "1")], TODAY - timedelta(days=1), "pickup",
                           "cash", today=TODAY)


def test_mpesa_farmer_reports_the_code_and_the_shop_confirms_it(world):
    oid = order(world)
    with pytest.raises(ValueError, match="once the agrovet has confirmed"):
        orders.report_payment(world["user_a"], oid, "SK3ABC12XY")
    orders.confirm_order(world["mboga"], oid, TODAY, today=TODAY)
    with pytest.raises(ValueError, match="M-Pesa code"):
        orders.report_payment(world["user_a"], oid, "abc")
    with pytest.raises(ValueError, match="not yours"):
        orders.report_payment(world["user_b"], oid, "SK3ABC12XY")
    orders.report_payment(world["user_a"], oid, " sk3abc12xy ")
    o = db.get_order(oid)
    assert o["payment_status"] == "reported" and o["mpesa_code"] == "SK3ABC12XY"
    with pytest.raises(ValueError, match="not placed with you"):
        orders.confirm_payment(world["rival"], oid)
    orders.confirm_payment(world["mboga"], oid)
    assert db.get_order(oid)["payment_status"] == "received"
    with pytest.raises(ValueError, match="paid for this order"):
        orders.cancel_order(world["user_a"], oid)


def test_the_shop_can_confirm_a_code_from_its_own_messages(world):
    oid = confirmed(world)
    with pytest.raises(ValueError, match="enter the M-Pesa code"):
        orders.confirm_payment(world["mboga"], oid)
    orders.confirm_payment(world["mboga"], oid, "QW12ER34TY")
    assert db.get_order(oid)["mpesa_code"] == "QW12ER34TY"


# --- confirming and handing over -----------------------------------------------------------------


def test_confirming_copies_todays_prices_and_a_later_price_change_does_not_alter_it(world):
    oid = order(world)
    with pytest.raises(ValueError, match="not placed with you"):
        orders.confirm_order(world["rival"], oid, TODAY, today=TODAY)
    orders.confirm_order(world["mboga"], oid, TODAY + timedelta(days=1), note="ready after 10am", today=TODAY)
    orders.record_product(world["mboga"], "Dairy meal", "70 kg bag", "3000")
    lines = db.order_lines(oid)
    assert [float(ln["unit_price_kes"]) for ln in lines] == [2600.0, 900.0] and orders.order_total(lines) == 6100
    with pytest.raises(ValueError, match="only a waiting order"):
        orders.confirm_order(world["mboga"], oid, TODAY, today=TODAY)


def test_an_mpesa_hand_over_needs_the_payment_confirmed_and_then_bills_and_restocks(world):
    oid = confirmed(world)
    with pytest.raises(ValueError, match="confirm the M-Pesa payment first"):
        orders.hand_over(world["mboga"], oid, today=TODAY)
    orders.confirm_payment(world["mboga"], oid, "SK3ABC12XY")
    orders.hand_over(world["mboga"], oid, today=TODAY)
    o = db.get_order(oid)
    assert o["status"] == "collected" and o["collected_on"] == TODAY
    charges = sorted(db.charges_for_farm(world["farm_a"]), key=lambda c: c["category"])
    assert [(c["category"], float(c["amount_kes"]), c["terms"], float(c["paid_kes"])) for c in charges] == [
        ("agrovet", 900.0, "paid", 900.0), ("feed", 5200.0, "paid", 5200.0)]
    assert db.payments_for_charge(charges[1]["id"])[0]["reference"] == "SK3ABC12XY"
    (s,) = stock.farm_stock(world["farm_a"], TODAY)
    assert s["on_hand_kg"] == 140 and s["on_hand_units"] == 2


def test_a_cash_hand_over_needs_the_cash_ticked(world):
    oid = confirmed(world, pay="cash")
    with pytest.raises(ValueError, match="received the cash"):
        orders.hand_over(world["mboga"], oid, today=TODAY)
    orders.hand_over(world["mboga"], oid, cash_received=True, today=TODAY)
    assert all(c["terms"] == "paid" and ledger.owed(c) == 0 for c in db.charges_for_farm(world["farm_a"]))
    assert {p["method"] for c in db.charges_for_farm(world["farm_a"]) for p in db.payments_for_charge(c["id"])} == {"cash"}


def test_the_buyers_store_bills_the_milk_payment(world):
    oid = confirmed(world, lines=[(world["store_meal"], "1")], pay="milk_deduction", shop="store")
    orders.hand_over(world["store"], oid, today=TODAY)
    (c,) = db.charges_for_farm(world["farm_a"])
    assert c["terms"] == "milk_deduction" and float(c["amount_kes"]) == 2550


def test_two_hand_overs_at_once_bill_the_order_once(world):
    oid = confirmed(world, pay="cash")
    results = []

    def go():
        try:
            orders.hand_over(world["mboga"], oid, cash_received=True, today=TODAY)
            results.append("ok")
        except ValueError:
            results.append("refused")

    threads = [threading.Thread(target=go) for _ in range(2)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert sorted(results) == ["ok", "refused"] and len(db.charges_for_farm(world["farm_a"])) == 2


def test_declining_tells_the_farmer_why_and_not_after_payment(world):
    oid = order(world)
    with pytest.raises(ValueError, match="tell the farmer why"):
        orders.decline_order(world["mboga"], oid, " ")
    orders.decline_order(world["mboga"], oid, "out of dairy meal until Monday")
    assert db.get_order(oid)["status"] == "declined"
    paid = confirmed(world)
    orders.confirm_payment(world["mboga"], paid, "SK3ABC12XY")
    with pytest.raises(ValueError, match="refund the farmer first"):
        orders.decline_order(world["mboga"], paid, "sorry")


def test_delivery_rounds_group_by_route(world):
    a = orders.place_order(world["user_a"], world["farm_a"], world["mboga"]["id"], [(world["meal"], "1")], TODAY, "delivery", "cash",
                           today=TODAY)
    b = orders.place_order(world["user_b"], world["farm_b"], world["mboga"]["id"], [(world["meal"], "1")], TODAY, "pickup", "cash",
                           today=TODAY)
    for oid in (a, b):
        orders.confirm_order(world["mboga"], oid, TODAY, today=TODAY)
    r = orders.rounds(world["mboga"], TODAY)
    assert list(r["deliveries"]) == ["4A"] and [o["id"] for o in r["pickups"]] == [b]


# --- promotions and sales ------------------------------------------------------------------------


def test_a_promotion_lowers_the_confirmed_price_only_while_it_runs(world):
    pid = orders.add_promotion(world["mboga"], world["meal"], 10, TODAY, TODAY + timedelta(days=3), today=TODAY)
    during = order(world, lines=[(world["meal"], "1")])
    orders.confirm_order(world["mboga"], during, TODAY, today=TODAY)
    assert float(db.order_lines(during)[0]["unit_price_kes"]) == 2340
    orders.end_promotion(world["mboga"], pid, today=TODAY)
    after = order(world, lines=[(world["meal"], "1")])
    orders.confirm_order(world["mboga"], after, TODAY, today=TODAY)
    assert float(db.order_lines(after)[0]["unit_price_kes"]) == 2600


def test_promotion_rules(world):
    w = world
    for args, why in (((w["rival_meal"], 10, TODAY, TODAY), "your products"), ((w["meal"], 0, TODAY, TODAY), "between 1%"),
                      ((w["meal"], 60, TODAY, TODAY), "between 1%"), ((w["meal"], 10, TODAY - timedelta(days=1), TODAY), "past"),
                      ((w["meal"], 10, TODAY, TODAY - timedelta(days=1)), "before the start"),
                      ((w["meal"], 10, TODAY, TODAY + timedelta(days=61)), "at most 60")):
        with pytest.raises(ValueError, match=why):
            orders.add_promotion(w["mboga"], *args, today=TODAY)
    pid = orders.add_promotion(w["mboga"], w["meal"], 10, TODAY, TODAY + timedelta(days=3), today=TODAY)
    orders.end_promotion(w["rival"], pid, today=TODAY)  # another shop can't end it
    assert db.promotions_for(w["mboga"]["id"], TODAY)


def test_sales_show_best_and_slow_sellers_and_repeat_customers(world):
    for _ in range(2):
        oid = confirmed(world, lines=[(world["meal"], "2")], pay="cash")
        orders.hand_over(world["mboga"], oid, cash_received=True, today=TODAY)
    s = orders.sales(world["mboga"], TODAY)
    assert [(r["product_name"], float(r["qty"]), float(r["kes"]), r["orders"]) for r in s["products"]] == [("Dairy meal", 4.0, 10400.0, 2)]
    assert [p["name"] for p in s["slow"]] == ["Mineral lick"] and s["repeat"] == 1 and s["kes"] == 10400


def test_deleting_a_farm_removes_its_orders_and_deleting_the_agrovet_keeps_the_farmers_history(world):
    oid = confirmed(world, pay="cash")
    orders.hand_over(world["mboga"], oid, cash_received=True, today=TODAY)
    accounts.delete_own_account(world["mboga"], "DELETE")
    o = db.get_order(oid)
    assert o["agrovet_user_id"] is None and o["agrovet_name"] == "Mboga Center"
    db.delete_farm(world["farm_a"])
    assert db._query("SELECT COUNT(*) AS n FROM orders", one=True)["n"] == 0
