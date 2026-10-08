"""Manual yield and feed entry: validate input, then write via src.db.

Validation is separate from the DB call so it can be tested without Postgres.
"""
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
