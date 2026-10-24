"""Vaccination days: an admin or vet posts a day, farmers book animals, the route vet's day sheet shows it.

Logic only (no Streamlit). Rules that matter:
  - an admin may post for one route or all routes; a vet only for their own routes;
  - a farmer can book only a day that is for their route (or for all routes), not past, not cancelled,
    and only once per day (the database refuses a second booking too);
  - a booking is a vaccination visit already scheduled for that day, so it appears on the vet's day
    sheet, in what to carry (doses of that vaccine) and in the admin's attendance view for free;
  - posting can also create a notice alert for the route; texting it is still the separate, confirmed
    step on the alerts page.
"""
from datetime import date, timedelta

import psycopg2

from src import alerts, db, services

MAX_VACCINE = 40
MAX_PLACE = 100
MAX_NOTES = 200
MAX_ANIMALS = 200


def _clean(text, limit, what):
    text = " ".join(str(text or "").split())
    if len(text) > limit:
        raise ValueError(f"{what} is too long ({limit} characters at most)")
    return text


def _allowed_routes(user):
    if user["role"] not in ("admin", "vet"):
        raise ValueError("only an admin or a vet can do this")
    return alerts.routes_of(user)


def post_day(user, vaccine, day, route_id=None, place=None, notes=None, announce=True, today=None):
    """Post a vaccination day. Returns its id."""
    today = today or date.today()
    allowed = _allowed_routes(user)
    vaccine = _clean(vaccine, MAX_VACCINE, "the vaccine name")
    place, notes = _clean(place, MAX_PLACE, "the place"), _clean(notes, MAX_NOTES, "the note")
    if not vaccine:
        raise ValueError("enter the vaccine")
    if day < today:
        raise ValueError("the day cannot be in the past")
    if day > today + timedelta(days=services.HORIZON_DAYS):
        raise ValueError(f"the day must be within the next {services.HORIZON_DAYS} days")
    if route_id is None:
        if allowed is not None:
            raise ValueError("a vet can post only for their own routes")
    elif route_id not in {r["id"] for r in db.list_routes()} or (allowed is not None and route_id not in allowed):
        raise ValueError("choose one of your routes")
    day_id = db.add_vaccination_day(vaccine, day, route_id, user["id"], place or None, notes or None)
    if announce:
        body = f"Vaccination day on {day:%A %d %b}" + (f" at {place}" if place else "") + ". Book your animals on the Vaccination page."
        if notes:
            body += f" {notes}"
        alerts.post_alert(user, "notice", f"{vaccine} vaccination, {day:%d %b}", body, route_id, expires_on=day, today=today)
    return day_id


def cancel_day(user, day_id):
    """Cancel a day and the bookings on it that are not done. A vet can cancel only their own routes' days."""
    allowed = _allowed_routes(user)
    d = db.get_vaccination_day(day_id)
    if not d or d["cancelled"]:
        raise ValueError("that vaccination day is not open")
    if allowed is not None and d["route_id"] not in allowed:
        raise ValueError("that day is not on your routes")
    db.cancel_vaccination_day(day_id)


def days_for(user, today=None):
    """The upcoming vaccination days this login may see."""
    today = today or date.today()
    if user["role"] in ("admin", "vet"):
        allowed = alerts.routes_of(user)
        return db.list_vaccination_days(today) if allowed is None else db.list_vaccination_days(today, allowed)
    farm = db.get_farmer(user["farmer_id"]) if user["farmer_id"] else None
    return db.list_vaccination_days(today, [farm["route_id"]] if farm and farm["route_id"] else [])


def book(farmer_id, day_id, animals, today=None):
    """A farmer books animals on a vaccination day. Returns the visit (request) id."""
    today = today or date.today()
    d = db.get_vaccination_day(day_id)
    farm = db.get_farmer(farmer_id)
    if not d or d["cancelled"] or not farm or not farm["active"]:
        raise ValueError("that vaccination day is not open")
    if d["day"] < today:
        raise ValueError("that day has already passed")
    if d["route_id"] is not None and d["route_id"] != farm["route_id"]:
        raise ValueError("that vaccination day is not for your route")
    try:
        animals = int(animals)
    except (TypeError, ValueError):
        raise ValueError("enter how many animals") from None
    if not 1 <= animals <= MAX_ANIMALS:
        raise ValueError(f"enter between 1 and {MAX_ANIMALS} animals")
    try:
        return db.add_vaccination_booking(farmer_id, day_id, d["day"], animals, f"{d['vaccine']}: {animals} animal{'s' if animals != 1 else ''}")
    except psycopg2.errors.UniqueViolation:
        raise ValueError("you have already booked this day: cancel that booking first to change the number") from None


def my_booking(farmer_id, day_id):
    """The farm's active booking on a day, or None."""
    return next((b for b in db.bookings_for_day(day_id) if b["farmer_id"] == farmer_id), None)
