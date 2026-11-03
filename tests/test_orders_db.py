"""Agrovets, pre-orders, hand-over billing and restocking, against real Postgres. Need TEST_DATABASE_URL."""
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
    db._query("TRUNCATE order_lines, orders, farm_agrovets, agrovet_products, feed_stock_counts, feed_purchases, charge_payments, "
              "charges, feed_logs, feed_catalogue, sms_log, farmers, users, routes RESTART IDENTITY CASCADE")


@pytest.fixture
def world():
    route = accounts.record_route("4A")
    farm_a, farm_b = db.add_farmer("Mama A", "+254700000001", "A Farm"), db.add_farmer("Mama B", "+254700000002", "B Farm")
    accounts.assign_route(farm_a, route)
    as_user = lambda uid: accounts.session_user(db.get_user(uid))  # noqa: E731
    user_a = as_user(accounts.create_account("farmer", "Mama A", phone="0700000001", farmer_id=farm_a))
    user_b = as_user(accounts.create_account("farmer", "Mama B", phone="0700000002", farmer_id=farm_b))
    mboga = as_user(accounts.create_account("agrovet", "Mboga Center", phone="0720000000"))
    rival = as_user(accounts.create_account("agrovet", "Other Agrovet", phone="0721111111"))
    meal = orders.record_product(mboga, "Dairy meal", "70 kg bag", "2,600")
    lick = orders.record_product(mboga, "Mineral lick", "block", "900")
    rival_meal = orders.record_product(rival, "Dairy meal", "70 kg bag", "2,500")
    feed = db.upsert_catalogue_item(farm_a, "dairy meal", "bag", 70, 2600)
    orders.add_own_agrovet(farm_a, "0720 000 000")
    return dict(farm_a=farm_a, farm_b=farm_b, user_a=user_a, user_b=user_b, mboga=mboga, rival=rival, meal=meal, lick=lick,
                rival_meal=rival_meal, feed=feed)


def order(w, lines=None, **kw):
    lines = lines if lines is not None else [(w["meal"], "2", w["feed"]), (w["lick"], "1", None)]
    return orders.place_order(w["user_a"], w["farm_a"], w["mboga"]["id"], lines, TODAY + timedelta(days=1), "pickup", today=TODAY, **kw)


# --- roles and the product list ------------------------------------------------------------------


def test_an_agrovet_signs_up_with_a_shop_phone_and_waits_for_approval():
    uid = accounts.signup("agrovet", "Mboga Center", "mboga@example.com", "long-password-1", phone="0730000000")
    u = db.get_user(uid)
    assert u["role"] == "agrovet" and u["pending"] and not u["active"]
    with pytest.raises(ValueError, match="phone"):
        accounts.signup("agrovet", "No Phone", "nophone@example.com", "long-password-1")
    accounts.approve_signup(uid)
    assert db.get_user(uid)["active"] and db.get_user(uid)["farmer_id"] is None


def test_an_agrovet_sees_no_farms_and_no_texts(world):
    assert accounts.visible_farmers(world["mboga"]) == []
    db.log_sms(world["farm_a"], "hello", status="sent")
    assert alerts.outbox(world["mboga"]) == []


def test_only_an_agrovet_keeps_a_product_list(world):
    with pytest.raises(ValueError, match="only an agrovet"):
        orders.record_product(world["user_a"], "Dairy meal", "bag", "100")
    for name, unit, price, why in (("", "bag", "1", "product name"), ("X", "", "1", "how it is sold"), ("X", "bag", "0", "more than 0")):
        with pytest.raises(ValueError, match=why):
            orders.record_product(world["mboga"], name, unit, price)
    db.retire_product(world["rival"]["id"], world["meal"])  # another agrovet's product: nothing happens
    assert len(db.list_products(world["mboga"]["id"])) == 2


# --- placing an order ----------------------------------------------------------------------------


def test_a_farmer_orders_from_her_agrovet(world):
    oid = order(world, notes="before Friday please")
    o = db.get_order(oid)
    assert o["status"] == "requested" and o["agrovet_name"] == "Mboga Center" and o["notes"] == "before Friday please"
    assert [(ln["product_name"], float(ln["qty"]), ln["unit_price_kes"]) for ln in db.order_lines(oid)] == [
        ("Dairy meal", 2.0, None), ("Mineral lick", 1.0, None)]
    assert [x["id"] for x in db.orders_for_agrovet(world["mboga"]["id"], ("requested",))] == [oid]
    assert db.orders_for_agrovet(world["rival"]["id"], ("requested",)) == []


def test_ordering_rules(world):
    w = world
    with pytest.raises(ValueError, match="one of your agrovets"):
        orders.place_order(w["user_a"], w["farm_a"], w["rival"]["id"], [(w["rival_meal"], "1", None)], TODAY, "pickup", today=TODAY)
    with pytest.raises(ValueError, match="this agrovet's list"):
        order(w, lines=[(w["rival_meal"], "1", None)])
    with pytest.raises(ValueError, match="own feeds"):
        order(w, lines=[(w["meal"], "1", 9999)])
    with pytest.raises(ValueError, match="at least one product"):
        order(w, lines=[(w["meal"], "", None)])
    with pytest.raises(ValueError, match="at most 1,000"):
        order(w, lines=[(w["meal"], "5000", None)])
    with pytest.raises(ValueError, match="your own farm"):
        orders.place_order(w["user_b"], w["farm_a"], w["mboga"]["id"], [(w["meal"], "1", None)], TODAY, "pickup", today=TODAY)
    with pytest.raises(ValueError, match="past"):
        orders.place_order(w["user_a"], w["farm_a"], w["mboga"]["id"], [(w["meal"], "1", None)], TODAY - timedelta(days=1),
                           "pickup", today=TODAY)
    with pytest.raises(ValueError, match="no agrovet with that number"):
        orders.add_own_agrovet(w["farm_a"], "0700000002")  # a farmer's phone


def test_only_the_farmer_cancels_and_only_before_collection(world):
    oid = order(world)
    with pytest.raises(ValueError, match="not yours"):
        orders.cancel_order(world["user_b"], oid)
    orders.cancel_order(world["user_a"], oid)
    with pytest.raises(ValueError, match="only a waiting or confirmed"):
        orders.cancel_order(world["user_a"], oid)


# --- confirming and handing over -----------------------------------------------------------------


def test_confirming_copies_todays_prices_and_a_later_price_change_does_not_alter_it(world):
    oid = order(world)
    with pytest.raises(ValueError, match="not placed with you"):
        orders.confirm_order(world["rival"], oid, TODAY, today=TODAY)
    orders.confirm_order(world["mboga"], oid, TODAY + timedelta(days=1), note="ready after 10am", today=TODAY)
    orders.record_product(world["mboga"], "Dairy meal", "70 kg bag", "3000")  # repriced after confirming
    lines = db.order_lines(oid)
    assert [float(ln["unit_price_kes"]) for ln in lines] == [2600.0, 900.0] and orders.order_total(lines) == 6100
    o = db.get_order(oid)
    assert o["status"] == "confirmed" and o["ready_on"] == TODAY + timedelta(days=1) and o["agrovet_note"] == "ready after 10am"
    with pytest.raises(ValueError, match="only a waiting order"):
        orders.confirm_order(world["mboga"], oid, TODAY, today=TODAY)


def test_handing_over_bills_the_ledger_and_restocks_the_tied_feed(world):
    oid = order(world)
    orders.confirm_order(world["mboga"], oid, TODAY, today=TODAY)
    orders.hand_over(world["mboga"], oid, "credit", today=TODAY)
    o = db.get_order(oid)
    assert o["status"] == "collected" and o["collected_on"] == TODAY
    charges = sorted(db.charges_for_farm(world["farm_a"]), key=lambda c: c["category"])
    assert [(c["category"], float(c["amount_kes"]), c["terms"], c["provider_user_id"]) for c in charges] == [
        ("agrovet", 900.0, "credit", world["mboga"]["id"]), ("feed", 5200.0, "credit", world["mboga"]["id"])]
    assert all(ln["charge_id"] is not None for ln in db.order_lines(oid))
    (p,) = db.feed_purchases(world["farm_a"])
    assert float(p["units"]) == 2 and float(p["kg"]) == 140 and p["charge_id"] == next(c["id"] for c in charges if c["category"] == "feed")
    (s,) = stock.farm_stock(world["farm_a"], TODAY)
    assert s["on_hand_kg"] == 140
    # the agrovet's money page: who owes what
    d = ledger.debtors(db.charges_for_provider(world["mboga"]["id"], credit_only=True), TODAY)
    assert d[0]["farm"] == "A Farm" and d[0]["owed"] == 6100
    ledger.record_payment(world["mboga"], charges[1]["id"], "5200", "mpesa", today=TODAY)
    assert ledger.owed(db.get_charge(charges[1]["id"])) == 0


def test_hand_over_paid_now_and_what_it_refuses(world):
    oid = order(world)
    with pytest.raises(ValueError, match="only a confirmed order"):
        orders.hand_over(world["mboga"], oid, "paid", method="cash", today=TODAY)
    orders.confirm_order(world["mboga"], oid, TODAY, today=TODAY)
    with pytest.raises(ValueError, match="paid now or on credit"):
        orders.hand_over(world["mboga"], oid, "milk_deduction", today=TODAY)
    with pytest.raises(ValueError, match="not placed with you"):
        orders.hand_over(world["rival"], oid, "paid", method="cash", today=TODAY)
    orders.hand_over(world["mboga"], oid, "paid", method="mpesa", reference="SK3ABC12XY", today=TODAY)
    assert all(ledger.owed(c) == 0 and float(c["paid_kes"]) == float(c["amount_kes"]) for c in db.charges_for_farm(world["farm_a"]))


def test_two_hand_overs_at_once_bill_the_order_once(world):
    oid = order(world)
    orders.confirm_order(world["mboga"], oid, TODAY, today=TODAY)
    results = []

    def go():
        try:
            orders.hand_over(world["mboga"], oid, "credit", today=TODAY)
            results.append("ok")
        except ValueError:
            results.append("refused")

    threads = [threading.Thread(target=go) for _ in range(2)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert sorted(results) == ["ok", "refused"] and len(db.charges_for_farm(world["farm_a"])) == 2


def test_declining_tells_the_farmer_why(world):
    oid = order(world)
    with pytest.raises(ValueError, match="tell the farmer why"):
        orders.decline_order(world["mboga"], oid, " ")
    orders.decline_order(world["mboga"], oid, "out of dairy meal until Monday")
    o = db.get_order(oid)
    assert o["status"] == "declined" and o["agrovet_note"] == "out of dairy meal until Monday"


def test_a_product_removed_before_confirming_must_be_declined(world):
    oid = order(world)
    db.retire_product(world["mboga"]["id"], world["lick"])
    orders.confirm_order(world["mboga"], oid, TODAY, today=TODAY)  # retired but still known: list price stands
    db._query("DELETE FROM agrovet_products WHERE id = %s", (world["lick"],))
    oid2 = order(world, lines=[(world["meal"], "1", None)])
    db._query("UPDATE order_lines SET product_id = NULL WHERE order_id = %s", (oid2,))
    with pytest.raises(ValueError, match="no longer on your list"):
        orders.confirm_order(world["mboga"], oid2, TODAY, today=TODAY)


def test_delivery_rounds_group_by_route(world):
    orders.add_own_agrovet(world["farm_b"], "0720000000")
    a = orders.place_order(world["user_a"], world["farm_a"], world["mboga"]["id"], [(world["meal"], "1", None)], TODAY, "delivery", today=TODAY)
    b = orders.place_order(world["user_b"], world["farm_b"], world["mboga"]["id"], [(world["meal"], "1", None)], TODAY, "pickup", today=TODAY)
    for oid in (a, b):
        orders.confirm_order(world["mboga"], oid, TODAY, today=TODAY)
    r = orders.rounds(world["mboga"], TODAY)
    assert list(r["deliveries"]) == ["4A"] and [o["id"] for o in r["deliveries"]["4A"]] == [a] and [o["id"] for o in r["pickups"]] == [b]
    assert [c["farm"] for c in db.agrovet_customers(world["mboga"]["id"])] == ["A Farm", "B Farm"]


def test_deleting_a_farm_removes_its_orders_and_deleting_the_agrovet_keeps_the_farmers_history(world):
    oid = order(world)
    orders.confirm_order(world["mboga"], oid, TODAY, today=TODAY)
    orders.hand_over(world["mboga"], oid, "credit", today=TODAY)
    accounts.delete_own_account(world["mboga"], "DELETE")
    o = db.get_order(oid)
    assert o["agrovet_user_id"] is None and o["agrovet_name"] == "Mboga Center"
    assert {c["provider_name"] for c in db.charges_for_farm(world["farm_a"])} == {"Mboga Center"}
    db.delete_farm(world["farm_a"])
    assert db._query("SELECT COUNT(*) AS n FROM orders", one=True)["n"] == 0
