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
