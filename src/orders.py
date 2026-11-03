"""Agrovets and pre-orders: a farmer orders ahead, the agrovet confirms, the goods are ready when they arrive.

Logic only (no Streamlit). Rules that matter here:
  - an agrovet keeps its own product list and sees only orders placed with it (and the farms that placed them);
  - a farmer orders only from agrovets they added, only that agrovet's products, and can tie a line to
    one of their own feeds so collecting it restocks Feed stock;
  - prices are copied onto the order when the agrovet confirms it, so a later price change can't alter
    what was agreed;
  - handing over the goods bills the order into the money ledger (paid now or on credit, straight to the
    agrovet; the app moves no money), restocks tied feeds, and closes the order, all in one transaction
    that first locks the order, so a double click can't bill it twice.
"""
from datetime import date, timedelta
from decimal import Decimal

from src import db, ledger, stock
from src.ingestion import manual_entry as me

STATUS_WORDS = {"requested": "waiting for the agrovet", "confirmed": "confirmed", "collected": "collected",
                "cancelled": "cancelled", "declined": "declined by the agrovet"}
FULFILMENT = {"pickup": "I'll pick it up", "delivery": "Deliver to the farm"}
MAX_LINES = 10
MAX_OPEN_PER_AGROVET = 10
MAX_OWN_AGROVETS = 5
HORIZON_DAYS = 30
MAX_NOTE = 300


def _clean(text, limit, what):
    text = " ".join(str(text or "").split())
    if len(text) > limit:
        raise ValueError(f"{what} is too long ({limit} characters at most)")
    return text


def _is_agrovet(user):
    if not user or user.get("role") != "agrovet" or user.get("id") is None:
        raise ValueError("only an agrovet can do this")


def _own_farm(user, farmer_id):
    if not user or user.get("role") != "farmer" or user.get("farmer_id") != farmer_id:
        raise ValueError("you can only order for your own farm")


def _check_day(day, today, what):
    if day < today:
        raise ValueError(f"{what} cannot be in the past")
    if day > today + timedelta(days=HORIZON_DAYS):
        raise ValueError(f"{what} must be within the next {HORIZON_DAYS} days")


# --- the agrovet's product list -----------------------------------------------------------------


def record_product(user, name, unit, price):
    """Add or reprice a product. Returns its id."""
    _is_agrovet(user)
    name = _clean(name, 80, "the product name")
    unit = _clean(unit, 30, "the unit")
    if not name:
        raise ValueError("enter the product name")
    if not unit:
        raise ValueError("say how it is sold, like 70 kg bag")
    return db.upsert_product(user["id"], name, unit, ledger.parse_amount(price, "the price"))


# --- the farmer's side --------------------------------------------------------------------------


def add_own_agrovet(farmer_id, phone):
    """The farmer adds an agrovet they buy from, by the shop's phone. Returns its user id."""
    phone = me.normalize_phone(phone)
    shop = db.user_by_phone(phone)
    if not shop or shop["role"] != "agrovet" or not shop["active"] or shop.get("pending"):
        raise ValueError("no agrovet with that number uses Maziwa Plus yet: ask them to sign up as an agrovet")
    if not db.is_farm_agrovet(farmer_id, shop["id"]) and len(db.farm_agrovets(farmer_id)) >= MAX_OWN_AGROVETS:
        raise ValueError(f"you can add at most {MAX_OWN_AGROVETS} agrovets: remove one first")
    db.add_farm_agrovet(farmer_id, shop["id"])
    return shop["id"]


def place_order(user, farmer_id, agrovet_id, lines, wanted_on, fulfilment, notes=None, today=None):
    """lines = [(product id, quantity, the farm's feed id or None)]. Returns the order id."""
    today = today or date.today()
    _own_farm(user, farmer_id)
    if not db.is_farm_agrovet(farmer_id, agrovet_id):
        raise ValueError("choose one of your agrovets")
    if fulfilment not in FULFILMENT:
        raise ValueError("choose pickup or delivery")
    _check_day(wanted_on, today, "the day")
    products = {p["id"]: p for p in db.list_products(agrovet_id)}
    feeds = {i["id"]: i for i in db.list_catalogue(farmer_id)}
    clean = []
    for product_id, qty, feed_id in lines:
        if str(qty or "").strip() in ("", "0"):
            continue
        product = products.get(product_id)
        if product is None:
            raise ValueError("choose products from this agrovet's list")
        units = stock._units(qty, "the quantity")
        if not 0 < units <= 1000:
            raise ValueError("each quantity must be more than 0 and at most 1,000")
        if feed_id is not None and feed_id not in feeds:
            raise ValueError("choose one of your own feeds, or none")
        clean.append({"product_id": product_id, "product_name": product["name"], "unit": product["unit"], "qty": units,
                      "catalogue_id": feed_id})
    if not clean:
        raise ValueError("add at least one product")
    if len(clean) > MAX_LINES:
        raise ValueError(f"at most {MAX_LINES} products on one order")
    if db.open_order_count(farmer_id, agrovet_id) >= MAX_OPEN_PER_AGROVET:
        raise ValueError(f"you already have {MAX_OPEN_PER_AGROVET} open orders with this agrovet")
    shop = db.get_user(agrovet_id)
    order = {"farmer_id": farmer_id, "agrovet_user_id": agrovet_id, "agrovet_name": shop["name"][:80], "fulfilment": fulfilment,
             "wanted_on": wanted_on, "notes": _clean(notes, MAX_NOTE, "the note") or None}
    return db.add_order(order, clean)


def cancel_order(user, order_id):
    """The farmer withdraws their own order before it is collected."""
    o = db.get_order(order_id)
    if not o or user.get("role") != "farmer" or o["farmer_id"] != user.get("farmer_id"):
        raise ValueError("that order is not yours")
    if o["status"] not in ("requested", "confirmed"):
        raise ValueError("only a waiting or confirmed order can be cancelled")
    db.update_order(order_id, status="cancelled")


def suggested_lines(farmer_id, today=None):
    """The farm's feeds that are running low: a starting point for an order (feed id, name, days left)."""
    return [(r["id"], r["name"], r["days_left"]) for r in stock.running_low(farmer_id, today)]


# --- the agrovet's side -------------------------------------------------------------------------


def _own_order(user, order_id):
    _is_agrovet(user)
    o = db.get_order(order_id)
    if not o or o["agrovet_user_id"] != user["id"]:
        raise ValueError("that order was not placed with you")
    return o


def confirm_order(user, order_id, ready_on, note=None, today=None):
    """The agrovet accepts an order for a day; today's list prices are copied onto its lines."""
    today = today or date.today()
    o = _own_order(user, order_id)
    if o["status"] != "requested":
        raise ValueError("only a waiting order can be confirmed")
    _check_day(ready_on, today, "the ready day")
    prices = {p["id"]: p for p in db.list_products(user["id"], active_only=False)}
    lines = db.order_lines(order_id)
    missing = [ln["product_name"] for ln in lines if ln["product_id"] not in prices]
    if missing:
        raise ValueError(f"{', '.join(missing)} is no longer on your list: decline the order or ask the farmer to reorder")
    with db.batch():
        if db.lock_order_status(order_id) != "requested":
            raise ValueError("only a waiting order can be confirmed")
        for ln in lines:
            db.price_order_line(ln["id"], prices[ln["product_id"]]["price_kes"])
        db.update_order(order_id, status="confirmed", ready_on=ready_on, agrovet_note=_clean(note, MAX_NOTE, "the note") or None)


def decline_order(user, order_id, reason):
    o = _own_order(user, order_id)
    if o["status"] not in ("requested", "confirmed"):
        raise ValueError("this order is already closed")
    reason = _clean(reason, MAX_NOTE, "the reason")
    if not reason:
        raise ValueError("tell the farmer why, for example out of stock")
    db.update_order(order_id, status="declined", agrovet_note=reason)


def order_total(lines):
    return sum((Decimal(ln["qty"]) * Decimal(ln["unit_price_kes"]) for ln in lines if ln["unit_price_kes"] is not None), Decimal("0"))


def hand_over(user, order_id, terms, due_on=None, method=None, reference=None, today=None):
    """The goods are collected or delivered: bill each line into the ledger (paid now or on credit),
    restock the farm's tied feeds, and close the order, in one transaction."""
    today = today or date.today()
    o = _own_order(user, order_id)
    if o["status"] != "confirmed":
        raise ValueError("only a confirmed order can be handed over")
    if terms not in ("paid", "credit"):
        raise ValueError("choose paid now or on credit")
    due_on, method, reference = ledger._settlement(terms, due_on, today, method, reference, today)
    lines = db.order_lines(order_id)
    feeds = {i["id"]: i for i in db.list_catalogue(o["farmer_id"], active_only=False)}
    with db.batch():
        if db.lock_order_status(order_id) != "confirmed":
            raise ValueError("only a confirmed order can be handed over")
        for ln in lines:
            amount = (Decimal(ln["qty"]) * Decimal(ln["unit_price_kes"])).quantize(Decimal("0.01"))
            charge = {"farmer_id": o["farmer_id"], "provider_user_id": user["id"], "provider_name": user["name"][:80],
                      "category": "feed" if ln["catalogue_id"] else "agrovet",
                      "description": f"{Decimal(ln['qty']).normalize():f} x {ln['product_name']} ({ln['unit']})"[:200],
                      "amount_kes": amount, "charged_on": today, "terms": terms, "due_on": due_on, "request_id": None,
                      "created_by_user_id": user["id"]}
            payment = None if terms != "paid" else {"method": method, "paid_on": today, "reference": reference,
                                                    "recorded_by_user_id": user["id"]}
            (charge_id,) = db.add_charges([charge], payment)
            db.bill_order_line(ln["id"], charge_id)
            feed = feeds.get(ln["catalogue_id"])
            if feed is not None:  # restock: one unit ordered = one unit of the farm's feed (the farmer tied them)
                db.add_feed_purchase({"farmer_id": o["farmer_id"], "catalogue_id": feed["id"], "purchased_on": today,
                                      "units": ln["qty"], "kg": (Decimal(ln["qty"]) * Decimal(feed["kg_per_unit"])).quantize(Decimal("0.01")),
                                      "cost_kes": amount, "charge_id": charge_id, "created_by_user_id": user["id"]})
        db.update_order(order_id, status="collected", collected_on=today)


def rounds(user, day):
    """Confirmed orders ready on a day, grouped for the agrovet: deliveries by route (one trip per area),
    then pickups."""
    _is_agrovet(user)
    ready = [o for o in db.orders_for_agrovet(user["id"], ("confirmed",)) if o["ready_on"] == day]
    deliveries, pickups = {}, []
    for o in ready:
        if o["fulfilment"] == "delivery":
            deliveries.setdefault(o["route_code"] or "no route", []).append(o)
        else:
            pickups.append(o)
    return {"deliveries": dict(sorted(deliveries.items())), "pickups": pickups}
