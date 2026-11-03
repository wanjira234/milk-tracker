"""Agrovets and pre-orders: a farmer orders ahead, the agrovet confirms, both sides see it is paid,
and the goods are ready when the farmer arrives (or delivered).

Logic only (no Streamlit). The journey:
  1. the farmer picks a shop from the list of agrovets (nearest town first), the quantities, and how
     they'll pay: M-Pesa to the shop, cash when collecting, or deducted from the milk payment (only at
     the milk buyer's own store);
  2. the agrovet confirms it for a ready day; today's prices (with any running promotion) are copied
     onto the order, so the farmer sees the exact amount;
  3. M-Pesa: the farmer pays the shop's till and enters the code; the agrovet sees it and confirms the
     money arrived. Cash: the agrovet ticks "cash received" at hand-over;
  4. hand-over closes the order, bills it into the money ledger, and restocks the farm's Feed stock for
     products that match one of the farm's feeds, all in one transaction that locks the order first.
The app moves no money. An agrovet sees only orders placed with it, and the farms that placed them.
"""
import re
from datetime import date, datetime, timedelta, timezone
from decimal import ROUND_HALF_UP, Decimal

from src import db, ledger, stock

STATUS_WORDS = {"requested": "waiting for the agrovet to confirm", "confirmed": "confirmed", "collected": "collected",
                "cancelled": "cancelled", "declined": "declined by the agrovet"}
FULFILMENT = {"pickup": "I'll pick it up", "delivery": "Deliver to the farm"}
PAYMENT = {"mpesa": "M-Pesa to the shop", "cash": "Cash when I get it", "milk_deduction": "Deduct from my milk payment"}
# the same, as the agrovet reads them on an order card
FULFILMENT_SHOP = {"pickup": "Pickup", "delivery": "Delivery"}
PAYMENT_SHOP = {"mpesa": "M-Pesa", "cash": "Cash", "milk_deduction": "Milk payment"}
PAY_KINDS = {"till": "Till (Buy Goods)", "paybill": "Paybill"}
MAX_LINES = 10
MAX_OPEN_PER_AGROVET = 10
HORIZON_DAYS = 30
MAX_NOTE = 300
_CODE = re.compile(r"^[A-Z0-9]{8,12}$")
_KG = re.compile(r"(\d+(?:\.\d+)?)\s*kg", re.IGNORECASE)


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


def mpesa_code(code):
    code = "".join(str(code or "").split()).upper()
    if not _CODE.match(code):
        raise ValueError("enter the M-Pesa code from the confirmation SMS (letters and numbers, like SK3ABC12XY)")
    return code


def _now():
    return datetime.now(timezone.utc)


# --- the agrovet's shop and product list ---------------------------------------------------------


def set_shop(user, town, pay_kind, pay_number, pay_account=None):
    """The agrovet's town (so nearby farmers find it first) and where farmers pay by M-Pesa."""
    _is_agrovet(user)
    town = _clean(town, 60, "the town")
    if not town:
        raise ValueError("enter your town or area, so nearby farmers find you")
    pay_number = "".join(str(pay_number or "").split())
    if pay_number:
        if pay_kind not in PAY_KINDS:
            raise ValueError("choose Till or Paybill")
        if not re.fullmatch(r"[0-9]{5,10}", pay_number):
            raise ValueError("the till or paybill number is 5 to 10 digits")
        pay_account = _clean(pay_account, 30, "the account number") or None
        if pay_kind == "till":
            pay_account = None
    else:
        pay_kind = pay_account = None
    db.set_shop_profile(user["id"], town, pay_kind, pay_number or None, pay_account)


def where_to_pay(shop):
    """'Till 123456' / 'Paybill 400200, account A Farm' / None, for showing the farmer."""
    if not shop or not shop.get("pay_number"):
        return None
    if shop["pay_kind"] == "paybill":
        return f"Paybill {shop['pay_number']}" + (f", account {shop['pay_account']}" if shop.get("pay_account") else "")
    return f"Till {shop['pay_number']}"


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


# --- matching a product to the farm's own feed ---------------------------------------------------


def _words(text):
    return {w for w in re.findall(r"[a-z]+", str(text).lower()) if len(w) > 2}


def match_feed(product, feeds):
    """The farm feed a product restocks, and kg in one product unit: (feed, kg) or (None, None).

    A product matches a feed when their names share the feed's words ("Dairy meal 18%" and "dairy meal").
    kg comes from the product's unit when it says so ("70 kg bag"), otherwise from the feed's own unit when
    the units agree (the shop sells per "bag" and the farm counts in bags)."""
    name = _words(product["name"])
    for feed in feeds:
        fw = _words(feed["name"])
        if not fw or not fw <= name:
            continue
        m = _KG.search(product["unit"])
        if m:
            return feed, Decimal(m.group(1))
        if _words(feed["unit"]) & _words(product["unit"]):
            return feed, Decimal(feed["kg_per_unit"])
    return None, None


# --- the farmer's side --------------------------------------------------------------------------


def shops_for(farmer_id):
    """Agrovets the farmer can order from: shops in their town first."""
    farm = db.get_farmer(farmer_id)
    return db.list_agrovets(farm.get("town") if farm else None)


def can_deduct(farmer_id, agrovet_id):
    """Only a milk buyer's own store can take payment from the farm's milk money."""
    from src import orgs  # local import: orgs imports accounts, which this module must not need at load time

    return orgs.buyer_store_for(farmer_id, agrovet_id)


def payment_options(farmer_id, shop):
    out = []
    if shop.get("pay_number"):
        out.append("mpesa")
    out.append("cash")
    if can_deduct(farmer_id, shop["id"]):
        out.append("milk_deduction")
    return out


def place_order(user, farmer_id, agrovet_id, lines, wanted_on, fulfilment, payment_method="cash", notes=None, today=None):
    """lines = [(product id, quantity)]. Blank or 0 quantities are skipped. Returns the order id."""
    today = today or date.today()
    _own_farm(user, farmer_id)
    shop = db.shop(agrovet_id)
    if not shop:
        raise ValueError("choose an agrovet from the list")
    if fulfilment not in FULFILMENT:
        raise ValueError("choose pickup or delivery")
    if payment_method not in payment_options(farmer_id, shop):
        raise ValueError("choose how you'll pay" if payment_method not in PAYMENT else
                         "this shop doesn't take that: choose another way to pay")
    _check_day(wanted_on, today, "the day")
    products = {p["id"]: p for p in db.list_products(agrovet_id)}
    feeds = db.list_catalogue(farmer_id)
    clean = []
    for product_id, qty in lines:
        if str(qty or "").strip() in ("", "0", "0.0"):
            continue
        product = products.get(product_id)
        if product is None:
            raise ValueError("choose products from this agrovet's list")
        units = stock._units(qty, "the quantity")
        if units == 0:
            continue
        if units > 1000:
            raise ValueError("each quantity must be at most 1,000")
        feed, kg_each = match_feed(product, feeds)
        clean.append({"product_id": product_id, "product_name": product["name"], "unit": product["unit"], "qty": units,
                      "catalogue_id": feed["id"] if feed else None, "kg_each": kg_each})
    if not clean:
        raise ValueError("enter how many of at least one product")
    if len(clean) > MAX_LINES:
        raise ValueError(f"at most {MAX_LINES} products on one order")
    if db.open_order_count(farmer_id, agrovet_id) >= MAX_OPEN_PER_AGROVET:
        raise ValueError(f"you already have {MAX_OPEN_PER_AGROVET} open orders with this agrovet")
    order = {"farmer_id": farmer_id, "agrovet_user_id": agrovet_id, "agrovet_name": shop["name"][:80], "fulfilment": fulfilment,
             "wanted_on": wanted_on, "notes": _clean(notes, MAX_NOTE, "the note") or None, "payment_method": payment_method}
    return db.add_order(order, clean)


def cancel_order(user, order_id):
    """The farmer withdraws their own order before it is collected, as long as no M-Pesa payment is on it."""
    o = db.get_order(order_id)
    if not o or user.get("role") != "farmer" or o["farmer_id"] != user.get("farmer_id"):
        raise ValueError("that order is not yours")
    if o["status"] not in ("requested", "confirmed"):
        raise ValueError("only a waiting or confirmed order can be cancelled")
    if o["payment_status"] != "unpaid":
        raise ValueError("you've paid for this order: ask the agrovet to cancel it and refund you")
    db.update_order(order_id, status="cancelled")


def report_payment(user, order_id, code):
    """The farmer says they paid by M-Pesa and gives the code; the agrovet then confirms it arrived."""
    o = db.get_order(order_id)
    if not o or user.get("role") != "farmer" or o["farmer_id"] != user.get("farmer_id"):
        raise ValueError("that order is not yours")
    if o["payment_method"] != "mpesa":
        raise ValueError("this order isn't paid by M-Pesa")
    if o["status"] != "confirmed":
        raise ValueError("pay once the agrovet has confirmed the order and its total")
    if o["payment_status"] == "received":
        raise ValueError("the agrovet has already confirmed your payment")
    db.update_order(order_id, payment_status="reported", mpesa_code=mpesa_code(code), payment_reported_at=_now())


def suggested_feeds(farmer_id, today=None):
    """The farm's feeds that are running low, for the top of the order page: [(feed id, name, days left)]."""
    return [(r["id"], r["name"], r["days_left"]) for r in stock.running_low(farmer_id, today)]


# --- the agrovet's side -------------------------------------------------------------------------


def _own_order(user, order_id):
    _is_agrovet(user)
    o = db.get_order(order_id)
    if not o or o["agrovet_user_id"] != user["id"]:
        raise ValueError("that order was not placed with you")
    return o


def price_today(product, promos, today):
    """A product's price today: the list price, less a running promotion on it."""
    price = Decimal(product["price_kes"])
    promo = next((p for p in promos if p["product_id"] == product["id"] and p["starts_on"] <= today <= p["ends_on"]), None)
    if promo:
        price = (price * (100 - Decimal(promo["percent_off"])) / 100).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    return price, promo


def confirm_order(user, order_id, ready_on, note=None, today=None):
    """The agrovet accepts an order for a day; today's prices (with promotions) are copied onto its lines."""
    today = today or date.today()
    o = _own_order(user, order_id)
    if o["status"] != "requested":
        raise ValueError("only a waiting order can be confirmed")
    _check_day(ready_on, today, "the ready day")
    products = {p["id"]: p for p in db.list_products(user["id"], active_only=False)}
    promos = db.promotions_for(user["id"])
    lines = db.order_lines(order_id)
    missing = [ln["product_name"] for ln in lines if ln["product_id"] not in products]
    if missing:
        raise ValueError(f"{', '.join(missing)} is no longer on your list: decline the order or ask the farmer to reorder")
    with db.batch():
        if db.lock_order_status(order_id) != "requested":
            raise ValueError("only a waiting order can be confirmed")
        for ln in lines:
            db.price_order_line(ln["id"], price_today(products[ln["product_id"]], promos, today)[0])
        db.update_order(order_id, status="confirmed", ready_on=ready_on, agrovet_note=_clean(note, MAX_NOTE, "the note") or None)


def decline_order(user, order_id, reason):
    o = _own_order(user, order_id)
    if o["status"] not in ("requested", "confirmed"):
        raise ValueError("this order is already closed")
    if o["payment_status"] == "received":
        raise ValueError("you've confirmed this order's payment: refund the farmer first, then decline it")
    reason = _clean(reason, MAX_NOTE, "the reason")
    if not reason:
        raise ValueError("tell the farmer why, for example out of stock")
    db.update_order(order_id, status="declined", agrovet_note=reason)


def confirm_payment(user, order_id, code=None):
    """The agrovet confirms an M-Pesa payment arrived: the one the farmer reported, or a code the agrovet
    has in its own M-Pesa messages (when the farmer paid but didn't enter it)."""
    o = _own_order(user, order_id)
    if o["payment_method"] != "mpesa":
        raise ValueError("this order isn't paid by M-Pesa")
    if o["status"] not in ("confirmed", "requested"):
        raise ValueError("this order is already closed")
    if o["payment_status"] == "received":
        raise ValueError("already confirmed")
    code = mpesa_code(code) if str(code or "").strip() else o["mpesa_code"]
    if not code:
        raise ValueError("enter the M-Pesa code from your messages")
    db.update_order(order_id, payment_status="received", mpesa_code=code, payment_received_at=_now())


def order_total(lines):
    return sum((Decimal(ln["qty"]) * Decimal(ln["unit_price_kes"]) for ln in lines if ln["unit_price_kes"] is not None), Decimal("0"))


def hand_over(user, order_id, cash_received=False, today=None):
    """The goods are collected or delivered: bill each line (paid by M-Pesa or cash, or to the milk payment),
    restock the farm's matching feeds, and close the order, in one transaction."""
    today = today or date.today()
    o = _own_order(user, order_id)
    if o["status"] != "confirmed":
        raise ValueError("only a confirmed order can be handed over")
    method = o["payment_method"]
    if method == "mpesa" and o["payment_status"] != "received":
        raise ValueError("confirm the M-Pesa payment first (or enter the code from your messages)")
    if method == "cash" and not cash_received:
        raise ValueError("tick that you received the cash")
    terms = "milk_deduction" if method == "milk_deduction" else "paid"
    payment = None if terms != "paid" else {"method": method, "paid_on": today,
                                            "reference": o["mpesa_code"] if method == "mpesa" else None,
                                            "recorded_by_user_id": user["id"]}
    lines = db.order_lines(order_id)
    feeds = {i["id"]: i for i in db.list_catalogue(o["farmer_id"], active_only=False)}
    with db.batch():
        if db.lock_order_status(order_id) != "confirmed":
            raise ValueError("only a confirmed order can be handed over")
        for ln in lines:
            amount = (Decimal(ln["qty"]) * Decimal(ln["unit_price_kes"])).quantize(Decimal("0.01"))
            feed = feeds.get(ln["catalogue_id"])
            charge = {"farmer_id": o["farmer_id"], "provider_user_id": user["id"], "provider_name": user["name"][:80],
                      "category": "feed" if feed else "agrovet",
                      "description": f"{Decimal(ln['qty']).normalize():f} x {ln['product_name']} ({ln['unit']})"[:200],
                      "amount_kes": amount, "charged_on": today, "terms": terms, "due_on": None, "request_id": None,
                      "created_by_user_id": user["id"]}
            (charge_id,) = db.add_charges([charge], payment)
            db.bill_order_line(ln["id"], charge_id)
            if feed is not None and ln["kg_each"]:
                kg = (Decimal(ln["qty"]) * Decimal(ln["kg_each"])).quantize(Decimal("0.01"))
                db.add_feed_purchase({"farmer_id": o["farmer_id"], "catalogue_id": feed["id"], "purchased_on": today,
                                      "units": (kg / Decimal(feed["kg_per_unit"])).quantize(Decimal("0.01")), "kg": kg,
                                      "cost_kes": amount, "charge_id": charge_id, "created_by_user_id": user["id"]})
        db.update_order(order_id, status="collected", collected_on=today)


def rounds(user, day):
    """Confirmed orders ready on a day, for the agrovet: deliveries by route (one trip per area), then pickups."""
    _is_agrovet(user)
    ready = [o for o in db.orders_for_agrovet(user["id"], ("confirmed",)) if o["ready_on"] == day]
    deliveries, pickups = {}, []
    for o in ready:
        if o["fulfilment"] == "delivery":
            deliveries.setdefault(o["route_code"] or "no route", []).append(o)
        else:
            pickups.append(o)
    return {"deliveries": dict(sorted(deliveries.items())), "pickups": pickups}


# --- promotions and what sells ------------------------------------------------------------------

MAX_PERCENT = 50
MAX_PROMO_DAYS = 60


def add_promotion(user, product_id, percent_off, starts_on, ends_on, today=None):
    """A percentage off one product for a few days. Farmers see it on the order page; confirming an order
    in that window applies it. Returns the promotion id."""
    today = today or date.today()
    _is_agrovet(user)
    if product_id not in {p["id"] for p in db.list_products(user["id"])}:
        raise ValueError("choose one of your products")
    try:
        percent = int(percent_off)
    except (TypeError, ValueError):
        raise ValueError("enter a whole percentage, like 10") from None
    if not 1 <= percent <= MAX_PERCENT:
        raise ValueError(f"between 1% and {MAX_PERCENT}% off")
    if starts_on < today:
        raise ValueError("a promotion can't start in the past")
    if ends_on < starts_on:
        raise ValueError("the end date is before the start")
    if (ends_on - starts_on).days > MAX_PROMO_DAYS:
        raise ValueError(f"a promotion runs at most {MAX_PROMO_DAYS} days")
    return db.add_promotion(user["id"], product_id, percent, starts_on, ends_on)


def end_promotion(user, promo_id, today=None):
    _is_agrovet(user)
    db.end_promotion(user["id"], promo_id, today or date.today())


def sales(user, today=None, days=30):
    """What sold in the last `days` days, from collected orders: per product (qty, KES, orders), best first,
    plus listed products that sold nothing (slow movers), and the repeat-customer count."""
    today = today or date.today()
    _is_agrovet(user)
    rows = db.agrovet_sales(user["id"], today - timedelta(days=days), today)
    sold = {r["product_name"] for r in rows}
    # "not selling" only means something once something has sold; before that it would be every product
    slow = [p for p in db.list_products(user["id"]) if p["name"] not in sold] if rows else []
    customers = [c for c in db.agrovet_customers(user["id"]) if (c["orders"] or 0) > 0]
    return {"products": rows, "slow": slow, "customers": customers,
            "repeat": sum(1 for c in customers if (c["orders"] or 0) >= 2), "kes": sum(float(r["kes"]) for r in rows)}
