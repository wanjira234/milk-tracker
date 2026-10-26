"""The bell in the top bar: what needs this person's attention right now, worked out from the records.

Each item is (text, page). Nothing is stored: the bell is a live "to look at" list, so it can never say
something is new after it has been dealt with. Farmers hear about alerts, vaccination days and their visits;
vets about requests waiting for a day and today's visits; head admins about signups, Contact us messages and
requests nobody has handled by the day the farmer asked for.
"""
from datetime import date, timedelta

from src import accounts, db

ALERT_DAYS = 7          # a farmer sees an alert in the bell for a week
VACCINATION_DAYS = 14   # and a vaccination day from two weeks before it
DONE_DAYS = 3           # a finished visit stays for three days
MAX_ITEMS = 8


def _plural(n, one, many):
    return f"{n} {one if n == 1 else many}"


def _farmer(user, today):
    fid = user.get("farmer_id")
    if not fid:
        return []
    farm = db.get_farmer(fid) or {}
    routes = [farm["route_id"]] if farm.get("route_id") else []
    items = []
    for a in db.list_alerts(today, routes, limit=20):
        if a["created_at"].date() >= today - timedelta(days=ALERT_DAYS):
            label = "Outbreak alert" if a["kind"] == "outbreak" else "Notice"
            items.append((f"{label}: {a['title']}", "pages/11_alerts.py"))
    mine = db.requests_for_farm(fid)
    booked = {q["vaccination_day_id"] for q in mine if q["vaccination_day_id"] and q["status"] in ("open", "scheduled", "done")}
    for d in db.list_vaccination_days(today, routes):
        if d["id"] not in booked and d["day"] <= today + timedelta(days=VACCINATION_DAYS):
            items.append((f"Vaccination day: {d['vaccine']} on {d['day']:%d %b}. Book your animals.", "pages/12_vaccination.py"))
    for q in mine:
        if q["status"] == "scheduled" and q["scheduled_for"] and q["scheduled_for"] >= today:
            items.append((f"Your {q['kind']} visit is booked for {q['scheduled_for']:%d %b}.", "pages/9_ask_the_vet.py"))
        elif q["status"] == "done" and q["done_on"] and q["done_on"] >= today - timedelta(days=DONE_DAYS):
            items.append((f"Your {q['kind']} visit was done on {q['done_on']:%d %b}.", "pages/9_ask_the_vet.py"))
    return items


def _vet(user, today):
    waiting = db.requests_for_vet(user["id"], ["open"])
    todays = [q for q in db.requests_for_vet(user["id"], ["scheduled"]) if q["scheduled_for"] == today]
    items = []
    if todays:
        items.append((f"{_plural(len(todays), 'visit', 'visits')} to do today.", "pages/8_my_day.py"))
    if waiting:
        items.append((f"{_plural(len(waiting), 'request is', 'requests are')} waiting for a day.", "pages/8_my_day.py"))
    return items


def _admin(user, today):
    if not accounts.is_head_admin(user):
        return []
    items = []
    pending = len(db.list_pending_users())
    if pending:
        items.append((f"{_plural(pending, 'signup', 'signups')} waiting for approval.", "pages/7_admin.py"))
    msgs = db.count_unhandled_messages()
    if msgs:
        items.append((f"{_plural(msgs, 'Contact us message', 'Contact us messages')} to read.", "pages/7_admin.py"))
    late = [q for q in db.requests_for_attendance(today) if q["status"] == "open" and q["preferred_date"] < today]
    if late:
        items.append((f"{_plural(len(late), 'request is', 'requests are')} still open past the day the farmer asked for.", "pages/10_attendance.py"))
    return items


def for_user(user, today=None):
    """[(text, page)] for the bell, most important first, at most MAX_ITEMS. Never raises: a bell must not break a page."""
    today = today or date.today()
    try:
        role = user.get("role")
        items = _farmer(user, today) if role == "farmer" else _vet(user, today) if role == "vet" else _admin(user, today) if role == "admin" else []
    except Exception:
        return []
    return items[:MAX_ITEMS]
