"""Manual yield and feed entry: validate input, then write via src.db.

Validation is separate from the DB call so it can be tested without Postgres.
"""
import re
from datetime import date

from src import db

SESSIONS = ("morning", "afternoon", "evening")
MAX_LITRES_PER_SESSION = 300  # sanity cap for a smallholder herd; catches typos like 1000
MAX_FEED_KG = 2000


def validate_yield(log_date, session, litres, today=None):
    """Return a cleaned (log_date, session, litres) tuple or raise ValueError."""
    today = today or date.today()
    session = str(session).strip().lower()
    if session not in SESSIONS:
        raise ValueError(f"session must be one of {', '.join(SESSIONS)}")
    if log_date > today:
        raise ValueError("date cannot be in the future")
    try:
        litres = float(litres)
    except (TypeError, ValueError):
        raise ValueError("litres must be a number") from None
    if litres < 0:
        raise ValueError("litres cannot be negative")
    if litres > MAX_LITRES_PER_SESSION:
        raise ValueError(f"litres looks too high (over {MAX_LITRES_PER_SESSION}); check for a typo")
    return log_date, session, round(litres, 2)


def validate_feed(log_date, feed_type, kg, cost_kes=None, today=None):
    """Return a cleaned (log_date, feed_type, kg, cost_kes) tuple or raise ValueError."""
    today = today or date.today()
    feed_type = " ".join(str(feed_type).split()).lower()
    if not feed_type:
        raise ValueError("feed type is required")
    if log_date > today:
        raise ValueError("date cannot be in the future")
    try:
        kg = float(kg)
    except (TypeError, ValueError):
        raise ValueError("kg must be a number") from None
    if kg <= 0:
        raise ValueError("kg must be greater than zero")
    if kg > MAX_FEED_KG:
        raise ValueError(f"kg looks too high (over {MAX_FEED_KG}); check for a typo")
    if cost_kes in (None, ""):
        cost = None
    else:
        try:
            cost = float(cost_kes)
        except (TypeError, ValueError):
            raise ValueError("cost must be a number") from None
        if cost < 0:
            raise ValueError("cost cannot be negative")
        cost = round(cost, 2)
    return log_date, feed_type, round(kg, 2), cost


def normalize_phone(raw):
    """Return a Kenyan mobile number as +254XXXXXXXXX, or raise ValueError.

    Accepts 0712345678, 712345678, 254712345678, +254 712 345 678, 0112345678.
    """
    digits = re.sub(r"[\s\-().]", "", str(raw))
    if digits.startswith("+"):
        digits = digits[1:]
    if not digits.isdigit():
        raise ValueError("phone number should contain digits only")
    if digits.startswith("254"):
        national = digits[3:]
    elif digits.startswith("0"):
        national = digits[1:]
    else:
        national = digits
    if not re.fullmatch(r"[17]\d{8}", national):
        raise ValueError("enter a Kenyan mobile number, e.g. 0712 345 678")
    return "+254" + national


def record_yield(farmer_id, log_date, session, litres):
    """Validate and save one milking session. Returns the cleaned values."""
    log_date, session, litres = validate_yield(log_date, session, litres)
    db.upsert_yield(farmer_id, log_date, session, litres, source="manual")
    return {"log_date": log_date, "session": session, "litres": litres}


def record_feed(farmer_id, log_date, feed_type, kg, cost_kes=None):
    """Validate and save one feed entry. Returns the cleaned values."""
    log_date, feed_type, kg, cost = validate_feed(log_date, feed_type, kg, cost_kes)
    db.add_feed(farmer_id, log_date, feed_type, kg, cost)
    return {"log_date": log_date, "feed_type": feed_type, "kg": kg, "cost_kes": cost}


# --- water -------------------------------------------------------------------

BUCKET_LITRES = 20.0
MAX_WATER_LITRES = 20000


def validate_water(log_date, amount, bucket=False, today=None):
    """(log_date, litres) for a day's water. `amount` is litres, or number of 20 L buckets if bucket=True."""
    today = today or date.today()
    if log_date > today:
        raise ValueError("date cannot be in the future")
    try:
        amount = float(amount)
    except (TypeError, ValueError):
        raise ValueError("water must be a number") from None
    if amount != amount or amount <= 0:
        raise ValueError("water must be greater than zero")
    litres = round(amount * BUCKET_LITRES if bucket else amount, 1)
    if litres > MAX_WATER_LITRES:
        raise ValueError(f"water looks too high (over {MAX_WATER_LITRES:,} litres); check for a typo")
    return log_date, litres


def record_water(farmer_id, log_date, amount, bucket=False):
    """Validate and save the day's total water. Returns the cleaned values."""
    log_date, litres = validate_water(log_date, amount, bucket)
    db.set_water(farmer_id, log_date, litres)
    return {"log_date": log_date, "litres": litres}


# --- cows: breeding, semen, deworming ------------------------------------------

from src.breeding import KINDS, STAGES, cow_status  # noqa: E402
from src.herd import lactation_on  # noqa: E402


def record_cow(farmer_id, tag, sex="female", life_stage="cow", birth_date=None, mother_id=None,
               lactation=None, since=None, today=None):
    """Add a cow, heifer, calf or bull. Returns {"id", "tag"}.

    lactation ('milking' or 'dry') is for an adult cow being added now: it records that she was
    already milking, or already dry, from `since`.
    """
    today = today or date.today()
    tag = " ".join(str(tag).split())
    if not tag:
        raise ValueError("enter the cow's name or tag number")
    if len(tag) > 40:
        raise ValueError("that name is too long")
    if sex not in ("female", "male"):
        raise ValueError("choose female or male")
    if life_stage not in STAGES:
        raise ValueError("choose calf, heifer, cow or bull")
    if sex == "male" and life_stage in ("heifer", "cow"):
        raise ValueError("a male is a calf or a bull")
    if sex == "female" and life_stage == "bull":
        raise ValueError("a female is a calf, heifer or cow")
    if birth_date is not None and birth_date > today:
        raise ValueError("birth date cannot be in the future")
    if mother_id is not None:
        mother = next((c for c in db.list_cows(farmer_id, active_only=False) if c["id"] == mother_id), None)
        if mother is None:
            raise ValueError("choose the mother from the list")
        if mother["sex"] != "female":
            raise ValueError("the mother must be a female")
    if lactation not in (None, "milking", "dry"):
        raise ValueError("choose milking or dry")
    if lactation and life_stage != "cow":
        raise ValueError("only a cow can be milking or dry")
    since = since or today
    if since > today:
        raise ValueError("date cannot be in the future")
    cow_id = db.add_cow(farmer_id, tag, sex, life_stage, birth_date, mother_id)
    if lactation:
        db.add_breeding_event(farmer_id, cow_id, since, "milking" if lactation == "milking" else "dried_off")
    return {"id": cow_id, "tag": tag}


def record_wean(farmer_id, cow_id, on, today=None):
    """A calf stops drinking milk."""
    today = today or date.today()
    cow = next((c for c in db.list_cows(farmer_id) if c["id"] == cow_id), None)
    if cow is None or cow["life_stage"] != "calf":
        raise ValueError("choose a calf from the list")
    if on > today:
        raise ValueError("date cannot be in the future")
    if cow["birth_date"] and on < cow["birth_date"]:
        raise ValueError("a calf cannot be weaned before it was born")
    db.wean_calf(farmer_id, cow_id, on)


def record_semen(farmer_id, name):
    name = " ".join(str(name).split())
    if not name:
        raise ValueError("enter the bull name or breed")
    if len(name) > 80:
        raise ValueError("that name is too long")
    return {"id": db.add_semen(farmer_id, name), "name": name}


def record_breeding_event(farmer_id, cow_id, event_date, kind, semen_id=None, today=None):
    """Validate against the cow's own history, then save.

    A pregnancy result needs a service to refer to, semen can only go with a service, only a
    milking cow can be dried off, and calves and bulls have no breeding or milking events.
    """
    today = today or date.today()
    if kind not in KINDS:
        raise ValueError("choose what happened")
    if event_date > today:
        raise ValueError("date cannot be in the future")
    cow = next((c for c in db.list_cows(farmer_id) if c["id"] == cow_id), None)
    if cow is None:
        raise ValueError("choose a cow from the list")
    if cow["life_stage"] in ("calf", "bull"):
        raise ValueError("a calf or bull has no breeding or milking records")
    if kind != "served":
        semen_id = None
    elif semen_id is not None and semen_id not in {s["id"] for s in db.list_semen(farmer_id)}:
        raise ValueError("choose the semen from the list")
    history = db.breeding_events(farmer_id, cow_id)
    if kind in ("confirmed_pregnant", "not_pregnant"):
        if cow_status(history, event_date)["state"] not in ("served", "in_calf"):
            raise ValueError("record the service first: a pregnancy result needs a service to refer to")
    if kind == "dried_off" and lactation_on(history, event_date) != "milking":
        raise ValueError("she is not recorded as milking on that date, so she can't be dried off")
    db.add_breeding_event(farmer_id, cow_id, event_date, kind, semen_id)
    if kind in ("calved", "milking"):
        db.make_adult(farmer_id, cow_id)  # a heifer who calves becomes a cow
    return {"cow_id": cow_id, "event_date": event_date, "kind": kind, "semen_id": semen_id}


def record_calving(farmer_id, cow_id, event_date, calf_tag=None, calf_sex="female", today=None):
    """Record a calving and, if a tag is given, add the calf with its mother linked."""
    today = today or date.today()
    calf_tag = " ".join(str(calf_tag or "").split())
    if calf_tag:
        if calf_sex not in ("female", "male"):
            raise ValueError("choose whether the calf is female or male")
        if any(c["tag"] == calf_tag for c in db.list_cows(farmer_id, active_only=False)):
            raise ValueError(f"there is already an animal called {calf_tag}; use a different name for the calf")
    saved = record_breeding_event(farmer_id, cow_id, event_date, "calved", today=today)
    if calf_tag:
        record_cow(farmer_id, calf_tag, sex=calf_sex, life_stage="calf", birth_date=event_date, mother_id=cow_id, today=today)
    return saved


def record_deworming(farmer_id, given_on, cow_id=None, product=None, today=None):
    today = today or date.today()
    if given_on > today:
        raise ValueError("date cannot be in the future")
    if cow_id is not None and cow_id not in {c["id"] for c in db.list_cows(farmer_id)}:
        raise ValueError("choose a cow from the list")
    product = " ".join(str(product or "").split()) or None
    db.add_deworming(farmer_id, given_on, cow_id, product)
    return {"given_on": given_on, "cow_id": cow_id, "product": product}


# --- farm setup --------------------------------------------------------------

MAX_MILK_PRICE_KES = 500
MAX_COWS = 500
MAX_KG_PER_UNIT = 20000  # a truck load can hold several tonnes
MAX_KES_PER_UNIT = 1_000_000


def clean_name(raw):
    """Tidy a feed name: trimmed, single spaces, lowercase."""
    return " ".join(str(raw).split()).lower()


def _number(value, label):
    try:
        return float(value)
    except (TypeError, ValueError):
        raise ValueError(f"{label} must be a number") from None


def validate_milk_price(price):
    price = _number(price, "price")
    if price <= 0:
        raise ValueError("price must be greater than zero")
    if price > MAX_MILK_PRICE_KES:
        raise ValueError(f"price looks too high (over KES {MAX_MILK_PRICE_KES} a litre); check for a typo")
    return round(price, 2)


def validate_catalogue_item(name, unit, kg_per_unit, kes_per_unit):
    """Return a cleaned (name, unit, kg_per_unit, kes_per_unit) tuple or raise ValueError."""
    name, unit = clean_name(name), clean_name(unit)
    if not name:
        raise ValueError("feed name is required")
    if not unit:
        raise ValueError("unit is required (for example trunk, wheelbarrow, bag)")
    kg = _number(kg_per_unit, "kg per unit")
    if kg <= 0:
        raise ValueError("kg per unit must be greater than zero")
    if kg > MAX_KG_PER_UNIT:
        raise ValueError(f"kg per unit looks too high (over {MAX_KG_PER_UNIT}); check for a typo")
    kes = _number(kes_per_unit, "price per unit")
    if kes < 0:
        raise ValueError("price per unit cannot be negative")
    if kes > MAX_KES_PER_UNIT:
        raise ValueError("price per unit looks too high; check for a typo")
    return name, unit, round(kg, 2), round(kes, 2)


def validate_cows(effective_date, cows, today=None):
    """Return (effective_date, cows) with cows a whole number, or raise ValueError."""
    today = today or date.today()
    if effective_date > today:
        raise ValueError("date cannot be in the future")
    cows = _number(cows, "cows in milk")
    if cows != int(cows):
        raise ValueError("cows in milk must be a whole number")
    cows = int(cows)
    if cows < 0:
        raise ValueError("cows in milk cannot be negative")
    if cows > MAX_COWS:
        raise ValueError(f"cows in milk looks too high (over {MAX_COWS}); check for a typo")
    return effective_date, cows


def record_milk_price(farmer_id, price):
    price = validate_milk_price(price)
    db.set_milk_price(farmer_id, price)
    return price


def record_catalogue_item(farmer_id, name, unit, kg_per_unit, kes_per_unit):
    """Validate and save a feed in the farm's catalogue. Returns the cleaned values."""
    name, unit, kg, kes = validate_catalogue_item(name, unit, kg_per_unit, kes_per_unit)
    item_id = db.upsert_catalogue_item(farmer_id, name, unit, kg, kes)
    return {"id": item_id, "name": name, "unit": unit, "kg_per_unit": kg, "kes_per_unit": kes}


def record_cows_in_milk(farmer_id, effective_date, cows):
    effective_date, cows = validate_cows(effective_date, cows)
    db.set_cows_in_milk(farmer_id, effective_date, cows)
    return {"effective_date": effective_date, "cows_in_milk": cows}


def feed_from_units(item, units):
    """Convert units of a catalogue feed to (kg, cost_kes). `item` is a feed_catalogue row."""
    units = _number(units, "units")
    if units <= 0:
        raise ValueError("units must be greater than zero")
    return units * float(item["kg_per_unit"]), units * float(item["kes_per_unit"])


def record_feed_units(farmer_id, log_date, item, units):
    """Log feed in the farm's own units. kg and cost are computed from the catalogue and
    stored on the entry, so a later price change doesn't rewrite history."""
    kg, cost = feed_from_units(item, units)
    log_date, feed_type, kg, cost = validate_feed(log_date, item["name"], kg, cost)
    db.add_feed(farmer_id, log_date, feed_type, kg, cost, units=round(float(units), 2), catalogue_id=item["id"])
    return {"log_date": log_date, "feed_type": feed_type, "units": float(units), "unit": item["unit"], "kg": kg, "cost_kes": cost}
