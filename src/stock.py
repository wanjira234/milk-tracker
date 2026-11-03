"""Feed bought, feed left, and when it runs out.

Farms here don't weigh napier or banana trunks: they buy a truck load and see when it's gone. So stock
works in the farm's own units, from two kinds of record that match how a farm already thinks:
  - a purchase: "a full truck of napier arrived today" (kg worked out from the catalogue);
  - a count: "the napier finished today" (0 left), or "about half a truck left".
Stock on hand = the last count + what was bought since - what the feed log says was fed since.

Daily use comes from the feed log when the farm logs that feed (the average over recent logged days);
otherwise from how long the last load lasted (bought, then marked finished). With neither, the app
says so instead of guessing.

record_* functions check input and permissions, then write. item_status is pure and tested without a database.
"""
from datetime import date, timedelta
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation

from src import db, ledger

RATE_WINDOW_DAYS = 14   # recent days the feed-log rate is averaged over
MIN_LOGGED_DAYS = 3     # fewer logged days than this: not enough to trust the feed-log rate
MAX_UNITS = Decimal("10000")
MAX_BACKDATE_DAYS = 60  # stock records are for now, not for history


def _units(value, what="how many"):
    try:
        units = Decimal(str(value).replace(",", "").strip()).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    except (InvalidOperation, ValueError):
        raise ValueError(f"enter {what} as a number, like 1 or 0.5") from None
    if not units.is_finite() or units < 0:
        raise ValueError(f"{what} cannot be negative")
    if units > MAX_UNITS:
        raise ValueError(f"{what} is too large")
    return units


def _check_day(day, today):
    if day > today:
        raise ValueError("the date cannot be in the future")
    if day < today - timedelta(days=MAX_BACKDATE_DAYS):
        raise ValueError(f"the date must be within the last {MAX_BACKDATE_DAYS} days")


def _own_item(user, farmer_id, item_id):
    if not user or user.get("role") != "farmer" or user.get("farmer_id") != farmer_id:
        raise ValueError("you can only record stock for your own farm")
    item = db.get_catalogue_item(farmer_id, item_id)
    if not item or not item["active"]:
        raise ValueError("choose a feed from your farm setup")
    return item


# --- recording ------------------------------------------------------------------------------------


def record_purchase(user, farmer_id, item_id, units, purchased_on, supplier=None, price=None, terms="paid",
                    due_on=None, method=None, reference=None, today=None):
    """A load or bags of a feed arrived. `price` blank = units x the catalogue price; 0 = free (own land,
    a gift) and then no supplier or payment is needed. A priced purchase also becomes a charge in the
    money ledger, saved in the same transaction. Returns the purchase id."""
    today = today or date.today()
    item = _own_item(user, farmer_id, item_id)
    units = _units(units)
    if units == 0:
        raise ValueError("how many must be more than 0")
    _check_day(purchased_on, today)
    if str(price or "").strip() == "":
        cost = (units * Decimal(item["kes_per_unit"])).quantize(Decimal("0.01"))
    else:
        cost = _units(price, "the price")
    charge = payment = None
    if cost > 0:
        charge, payment = ledger.farm_charge(
            user, farmer_id, supplier, "feed", cost, purchased_on, terms, due_on, method, reference,
            description=f"{units.normalize():f} {item['unit']} {item['name']}", today=today)
    purchase = {"farmer_id": farmer_id, "catalogue_id": item_id, "purchased_on": purchased_on, "units": units,
                "kg": (units * Decimal(item["kg_per_unit"])).quantize(Decimal("0.01")), "cost_kes": cost,
                "created_by_user_id": user["id"]}
    return db.add_feed_purchase(purchase, charge, payment)


def record_count(user, farmer_id, item_id, counted_on, units_left, today=None):
    """How much of a feed is left today, in the farm's unit (0 = finished)."""
    today = today or date.today()
    item = _own_item(user, farmer_id, item_id)
    left = _units(units_left, "what is left")
    _check_day(counted_on, today)
    db.set_stock_count(farmer_id, item_id, counted_on, (left * Decimal(item["kg_per_unit"])).quantize(Decimal("0.01")))


def set_warning_days(user, farmer_id, item_id, days):
    """How many days before running out the farm wants to hear about it (the time it takes to restock)."""
    _own_item(user, farmer_id, item_id)
    try:
        days = int(days)
    except (TypeError, ValueError):
        raise ValueError("enter a whole number of days") from None
    if not 0 <= days <= 60:
        raise ValueError("between 0 and 60 days")
    db.set_lead_days(farmer_id, item_id, days)


# --- the forecast (pure) -------------------------------------------------------------------------


def _last_load_rate(purchases, counts):
    """kg per day from the most recent load that was marked finished: what was there at the count before
    it (or 0), plus what was bought in between, spread over the days from the first delivery (or that
    count) to the finish. None if there is no finished load to learn from."""
    finished = [c for c in counts if float(c["kg"]) == 0]
    if not finished:
        return None
    end = finished[-1]["counted_on"]
    before = [c for c in counts if c["counted_on"] < end]
    start_count = before[-1] if before else None
    since = start_count["counted_on"] if start_count else None
    loads = [p for p in purchases if p["purchased_on"] < end and (since is None or p["purchased_on"] >= since)]
    total = (float(start_count["kg"]) if start_count else 0.0) + sum(float(p["kg"]) for p in loads)
    begin = since if since is not None else (min(p["purchased_on"] for p in loads) if loads else None)
    if begin is None or total <= 0:
        return None
    days = (end - begin).days
    return total / days if days >= 1 else None


def item_status(item, purchases, counts, fed, logged_days, today):
    """One feed's stock and forecast.

    purchases / counts / fed = this item's rows (purchased_on+kg / counted_on+kg / log_date+kg), any order;
    logged_days = days the farm logged ANY feed in the rate window (so a day with no entry isn't read as
    'fed nothing'). Returns a dict; on_hand and days_left are None when there is nothing to go on."""
    purchases = sorted(purchases, key=lambda p: p["purchased_on"])
    counts = sorted((c for c in counts if c["counted_on"] <= today), key=lambda c: c["counted_on"])
    kg_per_unit = float(item["kg_per_unit"])
    out = {"id": item["id"], "name": item["name"], "unit": item["unit"], "lead_days": int(item.get("lead_days") or 0),
           "on_hand_kg": None, "on_hand_units": None, "daily_kg": None, "daily_units": None, "rate_from": None,
           "days_left": None, "runs_out_on": None, "low": False, "last_bought": purchases[-1]["purchased_on"] if purchases else None}
    if not purchases and not counts:
        return out
    last = counts[-1] if counts else None
    if last is not None:
        # a count is what was left before that day's delivery; feeding that day happened before the count
        bought = sum(float(p["kg"]) for p in purchases if last["counted_on"] <= p["purchased_on"] <= today)
        eaten = sum(float(f["kg"]) for f in fed if last["counted_on"] < f["log_date"] <= today)
        on_hand = float(last["kg"]) + bought - eaten
    else:
        first = purchases[0]["purchased_on"]
        bought = sum(float(p["kg"]) for p in purchases if p["purchased_on"] <= today)
        eaten = sum(float(f["kg"]) for f in fed if first <= f["log_date"] <= today)
        on_hand = bought - eaten
    on_hand = max(on_hand, 0.0)
    out.update(on_hand_kg=on_hand, on_hand_units=on_hand / kg_per_unit)

    window_start = today - timedelta(days=RATE_WINDOW_DAYS)
    days = {d for d in logged_days if window_start <= d < today}
    fed_recent = sum(float(f["kg"]) for f in fed if window_start <= f["log_date"] < today)
    if len(days) >= MIN_LOGGED_DAYS and fed_recent > 0:
        rate, source = fed_recent / len(days), "feed log"
    else:
        rate, source = _last_load_rate(purchases, counts), "last load"
    if rate:
        days_left = on_hand / rate
        out.update(daily_kg=rate, daily_units=rate / kg_per_unit, rate_from=source, days_left=days_left,
                   runs_out_on=today + timedelta(days=int(days_left)), low=days_left <= out["lead_days"])
    return out


def farm_stock(farmer_id, today=None):
    """Every active feed in the farm's catalogue with its stock and forecast, the ones running out first."""
    today = today or date.today()
    items = db.list_catalogue(farmer_id)
    if not items:
        return []
    since = today - timedelta(days=365)
    purchases = db.feed_purchases(farmer_id, since)
    counts = db.stock_counts(farmer_id)
    fed = db.fed_by_item(farmer_id, since, today)
    logged = db.feed_logged_days(farmer_id, today - timedelta(days=RATE_WINDOW_DAYS), today)
    rows = [item_status(i, [p for p in purchases if p["catalogue_id"] == i["id"]],
                        [c for c in counts if c["catalogue_id"] == i["id"]],
                        [f for f in fed if f["catalogue_id"] == i["id"]], logged, today) for i in items]
    return sorted(rows, key=lambda r: (r["days_left"] is None, r["days_left"] if r["days_left"] is not None else 0, r["name"]))


def running_low(farmer_id, today=None):
    return [r for r in farm_stock(farmer_id, today) if r["low"]]
